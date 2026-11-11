import pytest

from conftest import NOW, fixture, offer
from precos import filters
from precos.collectors.kabum import parse


def product(real_config, pid):
    return next(p for p in real_config.products if p.id == pid)


def check(real_config, pid, **kw):
    return filters.evaluate(product(real_config, pid), offer(product_id=pid, **kw), real_config.default_forbidden)


def test_console_certo_passa(real_config):
    o = parse(fixture("kabum_console_esgotado.html"), "console", "https://x/1", NOW)
    assert filters.evaluate(product(real_config, "console"), o, real_config.default_forbidden).ok


def test_bundle_com_console_nao_e_o_console(real_config):
    o = parse(fixture("kabum_bundle_em_estoque.html"), "console", "https://x/1", NOW)
    v = filters.evaluate(product(real_config, "console"), o, real_config.default_forbidden)
    assert not v.ok and "bundle" in v.reason


def test_terceiros_sao_recusados(real_config):
    v = check(real_config, "console", title="Console Nintendo Switch 2 256GB", first_party=False, seller="MOOVE GAMES")
    assert not v.ok and "terceiros" in v.reason and "MOOVE" in v.reason


@pytest.mark.parametrize("title, fragment", [
    ("Console Nintendo Switch 2 256GB Recondicionado", "recondicionado"),
    ("Console Nintendo Switch 2 256GB Usado", "usado"),
    ("Console Nintendo Switch 2 256GB Importado", "importado"),
])
def test_usado_recondicionado_e_importado(real_config, title, fragment):
    v = check(real_config, "console", title=title)
    assert not v.ok and fragment in v.reason


def test_condicao_vem_do_coletor(real_config):
    v = check(real_config, "console", title="Console Nintendo Switch 2 256GB", condition="refurbished")
    assert not v.ok and "refurbished" in v.reason


def test_switch_1_nao_confunde_com_switch_2(real_config):
    v = check(real_config, "zelda-ocarina", title="Jogo The Legend of Zelda: Ocarina of Time, Nintendo Switch")
    assert not v.ok and "switch 2" in v.reason


def test_jogo_fisico_passa_e_acentos_nao_atrapalham(real_config):
    assert check(real_config, "zelda-ocarina", title="Jogo The Legend of Zelda: Ocarina of Time, Nintendo Switch 2, Edição Capa Normal").ok
    assert check(real_config, "pokemon-za", title="Jogo Pokémon Legends Z-A, Nintendo Switch 2").ok


@pytest.mark.parametrize("title", [
    "Gift Card The Legend of Zelda: Breath of the Wild - Pacote de Melhoria, Nintendo Switch 2 Edition",
    "Zelda Breath of the Wild Switch 2 Edition - Código Digital",
    "Zelda Breath of the Wild Switch 2 Edition Game-Key Card",
    "Zelda Breath of the Wild Switch 2 Edition Game Key",
])
def test_jogo_digital_e_game_key_card_sao_recusados(real_config, title):
    assert not check(real_config, "zelda-botw", title=title).ok


def test_flag_digital_do_coletor_recusa_jogo(real_config):
    v = check(real_config, "zelda-botw", title="Jogo Zelda Breath of the Wild Nintendo Switch 2 Edition", digital=True)
    assert not v.ok and "digital" in v.reason


def test_flag_digital_nao_afeta_console(real_config):
    assert check(real_config, "console", title="Console Nintendo Switch 2 256GB", digital=True).ok
