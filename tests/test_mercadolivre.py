from datetime import timedelta

import httpx
import pytest

from conftest import NOW, make_config
from precos import filters
from precos.collectors.http import FetchError
from precos.collectors.mercadolivre import MercadoLivreCollector, MLAuth, MLAuthError, ParseError, parse_item, resolve

REDIRECT = "https://precos.mgdn.com.br/ml/callback"
ITEM = {"id": "MLB3456789012", "title": "Console Nintendo Switch 2 256gb", "price": 3799.0, "condition": "new",
        "status": "active", "available_quantity": 5, "official_store_id": 1234, "seller_id": 99,
        "permalink": "https://produto.mercadolivre.com.br/MLB-3456789012-console-nintendo-switch-2", "shipping": {"free_shipping": True}}
TOKEN = {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 21600, "token_type": "Bearer"}


def client(routes, calls=None):
    def handler(request):
        if calls is not None:
            calls.append((request.method, request.url.path, dict(request.headers)))
        out = routes[request.url.path]
        return out(request) if callable(out) else out
    return httpx.Client(transport=httpx.MockTransport(handler))


def auth(db, c):
    return MLAuth(db, "APP123", "SEGREDO", REDIRECT, client=c)


# --- resolução de URL ---------------------------------------------------------------------
@pytest.mark.parametrize("url, expected", [
    ("https://produto.mercadolivre.com.br/MLB-3456789012-console-nintendo-switch-2_JM", ("item", "MLB3456789012")),
    ("https://www.mercadolivre.com.br/MLB3456789012", ("item", "MLB3456789012")),
    ("https://www.mercadolivre.com.br/console-nintendo-switch-2/p/MLB44556677", ("product", "MLB44556677")),
])
def test_resolve_aceita_anuncio_e_catalogo(url, expected):
    assert resolve(url) == expected


@pytest.mark.parametrize("url", ["https://www.mercadolivre.com.br/x/up/MLBU123", "https://www.mercadolivre.com.br/sem-id"])
def test_resolve_recusa_o_que_nao_entende(url):
    with pytest.raises(ParseError):
        resolve(url)


# --- leitura do anúncio -------------------------------------------------------------------
def test_loja_oficial_ativa_vira_vendedor_proprio():
    o = parse_item(ITEM, "console", "https://x", NOW)
    assert o.first_party and o.available and o.condition == "new"
    assert o.price_pix == 3799.0 and o.best_price == 3799.0 and o.free_shipping is True
    assert o.seller == "Loja Oficial #1234" and o.url == ITEM["permalink"]


def test_vendedor_comum_nao_e_loja_oficial():
    o = parse_item({**ITEM, "official_store_id": None}, "console", "https://x", NOW)
    assert o.first_party is False and o.seller == "vendedor #99"


@pytest.mark.parametrize("patch, available", [({"status": "paused"}, False), ({"available_quantity": 0}, False)])
def test_pausado_ou_sem_estoque_nao_esta_disponivel(patch, available):
    assert parse_item({**ITEM, **patch}, "console", "https://x", NOW).available is available


def test_usado_e_condicao_desconhecida_sao_recusados_pelos_filtros(real_config):
    console = next(p for p in real_config.products if p.id == "console")
    for cond in ("used", "not_specified"):
        o = parse_item({**ITEM, "condition": cond}, "console", "https://x", NOW)
        assert not filters.evaluate(console, o, real_config.default_forbidden).ok
    assert filters.evaluate(console, parse_item(ITEM, "console", "https://x", NOW), real_config.default_forbidden).ok


def test_anuncio_sem_preco_e_erro_claro():
    with pytest.raises(ParseError, match="sem preço"):
        parse_item({**ITEM, "price": None}, "console", "https://x", NOW)


# --- OAuth ---------------------------------------------------------------------------------
def test_url_de_autorizacao_leva_client_id_e_redirect(db):
    url = auth(db, client({})).authorize_url()
    assert url.startswith("https://auth.mercadolivre.com.br/authorization?")
    assert "client_id=APP123" in url and "response_type=code" in url and "redirect_uri=https%3A%2F%2Fprecos.mgdn.com.br%2Fml%2Fcallback" in url


def test_troca_do_code_manda_o_que_a_api_pede_e_grava_os_tokens(db):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json=TOKEN)
    a = auth(db, httpx.Client(transport=httpx.MockTransport(handler)))
    a.exchange_code("TG-abc", NOW)
    method, path, body = seen[0]
    assert (method, path) == ("POST", "/oauth/token")
    assert dict(body) == {"client_id": "APP123", "client_secret": "SEGREDO", "grant_type": "authorization_code",
                          "code": "TG-abc", "redirect_uri": REDIRECT}
    assert db.get_state("ml:access_token") == "AT1" and db.get_state("ml:refresh_token") == "RT1"


def test_token_valido_e_reaproveitado_sem_chamar_a_api(db):
    calls = []
    a = auth(db, client({"/oauth/token": httpx.Response(200, json=TOKEN)}, calls))
    a.exchange_code("c", NOW)
    n = len(calls)
    assert a.token(NOW + timedelta(hours=1)) == "AT1" and len(calls) == n


