"""KaBuM: lê a página de produto (URL fixa). O Next.js embute o produto em __NEXT_DATA__; o JSON-LD é só reserva."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from ..config import Product
from ..filters import normalize
from ..models import Offer
from .http import PoliteClient

_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LD = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


class ParseError(Exception):
    pass


def _jsons(pattern: re.Pattern, html: str):
    for m in pattern.finditer(html):
        try:
            yield json.loads(m.group(1))
        except json.JSONDecodeError:
            continue


def _num(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse(html: str, product_id: str, url: str, now: datetime, first_party: tuple[str, ...] = ("kabum!", "kabum")) -> Offer:
    for data in _jsons(_NEXT, html):
        p = (data.get("props") or {}).get("pageProps", {}).get("product")
        if isinstance(p, dict):
            return _from_next(p, product_id, url, now, first_party)
    # Reserva: o JSON-LD não diz quem vende, então a oferta nasce como "terceiro" e os filtros a recusam.
    for data in _jsons(_LD, html):
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Product":
                offer = item.get("offers") or {}
                price = _num(offer.get("price"))
                if price is None:
                    continue
                return Offer(
                    product_id=product_id, store="kabum", url=url, title=item.get("name", ""), fetched_at=now,
                    first_party=False, available=str(offer.get("availability", "")).endswith("InStock"),
                    price_pix=price,
                )
    raise ParseError("nem __NEXT_DATA__ nem JSON-LD com preço: o layout da KaBuM mudou?")


def _from_next(p: dict, product_id: str, url: str, now: datetime, first_party: tuple[str, ...]) -> Offer:
    flags = p.get("flags") or {}
    prices = p.get("prices") or {}
    pix = _num(prices.get("priceWithDiscount")) or _num(prices.get("price"))
    if pix is None and _num(p.get("price")) is None:
        raise ParseError("produto sem preço")
    seller = p.get("sellerName")
    inst = p.get("installment") or {}
    n, amount = inst.get("installment"), _num(inst.get("amount"))
    has_plan = isinstance(n, int) and n > 0 and amount is not None
    return Offer(
        product_id=product_id,
        store="kabum",
        url=url,
        title=p.get("title") or p.get("friendlyName") or "",
        fetched_at=now,
        seller=seller,
        first_party=not flags.get("isMarketplace", True) and normalize(seller or "") in first_party,
        condition="refurbished" if flags.get("isOpenbox") else "new",
        digital=bool(flags.get("isDigital")),
        available=bool(p.get("available")) and bool(flags.get("isAvailable", True)),
        price_pix=pix or _num(p.get("price")),
        price_card=_num(prices.get("price")),
        installments=n if has_plan else None,
        installment_amount=amount if has_plan else None,
        interest_free=has_plan and not inst.get("hasFee", True),
        free_shipping=flags.get("isFreeShipping") if "isFreeShipping" in flags else None,
    )


class KabumCollector:
    store = "kabum"

    def __init__(self, http: PoliteClient, first_party: tuple[str, ...] = ("kabum!", "kabum")):
        self.http, self.first_party = http, first_party

    def fetch(self, product: Product, url: str) -> Offer:
        html = self.http.get(url)
        return parse(html, product.id, url, datetime.now(timezone.utc), self.first_party)
