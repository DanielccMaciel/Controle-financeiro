import pytest

from app import config


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    return tmp_path


def test_registrar_e_contar_abertas():
    from app.ocorrencias import registro

    registro.registrar("ERRO", "leitura", "Layout não reconhecido", arquivo="a.pdf", conta_id=1)
    registro.registrar("CONFERIR", "conferencia_saldo", "Saldo do dia 05/08 não bate", pagina=2)
    registro.registrar("REVISAR", "duplicidade", "Possível duplicada")
    registro.registrar("INFO", "importacao", "Importado: 16 novas")

    assert registro.contar_abertas() == {"ERRO": 1, "CONFERIR": 1, "REVISAR": 1}
    assert len(registro.listar()) == 4
    assert len(registro.listar(somente_abertas=True)) == 3
    assert [o.nivel for o in registro.listar(niveis=["ERRO"])] == ["ERRO"]
    assert registro.listar(conta_id=1)[0].conta_nome == "Daniel"


def test_resolver_mantem_historico():
    from app.ocorrencias import registro

    oid = registro.registrar("ERRO", "leitura", "PDF corrompido")
    registro.resolver(oid, "Baixei o PDF de novo")

    assert registro.contar_abertas()["ERRO"] == 0
    o = registro.listar()[0]
    assert o.resolvida_em and o.resolucao == "Baixei o PDF de novo" and not o.aberta

    with pytest.raises(ValueError):
        registro.resolver(oid, "de novo")  # já resolvida


def test_resolver_exige_descricao_e_info_nao_resolve():
    from app.ocorrencias import registro

    oid = registro.registrar("CONFERIR", "x", "y")
    with pytest.raises(ValueError):
        registro.resolver(oid, "   ")
    info = registro.registrar("INFO", "x", "só registro")
    with pytest.raises(ValueError):
        registro.resolver(info, "ok")


def test_nivel_invalido():
    from app.ocorrencias import registro

    with pytest.raises(ValueError):
        registro.registrar("GRAVE", "x", "y")


def test_log_tecnico_em_arquivo():
    from app.ocorrencias import registro

    registro.registrar("ERRO", "leitura", "Layout não reconhecido", arquivo="extrato.pdf")
    for h in registro.logger_tecnico().handlers:
        h.flush()
    texto = (config.pasta_logs() / "programa.log").read_text(encoding="utf-8")
    assert "ERROR" in texto and "Layout não reconhecido" in texto and "extrato.pdf" in texto


def test_backup_gera_registro():
    from app.backup import backup
    from app.ocorrencias import registro

    backup.fazer_backup("manual")
    ultima = registro.listar()[0]
    assert ultima.nivel == "INFO" and ultima.etapa == "backup"


def test_formatos_de_exibicao():
    from app.ocorrencias.registro import data_br, nome_etapa

    assert data_br("2026-09-26 17:48:41") == "26/09/2026 17:48"
    assert data_br(None) == ""
    assert nome_etapa("conferencia_saldo") == "Conferência de saldo"
    assert nome_etapa("outra") == "outra"
