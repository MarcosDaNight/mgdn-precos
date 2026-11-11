from datetime import timedelta

import pytest

from conftest import NOW, make_config, offer
from precos import runner
from precos.collectors.http import Blocked, FetchError


class FakeCollector:
    """Devolve uma Offer pronta por URL, ou levanta a exceção cadastrada."""

    def __init__(self, store, results):
        self.store, self.results, self.calls = store, results, []

    def fetch(self, product, url):
        self.calls.append(url)
        r = self.results[url]
        if isinstance(r, Exception):
            raise r
        return r(product) if callable(r) else r


class Sink:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, title, message, *, priority=3, tags=(), click=None):
        if self.fail:
            raise RuntimeError("ntfy fora do ar")
        self.sent.append((title, message, priority, tags, click))


A1, A2, B1, OB = "https://loja.test/a1", "https://loja.test/a2", "https://loja.test/b1", "https://outra.test/b"


def good(pid, url, price, title=None):
    return offer(product_id=pid, url=url, price_pix=price, title=title or ("Acessorio Switch 2" if pid == "a" else "Zelda Switch 2"))


def test_rodada_grava_oferta_e_avisa_quando_bate_a_meta(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: good("a", A1, 90.0), A2: good("a", A2, 120.0), B1: good("b", B1, 350.0)})
    sink = Sink()
    rep = runner.run_collection(cfg, db, {"fake": col}, sink, NOW)
    assert (rep.collected, rep.rejected, rep.failed, rep.alerts) == (3, 0, 0, 1)
    assert len(sink.sent) == 1 and sink.sent[0][0].startswith("COMPRAR · Produto A")
    assert sink.sent[0][4] == A1  # o link da loja vai como clique
    assert db.history_count("a") == 2 and db.last_alert("a", "fake")["price"] == 90.0


def test_oferta_recusada_fica_registrada_com_motivo_e_nao_avisa(db):
    cfg = make_config()
    terceiro = offer(product_id="a", url=A1, price_pix=10.0, title="Acessorio Switch 2", first_party=False, seller="Fulano")
    col = FakeCollector("fake", {A1: terceiro, A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    sink = Sink()
    rep = runner.run_collection(cfg, db, {"fake": col}, sink, NOW)
    assert rep.rejected == 1 and sink.sent == []
    row = db.conn.execute("SELECT accepted, reject_reason FROM offer WHERE url = ?", (A1,)).fetchone()
    assert row["accepted"] == 0 and "terceiros" in row["reject_reason"]
    assert db.history_count("a") == 1  # a recusada não entra no histórico


def test_um_coletor_quebrado_nao_derruba_os_outros(db):
    cfg = make_config()
    quebrado = FakeCollector("fake", {A1: FetchError("boom"), A2: ValueError("parse"), B1: good("b", B1, 250.0)})
    outra = FakeCollector("outra", {OB: good("b", OB, 400.0)})
    rep = runner.run_collection(cfg, db, {"fake": quebrado, "outra": outra}, Sink(), NOW)
    assert rep.failed == 2 and rep.collected == 2
    assert outra.calls == [OB] and quebrado.calls == [A1, A2, B1]


def test_aviso_so_na_terceira_falha_seguida_e_so_uma_vez(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: FetchError("fora"), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    sink = Sink()
    for i in range(2):
        runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=i))
    assert sink.sent == []
    runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=2))
    assert len(sink.sent) == 1 and "falhando" in sink.sent[0][0] and A1 in sink.sent[0][1]
    runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=3))
    assert len(sink.sent) == 1  # não repete o aviso


