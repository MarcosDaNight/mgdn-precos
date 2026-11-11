import httpx
import pytest

from precos.collectors.http import Blocked, FetchError, PoliteClient, RobotsDisallowed

UA = "mgdn-precos/0.1 (monitor pessoal de precos)"
ROBOTS_OK = "User-agent: *\nDisallow: /privado\n"


def client(handler, delay=5.0, **kw):
    sleeps = []
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    c = PoliteClient(UA, delay=delay, client=httpx.Client(transport=httpx.MockTransport(wrapped)),
                     sleep=sleeps.append, monotonic=lambda: 0.0, **kw)
    return c, calls, sleeps


def ok_handler(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS_OK)
    return httpx.Response(200, text="<html>ok</html>")


def test_busca_a_pagina_com_user_agent_identificavel():
    c, calls, _ = client(ok_handler)
    assert c.get("https://loja.test/produto/1") == "<html>ok</html>"
    assert all(r.headers["user-agent"] == UA for r in calls)
    assert [r.url.path for r in calls] == ["/robots.txt", "/produto/1"]


def test_robots_e_lido_uma_vez_por_host():
    c, calls, _ = client(ok_handler)
    c.get("https://loja.test/a")
    c.get("https://loja.test/b")
    assert sum(r.url.path == "/robots.txt" for r in calls) == 1


def test_caminho_proibido_pelo_robots_nem_e_pedido():
    c, calls, _ = client(ok_handler)
    with pytest.raises(RobotsDisallowed):
        c.get("https://loja.test/privado/x")
    assert [r.url.path for r in calls] == ["/robots.txt"]


@pytest.mark.parametrize("status", [403, 429])
def test_bloqueio_nao_e_repetido_nem_contornado(status):
    def handler(request):
        return httpx.Response(200, text=ROBOTS_OK) if request.url.path == "/robots.txt" else httpx.Response(status)
    c, calls, _ = client(handler)
    with pytest.raises(Blocked):
        c.get("https://loja.test/produto/1")
    assert sum(r.url.path == "/produto/1" for r in calls) == 1  # uma única tentativa


def test_erro_5xx_tenta_de_novo_com_espera_crescente_e_depois_sucesso():
    seq = iter([500, 502, 200])

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        s = next(seq)
        return httpx.Response(s, text="<html>ok</html>")
    c, calls, sleeps = client(handler, delay=0)
    assert c.get("https://loja.test/p") == "<html>ok</html>"
    assert sum(r.url.path == "/p" for r in calls) == 3
    assert 1 in sleeps and 2 in sleeps  # backoff 2**0, 2**1


def test_falha_de_rede_esgota_as_tres_tentativas():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        raise httpx.ConnectError("sem rede")
    c, calls, _ = client(handler, delay=0)
    with pytest.raises(FetchError, match="3 vezes"):
        c.get("https://loja.test/p")
    assert sum(r.url.path == "/p" for r in calls) == 3


def test_404_e_erro_sem_retry():
    def handler(request):
        return httpx.Response(200, text=ROBOTS_OK) if request.url.path == "/robots.txt" else httpx.Response(404)
    c, calls, _ = client(handler)
    with pytest.raises(FetchError, match="404"):
        c.get("https://loja.test/sumiu")
    assert sum(r.url.path == "/sumiu" for r in calls) == 1


def test_robots_ausente_libera_e_robots_com_erro_bloqueia_por_seguranca():
    c, _, _ = client(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(200, text="x"))
    assert c.get("https://loja.test/p") == "x"
    c2, _, _ = client(lambda r: httpx.Response(403))
    with pytest.raises(FetchError, match="robots"):
        c2.get("https://loja.test/p")


def test_espera_entre_pedidos_ao_mesmo_host():
    c, _, sleeps = client(ok_handler, delay=5.0)
    clock = {"t": 0.0}
    c.monotonic = lambda: clock["t"]
    c.get("https://loja.test/a")
    clock["t"] = 1.0
    c.get("https://loja.test/b")
    assert any(s >= 3.5 for s in sleeps)  # ~5s de atraso menos 1s já decorrido (mais jitter)
