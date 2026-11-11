from __future__ import annotations

import os
from pathlib import Path


def env_or_file(name: str, default: str | None = None) -> str | None:
    """Lê NAME ou, se existir, o arquivo apontado por NAME_FILE (segredos da plataforma entram por arquivo,
    montado somente leitura). Arquivo ausente ou vazio conta como 'não configurado'."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        return value or default
    return os.environ.get(name) or default
