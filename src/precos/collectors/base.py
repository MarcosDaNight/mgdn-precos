from __future__ import annotations

from typing import Protocol

from ..config import Product
from ..models import Offer


class Collector(Protocol):
    """Interface comum: um coletor por loja. `fetch` lê UMA página de produto e devolve a oferta
    (com os fatos que a página trouxe, inclusive esgotado). Erros sobem como exceção."""

    store: str

    def fetch(self, product: Product, url: str) -> Offer: ...
