import json
import re

import pytest

from conftest import NOW, fixture
from precos.collectors.kabum import ParseError, parse

URL = "https://www.kabum.com.br/produto/1/x"


def test_console_esgotado_traz_o_preco_mas_nao_esta_disponivel():
    o = parse(fixture("kabum_console_esgotado.html"), "console", URL, NOW)
    assert o.available is False
    assert o.price_pix == 4499
    assert o.first_party is True and o.seller == "KaBuM!"
    assert o.installments is None and o.installment_total is None
    assert o.best_price == 4499
    assert "256GB" in o.title and o.condition == "new" and o.digital is False


def test_em_estoque_le_pix_cartao_e_parcelas_sem_juros():
    o = parse(fixture("kabum_bundle_em_estoque.html"), "console", URL, NOW)
    assert o.available is True
    assert o.price_pix == 4463.07  # priceWithDiscount: o Pix
    assert o.price_card == 4799
    assert (o.installments, o.installment_amount, o.interest_free) == (10, 479.9, True)
    assert o.installment_total == 4799.0
    assert o.best_price == 4463.07
    assert o.free_shipping is False


def test_jogo_fisico_esgotado():
    o = parse(fixture("kabum_ocarina_esgotado.html"), "ocarina", URL, NOW)
    assert o.price_pix == 439.9 and o.available is False and o.digital is False


def _page_with(mutate) -> str:
    html = fixture("kabum_bundle_em_estoque.html")
    m = re.search(r'(<script id="__NEXT_DATA__" type="application/json">)(.*?)(</script>)', html, re.S)
    data = json.loads(m.group(2))
    mutate(data["props"]["pageProps"]["product"])
    return html[: m.start(2)] + json.dumps(data) + html[m.end(2):]


def test_marketplace_nao_conta_como_vendedor_proprio():
    def mk(p):
        p["flags"]["isMarketplace"] = True
        p["sellerName"] = "MOOVE GAMES"
    o = parse(_page_with(mk), "x", URL, NOW)
    assert o.first_party is False and o.seller == "MOOVE GAMES"


def test_vendedor_desconhecido_mesmo_sem_flag_de_marketplace_nao_e_proprio():
    def mk(p):
        p["sellerName"] = "Outra Loja LTDA"
    assert parse(_page_with(mk), "x", URL, NOW).first_party is False


def test_parcelas_com_juros_nao_sao_sem_juros():
    def mk(p):
        p["installment"]["hasFee"] = True
    o = parse(_page_with(mk), "x", URL, NOW)
    assert o.interest_free is False and o.installment_total is None
    assert o.best_price == o.price_pix  # o parcelado com juros não compete


def test_digital_e_open_box_vem_das_flags():
    def mk(p):
        p["flags"]["isDigital"] = True
        p["flags"]["isOpenbox"] = True
    o = parse(_page_with(mk), "x", URL, NOW)
    assert o.digital is True and o.condition == "refurbished"


def test_reserva_json_ld_nunca_vira_vendedor_proprio():
    ld = ('<script type="application/ld+json">{"@type":"Product","name":"Console Switch 2",'
          '"offers":{"price":4000,"availability":"https://schema.org/InStock"}}</script>')
    o = parse(f"<html>{ld}</html>", "console", URL, NOW)
    assert o.price_pix == 4000 and o.available is True and o.first_party is False


def test_layout_desconhecido_vira_erro_claro():
    with pytest.raises(ParseError, match="layout"):
        parse("<html><body>sem dados</body></html>", "x", URL, NOW)