def test_token_vencido_renova_e_guarda_o_novo_refresh_token(db):
    bodies = []

    def handler(request):
        bodies.append(httpx.QueryParams(request.content.decode()))
        n = len(bodies)
        return httpx.Response(200, json={"access_token": f"AT{n}", "refresh_token": f"RT{n}", "expires_in": 21600})
    a = auth(db, httpx.Client(transport=httpx.MockTransport(handler)))
    a.exchange_code("c", NOW)
    assert a.token(NOW + timedelta(hours=7)) == "AT2"  # venceu: renovou
    assert bodies[1]["grant_type"] == "refresh_token" and bodies[1]["refresh_token"] == "RT1"
    assert db.get_state("ml:refresh_token") == "RT2"  # o refresh token ROTACIONA: o novo foi gravado
    a.invalidate()
    a.token(NOW + timedelta(hours=7, minutes=1))
    assert bodies[2]["refresh_token"] == "RT2"


def test_sem_token_a_mensagem_diz_o_que_fazer(db):
    with pytest.raises(MLAuthError, match="ml-auth"):
        auth(db, client({})).token(NOW)


def test_token_recusado_vira_erro_com_o_motivo(db):
    a = auth(db, client({"/oauth/token": httpx.Response(400, json={"error": "invalid_grant"})}))
    with pytest.raises(MLAuthError, match="invalid_grant"):
        a.exchange_code("velho", NOW)


# --- coletor -------------------------------------------------------------------------------
def collector(db, routes, calls=None, sleeps=None):
    c = client({"/oauth/token": httpx.Response(200, json=TOKEN), **routes}, calls)
    a = auth(db, c)
    a.exchange_code("c", NOW)
    return MercadoLivreCollector(a, "mgdn-precos/0.1 (teste)", client=c, sleep=(sleeps.append if sleeps is not None else lambda s: None),
                                 clock=lambda: NOW)


def product():
    return make_config().products[0]


def test_busca_o_anuncio_com_bearer_e_user_agent_identificavel(db):
    calls = []
    col = collector(db, {"/items/MLB3456789012": httpx.Response(200, json=ITEM)}, calls)
    o = col.fetch(product(), "https://produto.mercadolivre.com.br/MLB-3456789012-x")
    assert o.price_pix == 3799.0 and o.first_party
    _, _, headers = next(c for c in calls if c[1] == "/items/MLB3456789012")
    assert headers["authorization"] == "Bearer AT1" and headers["user-agent"].startswith("mgdn-precos/")


def test_pagina_de_catalogo_usa_o_vencedor_da_buy_box(db):
    col = collector(db, {"/products/MLB44556677": httpx.Response(200, json={"buy_box_winner": {"item_id": "MLB3456789012"}}),
                         "/items/MLB3456789012": httpx.Response(200, json=ITEM)})
    assert col.fetch(product(), "https://www.mercadolivre.com.br/x/p/MLB44556677").price_pix == 3799.0


def test_catalogo_sem_vencedor_e_erro_claro(db):
    col = collector(db, {"/products/MLB44556677": httpx.Response(200, json={"buy_box_winner": None})})
    with pytest.raises(ParseError, match="buy box"):
        col.fetch(product(), "https://www.mercadolivre.com.br/x/p/MLB44556677")


def test_401_renova_o_token_e_tenta_de_novo_uma_vez(db):
    seq = iter([401, 200])

    def item(request):
        return httpx.Response(next(seq), json=ITEM)
    calls = []
    col = collector(db, {"/items/MLB3456789012": item}, calls)
    assert col.fetch(product(), "https://produto.mercadolivre.com.br/MLB-3456789012-x").price_pix == 3799.0
    assert sum(1 for c in calls if c[1] == "/oauth/token") == 2  # o da troca do code + a renovação


def test_429_espera_o_retry_after_uma_vez_e_depois_desiste(db):
    sleeps = []
    col = collector(db, {"/items/MLB3456789012": httpx.Response(429, headers={"retry-after": "7"})}, sleeps=sleeps)
    with pytest.raises(FetchError, match="limitou"):
        col.fetch(product(), "https://produto.mercadolivre.com.br/MLB-3456789012-x")
    assert 7.0 in sleeps


def test_403_diz_para_conferir_token_escopo_e_termos(db):
    col = collector(db, {"/items/MLB3456789012": httpx.Response(403)})
    with pytest.raises(FetchError, match="Termos"):
        col.fetch(product(), "https://produto.mercadolivre.com.br/MLB-3456789012-x")


def test_403_mostra_o_motivo_dado_pela_api(db):
    body = {"message": "At least one policy returned UNAUTHORIZED.", "error": "forbidden", "blocked_by": "PolicyAgent", "code": "PA_UNAUTHORIZED_RESULT_FROM_POLICIES"}
    col = collector(db, {"/items/MLB3456789012": httpx.Response(403, json=body)})
    with pytest.raises(FetchError, match="blocked_by=PolicyAgent") as e:
        col.fetch(product(), "https://produto.mercadolivre.com.br/MLB-3456789012-x")
    assert "PA_UNAUTHORIZED_RESULT_FROM_POLICIES" in str(e.value)


def test_404_e_erro_sem_retry(db):
    calls = []
    col = collector(db, {"/items/MLB3456789012": httpx.Response(404)}, calls)
    with pytest.raises(FetchError, match="não encontrado"):
        col.fetch(product(), "https://produto.mercadolivre.com.br/MLB-3456789012-x")
    assert sum(1 for c in calls if c[1].startswith("/items/")) == 1
