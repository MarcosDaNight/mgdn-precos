from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from precos import config as config_mod
from precos.db import DB
from precos.models import Offer

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)  # 09:00 em Recife


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def real_config():
    return config_mod.load(ROOT / "config.yaml")


@pytest.fixture
def db():
    d = DB(":memory:")
    yield d
    d.close()


def make_config(**overrides):
    raw = {
        "timezone": "America/Recife",
        "defaults": {"forbidden": ["usado"]},
        "products": [
            {"id": "a", "name": "Produto A", "category": "accessory", "required": ["switch 2"], "target": 100,
             "stores": {"fake": ["https://loja.test/a1", "https://loja.test/a2"]}},
            {"id": "b", "name": "Produto B", "category": "game", "required": ["zelda"], "target": {"pix": 300},
             "stores": {"fake": ["https://loja.test/b1"], "outra": ["https://outra.test/b"]}},
        ],
    }
    raw.update(overrides)
    return config_mod.parse(raw)


def offer(**kw) -> Offer:
    base = dict(product_id="a", store="fake", url="https://loja.test/a1", title="Acessorio Nintendo Switch 2",
                fetched_at=NOW, seller="Loja", first_party=True, price_pix=90.0)
    base.update(kw)
    return Offer(**base)


def seed_history(db: DB, product_id: str, prices: list[float], store="fake", end: datetime = NOW, step_hours=6):
    """Grava ofertas aceitas, em estoque, terminando antes de `end` (a mais nova a `step_hours` de end)."""
    for i, price in enumerate(reversed(prices)):
        ts = end - timedelta(hours=step_hours * (i + 1))
        db.insert_offer(offer(product_id=product_id, store=store, fetched_at=ts, price_pix=price), True)
