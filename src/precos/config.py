from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

import yaml

CATEGORIES = {"console", "game", "accessory"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Targets:
    pix: float | None = None
    installment: float | None = None  # total do parcelado sem juros
    any: float | None = None  # alvo único, vale para o menor entre Pix e parcelado

    def empty(self) -> bool:
        return self.pix is None and self.installment is None and self.any is None


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    required: tuple[str, ...]
    forbidden: tuple[str, ...]
    targets: Targets
    stores: dict[str, tuple[str, ...]]  # loja -> URLs fixas de produto
    physical_only: bool = False


@dataclass(frozen=True)
class AlertRules:
    drop_pct: float = 8.0
    drop_window_days: int = 14
    dedupe_hours: int = 24
    min_history: int = 3  # observações anteriores para valer "novo mínimo" e "queda"
    installment_vs_pix_pct: float = 5.0


@dataclass(frozen=True)
class Schedule:
    collect_every_hours: float = 6
    burst_from: date | None = None
    burst_to: date | None = None
    burst_every_hours: float = 1
    summary_at: time = time(9, 0)


@dataclass(frozen=True)
class Config:
    timezone: str
    schedule: Schedule
    alerts: AlertRules
    default_forbidden: tuple[str, ...]
    products: tuple[Product, ...]
    user_agent: str = "mgdn-precos/0.1 (monitor pessoal de precos)"
    request_delay_seconds: float = 5.0
    first_party_sellers: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _norm_list(v, where: str) -> tuple[str, ...]:
    if v is None:
        return ()
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{where}: precisa ser uma lista de textos")
    return tuple(x.strip().lower() for x in v if x.strip())


def _targets(v, where: str) -> Targets:
    if v is None:
        return Targets()
    if isinstance(v, (int, float)):
        return Targets(any=float(v))
    if isinstance(v, dict):
        extra = set(v) - {"pix", "installment"}
        if extra:
            raise ConfigError(f"{where}: chaves desconhecidas {sorted(extra)}")
        return Targets(
            pix=float(v["pix"]) if v.get("pix") is not None else None,
            installment=float(v["installment"]) if v.get("installment") is not None else None,
        )
    raise ConfigError(f"{where}: use um número ou {{pix:, installment:}}")


def parse(raw: dict) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config vazia ou inválida")
    s = raw.get("schedule") or {}
    burst = s.get("burst") or {}
    h, m = str(s.get("summary_at", "09:00")).split(":")
    schedule = Schedule(
        collect_every_hours=float(s.get("collect_every_hours", 6)),
        burst_from=burst.get("from"),
        burst_to=burst.get("to"),
        burst_every_hours=float(burst.get("every_hours", 1)),
        summary_at=time(int(h), int(m)),
    )
    for d in (schedule.burst_from, schedule.burst_to):
        if d is not None and not isinstance(d, date):
            raise ConfigError("schedule.burst: datas no formato AAAA-MM-DD")
    a = raw.get("alerts") or {}
    rules = AlertRules(
        drop_pct=float(a.get("drop_pct", 8)),
        drop_window_days=int(a.get("drop_window_days", 14)),
        dedupe_hours=int(a.get("dedupe_hours", 24)),
        min_history=int(a.get("min_history", 3)),
        installment_vs_pix_pct=float(a.get("installment_vs_pix_pct", 5)),
    )
    default_forbidden = _norm_list((raw.get("defaults") or {}).get("forbidden"), "defaults.forbidden")

    products, seen = [], set()
    for i, p in enumerate(raw.get("products") or []):
        where = f"products[{i}]"
        pid = p.get("id")
        if not pid or pid in seen:
            raise ConfigError(f"{where}: id ausente ou repetido")
        seen.add(pid)
        if p.get("category") not in CATEGORIES:
            raise ConfigError(f"{where} ({pid}): category deve ser uma de {sorted(CATEGORIES)}")
        required = _norm_list(p.get("required"), f"{where}.required")
        if not required:
            raise ConfigError(f"{where} ({pid}): required não pode ser vazio (evita confundir Switch 1 com Switch 2)")
        stores = {}
        for store, urls in (p.get("stores") or {}).items():
            if not isinstance(urls, list) or not all(isinstance(u, str) and u.startswith("https://") for u in urls):
                raise ConfigError(f"{where} ({pid}).stores.{store}: lista de URLs https")
            stores[store] = tuple(urls)
        products.append(
            Product(
                id=pid,
                name=p.get("name", pid),
                category=p["category"],
                required=required,
                forbidden=_norm_list(p.get("forbidden"), f"{where}.forbidden"),
                targets=_targets(p.get("target"), f"{where} ({pid}).target"),
                stores=stores,
                physical_only=bool(p.get("physical_only", p["category"] == "game")),
            )
        )
    return Config(
        timezone=raw.get("timezone", "America/Recife"),
        schedule=schedule,
        alerts=rules,
        default_forbidden=default_forbidden,
        products=tuple(products),
        user_agent=raw.get("user_agent", "mgdn-precos/0.1 (monitor pessoal de precos)"),
        request_delay_seconds=float(raw.get("request_delay_seconds", 5)),
        first_party_sellers={k: _norm_list(v, f"first_party_sellers.{k}") for k, v in (raw.get("first_party_sellers") or {}).items()},
    )


def load(path: str | Path) -> Config:
    return parse(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
