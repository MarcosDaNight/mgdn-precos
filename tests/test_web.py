import urllib.error
import urllib.request
from datetime import timedelta

import pytest

from conftest import NOW, make_config, offer
from precos import web
from precos.db import DB


# --- /healthz -------------------------------------------------------------------------------
def test_processo_novo_sem_coleta_ainda_e_saudavel(db):
    assert web.health(db, started=NOW - timedelta(hours=1), now=NOW)[0] == 200


def test_processo_antigo_que_nunca_coletou_e_doente(db):
    code, msg = web.health(db, started=NOW - timedelta(hours=30), now=NOW)
    assert code == 503 and "nenhuma coleta" in msg


def test_coleta_recente_e_ok_e_velha_e_503(db):
    db.set_state("last_ok", (NOW - timedelta(hours=5)).isoformat())
    assert web.health(db, NOW - timedelta(days=9), NOW) == (200, "ok")
    db.set_state("last_ok", (NOW - timedelta(hours=27)).isoformat())
    code, msg = web.health(db, NOW - timedelta(days=9), NOW)
    assert code == 503 and "27 h" in msg


# --- painel ---------------------------------------------------------------------------------
def test_mostra_melhor_preco_com_link_meta_e_minimo(db):
    cfg = make_config()
    db.insert_offer(offer(product_id="a", store="fake", url="https://loja.test/a1", price_pix=90.0), True)
    db.insert_offer(offer(product_id="a", store="outra", url="https://outra.test/a", price_pix=95.0), True)
    page = web.render(cfg, db, NOW)
    assert 'href="https://loja.test/a1"' in page and "R$ 90,00" in page
    assert "META ✓" in page  # 90 <= meta 100
    assert "Produto B" in page and "sem leitura válida" in page


def test_esgotado_aparece_como_indisponivel(db):
    cfg = make_config()
    db.insert_offer(offer(product_id="a", price_pix=90.0, available=False), True)
    page = web.render(cfg, db, NOW)
    assert "indisponível" in page and "fake esgotado" in page and "META ✓" not in page


def test_loja_desativada_mostra_o_motivo(db):
    cfg = make_config()
    db.set_state("disabled:fake", "loja.test respondeu 403")
    assert "desativada" in web.render(cfg, db, NOW) and "respondeu 403" in web.render(cfg, db, NOW)


def test_recusadas_aparecem_e_o_html_e_escapado(db):
    cfg = make_config()
    db.insert_offer(offer(product_id="a", title="<script>alert(1)</script> Switch 2", seller="x"), False, "vendedor de terceiros (<b>X</b>)")
    page = web.render(cfg, db, NOW)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "<b>X</b>" not in page and "vendedor de terceiros" in page


def test_recusadas_antigas_nao_aparecem(db):
    cfg = make_config()
    db.insert_offer(offer(product_id="a", fetched_at=NOW - timedelta(hours=60)), False, "motivo antigo")
    assert "motivo antigo" not in web.render(cfg, db, NOW)


# --- servidor HTTP de verdade ----------------------------------------------------------------
@pytest.fixture
def server(tmp_path):
    path = str(tmp_path / "p.sqlite")
    DB(path).close()  # cria o esquema
    srv = web.serve(make_config(), path, port=0, host="127.0.0.1")
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def test_servidor_responde_healthz_painel_e_404(server):
    code, body, headers = get(server + "/healthz")
    assert code == 200 and "iniciando" in body and "no-store" in headers["Cache-Control"]
    code, body, headers = get(server + "/")
    assert code == 200 and "Monitor de preços" in body and "text/html" in headers["Content-Type"]
    assert get(server + "/nada")[0] == 404


def test_healthz_vira_503_quando_a_coleta_esta_velha(tmp_path):
    path = str(tmp_path / "p.sqlite")
    d = DB(path)
    d.set_state("last_ok", "2020-01-01T00:00:00+00:00")
    srv = web.serve(make_config(), path, port=0, host="127.0.0.1")
    try:
        assert get(f"http://127.0.0.1:{srv.server_address[1]}/healthz")[0] == 503
    finally:
        srv.shutdown()
        d.close()


def test_banco_inexistente_da_503_e_nao_derruba_o_servidor(tmp_path):
    srv = web.serve(make_config(), str(tmp_path / "nao-existe.sqlite"), port=0, host="127.0.0.1")
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert get(base + "/healthz")[0] == 503
        assert get(base + "/healthz")[0] == 503  # segue de pé
    finally:
        srv.shutdown()
