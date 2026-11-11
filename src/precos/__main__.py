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
from .db import DB
from .heartbeat import make_heartbeat
from .notify import ConsoleNotifier, NtfyNotifier
from .runner import run_collection, tick
from .summary import build_summary


def _collectors(cfg):
    http = PoliteClient(cfg.user_agent, cfg.request_delay_seconds)
    return {"kabum": KabumCollector(http, cfg.first_party_sellers.get("kabum", ("kabum!", "kabum")))}


def _notifier(dry_run: bool):
    url = os.environ.get("NTFY_URL")
    if dry_run or not url:
        if not dry_run:
            logging.warning("NTFY_URL não definida: usando o modo de teste (só imprime)")
        return ConsoleNotifier()
    return NtfyNotifier(url)


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
    notifier = _notifier(args.dry_run)
    now = datetime.now(timezone.utc)
    if args.cmd == "summary":
        title, msg = build_summary(cfg, db, now)
        notifier.send(title, msg)
    elif args.cmd == "once":
        print(run_collection(cfg, db, _collectors(cfg), notifier, now))
    else:
        collectors = _collectors(cfg)
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
