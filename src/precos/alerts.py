"""Quando avisar: preço <= meta, novo mínimo histórico ou queda >= 8% sobre a mediana de 14 dias.
Sem repetir o mesmo produto e loja em 24 h, salvo se o preço cair de novo."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import AlertRules, Product
from .db import DB
from .models import Offer


def brl(v: float | None) -> str:
    if v is None:
        return "—"
    s = f"{v:,.2f}"  # 3,789.00 -> 3.789,00
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass(frozen=True)
class Alert:
    product: Product
    offer: Offer
    reasons: tuple[str, ...]  # meta | minimo | queda
    verdict: str  # COMPRAR | ESPERAR
    hist_min: float | None
    payment_advice: str


SUSPECT_RATIO = 0.5  # abaixo de 50% da mediana recente, desconfia de erro de leitura
CONFIRM_TOLERANCE = 0.03  # a 2ª leitura confirma se ficar a até 3% da 1ª


def is_suspect(product: Product, offer: Offer, db: DB, now: datetime, rules: AlertRules) -> bool:
    """Preço muito abaixo da mediana: pode ser promoção real ou erro do parser (R$ 4,99 em vez de R$ 499).
    Só vale depois de uma segunda leitura parecida. Precisa de histórico; sem ele, a guarda não atua."""
    best = offer.best_price
    if best is None:
        return False
    median = db.median_since(product.id, now - timedelta(days=rules.drop_window_days), rules.min_history)
    return median is not None and best < median * SUSPECT_RATIO


def confirmed(db: DB, offer: Offer, suspect_prefix: str) -> bool:
    """A leitura anterior desta mesma URL foi recusada como suspeita e esta chegou a até 3% dela?"""
    prev = db.last_offer_for_url(offer.url)
    best = offer.best_price
    if prev is None or best is None or not (prev["reject_reason"] or "").startswith(suspect_prefix):
        return False
    return prev["best_price"] is not None and abs(best - prev["best_price"]) <= prev["best_price"] * CONFIRM_TOLERANCE


def meets_target(product: Product, offer: Offer) -> bool:
    t = product.targets
    if t.pix is not None and offer.price_pix is not None and offer.price_pix <= t.pix:
        return True
    if t.installment is not None and offer.installment_total is not None and offer.installment_total <= t.installment:
        return True
    return t.any is not None and offer.best_price is not None and offer.best_price <= t.any


def payment_advice(offer: Offer, rules: AlertRules) -> str:
    """Parcelar só quando o sem juros custa até X% a mais que o Pix."""
    pix, total = offer.price_pix, offer.installment_total
    if pix and total:
        extra = (total / pix - 1) * 100
        plan = f"{offer.installments}x sem juros"
        # Compara em centavos: 1050 contra 1000 é exatamente +5%, e o ponto flutuante daria 5,0000000000000004.
        if round(total, 2) <= round(pix * (1 + rules.installment_vs_pix_pct / 100), 2):
            return f"parcelar em {plan} (custa só {extra:.1f}% a mais que o Pix)"
        return f"pagar no Pix (o parcelado em {plan} custa {extra:.1f}% a mais)"
    if pix:
        return "pagar no Pix (sem parcelamento sem juros)"
    if total:
        return f"parcelar em {offer.installments}x sem juros (sem preço no Pix)"
    return "conferir as condições de pagamento na loja"


def evaluate(product: Product, offer: Offer, db: DB, now: datetime, rules: AlertRules) -> Alert | None:
    """Chame ANTES de gravar a oferta no histórico, para ela não se comparar consigo mesma."""
    best = offer.best_price
    if best is None or not offer.available:
        return None

    reasons = []
    on_target = meets_target(product, offer)
    if on_target:
        reasons.append("meta")
    hist_min = db.history_min(product.id)
    enough_history = db.history_count(product.id) >= rules.min_history
    if enough_history and hist_min is not None and best < hist_min:
        reasons.append("minimo")
    median = db.median_since(product.id, now - timedelta(days=rules.drop_window_days), rules.min_history)
    if median is not None and best <= median * (1 - rules.drop_pct / 100):
        reasons.append("queda")
    if not reasons:
        return None

    last = db.last_alert(product.id, offer.store)
    if last is not None:
        age = now - datetime.fromisoformat(last["ts"])
        if age < timedelta(hours=rules.dedupe_hours) and best >= last["price"]:
            return None  # já avisei há pouco e o preço não caiu de novo

    return Alert(
        product=product,
        offer=offer,
        reasons=tuple(reasons),
        verdict="COMPRAR" if on_target else "ESPERAR",
        hist_min=min(hist_min, best) if hist_min is not None else best,
        payment_advice=payment_advice(offer, rules),
    )


_REASON_TEXT = {"meta": "meta atingida", "minimo": "novo mínimo histórico", "queda": "queda sobre a mediana recente"}


def target_text(product: Product) -> str:
    t, parts = product.targets, []
    if t.pix is not None:
        parts.append(f"Pix {brl(t.pix)}")
    if t.installment is not None:
        parts.append(f"parcelado {brl(t.installment)}")
    if t.any is not None:
        parts.append(brl(t.any))
    return " / ".join(parts) or "sem meta"


def format_alert(a: Alert) -> tuple[str, str, int]:
    """(título, mensagem, prioridade do ntfy)."""
    o = a.offer
    parcel = (
        f"{o.installments}x {brl(o.installment_amount)} = {brl(o.installment_total)} sem juros"
        if o.installment_total
        else "sem parcelado sem juros"
    )
    lines = [
        a.product.name,
        f"Pix/à vista: {brl(o.price_pix)}",
        f"Parcelado: {parcel}",
        f"Loja: {o.store}",
        f"Meta: {target_text(a.product)}",
        f"Mínimo histórico: {brl(a.hist_min)}",
        f"Motivo: {', '.join(_REASON_TEXT[r] for r in a.reasons)}",
        f"Recomendação: {a.payment_advice}",
        f"Veredito: {a.verdict}",
    ]
    return f"{a.verdict} · {a.product.name}", "\n".join(lines), 4 if a.verdict == "COMPRAR" else 3
