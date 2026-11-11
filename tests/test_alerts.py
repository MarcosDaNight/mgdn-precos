from datetime import timedelta

from conftest import NOW, make_config, offer, seed_history
from precos import alerts
from precos.config import AlertRules

RULES = AlertRules()


def prod(real_config, pid):
    return next(p for p in real_config.products if p.id == pid)


def ev(real_config, db, pid, now=NOW, **kw):
    return alerts.evaluate(prod(real_config, pid), offer(product_id=pid, **kw), db, now, RULES)


def test_meta_no_pix_do_console(real_config, db):
    a = ev(real_config, db, "console", price_pix=3650.0)
    assert a and a.reasons == ("meta",) and a.verdict == "COMPRAR"


def test_meta_no_parcelado_sem_juros(real_config, db):
    a = ev(real_config, db, "console", price_pix=3950.0, installments=12, installment_amount=316.66, interest_free=True)
    assert a and "meta" in a.reasons  # 12 x 316,66 = 3.799,92 <= 3.800


def test_parcelado_com_juros_nao_atinge_a_meta(real_config, db):
    assert ev(real_config, db, "console", price_pix=3950.0, installments=12, installment_amount=300.0, interest_free=False) is None


def test_acima_da_meta_e_sem_historico_nao_alerta(real_config, db):
    assert ev(real_config, db, "console", price_pix=3859.0) is None


def test_meta_unica_vale_para_o_menor_preco(real_config, db):
    assert ev(real_config, db, "zelda-ocarina", price_pix=399.0).verdict == "COMPRAR"
    assert ev(real_config, db, "zelda-ocarina", price_pix=409.0) is None


def test_novo_minimo_historico_sem_meta_e_esperar(real_config, db):
    seed_history(db, "console", [4100.0, 4000.0, 4050.0])
    a = ev(real_config, db, "console", price_pix=3950.0)
    assert a and a.reasons == ("minimo",) and a.verdict == "ESPERAR" and a.hist_min == 3950.0


def test_minimo_e_queda_exigem_historico_minimo(real_config, db):
    seed_history(db, "console", [4100.0, 4000.0])  # só 2 < min_history (3)
    assert ev(real_config, db, "console", price_pix=3900.0) is None


def test_queda_de_8_por_cento_sobre_a_mediana_de_14_dias(real_config, db):
    seed_history(db, "pokemon-za", [440.0, 440.0, 440.0, 440.0, 420.0])
    a = ev(real_config, db, "pokemon-za", price_pix=400.0)  # 400 <= 440 * 0.92
    assert a and "queda" in a.reasons


def test_queda_menor_que_8_por_cento_nao_conta(real_config, db):
    seed_history(db, "pokemon-za", [400.0, 440.0, 440.0, 440.0])  # mediana 440, mínimo 400
    assert ev(real_config, db, "pokemon-za", price_pix=410.0) is None  # -6,8%: abaixo de 8% e não é mínimo


def test_nao_repete_em_24h_salvo_se_o_preco_cair_de_novo(real_config, db):
    db.record_alert(NOW - timedelta(hours=2), "console", "fake", 3650.0, ["meta"])
    assert ev(real_config, db, "console", price_pix=3650.0) is None  # mesmo preço
    assert ev(real_config, db, "console", price_pix=3700.0) is None  # mais caro
    assert ev(real_config, db, "console", price_pix=3600.0) is not None  # caiu de novo


def test_depois_de_24h_pode_repetir(real_config, db):
    db.record_alert(NOW - timedelta(hours=25), "console", "fake", 3650.0, ["meta"])
    assert ev(real_config, db, "console", price_pix=3650.0) is not None


def test_dedup_e_por_produto_e_loja(real_config, db):
    db.record_alert(NOW - timedelta(hours=2), "console", "outra-loja", 3650.0, ["meta"])
    assert ev(real_config, db, "console", price_pix=3650.0) is not None


def test_esgotado_nao_alerta_mesmo_abaixo_da_meta(real_config, db):
    assert ev(real_config, db, "console", price_pix=3000.0, available=False) is None


def test_recomendacao_parcelar_so_ate_5_por_cento_a_mais_que_o_pix():
    barato = offer(price_pix=1000.0, installments=12, installment_amount=87.0, interest_free=True)  # 1044 = +4,4%
    caro = offer(price_pix=4463.07, installments=10, installment_amount=479.9, interest_free=True)  # +7,5%
    assert alerts.payment_advice(barato, RULES).startswith("parcelar em 12x")
    assert alerts.payment_advice(caro, RULES).startswith("pagar no Pix")
    assert alerts.payment_advice(offer(price_pix=100.0), RULES).startswith("pagar no Pix")


def test_limite_exato_de_5_por_cento_ainda_parcela():
    o = offer(price_pix=1000.0, installments=10, installment_amount=105.0, interest_free=True)  # exatamente +5%
    assert alerts.payment_advice(o, RULES).startswith("parcelar")


def test_brl_formata_em_reais():
    assert alerts.brl(3789) == "R$ 3.789,00"
    assert alerts.brl(4463.07) == "R$ 4.463,07"
    assert alerts.brl(1234567.5) == "R$ 1.234.567,50"
    assert alerts.brl(None) == "—"


def test_mensagem_traz_o_que_foi_pedido(real_config, db):
    seed_history(db, "console", [4100.0, 4000.0, 4050.0])
    a = ev(real_config, db, "console", price_pix=3650.0, installments=10, installment_amount=400.0, interest_free=True)
    title, msg, prio = alerts.format_alert(a)
    assert title == "COMPRAR · Console Nintendo Switch 2 256 GB" and prio == 4
    for piece in ("Pix: R$ 3.650,00", "10x R$ 400,00 = R$ 4.000,00 sem juros", "Loja: fake",
                  "Meta: Pix R$ 3.700,00 / parcelado R$ 3.800,00", "Mínimo histórico: R$ 3.650,00",
                  "meta atingida", "novo mínimo histórico", "Veredito: COMPRAR", "Recomendação: pagar no Pix"):
        assert piece in msg, piece