def test_sucesso_zera_a_contagem_de_falhas(db):
    cfg = make_config()
    sink = Sink()
    falha = FakeCollector("fake", {A1: FetchError("x"), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    for i in range(2):
        runner.run_collection(cfg, db, {"fake": falha}, sink, NOW + timedelta(hours=i))
    bom = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    runner.run_collection(cfg, db, {"fake": bom}, sink, NOW + timedelta(hours=2))
    for i in range(3, 5):
        runner.run_collection(cfg, db, {"fake": falha}, sink, NOW + timedelta(hours=i))
    assert sink.sent == []  # recomeçou do zero: só 2 falhas seguidas


def test_loja_que_bloqueia_o_ua_sai_do_coletor_e_avisa(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: Blocked("loja.test respondeu 403"), A2: good("a", A2, 1.0), B1: good("b", B1, 1.0)})
    sink = Sink()
    rep = runner.run_collection(cfg, db, {"fake": col}, sink, NOW)
    assert rep.disabled == ["fake"] and col.calls == [A1]  # parou na hora, sem tentar as outras URLs
    assert "Loja desativada" in sink.sent[0][0] and "enable fake" in sink.sent[0][1]
    runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=6))
    assert col.calls == [A1]  # desativada: nem tenta de novo
    db.del_state("disabled:fake")  # `python -m precos enable fake`
    runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=12))
    assert col.calls == [A1, A1]


def test_ntfy_fora_do_ar_nao_derruba_a_rodada_e_o_alerta_e_refeito(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: good("a", A1, 90.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    rep = runner.run_collection(cfg, db, {"fake": col}, Sink(fail=True), NOW)
    assert rep.collected == 3 and rep.alerts == 0 and db.last_alert("a", "fake") is None
    sink = Sink()
    runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=1))
    assert len(sink.sent) == 1  # como não foi gravado, avisa na próxima


def test_loja_sem_coletor_e_ignorada(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    rep = runner.run_collection(cfg, db, {"fake": col}, Sink(), NOW)  # "outra" sem coletor
    assert rep.collected == 3


def test_tick_coleta_e_manda_resumo_uma_vez(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    sink = Sink()
    runner.tick(cfg, db, {"fake": col}, sink, NOW)  # 09:00 em Recife
    assert [t for t, *_ in sink.sent] == ["Resumo diário de preços"]
    n = len(col.calls)
    runner.tick(cfg, db, {"fake": col}, sink, NOW + timedelta(minutes=1))
    assert len(col.calls) == n and len(sink.sent) == 1  # nem coleta nem resume de novo
    runner.tick(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=6))
    assert len(col.calls) == 2 * n  # intervalo de 6 h vencido
    assert len(sink.sent) == 1  # o resumo é diário


# --- guarda contra preço absurdo e heartbeat ---------------------------------------------------
from conftest import seed_history  # noqa: E402


def _cheap(price):
    return FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, price)})


def test_preco_muito_abaixo_da_mediana_espera_confirmacao_antes_de_alertar(db):
    cfg = make_config()
    seed_history(db, "b", [440.0, 440.0, 440.0, 440.0])
    sink = Sink()
    runner.run_collection(cfg, db, {"fake": _cheap(100.0)}, sink, NOW)  # parece erro de leitura
    assert sink.sent == []
    row = db.last_offer_for_url(B1)
    assert row["accepted"] == 0 and row["reject_reason"].startswith("preço suspeito")
    assert db.history_min("b") == 440.0  # o suspeito NÃO contamina o mínimo histórico
    runner.run_collection(cfg, db, {"fake": _cheap(101.0)}, sink, NOW + timedelta(hours=6))  # confirmou (±3%)
    assert len(sink.sent) == 1 and sink.sent[0][0].startswith("COMPRAR · Produto B")
    assert db.history_min("b") == 101.0


def test_segunda_leitura_diferente_nao_confirma(db):
    cfg = make_config()
    seed_history(db, "b", [440.0, 440.0, 440.0, 440.0])
    sink = Sink()
    runner.run_collection(cfg, db, {"fake": _cheap(100.0)}, sink, NOW)
    runner.run_collection(cfg, db, {"fake": _cheap(150.0)}, sink, NOW + timedelta(hours=6))  # ainda suspeito, longe de 100
    assert sink.sent == [] and db.history_min("b") == 440.0


def test_sem_historico_a_guarda_nao_atua(db):
    cfg = make_config()
    sink = Sink()
    runner.run_collection(cfg, db, {"fake": _cheap(100.0)}, sink, NOW)
    assert len(sink.sent) == 1  # sem mediana não dá para desconfiar; vale a meta


def test_queda_normal_nao_e_suspeita(db):
    cfg = make_config()
    seed_history(db, "b", [440.0, 440.0, 440.0, 440.0])
    sink = Sink()
    runner.run_collection(cfg, db, {"fake": _cheap(290.0)}, sink, NOW)  # -34%: promoção, não erro
    assert len(sink.sent) == 1


