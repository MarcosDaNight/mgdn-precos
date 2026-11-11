"""Painel de uma página (tabela HTML) e /healthz. Só leitura: cada requisição abre o banco em modo ro."""
from __future__ import annotations

import html
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from .alerts import brl, meets_target, target_text
from .config import Config
from .db import DB
from .models import Offer

STALE_AFTER = timedelta(hours=26)  # "pelo menos 1 vez por dia", com folga


def health(db: DB, started: datetime, now: datetime) -> tuple[int, str]:
    """200 se coletou de verdade nas últimas 26 h (ou se o processo é novo demais para julgar)."""
    last = db.get_state("last_ok")
    if last is None:
        return (200, "iniciando: ainda sem coleta") if now - started < STALE_AFTER else (503, "sem nenhuma coleta bem-sucedida")
    age = now - datetime.fromisoformat(last)
    if age > STALE_AFTER:
        return 503, f"última coleta bem-sucedida há {age.total_seconds() / 3600:.0f} h"
    return 200, "ok"


def _offer_from_row(r) -> Offer:
    return Offer(product_id=r["product_id"], store=r["store"], url=r["url"], title=r["title"] or "",
                 fetched_at=datetime.fromisoformat(r["ts"]), seller=r["seller"], first_party=True,
                 available=bool(r["available"]), price_pix=r["price_pix"], price_card=r["price_card"],
                 installments=r["installments"], installment_amount=r["installment_amount"],
                 interest_free=bool(r["interest_free"]))


CSS = """:root{color-scheme:light dark;--bg:#f4f7fa;--card:#fff;--ink:#13284b;--mut:#5b6b82;--ok:#138a7a;--warn:#c2410c;--line:#dce5ef}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--mut:#9aa7b6;--ok:#2bc4ac;--warn:#fb923c;--line:#2b3440}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif;padding:16px;max-width:980px;margin-inline:auto}
h1{font-size:1.4rem}h2{font-size:1.05rem;margin-top:28px}.m{color:var(--mut);font-size:.85rem}
.t{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%}th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:.75rem;text-transform:uppercase;color:var(--mut)}tr:last-child td{border:0}a{color:var(--ok)}
.ok{color:var(--ok);font-weight:700}.w{color:var(--warn)}"""


def _e(x) -> str:
    return html.escape(str(x))


def render(cfg: Config, db: DB, now: datetime) -> str:
    tz = ZoneInfo(cfg.timezone)
    rows = []
    for p in cfg.products:
        offers = db.latest_any_by_store(p.id)
        best = next((r for r in offers if r["available"]), None)
        hist_min = db.history_min(p.id)
        if best is not None:
            o = _offer_from_row(best)
            price = f'<a href="{_e(best["url"])}" rel="noopener">{brl(best["best_price"])}</a>'
            where = _e(best["store"])
            status = '<span class="ok">META ✓</span>' if meets_target(p, o) else "esperar"
            seen = datetime.fromisoformat(best["ts"]).astimezone(tz).strftime("%d/%m %H:%M")
        else:
            esgot = ", ".join(f'{_e(r["store"])} esgotado' for r in offers) or "sem leitura válida"
            price, where, status, seen = "—", esgot, '<span class="w">indisponível</span>', ""
        rows.append(f"<tr><td>{_e(p.name)}</td><td>{price}</td><td>{where}</td><td>{_e(target_text(p))}</td>"
                    f"<td>{brl(hist_min)}</td><td>{status}</td><td class='m'>{seen}</td></tr>")
    store_rows = []
    for store in sorted({s for p in cfg.products for s in p.stores}):
        off = db.get_state(f"disabled:{store}")
        store_rows.append(f"<tr><td>{_e(store)}</td><td>{'<span class=w>desativada</span> — ' + _e(off) if off else 'ativa'}</td></tr>")
    fails = "".join(
        f"<tr><td>{_e(r['key'].split('|', 1)[-1][-70:])}</td><td>{r['consecutive']}×</td><td class='m'>{_e((r['last_error'] or '')[:140])}</td></tr>"
        for r in db.failures())
    rej = "".join(
        f"<tr><td class='m'>{datetime.fromisoformat(r['ts']).astimezone(tz):%d/%m %H:%M}</td><td>{_e(r['store'])}</td>"
        f"<td>{_e((r['title'] or '')[:70])}</td><td class='m'>{_e(r['reject_reason'])}</td></tr>"
        for r in db.recent_rejections(now - timedelta(hours=48)))
    last_ok = db.get_state("last_ok")
    last = datetime.fromisoformat(last_ok).astimezone(tz).strftime("%d/%m %H:%M") if last_ok else "ainda não"
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Preços</title><style>{CSS}</style></head><body>
<h1>Monitor de preços</h1><p class="m">Última coleta bem-sucedida: {last} · preços lidos das páginas, confira no checkout (frete e cupom ficam de fora)</p>
<div class="t"><table><tr><th>Produto</th><th>Melhor preço</th><th>Loja</th><th>Meta</th><th>Mínimo</th><th>Situação</th><th>Lido em</th></tr>{''.join(rows)}</table></div>
<h2>Lojas</h2><div class="t"><table>{''.join(store_rows) or '<tr><td class="m">nenhuma loja configurada</td></tr>'}</table></div>
<h2>Falhas (URLs que não foram lidas)</h2><div class="t"><table>{fails or '<tr><td class="m">nenhuma falha</td></tr>'}</table></div>
<h2>Recusadas nas últimas 48 h</h2><div class="t"><table>{rej or '<tr><td class="m">nada recusado</td></tr>'}</table></div>
</body></html>"""


def make_handler(cfg: Config, db_path: str, started: datetime):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            now = datetime.now(timezone.utc)
            try:
                db = DB(db_path, readonly=True)
            except Exception as e:  # banco ainda não criado, ou ilegível
                return self._send(503, f"banco indisponível: {e}", "text/plain")
            try:
                if self.path == "/healthz":
                    code, msg = health(db, started, now)
                    return self._send(code, msg + "\n", "text/plain")
                if self.path in ("/", "/index.html"):
                    return self._send(200, render(cfg, db, now), "text/html")
                return self._send(404, "não encontrado\n", "text/plain")
            finally:
                db.close()

        def _send(self, code, body, ctype):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # sem ruído no log a cada checagem de saúde
            pass

    return Handler


def serve(cfg: Config, db_path: str, port: int = 8080, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(cfg, db_path, datetime.now(timezone.utc)))
    threading.Thread(target=server.serve_forever, daemon=True, name="painel").start()
    return server
