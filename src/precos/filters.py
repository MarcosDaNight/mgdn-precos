"""Filtros obrigatórios: só entra no histórico e nos alertas o que for novo, físico (jogos),
vendido pela própria loja e com o título certo. Tudo o mais é registrado com o motivo."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .config import Product
from .models import Offer

SUSPECT = "preço suspeito"  # leitura muito abaixo do normal: só vale depois de confirmada
GAME_KEY = ("game-key", "game key", "gamekey")
USED = ("usado", "seminovo", "recondicionado", "open box", "openbox", "vitrine")
DIGITAL = ("digital", "codigo", "download", "gift card", "pacote de melhoria")


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, para 'Pokémon' casar com 'pokemon'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None


def _first(title: str, words) -> str | None:
    return next((w for w in words if normalize(w) in title), None)


def evaluate(product: Product, offer: Offer, default_forbidden: tuple[str, ...] = ()) -> Verdict:
    title = normalize(offer.title)
    if not offer.first_party:
        return Verdict(False, f"vendedor de terceiros ({offer.seller or 'desconhecido'})")
    if offer.condition != "new":
        return Verdict(False, f"condição: {offer.condition}")
    if product.physical_only:
        if offer.digital:
            return Verdict(False, "mídia digital")
        if w := _first(title, DIGITAL):
            return Verdict(False, f"digital ({w})")
        if w := _first(title, GAME_KEY):
            return Verdict(False, f"Game-Key Card ({w})")
    if w := _first(title, USED):
        return Verdict(False, f"condição: {w}")
    for w in (*default_forbidden, *product.forbidden):
        if normalize(w) in title:
            return Verdict(False, f"palavra proibida: {w}")
    for w in product.required:
        if normalize(w) not in title:
            return Verdict(False, f"faltou no título: {w}")
    return Verdict(True)
