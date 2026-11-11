"""Dead-man's switch: a cada rodada que coleta de verdade, avisa o Healthchecks (o mesmo serviço que a
plataforma já usa). Se passar o prazo sem aviso, é o Healthchecks que alerta, mesmo com o coletor travado."""
from __future__ import annotations

import httpx


def make_heartbeat(url: str, client: httpx.Client | None = None):
    c = client or httpx.Client(timeout=10)

    def beat() -> None:
        r = c.get(url)
        r.raise_for_status()

    return beat
