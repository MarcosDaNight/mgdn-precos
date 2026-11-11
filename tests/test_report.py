from conftest import NOW, offer
from precos import report


def ml(title, **kw):
    return offer(product_id="x", store="mercadolivre", title=title, seller="Loja Oficial #1", first_party=True,
                 price_pix=3799.0, url="https://produto.mercadolivre.com.br/MLB-1", **kw)


def test_mostra_o_que_foi_lido_de_forma_legivel():
    txt = report.format_offer(ml("Console Nintendo Switch 2", free_shipping=True))
    for piece in ("título:       Console Nintendo Switch 2", "R$ 3.799,00", "Loja Oficial #1", "loja oficial/própria: sim", "frete grátis: sim"):
        assert piece in txt
    assert "frete grátis: não informado" in report.format_offer(ml("x"))


def test_oferta_aceita_diz_para_qual_produto(real_config):
    lines = report.verdict_lines(ml("Jogo The Legend of Zelda Ocarina of Time Nintendo Switch 2 Edição Capa Normal"), real_config)
    assert lines == ["ACEITO para: zelda-ocarina"]


def test_avalia_contra_todos_e_nao_so_contra_o_primeiro(real_config):
    # o primeiro produto do config é o console: um controle NÃO pode ser julgado contra ele
    lines = report.verdict_lines(ml("Controle Nintendo Switch 2 Pro Controller Original"), real_config)
    assert lines[0].startswith("ACEITO para:") and "pro-controller" in lines[0]


def test_sem_produto_aceito_lista_o_motivo_de_cada_um(real_config):
    lines = report.verdict_lines(ml("Console Nintendo Switch 2 Mario Kart World Bundle"), real_config)
    assert lines[0] == "NENHUM produto aceita esta oferta. Motivo por produto:"
    assert any(l.startswith("  console: palavra proibida") for l in lines)
    assert len(lines) == 1 + len(real_config.products)


def test_filtra_por_um_produto_e_avisa_id_inexistente(real_config):
    assert report.verdict_lines(ml("Console Nintendo Switch 2"), real_config, only="console") == ["ACEITO para: console"]
    assert "não existe no config" in report.verdict_lines(ml("x"), real_config, only="nada")[0]


def test_console_modelo_nacional_sem_256_no_titulo_e_aceito(real_config):
    """Slug real do anúncio: o Switch 2 só tem 256 GB, então o título não precisa dizer."""
    assert report.verdict_lines(ml("Console Nintendo Switch 2 Modelo Nacional De Tomada"), real_config) == ["ACEITO para: console"]
