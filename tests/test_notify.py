import json

import httpx
import pytest

from precos.notify import NtfyNotifier


def make(handler, url="https://ntfy.sh/precos-segredo123"):
    sleeps = []
    n = NtfyNotifier(url, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    return n, sleeps


def test_publica_json_utf8_no_topico_com_link_e_botao():
    seen = []
    n, _ = make(lambda r: (seen.append(r), httpx.Response(200))[1])
    n.send("COMPRAR · Pokémon", "Preço: R$ 379,00", priority=4, tags=("moneybag",), click="https://loja.test/p")
    req = seen[0]
    assert str(req.url) == "https://ntfy.sh"
    body = json.loads(req.content)
    assert body["topic"] == "precos-segredo123" and body["title"] == "COMPRAR · Pokémon"
    assert body["priority"] == 4 and body["tags"] == ["moneybag"] and body["click"] == "https://loja.test/p"
    assert body["actions"][0]["url"] == "https://loja.test/p"


def test_sem_link_nao_manda_botao():
    seen = []
    n, _ = make(lambda r: (seen.append(r), httpx.Response(200))[1])
    n.send("t", "m")
    assert "click" not in json.loads(seen[0].content) and "actions" not in json.loads(seen[0].content)


def test_tenta_de_novo_em_erro_e_depois_conta_como_enviado():
    codes = iter([500, 200])
    n, sleeps = make(lambda r: httpx.Response(next(codes)))
    n.send("t", "m")
    assert sleeps == [1]


def test_desiste_depois_de_tres_tentativas():
    n, sleeps = make(lambda r: httpx.Response(503))
    with pytest.raises(RuntimeError, match="ntfy indisponível"):
        n.send("t", "m")
    assert sleeps == [1, 2, 4]


def test_url_sem_topico_e_recusada():
    with pytest.raises(ValueError):
        NtfyNotifier("https://ntfy.sh/")
