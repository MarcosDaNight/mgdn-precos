from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

from . import config as config_mod
from .collectors.http import PoliteClient
from .collectors.kabum import KabumCollector
from .collectors.mercadolivre import MercadoLivreCollector, MLAuth
from .db import DB
from .heartbeat import make_heartbeat
from .notify import ConsoleNotifier, NtfyNotifier
from .runner import run_collection, tick
from .summary import build_summary


def _ml_auth(db):
    cid, secret = os.environ.get("ML_CLIENT_ID"), os.environ.get("ML_CLIENT_SECRET")
    if not (cid and secret):
        return None
    return MLAuth(db, cid, secret, os.environ.get("ML_REDIRECT_URI", "https://precos.mgdn.com.br/ml/callback"))


def _collectors(cfg, db):
    http = PoliteClient(cfg.user_agent, cfg.request_delay_seconds)
    collectors = {"kabum": KabumCollector(http, cfg.first_party_sellers.get("kabum", ("kabum!", "kabum")))}
    if auth := _ml_auth(db):
        collectors["mercadolivre"] = MercadoLivreCollector(auth, cfg.user_agent)
    else:
        logging.warning("ML_CLIENT_ID/ML_CLIENT_SECRET não definidas: Mercado Livre desligado")
    return collectors


def _notifier(dry_run: bool):
    url = os.environ.get("NTFY_URL")
    if dry_run or not url:
        if not dry_run:
            logging.warning("NTFY_URL não definida: usando o modo de teste (só imprime)")
        return ConsoleNotifier()
    return NtfyNotifier(url)


def _ml_command(args, cfg, db) -> int:
    auth = _ml_auth(db)
    if auth is None:
        print("defina ML_CLIENT_ID e ML_CLIENT_SECRET (o secret vai por segredo cifrado, nunca no chat)", file=sys.stderr)
        return 2
    if args.cmd == "ml-auth-url":
        print(auth.authorize_url())
        return 0
    if args.cmd == "ml-auth":
        auth.exchange_code(args.code)
        print("tokens gravados no banco")
        return 0
    from . import filters
    product = next((p for p in cfg.products if args.url in p.stores.get("mercadolivre", ())), cfg.products[0])
    offer = MercadoLivreCollector(auth, cfg.user_agent).fetch(product, args.url)
    verdict = filters.evaluate(product, offer, cfg.default_forbidden)
    print(offer)
    print(f"produto avaliado: {product.id} | filtros: {'ACEITA' if verdict.ok else 'RECUSA: ' + str(verdict.reason)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="precos", description="Monitor pessoal de preços")
    ap.add_argument("--config", default=os.environ.get("PRECOS_CONFIG", "config.yaml"))
    ap.add_argument("--db", default=os.environ.get("PRECOS_DB", "data/precos.sqlite"))
    ap.add_argument("--dry-run", action="store_true", help="não envia ao ntfy: imprime")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="laço contínuo (o que roda no container)")
    sub.add_parser("once", help="uma rodada de coleta agora")
    sub.add_parser("summary", help="imprime/envia o resumo diário agora")
    sub.add_parser("check-config", help="valida o config.yaml")
    sub.add_parser("ml-auth-url", help="URL para autorizar o app no Mercado Livre (abra no navegador)")
    ma = sub.add_parser("ml-auth", help="troca o `code` da URL de retorno pelos tokens")
    ma.add_argument("code")
    mc = sub.add_parser("ml-check", help="lê UM anúncio pela API e mostra o que os filtros decidem")
    mc.add_argument("url")
    en = sub.add_parser("enable", help="reativa uma loja desativada por bloqueio")
    en.add_argument("store")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = config_mod.load(args.config)
    except (config_mod.ConfigError, OSError) as e:
        print(f"config inválida: {e}", file=sys.stderr)
        return 2
    if args.cmd == "check-config":
        n = sum(len(u) for p in cfg.products for u in p.stores.values())
        print(f"ok: {len(cfg.products)} produtos, {n} URLs")
        return 0

    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    db = DB(args.db)
    if args.cmd == "enable":
        db.del_state(f"disabled:{args.store}")
        print(f"{args.store} reativada")
        return 0
    if args.cmd in ("ml-auth-url", "ml-auth", "ml-check"):
        return _ml_command(args, cfg, db)
    notifier = _notifier(args.dry_run)
    now = datetime.now(timezone.utc)
    if args.cmd == "summary":
        title, msg = build_summary(cfg, db, now)
        notifier.send(title, msg)
    elif args.cmd == "once":
        print(run_collection(cfg, db, _collectors(cfg, db), notifier, now))
    else:
        collectors = _collectors(cfg, db)
        hc = os.environ.get("HEALTHCHECK_URL")
        heartbeat = make_heartbeat(hc) if hc else None
        logging.info("iniciado: %d produtos (heartbeat %s)", len(cfg.products), "ligado" if heartbeat else "desligado")
        while True:
            try:
                tick(cfg, db, collectors, notifier, heartbeat=heartbeat)
            except Exception:
                logging.exception("erro na rodada (o laço continua)")
            time.sleep(60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
