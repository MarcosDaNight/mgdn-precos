from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Offer:
    """O que uma loja oferece agora por um produto. Os coletores só preenchem os fatos;
    quem decide se vale (filtros, alertas) são os outros módulos."""

    product_id: str
    store: str
    url: str
    title: str
    fetched_at: datetime
    seller: str | None = None
    first_party: bool = False  # vendido e entregue pela própria loja (não marketplace)
    condition: str = "new"  # new | used | refurbished
    digital: bool = False
    available: bool = True
    price_pix: float | None = None  # preço à vista no Pix
    price_card: float | None = None  # preço cheio (cartão/boleto)
    installments: int | None = None
    installment_amount: float | None = None
    interest_free: bool = False
    free_shipping: bool | None = None  # só quando a página informa

    @property
    def installment_total(self) -> float | None:
        """Total do parcelado, só se for sem juros (com juros não compete com o Pix)."""
        if self.interest_free and self.installments and self.installment_amount:
            return round(self.installments * self.installment_amount, 2)
        return None

    @property
    def best_price(self) -> float | None:
        prices = [p for p in (self.price_pix, self.installment_total) if p is not None]
        if prices:
            return min(prices)
        return self.price_card
