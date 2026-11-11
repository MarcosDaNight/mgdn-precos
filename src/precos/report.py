"""Texto do `ml-check`: o que foi lido de UM anúncio e o que os filtros decidem para CADA produto do config."""
from __future__ import annotations

from . import filters
from .alerts import brl
from .config import Config
from .models import Offer


def format_offer(o: Offer) -> str:
    sim = lambda b: "sim" if b else "não"  # noqa: E731
    return "\n".join([
        f"título:       {o.title}",
        f"preço:        {brl(o.best_price)} (à vista/Pix: {brl(o.price_pix)})",
        f"vendedor:     {o.seller} | loja oficial/própria: {sim(o.first_party)}",
        f"condição:     {o.condition} | disponível: {sim(o.available)} | frete grátis: "
        + ("não informado" if o.free_shipping is None else sim(o.free_shipping)),
        f"link:         {o.url}",
    ])


def verdict_lines(o: Offer, cfg: Config, only: str | None = None) -> list[str]:
    """Avalia contra todos os produtos (ou só `only`) e diz qual aceita a oferta, ou por que nenhum aceita."""
    products = [p for p in cfg.products if only in (None, p.id)]
    if not products:
        return [f"produto '{only}' não existe no config (ids: {', '.join(p.id for p in cfg.products)})"]
    results = [(p, filters.evaluate(p, o, cfg.default_forbidden)) for p in products]
    ok = [p.id for p, v in results if v.ok]
    if ok:
        return [f"ACEITO para: {', '.join(ok)}"]
    return ["NENHUM produto aceita esta oferta. Motivo por produto:"] + [f"  {p.id}: {v.reason}" for p, v in results]
