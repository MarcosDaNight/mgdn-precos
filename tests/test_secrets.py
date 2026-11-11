from precos.secrets import env_or_file


def test_le_da_variavel(monkeypatch):
    monkeypatch.setenv("X_TESTE", "valor")
    assert env_or_file("X_TESTE") == "valor"


def test_arquivo_vence_a_variavel_e_remove_o_espaco(monkeypatch, tmp_path):
    f = tmp_path / "s"
    f.write_text("do-arquivo\n")
    monkeypatch.setenv("X_TESTE", "da-variavel")
    monkeypatch.setenv("X_TESTE_FILE", str(f))
    assert env_or_file("X_TESTE") == "do-arquivo"


def test_arquivo_vazio_ou_ausente_conta_como_nao_configurado(monkeypatch, tmp_path):
    f = tmp_path / "vazio"
    f.write_text("\n")
    monkeypatch.delenv("X_TESTE", raising=False)
    monkeypatch.setenv("X_TESTE_FILE", str(f))
    assert env_or_file("X_TESTE") is None
    monkeypatch.setenv("X_TESTE_FILE", str(tmp_path / "nao-existe"))
    assert env_or_file("X_TESTE", "padrao") == "padrao"


def test_nada_definido_devolve_o_padrao(monkeypatch):
    monkeypatch.delenv("X_TESTE", raising=False)
    monkeypatch.delenv("X_TESTE_FILE", raising=False)
    assert env_or_file("X_TESTE") is None and env_or_file("X_TESTE", "d") == "d"
