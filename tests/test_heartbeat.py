import httpx
import pytest

from precos.heartbeat import make_heartbeat


def test_ping_faz_get_na_url_do_healthchecks():
    seen = []
    beat = make_heartbeat("https://hc-ping.com/abc", client=httpx.Client(transport=httpx.MockTransport(lambda r: (seen.append(str(r.url)), httpx.Response(200))[1])))
    beat()
    assert seen == ["https://hc-ping.com/abc"]


def test_resposta_de_erro_sobe_para_o_chamador_registrar():
    beat = make_heartbeat("https://hc-ping.com/abc", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(httpx.HTTPStatusError):
        beat()
