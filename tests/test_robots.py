from precos.collectors.robots import Robots

KABUM = """
User-agent: *
Allow: /.css
Disallow: /carrinho*
Disallow: /busca/*?
Disallow: *?query=*
Disallow: *sort=-price
Disallow: /manager/

User-agent: Googlebot
Disallow:
"""
UA = "mgdn-precos/0.1 (monitor pessoal de precos)"


def test_pagina_de_produto_liberada_e_busca_com_query_bloqueada():
    r = Robots(KABUM, UA)
    assert r.allowed("/produto/777177/console-nintendo-switch-2")
    assert not r.allowed("/busca/switch?page=2")
    assert r.allowed("/busca/switch")
    assert not r.allowed("/produto/1?query=a")
    assert not r.allowed("/carrinho/x")
    assert not r.allowed("/gamer/nintendo?sort=-price")


def test_grupo_especifico_do_agente_vence_o_curinga():
    r = Robots("User-agent: *\nDisallow: /\n\nUser-agent: mgdn-precos\nAllow: /\n", UA)
    assert r.allowed("/qualquer")


def test_curinga_vale_quando_nao_ha_grupo_especifico():
    assert not Robots("User-agent: *\nDisallow: /\n", UA).allowed("/qualquer")


def test_regra_mais_longa_vence_e_empate_vai_para_allow():
    r = Robots("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /c\nAllow: /c\n", UA)
    assert r.allowed("/a/b/x") and not r.allowed("/a/c")
    assert r.allowed("/c")


def test_disallow_vazio_nao_bloqueia_e_dolar_ancora_o_fim():
    assert Robots("User-agent: *\nDisallow:\n", UA).allowed("/x")
    r = Robots("User-agent: *\nDisallow: /*.php$\n", UA)
    assert not r.allowed("/index.php") and r.allowed("/index.php?x=1")


def test_sem_regras_tudo_liberado():
    assert Robots("", UA).allowed("/x")
