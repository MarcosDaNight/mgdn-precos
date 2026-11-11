"""Mercado Livre: SOMENTE pela API oficial, com token OAuth. Nada de HTML.

ATENÇÃO: escrito contra a documentação pública da API, sem token para testar contra a API real.
A primeira validação é `python -m precos ml-check <url>`, que mostra o que foi lido e o que os filtros decidem.
Termos do Programa de Desenvolvedores (uso pessoal, guardar histórico, limite de chamadas): conferir no portal."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from ..config import Product
from ..db import DB
from ..models import Offer
from .http import FetchError

log = logging.getLogger(__name__)
API = "https://api.mercadolibre.com"
AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
_ITEM_ID = re.compile(r"MLB-?(\d{6,})")
_PRODUCT_ID = re.compile(r"/p/(MLB\d+)")
_COND = {"new": "new", "used": "used"}


def _brief(r: httpx.Response) -> str:
    """Corpo do erro da API (só mensagem/código, sem tokens): é o que diz POR QUE o acesso foi negado."""
    try:
        b = r.json()
        parts = [f"{k}={b[k]}" for k in ("error", "message", "blocked_by", "code") if isinstance(b, dict) and b.get(k)]
        if parts:
            return "; ".join(parts)[:300]
    except ValueError:
        pass
    return (r.text or "(vazia)")[:200]


class MLAuthError(FetchError):
    pass


class ParseError(Exception):
    pass


def resolve(url: str) -> tuple[str, str]:
    """('item', 'MLB123') para anúncio; ('product', 'MLB123') para página de catálogo (/p/MLB...)."""
    if m := _PRODUCT_ID.search(url):
        return "product", m.group(1)
    if "/up/" in url:
        raise ParseError(f"página de produto de usuário (/up/) não é suportada: use o link do anúncio ({url})")
    if m := _ITEM_ID.search(url):
        return "item", f"MLB{m.group(1)}"
    raise ParseError(f"não achei um id MLB na URL: {url}")


def _num(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_item(item: dict, product_id: str, url: str, now: datetime) -> Offer:
    price = _num(item.get("price"))
    if price is None:
        raise ParseError("anúncio sem preço")
    official = item.get("official_store_id")
    seller = f"Loja Oficial #{official}" if official is not None else f"vendedor #{item.get('seller_id')}"
    return Offer(
        product_id=product_id,
        store="mercadolivre",
        url=item.get("permalink") or url,
        title=item.get("title", ""),
        fetched_at=now,
        seller=seller,
        first_party=official is not None,  # "Loja Oficial": a única venda aceita no Mercado Livre
        condition=_COND.get(item.get("condition"), "unknown"),
        available=item.get("status") == "active" and (item.get("available_quantity") or 0) > 0,
        price_pix=price,  # o ML não separa Pix: `price` é o valor à vista
        free_shipping=(item.get("shipping") or {}).get("free_shipping"),
    )


class MLAuth:
    """OAuth do Mercado Livre. O refresh token ROTACIONA a cada renovação, então o novo é sempre regravado."""

    def __init__(self, db: DB, client_id: str, client_secret: str, redirect_uri: str, client: httpx.Client | None = None):
        self.db, self.client_id, self.secret, self.redirect_uri = db, client_id, client_secret, redirect_uri
        self.client = client or httpx.Client(timeout=20)

    def authorize_url(self) -> str:
        return AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri})

    def _token_request(self, data: dict, now: datetime) -> None:
        r = self.client.post(f"{API}/oauth/token", data={"client_id": self.client_id, "client_secret": self.secret, **data},
                             headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"})
        if r.status_code != 200:
            raise MLAuthError(f"token recusado ({r.status_code}): {r.text[:200]}")
        body = r.json()
        self.db.set_state("ml:access_token", body["access_token"])
        self.db.set_state("ml:refresh_token", body["refresh_token"])
        self.db.set_state("ml:expires_at", (now + timedelta(seconds=int(body.get("expires_in", 21600)))).isoformat())

    def exchange_code(self, code: str, now: datetime | None = None) -> None:
        self._token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri}, now or datetime.now(timezone.utc))

    def invalidate(self) -> None:
        self.db.del_state("ml:expires_at")

    def token(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        access, exp = self.db.get_state("ml:access_token"), self.db.get_state("ml:expires_at")
        if access and exp and datetime.fromisoformat(exp) - timedelta(seconds=120) > now:
            return access
        refresh = self.db.get_state("ml:refresh_token")
        if not refresh:
            raise MLAuthError("sem token do Mercado Livre: rode `python -m precos ml-auth <code>` (veja `ml-auth-url`)")
        self._token_request({"grant_type": "refresh_token", "refresh_token": refresh}, now)
        return self.db.get_state("ml:access_token")


class MercadoLivreCollector:
    store = "mercadolivre"

    def __init__(self, auth: MLAuth, user_agent: str, client: httpx.Client | None = None, sleep=time.sleep,
                 delay: float = 1.0, clock=lambda: datetime.now(timezone.utc)):
        self.auth, self.ua, self.sleep, self.delay, self.clock = auth, user_agent, sleep, delay, clock
        self.client = client or httpx.Client(timeout=20)

    def _get(self, path: str) -> dict:
        refreshed = False
        for attempt in range(3):
            self.sleep(self.delay)
            r = self.client.get(f"{API}{path}", headers={"Authorization": f"Bearer {self.auth.token(self.clock())}",
                                                         "User-Agent": self.ua, "Accept": "application/json"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and not refreshed:
                refreshed = True
                self.auth.invalidate()  # token vencido antes da hora: renova e tenta de novo, uma vez
                continue
            if r.status_code == 429:
                wait = min(float(r.headers.get("retry-after", 30) or 30), 60)
                if attempt == 0:
                    self.sleep(wait)
                    continue
                raise FetchError(f"Mercado Livre limitou as chamadas (429) em {path}")
            if r.status_code == 403:
                raise FetchError(f"Mercado Livre negou acesso (403) a {path}: confira o token, os escopos e os Termos do Programa de Desenvolvedores. "
                                 f"Resposta: {_brief(r)}")
            if r.status_code == 404:
                raise FetchError(f"não encontrado no Mercado Livre: {path}")
            if r.status_code >= 500:
                self.sleep(2**attempt)
                continue
            raise FetchError(f"Mercado Livre respondeu {r.status_code} em {path}. Resposta: {_brief(r)}")
        raise FetchError(f"falhou 3 vezes em {path}")

    def fetch(self, product: Product, url: str) -> Offer:
        kind, ident = resolve(url)
        if kind == "product":  # catálogo: usa o anúncio vencedor da buy box
            winner = (self._get(f"/products/{ident}").get("buy_box_winner") or {}).get("item_id")
            if not winner:
                raise ParseError(f"produto de catálogo {ident} sem vencedor da buy box")
            ident = winner
        return parse_item(self._get(f"/items/{ident}"), product.id, url, self.clock())
