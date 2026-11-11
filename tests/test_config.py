import pytest

from precos import config as c


def base(**p):
    prod = {"id": "x", "category": "game", "required": ["switch 2"], "target": 100, "stores": {"kabum": ["https://k.test/p"]}}
    prod.update(p)
    return {"products": [prod]}


def test_config_do_repositorio_e_valida(real_config):
    assert {p.id for p in real_config.products} >= {"console", "zelda-ocarina"}
    console = next(p for p in real_config.products if p.id == "console")
    assert (console.targets.pix, console.targets.installment) == (3700, 3800)
    ocarina = next(p for p in real_config.products if p.id == "zelda-ocarina")
    assert ocarina.targets.any == 399 and ocarina.physical_only is True
    assert real_config.schedule.burst_from.isoformat() == "2026-11-20"


def test_jogo_e_fisico_por_padrao_e_acessorio_nao():
    assert c.parse(base()).products[0].physical_only is True
    assert c.parse(base(category="accessory")).products[0].physical_only is False


@pytest.mark.parametrize("raw, msg", [
    (base(required=[]), "required"),
    (base(category="brinquedo"), "category"),
    (base(stores={"kabum": ["http://k.test/p"]}), "https"),
    (base(target={"pix": 1, "boleto": 2}), "desconhecidas"),
    ({"products": [{"id": "x", "category": "game", "required": ["a"]}, {"id": "x", "category": "game", "required": ["a"]}]}, "repetido"),
])
def test_config_invalida_da_erro_claro(raw, msg):
    with pytest.raises(c.ConfigError, match=msg):
        c.parse(raw)


def test_palavras_sao_normalizadas_para_minusculas():
    assert c.parse(base(required=["Switch 2 "])).products[0].required == ("switch 2",)
