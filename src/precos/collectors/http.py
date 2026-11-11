from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlsplit

import httpx

from .robots import Robots

log = logging.getLogger(__name__)


class FetchError(Exception):
    pass


class Blocked(FetchError):
    """A loja barrou o nosso User-Agent identificável (403/429). Por regra, a loja sai do coletor."""


class RobotsDisallowed(FetchError):
    pass


class PoliteClient:
    """GET educado: User-Agent identificável, robots.txt, atraso entre pedidos ao mesmo host e retry com
    backoff só para falhas de rede e 5xx. 403/429 nunca é repetido nem contornado."""

    def __init__(self, user_agent: str, delay: float = 5.0, client: httpx.Client | None = None,
                 sleep=time.sleep, monotonic=time.monotonic):
        self.ua = user_agent
        self.delay = delay
        self.client = client or httpx.Client(timeout=20, follow_redirects=True)
        self.sleep, self.monotonic = sleep, monotonic
        self._last: dict[str, float] = {}
        self._robots: dict[str, Robots] = {}

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.ua, "Accept": "text/html,application/json;q=0.9", "Accept-Language": "pt-BR,pt;q=0.9"}

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = self.delay + random.uniform(0, self.delay * 0.3) - (self.monotonic() - last)
            if gap > 0:
                self.sleep(gap)
        self._last[host] = self.monotonic()

    def _robots_for(self, scheme: str, host: str) -> Robots:
        if host not in self._robots:
            self._wait(host)
            try:
                r = self.client.get(f"{scheme}://{host}/robots.txt", headers=self._headers())
            except httpx.HTTPError as e:
                raise FetchError(f"não consegui ler o robots.txt de {host}: {e}") from e
            if r.status_code == 404:
                text = ""  # sem robots.txt: sem restrições declaradas
            elif r.status_code == 200:
                text = r.text
            else:
                raise FetchError(f"robots.txt de {host} respondeu {r.status_code}; por segurança não coleto")
            self._robots[host] = Robots(text, self.ua)
        return self._robots[host]

    def get(self, url: str) -> str:
        parts = urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if not self._robots_for(parts.scheme, parts.netloc).allowed(path):
            raise RobotsDisallowed(f"robots.txt de {parts.netloc} não permite {path}")
        last: Exception | None = None
        for attempt in range(3):
            self._wait(parts.netloc)
            try:
                r = self.client.get(url, headers=self._headers())
            except httpx.HTTPError as e:
                last = e
            else:
                if r.status_code in (403, 429):
                    raise Blocked(f"{parts.netloc} respondeu {r.status_code} ao User-Agent identificável")
                if r.status_code >= 500:
                    last = FetchError(f"{parts.netloc} respondeu {r.status_code}")
                elif r.status_code >= 400:
                    raise FetchError(f"{url} respondeu {r.status_code}")
                else:
                    return r.text
            self.sleep(2**attempt)
        raise FetchError(f"falhou 3 vezes: {last}")
