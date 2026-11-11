from __future__ import annotations

import logging
import time
from typing import Protocol
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, title: str, message: str, *, priority: int = 3, tags: tuple[str, ...] = (), click: str | None = None) -> None: ...


class ConsoleNotifier:
    """Para --dry-run (e para a falta de NTFY_URL): mostra o que seria enviado, sem enviar.
    `delivers = False`: o que sai aqui NÃO conta como avisado, para a deduplicação não engolir o alerta real depois."""

    delivers = False

    def send(self, title, message, *, priority=3, tags=(), click=None):
        print(f"--- ntfy (prioridade {priority}) {' '.join(tags)}\n{title}\n{message}" + (f"\n{click}" if click else ""))


class NtfyNotifier:
    """Publica no ntfy por JSON (aceita UTF-8 em título e mensagem). `url` é a URL completa do tópico
    secreto, por exemplo https://ntfy.sh/precos-xxxxxxxx, e vem de um segredo, nunca do repositório."""

    def __init__(self, url: str, client: httpx.Client | None = None, sleep=time.sleep):
        parts = urlsplit(url)
        self.base = f"{parts.scheme}://{parts.netloc}"
        self.topic = parts.path.strip("/")
        if not self.topic:
            raise ValueError("a URL do ntfy precisa incluir o tópico")
        self.client = client or httpx.Client(timeout=15)
        self.sleep = sleep

    def send(self, title, message, *, priority=3, tags=(), click=None):
        body = {"topic": self.topic, "title": title, "message": message, "priority": priority, "tags": list(tags)}
        if click:
            body["click"] = click
            body["actions"] = [{"action": "view", "label": "Abrir loja", "url": click}]
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.client.post(self.base, json=body)
                if r.status_code < 300:
                    return
                last = RuntimeError(f"ntfy respondeu {r.status_code}")
            except httpx.HTTPError as e:
                last = e
            self.sleep(2**attempt)
        log.error("ntfy: não consegui enviar (%s)", last)
        raise RuntimeError(f"ntfy indisponível: {last}")
