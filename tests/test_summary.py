from conftest import NOW, make_config, offer
from precos.summary import build_summary


def test_resumo_pega_o_melhor_de_cada_item_e_soma_o_carrinho(db):
    cfg = make_config()
    db.insert_offer(offer(product_id="a", store="fake", price_pix=90.0), True)
    db.insert_offer(offer(product_id="a", store="outra", price_pix=80.0), True)
    db.insert_offer(offer(product_id="b", store="fake", title="Zelda", price_pix=290.0), True)
    title, msg = build_summary(cfg, db, NOW)
    assert title == "Resumo diário de preços"
    assert "Produto A: R$ 80,00 (outra, Pix)" in msg
    assert "Produto B: R$ 290,00 (fake, Pix)" in msg
    assert "Total do carrinho (2 itens): R$ 370,00" in msg


def test_item_sem_oferta_valida_aparece_e_nao_entra_no_total(db):
    cfg = make_config()
    db.insert_offer(offer(product_id="a", price_pix=90.0), True)
    db.insert_offer(offer(product_id="b", title="Zelda", price_pix=10.0), False, "vendedor de terceiros")  # recusada
    _, msg = build_summary(cfg, db, NOW)
    assert "Produto B: sem oferta válida" in msg
    assert "Total do carrinho (1 itens): R$ 90,00 — faltam 1 sem oferta" in msg


def test_esgotado_nao_entra_no_resumo(db):
    cfg = make_config()
    db.insert_offer(offer(product_id="a", price_pix=90.0, available=False), True)
    _, msg = build_summary(cfg, db, NOW)
    assert "Produto A: sem oferta válida" in msg


def test_so_considera_as_ultimas_24h(db):
    from datetime import timedelta
    cfg = make_config()
    db.insert_offer(offer(product_id="a", price_pix=90.0, fetched_at=NOW - timedelta(hours=30)), True)
    _, msg = build_summary(cfg, db, NOW)
    assert "Produto A: sem oferta válida" in msg
