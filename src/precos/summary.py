from __future__ import annotations

from datetime import datetime, timedelta

from .alerts import brl, target_text
from .config import Config
from .db import DB


def build_summary(cfg: Config, db: DB, now: datetime) -> tuple[str, str]:
    """Melhor preço de cada item (última leitura de cada loja nas últimas 24 h) e total do carrinho."""
    lines, total, found = [], 0.0, 0
    for p in cfg.products:
        rows = db.latest_by_store(p.id, now - timedelta(hours=24))
        if not rows:
            lines.append(f"• {p.name}: sem oferta válida nas últimas 24 h")
            continue
        best = rows[0]
        total += best["best_price"]
        found += 1
        how = "Pix" if best["price_pix"] is not None and best["price_pix"] == best["best_price"] else "parcelado"
        lines.append(f"• {p.name}: {brl(best['best_price'])} ({best['store']}, {how}) · meta {target_text(p)}")
    lines.append("")
    missing = len(cfg.products) - found
    lines.append(f"Total do carrinho ({found} itens): {brl(total)}" + (f" — faltam {missing} sem oferta" if missing else ""))
    return "Resumo diário de preços", "\n".join(lines)
