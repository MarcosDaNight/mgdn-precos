"""Quando coletar e quando mandar o resumo. Funções puras: o relógio entra como argumento."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Config


def collect_interval(now: datetime, cfg: Config) -> timedelta:
    """A cada 6 h; a cada 1 h dentro da janela da Black Friday (datas do fuso configurado, inclusive)."""
    s = cfg.schedule
    local = now.astimezone(ZoneInfo(cfg.timezone)).date()
    if s.burst_from and s.burst_to and s.burst_from <= local <= s.burst_to:
        return timedelta(hours=s.burst_every_hours)
    return timedelta(hours=s.collect_every_hours)


def collect_due(now: datetime, last: datetime | None, cfg: Config) -> bool:
    return last is None or now - last >= collect_interval(now, cfg)


def summary_due(now: datetime, last: datetime | None, cfg: Config) -> bool:
    """Uma vez por dia, a partir da hora configurada no fuso local (09:00 America/Recife)."""
    tz = ZoneInfo(cfg.timezone)
    local = now.astimezone(tz)
    due_at = datetime.combine(local.date(), cfg.schedule.summary_at, tzinfo=tz)
    if local < due_at:
        return False
    return last is None or last.astimezone(tz).date() < local.date()
