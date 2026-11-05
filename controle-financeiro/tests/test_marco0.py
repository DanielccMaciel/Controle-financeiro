import sqlite3

import pytest

from app import config


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    """Cada teste usa uma pasta temporária — nunca o banco real."""
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    return tmp_path


def test_banco_criado_com_contas_iniciais():
    from app.contas import repositorio as repo

    contas = repo.listar()
    assert config.caminho_banco().exists()
    # Daniel e a segunda conta de exemplo, nessa ordem (a principal vem primeiro nas telas)
    assert [c.nome for c in contas] == ["Daniel", "Dani 2"]
    assert {c.titular for c in contas} == {"Daniel"} and all(c.ativa for c in contas)
    # a segunda é de outro banco: assim os PDFs do Nubank entram na conta Daniel sem perguntar nada
    assert [(c.banco, c.pasta) for c in contas] == [("Nubank", "Daniel-Nubank"), ("Sicoob", "Dani-2-Sicoob")]
    assert "Exemplo" in contas[1].observacoes
    assert config.caminho_banco().name == "financas.db"


def test_migracoes_nao_reaplicam():
    from app.banco.conexao import conectar
    from app.banco.migracoes import MIGRACOES

    conectar().close()
    conn = conectar()
    assert conn.execute("SELECT COUNT(*) FROM contas").fetchone()[0] == 2
    assert conn.execute("SELECT MAX(versao) FROM schema_versao").fetchone()[0] == len(MIGRACOES)
    conn.close()


def test_inserir_cria_pasta_e_bloqueia_duplicado():
    from app.contas import repositorio as repo
    from app.contas.repositorio import Conta, ErroValidacao

    # dá para ter quantas contas quiser: uma terceira entra normalmente
    repo.inserir(Conta(nome="Dani 3", titular="Daniel", banco="Nubank", pasta="Dani-3"))
    assert (config.pasta_extratos() / "Dani-3").is_dir()
    assert [c.nome for c in repo.listar()] == ["Daniel", "Dani 2", "Dani 3"]

    with pytest.raises(ErroValidacao):
        repo.inserir(Conta(nome="dani 3", titular="X", banco="Nubank", pasta="Outra"))
    with pytest.raises(ErroValidacao):
        repo.inserir(Conta(nome="Outra", titular="X", banco="Nubank", pasta="dani-3"))


def test_validacoes():
    from app.contas import repositorio as repo
    from app.contas.repositorio import Conta, ErroValidacao

    with pytest.raises(ErroValidacao):
        repo.inserir(Conta(nome=" ", titular="X", banco="Nubank", pasta="P"))
    with pytest.raises(ErroValidacao):
        repo.inserir(Conta(nome="A", titular=" ", banco="Nubank", pasta="P"))
    with pytest.raises(ErroValidacao):
        repo.inserir(Conta(nome="A", titular="X", banco="Nubank", pasta="../fora"))


def test_desativar_mantem_historico():
    from app.contas import repositorio as repo

    conta = next(c for c in repo.listar() if c.nome == "Dani 2")
    conta.ativa = False
    repo.atualizar(conta)
    assert "Dani 2" not in {c.nome for c in repo.listar(somente_ativas=True)}
    assert "Dani 2" in {c.nome for c in repo.listar()}


def test_backup_consistente_e_limpeza():
    from app.backup import backup

    destino = backup.fazer_backup("teste")
    conn = sqlite3.connect(destino)
    assert conn.execute("SELECT COUNT(*) FROM contas").fetchone()[0] == 2
    conn.close()

    for i in range(5):
        (config.pasta_backups() / f"{config.PREFIXO_BACKUP}2000-01-0{i+1}_000000_x.db").write_bytes(b"")
    # arquivo de outro programa na mesma pasta não é contado nem apagado
    (config.pasta_backups() / "financeiro_1999-01-01_000000_x.db").write_bytes(b"")
    backup.limpar_antigos(manter=3)
    assert len(backup.listar_backups()) == 3
    assert destino in backup.listar_backups()  # o mais recente fica
    assert (config.pasta_backups() / "financeiro_1999-01-01_000000_x.db").exists()


def test_backup_automatico_antes_de_atualizar_a_estrutura(tmp_path, monkeypatch):
    """Banco de uma versão anterior: ao abrir, faz cópia e só então aplica as migrações novas."""
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    from app import config
    from app.banco import conexao
    from app.banco.migracoes import MIGRACOES

    monkeypatch.setattr(conexao, "MIGRACOES", MIGRACOES[:-1])
    conexao.conectar().close()
    assert not list(config.pasta_backups().glob("*antes-atualizacao*"))     # banco novo: sem cópia
    monkeypatch.setattr(conexao, "MIGRACOES", MIGRACOES)
    conn = conexao.conectar()
    try:
        assert conexao.versao_atual(conn) == MIGRACOES[-1][0]
    finally:
        conn.close()
    assert len(list(config.pasta_backups().glob("*antes-atualizacao*"))) == 1
    conexao.conectar().close()
    assert len(list(config.pasta_backups().glob("*antes-atualizacao*"))) == 1