def test_heartbeat_so_depois_de_coletar_de_verdade(db):
    cfg = make_config()
    beats = []
    ok = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    runner.tick(cfg, db, {"fake": ok}, Sink(), NOW, heartbeat=lambda: beats.append(1))
    assert beats == [1]
    tudo_falha = FakeCollector("fake", {u: FetchError("fora") for u in (A1, A2, B1)})
    runner.tick(cfg, db, {"fake": tudo_falha}, Sink(), NOW + timedelta(hours=6), heartbeat=lambda: beats.append(1))
    assert beats == [1]  # nada coletado: silêncio, e o Healthchecks é quem avisa


def test_heartbeat_com_erro_nao_derruba_a_rodada(db):
    cfg = make_config()
    ok = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})

    def boom():
        raise RuntimeError("healthchecks fora")
    rep = runner.tick(cfg, db, {"fake": ok}, Sink(), NOW, heartbeat=boom)
    assert rep.collected == 3


# --- sem NTFY_URL nada conta como enviado -------------------------------------------------------
class Printer:
    """Como o ConsoleNotifier: imprime e não entrega (delivers = False)."""
    delivers = False

    def __init__(self):
        self.printed = []

    def send(self, title, message, *, priority=3, tags=(), click=None):
        self.printed.append(title)


def test_modo_de_teste_nao_grava_o_alerta_e_o_real_vem_depois(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: good("a", A1, 90.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    pr = Printer()
    rep = runner.run_collection(cfg, db, {"fake": col}, pr, NOW)
    assert pr.printed and rep.alerts == 0 and db.last_alert("a", "fake") is None
    sink = Sink()  # o ntfy foi configurado: o alerta NÃO foi engolido pela deduplicação
    runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=1))
    assert len(sink.sent) == 1 and sink.sent[0][0].startswith("COMPRAR")


