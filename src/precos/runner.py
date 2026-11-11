from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import alerts, filters, schedule
from .collectors.base import Collector
from .collectors.http import Blocked
from .config import Config
from .db import DB
from .notify import Notifier
from .summary import build_summary

log = logging.getLogger(__name__)
FAILURES_BEFORE_WARNING = 3
ATTEMPT_COOLDOWN = timedelta(minutes=10)  # rodada que aborta é refeita, sem martelar as lojas
MAX_BACKOFF = timedelta(hours=3)  # teto do recuo quando NENHUMA página é lida


@dataclass
class Report:
    collected: int = 0
    rejected: int = 0
    failed: int = 0
    alerts: int = 0
    disabled: list[str] = field(default_factory=list)


def _notify(notifier: Notifier, *args, **kw) -> bool:
    """True só se o aviso foi ENTREGUE de verdade. Modo de teste (que só imprime) e ntfy fora do ar
    devolvem False: o alerta não é gravado como enviado e é refeito na rodada seguinte."""
    try:
        notifier.send(*args, **kw)
    except Exception:  # um ntfy fora do ar não pode derrubar a coleta
        log.exception("falha ao notificar")
        return False
    return getattr(notifier, "delivers", True)


def _process(cfg: Config, db: DB, notifier: Notifier, product, store: str, offer, now: datetime, rep: Report) -> None:
    """Filtros, guarda de preço, alerta e gravação de UMA oferta. Roda dentro do try da URL."""
    rep.collected += 1
    verdict = filters.evaluate(product, offer, cfg.default_forbidden)
    if verdict.ok and alerts.is_suspect(product, offer, db, now, cfg.alerts) and not alerts.confirmed(db, offer, filters.SUSPECT):
        verdict = filters.Verdict(False, f"{filters.SUSPECT} ({alerts.brl(offer.best_price)}, muito abaixo da mediana recente)")
        log.warning("%s em %s: espero a próxima leitura para confirmar", verdict.reason, offer.url)
    alert = alerts.evaluate(product, offer, db, now, cfg.alerts) if verdict.ok else None
    db.insert_offer(offer, verdict.ok, verdict.reason)
    if not verdict.ok:
        rep.rejected += 1
        log.info("recusada (%s): %s", verdict.reason, offer.title)
    if alert:
        title, message, priority = alerts.format_alert(alert)
        tags = ("moneybag",) if alert.verdict == "COMPRAR" else ("hourglass",)
        if _notify(notifier, title, message, priority=priority, tags=tags, click=offer.url):
            db.record_alert(now, product.id, store, offer.best_price, list(alert.reasons))
            rep.alerts += 1


def run_collection(cfg: Config, db: DB, collectors: dict[str, Collector], notifier: Notifier, now: datetime) -> Report:
    """Uma rodada. Cada URL é isolada: o erro de uma não derruba as outras nem os outros coletores."""
    rep = Report()
    for product in cfg.products:
        for store, urls in product.stores.items():
            collector = collectors.get(store)
            if collector is None:
                log.warning("sem coletor para %s (%s): ignorando", store, product.id)
                continue
            for url in urls:
                if db.get_state(f"disabled:{store}"):
                    break  # a loja saiu (bloqueou o UA identificável): nem tenta de novo
                key = f"{store}|{url}"
                try:
                    offer = collector.fetch(product, url)
                    _process(cfg, db, notifier, product, store, offer, now, rep)
                except Blocked as e:
                    reason = str(e)
                    db.set_state(f"disabled:{store}", reason)
                    rep.disabled.append(store)
                    log.error("%s desativada: %s", store, reason)
                    _notify(notifier, f"Loja desativada: {store}",
                            f"{reason}\nPor regra, a loja sai do coletor. Reative com: python -m precos enable {store}",
                            priority=4, tags=("warning",))
                    break
                except Exception as e:
                    rep.failed += 1
                    n, notified = db.record_failure(key, f"{type(e).__name__}: {e}")
                    log.warning("falha (%d seguidas) em %s: %s", n, url, e)
                    if n >= FAILURES_BEFORE_WARNING and not notified:
                        if _notify(notifier, f"Coletor {store} falhando",
                                   f"{n} falhas seguidas em {product.name}\n{url}\n{type(e).__name__}: {e}",
                                   priority=4, tags=("warning",)):
                            db.mark_failure_notified(key)
                    continue
                db.clear_failure(key)
    return rep


def reset_stale_state(db: DB) -> None:
    """Ao subir o serviço. A versão anterior gravava `last_collect` no INÍCIO da rodada: se nunca houve uma
    coleta bem-sucedida (`last_ok`), esse valor é de uma rodada que não terminou e não pode adiar a próxima."""
    db.del_state("last_attempt")
    if db.get_state("last_ok") is None:
        db.del_state("last_collect")
        db.del_state("empty_rounds")


def tick(cfg: Config, db: DB, collectors: dict[str, Collector], notifier: Notifier, now: datetime | None = None,
         heartbeat: Callable[[], None] | None = None) -> Report | None:
    """Chamado a cada minuto pelo laço: coleta e/ou manda o resumo, se for a hora."""
    now = now or datetime.now(timezone.utc)
    report = None
    last_collect = db.get_state("last_collect")  # só é gravado quando a rodada TERMINA
    last_attempt = db.get_state("last_attempt")
    # Rodadas seguidas em que NENHUMA página foi lida: recua (10, 20, 40... min, no máximo 3 h) em vez de
    # martelar uma loja que está fora do ar ou nos bloqueando de forma silenciosa.
    empty = int(db.get_state("empty_rounds") or 0)
    cooldown = min(ATTEMPT_COOLDOWN * 2**empty, MAX_BACKOFF)
    cooling = last_attempt is not None and now - datetime.fromisoformat(last_attempt) < cooldown
    if not cooling and schedule.collect_due(now, datetime.fromisoformat(last_collect) if last_collect else None, cfg):
        db.set_state("last_attempt", now.isoformat())
        report = run_collection(cfg, db, collectors, notifier, now)
        if report.collected > 0:
            # Só uma rodada que leu alguma página conta como feita. Se abortar, ou se tudo falhar, ela é refeita
            # (com recuo) em vez de o app achar que coletou e ficar 6 h sem tentar.
            db.set_state("last_collect", now.isoformat())
            db.del_state("empty_rounds")
        else:
            db.set_state("empty_rounds", str(empty + 1))
        log.info("rodada: %s", report)
        if report.collected > 0:
            db.set_state("last_ok", now.isoformat())  # o /healthz mede por aqui, não pela tentativa
        # "Estou vivo": só depois de coletar de verdade ao menos uma página. Se tudo falhar, o silêncio avisa.
        if heartbeat and report.collected > 0:
            try:
                heartbeat()
            except Exception:
                log.exception("heartbeat falhou (a coleta segue)")
    last_summary = db.get_state("last_summary")
    if schedule.summary_due(now, datetime.fromisoformat(last_summary) if last_summary else None, cfg):
        title, message = build_summary(cfg, db, now)
        if _notify(notifier, title, message, priority=3, tags=("shopping_cart",)):
            db.set_state("last_summary", now.isoformat())
    return report
