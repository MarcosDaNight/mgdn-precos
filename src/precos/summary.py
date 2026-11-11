from __future__ import annotations

from datetime import datetime, timedelta

from .alerts import brl, target_text
from .config import Config
from .db import DB


def _why_none(p, db: DB, now: datetime) -> str:
    """Por que o item não tem oferta disponível: esgotado, leitura velha, sem loja ou ainda sem leitura."""
    seen = db.latest_any_by_store(p.id)
    if not seen:
        return "sem loja configurada ainda" if not p.stores else "ainda sem leitura válida"
    sold_out = [r for r in seen if not r["available"]]
    if sold_out:
        return "esgotado em " + ", ".join(f"{r['store']} (último preço {brl(r['best_price'])})" for r in sold_out)
    r = seen[0]
    return f"sem leitura nas últimas 24 h (última: {brl(r['best_price'])} em {r['store']})"


def build_summary(cfg: Config, db: DB, now: datetime) -> tuple[str, str]:
    """Melhor preço de cada item (última leitura de cada loja nas últimas 24 h) e total do carrinho."""
    lines, total, found = [], 0.0, 0
    for p in cfg.products:
        rows = db.latest_by_store(p.id, now - timedelta(hours=24))
        if not rows:
            lines.append(f"• {p.name}: {_why_none(p, db, now)} · meta {target_text(p)}")
            continue
        best = rows[0]
        total += best["best_price"]
        found += 1
        how = "Pix" if best["price_pix"] is not None and best["price_pix"] == best["best_price"] else "parcelado"
        lines.append(f"• {p.name}: {brl(best['best_price'])} ({best['store']}, {how}) · meta {target_text(p)}")
    lines.append("")
    missing = len(cfg.products) - found
    lines.append(f"Total do carrinho ({found} itens disponíveis): {brl(total)}" + (f" — {missing} sem oferta disponível" if missing else ""))
    return "Resumo diário de preços", "\n".join(lines)