def test_resumo_em_modo_de_teste_nao_conta_como_enviado(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    runner.tick(cfg, db, {"fake": col}, Printer(), NOW)
    assert db.get_state("last_summary") is None  # hoje ainda sai o resumo de verdade
    sink = Sink()
    runner.tick(cfg, db, {"fake": col}, sink, NOW + timedelta(minutes=1))
    assert [t for t, *_ in sink.sent] == ["Resumo diário de preços"]


def test_aviso_de_falha_em_modo_de_teste_nao_marca_como_avisado(db):
    cfg = make_config()
    col = FakeCollector("fake", {A1: FetchError("fora"), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    for i in range(3):
        runner.run_collection(cfg, db, {"fake": col}, Printer(), NOW + timedelta(hours=i))
    sink = Sink()
    runner.run_collection(cfg, db, {"fake": col}, sink, NOW + timedelta(hours=3))
    assert len(sink.sent) == 1 and "falhando" in sink.sent[0][0]  # o aviso real ainda sai


# --- uma rodada que aborta não pode deixar o app cego por 6 h ----------------------------------------
def test_erro_no_processamento_de_uma_url_nao_derruba_a_rodada(db, monkeypatch):
    cfg = make_config()
    col = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    real = runner.alerts.evaluate

    def boom(product, offer, *a, **k):
        if offer.url == A1:
            raise ValueError("bug no alerta")
        return real(product, offer, *a, **k)
    monkeypatch.setattr(runner.alerts, "evaluate", boom)
    rep = runner.run_collection(cfg, db, {"fake": col}, Sink(), NOW)
    assert rep.failed == 1
    assert db.history_count("a") == 1 and db.history_count("b") == 1  # A2 e B1 foram gravadas
    f = db.failures()
    assert len(f) == 1 and f[0]["key"].endswith(A1) and "bug no alerta" in f[0]["last_error"]


def test_rodada_abortada_nao_marca_coleta_e_e_refeita_depois_do_intervalo_minimo(db, monkeypatch):
    cfg = make_config()
    ok = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    real, calls = runner.run_collection, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("o serviço caiu no meio da rodada")
        return real(*a, **k)
    monkeypatch.setattr(runner, "run_collection", flaky)
    with pytest.raises(RuntimeError):
        runner.tick(cfg, db, {"fake": ok}, Sink(), NOW)
    assert db.get_state("last_collect") is None  # a coleta NÃO foi marcada como feita
    runner.tick(cfg, db, {"fake": ok}, Sink(), NOW + timedelta(minutes=1))
    assert calls["n"] == 1  # dentro do intervalo mínimo: não martela as lojas
    runner.tick(cfg, db, {"fake": ok}, Sink(), NOW + timedelta(minutes=11))
    assert calls["n"] == 2 and db.get_state("last_collect") is not None
    assert db.get_state("last_ok") is not None


def test_coleta_so_e_marcada_ao_terminar_e_vale_pelo_intervalo_normal(db):
    cfg = make_config()
    ok = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    runner.tick(cfg, db, {"fake": ok}, Sink(), NOW)
    assert db.get_state("last_collect") == NOW.isoformat()
    n = len(ok.calls)
    runner.tick(cfg, db, {"fake": ok}, Sink(), NOW + timedelta(hours=5))  # 6 h de intervalo normal
    assert len(ok.calls) == n


def test_reiniciar_o_servico_limpa_o_intervalo_minimo(db):
    db.set_state("last_attempt", NOW.isoformat())
    db.del_state("last_attempt")  # o que o `run` faz ao subir
    cfg = make_config()
    ok = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    runner.tick(cfg, db, {"fake": ok}, Sink(), NOW)
    assert ok.calls


# --- estado legado da VM e rodada em que tudo falha ---------------------------------------------------
def test_estado_legado_da_vm_nao_adia_a_primeira_coleta(db):
    """O 1º deploy gravou last_collect no INÍCIO de uma rodada que abortou: sem last_ok, isso não vale."""
    db.set_state("last_collect", NOW.isoformat())
    db.set_state("last_attempt", NOW.isoformat())
    runner.reset_stale_state(db)
    ok = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    rep = runner.tick(make_config(), db, {"fake": ok}, Sink(), NOW + timedelta(minutes=20))
    assert rep is not None and rep.collected == 3 and db.get_state("last_ok") is not None


def test_estado_legado_so_e_limpo_se_nunca_houve_coleta_boa(db):
    db.set_state("last_ok", NOW.isoformat())
    db.set_state("last_collect", NOW.isoformat())
    runner.reset_stale_state(db)
    assert db.get_state("last_collect") == NOW.isoformat()  # havia coleta boa: o intervalo normal vale


def test_rodada_em_que_tudo_falha_nao_conta_como_feita_e_recua(db):
    cfg = make_config()
    fora = FakeCollector("fake", {u: FetchError("fora do ar") for u in (A1, A2, B1)})
    runner.tick(cfg, db, {"fake": fora}, Sink(), NOW)
    assert db.get_state("last_collect") is None and db.get_state("empty_rounds") == "1"
    n = len(fora.calls)
    runner.tick(cfg, db, {"fake": fora}, Sink(), NOW + timedelta(minutes=15))  # recuo de 20 min
    assert len(fora.calls) == n
    runner.tick(cfg, db, {"fake": fora}, Sink(), NOW + timedelta(minutes=21))
    assert len(fora.calls) == 2 * n and db.get_state("empty_rounds") == "2"
    runner.tick(cfg, db, {"fake": fora}, Sink(), NOW + timedelta(minutes=21 + 39))  # agora o recuo é de 40 min
    assert len(fora.calls) == 2 * n


def test_o_recuo_tem_teto_de_3_horas(db):
    db.set_state("empty_rounds", "20")
    db.set_state("last_attempt", NOW.isoformat())
    fora = FakeCollector("fake", {u: FetchError("x") for u in (A1, A2, B1)})
    runner.tick(make_config(), db, {"fake": fora}, Sink(), NOW + timedelta(hours=3, minutes=1))
    assert fora.calls  # nem com 20 falhas seguidas espera mais de 3 h


def test_volta_ao_normal_quando_uma_pagina_e_lida(db):
    cfg = make_config()
    db.set_state("empty_rounds", "3")
    ok = FakeCollector("fake", {A1: good("a", A1, 500.0), A2: good("a", A2, 500.0), B1: good("b", B1, 500.0)})
    runner.tick(cfg, db, {"fake": ok}, Sink(), NOW)
    assert db.get_state("empty_rounds") is None and db.get_state("last_collect") == NOW.isoformat()
