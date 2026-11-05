"""Testes da importação com extratos FALSOS no layout do Nubank."""

import copy
from datetime import date

import pytest

from app import config
from tests.ajudas import segunda_conta_no_nubank
from tests.gerador_nubank import Ajustes, Dia, Mov, cenario_agosto, gerar

INICIO, FIM = date(2026, 8, 1), date(2026, 8, 31)
SALDO_INICIAL = 123456


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    return tmp_path


def conta(nome="Daniel"):
    from app.contas import repositorio as repo
    return next(c for c in repo.listar() if c.nome == nome)


def pdf_na_pasta(nome, dias, pasta="Daniel-Nubank", **kw):
    from app.contas import repositorio as repo
    repo.garantir_pastas()
    destino = config.pasta_extratos() / pasta / nome
    params = dict(inicio=INICIO, fim=FIM, saldo_inicial=SALDO_INICIAL, itens_por_pagina=9)
    params.update(kw)
    gerar(destino, dias, **params)
    return destino


def contar(sql, *p):
    from app.banco.conexao import conectar
    conn = conectar()
    try:
        return conn.execute(sql, p).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- caminho feliz

def test_importa_mes_completo():
    from app.importacao import servico
    from app.ocorrencias import registro
    from app.backup import backup

    pdf = pdf_na_pasta("extrato-agosto.pdf", cenario_agosto())
    a = servico.analisar(conta(), pdf)
    assert a.pode_importar, [p.mensagem for p in a.problemas]
    assert len(a.extrato.itens) == 12 and len(a.novas) == 12 and not a.existentes

    doc_id = servico.importar(a)
    assert contar("SELECT COUNT(*) FROM documentos") == 1
    assert contar("SELECT COUNT(*) FROM movimentacoes") == 12
    assert contar("SELECT COUNT(*) FROM movimentacao_documento WHERE documento_id=?", doc_id) == 12
    assert contar("SELECT COUNT(*) FROM saldos_diarios") == 6
    # PDF solto na pasta da conta foi arrumado na pasta do mês
    assert (config.pasta_extratos() / "Daniel-Nubank" / "2026-08" / "extrato-agosto.pdf").exists()
    assert not pdf.exists()
    # backup automático + registro
    assert any("antes-importacao" in b.name for b in backup.listar_backups())
    assert registro.listar(niveis=["INFO"])[0].etapa == "importacao"
    # duas movimentações idênticas no mesmo dia foram mantidas
    assert contar("SELECT COUNT(*) FROM movimentacoes WHERE data='2026-08-08' AND valor=15000") == 2
    assert servico.pdfs_pendentes(conta()) == []


def test_mesmo_pdf_duas_vezes_nao_duplica():
    from app.importacao import servico

    pdf = pdf_na_pasta("a.pdf", cenario_agosto())
    servico.importar(servico.analisar(conta(), pdf))
    movido = config.pasta_extratos() / "Daniel-Nubank" / "2026-08" / "a.pdf"
    a2 = servico.analisar(conta(), movido)
    assert a2.documento_existente is not None and not a2.pode_importar
    assert contar("SELECT COUNT(*) FROM movimentacoes") == 12


# ---------------------------------------------------------------- PDF atualizado

def test_pdf_parcial_depois_completo():
    from app.importacao import servico

    mes = cenario_agosto()
    parcial = [d for d in mes if d.data.day <= 8]
    p1 = pdf_na_pasta("01-a-10.pdf", parcial, fim=date(2026, 8, 10))
    a1 = servico.analisar(conta(), p1)
    assert a1.pode_importar
    servico.importar(a1)
    assert contar("SELECT COUNT(*) FROM movimentacoes") == 7

    p2 = pdf_na_pasta("01-a-31.pdf", mes)
    a2 = servico.analisar(conta(), p2)
    assert a2.pode_importar
    assert len(a2.existentes) == 7 and len(a2.novas) == 5 and not a2.sumidas
    doc2 = servico.importar(a2)

    assert contar("SELECT COUNT(*) FROM movimentacoes") == 12
    assert contar("SELECT COUNT(*) FROM documentos") == 2
    # as 7 antigas agora aparecem nos dois documentos
    assert contar("SELECT COUNT(*) FROM movimentacao_documento WHERE documento_id=?", doc2) == 12
    assert contar(
        "SELECT COUNT(*) FROM (SELECT movimentacao_id FROM movimentacao_documento"
        " GROUP BY movimentacao_id HAVING COUNT(*) = 2)") == 7


def test_dia_parcial_com_movimentacoes_identicas():
    """PDF gerado no meio do dia 08 tinha só o 1º de dois Pix iguais; o completo traz o 2º."""
    from app.importacao import servico

    mes = cenario_agosto()
    parcial = copy.deepcopy([d for d in mes if d.data.day <= 8])
    parcial[-1].movs = parcial[-1].movs[:1]           # só o 1º Pix de R$ 150 do dia 08
    servico.importar(servico.analisar(conta(), pdf_na_pasta("p.pdf", parcial, fim=date(2026, 8, 8))))

    a2 = servico.analisar(conta(), pdf_na_pasta("c.pdf", mes))
    novas_dia8 = [i for i, _ in a2.novas if i.data.day == 8]
    assert [(i.valor, i.ordem_no_dia) for i in novas_dia8] == [(15000, 2), (21033, 3)]
    servico.importar(a2)
    assert contar("SELECT COUNT(*) FROM movimentacoes WHERE data='2026-08-08' AND valor=15000") == 2


def test_movimentacao_que_sumiu_vira_revisar():
    from app.importacao import servico
    from app.ocorrencias import registro

    mes = cenario_agosto()
    servico.importar(servico.analisar(conta(), pdf_na_pasta("v1.pdf", mes)))
    sem_uma = copy.deepcopy(mes)
    sem_uma[1].movs = sem_uma[1].movs[:-1]           # some o Pix do hortifruti
    a = servico.analisar(conta(), pdf_na_pasta("v2.pdf", sem_uma))
    assert a.pode_importar and len(a.sumidas) == 1
    servico.importar(a)
    assert registro.contar_abertas()["REVISAR"] == 1


# ---------------------------------------------------------------- travas

def test_saldo_do_dia_errado_bloqueia_e_registra_uma_vez():
    from app.importacao import servico
    from app.ocorrencias import registro

    pdf = pdf_na_pasta("x.pdf", cenario_agosto(),
                       ajustes=Ajustes(saldo_dia_delta={date(2026, 8, 12): 5000}))
    a = servico.analisar(conta(), pdf)
    assert not a.pode_importar
    assert any("Saldo do dia 12/08/2026" in p.mensagem for p in a.problemas)
    servico.analisar(conta(), pdf)                    # analisar de novo não duplica
    assert registro.contar_abertas()["CONFERIR"] == 1
    assert contar("SELECT COUNT(*) FROM movimentacoes") == 0
    with pytest.raises(ValueError):
        servico.importar(a)


def test_total_do_grupo_errado():
    from app.importacao import servico

    pdf = pdf_na_pasta("x.pdf", cenario_agosto(),
                       ajustes=Ajustes(total_grupo_delta={(date(2026, 8, 5), "Saída"): 100}))
    a = servico.analisar(conta(), pdf)
    assert any("Total de saídas do dia 05/08/2026" in p.mensagem for p in a.problemas)


def test_total_de_entradas_do_resumo_errado():
    from app.importacao import servico

    pdf = pdf_na_pasta("x.pdf", cenario_agosto(), ajustes=Ajustes(total_entradas_delta=100))
    a = servico.analisar(conta(), pdf)
    assert any("Total de entradas do período" in p.mensagem for p in a.problemas)


def test_linha_nao_reconhecida_bloqueia():
    from app.importacao import servico

    pdf = pdf_na_pasta("x.pdf", cenario_agosto(), ajustes=Ajustes(linha_estranha="Lançamento estranho sem valor"))
    a = servico.analisar(conta(), pdf)
    assert not a.pode_importar
    assert any(p.mensagem == "Linha que não consegui interpretar" for p in a.problemas)


def test_layout_desconhecido_vira_erro():
    from app.importacao import servico
    from app.ocorrencias import registro

    pdf = pdf_na_pasta("x.pdf", cenario_agosto(), ajustes=Ajustes(sem_marca_nubank=True))
    a = servico.analisar(conta(), pdf)
    assert a.erro and "Layout não reconhecido" in a.erro.mensagem
    assert registro.contar_abertas()["ERRO"] == 1


def test_extrato_de_conta_pj_entra_como_qualquer_outro():
    """Não há conta "PF" e conta "PJ": se a pessoa também tem uma conta de empresa (MEI),
    o extrato dela (cabeçalho com CNPJ) entra na conta que ela cadastrou, sem bloqueio."""
    from app.importacao import servico

    dani2 = segunda_conta_no_nubank()
    pdf = pdf_na_pasta("x.pdf", cenario_agosto(), pasta=dani2.pasta,
                       titular="DANIEL SERVICOS LTDA", documento="CNPJ 12.345.678/0001-90")
    a = servico.analisar(dani2, pdf)
    assert a.extrato.tipo_titular == "PJ" and a.pode_importar, a.erro
    servico.importar(a)
    assert contar("SELECT COUNT(*) FROM movimentacoes WHERE conta_id = ?", conta("Dani 2").id) == 12


def test_numero_da_conta_e_guardado_e_protege_contra_pdf_de_outra_conta():
    from app.importacao import servico

    assert conta().numero_conta is None
    servico.importar(servico.analisar(conta(), pdf_na_pasta("a.pdf", cenario_agosto())))
    assert conta().numero_conta == "12345678-9"          # preenchido sozinho na 1ª importação

    outro = pdf_na_pasta("b.pdf", cenario_agosto(), conta="99999999-1", saldo_inicial=5)
    a = servico.analisar(conta(), outro)
    assert a.erro and "número da conta" in a.erro.mensagem
    # o mesmo PDF na segunda conta (ainda sem número) entra
    assert servico.analisar(segunda_conta_no_nubank(), outro).pode_importar


def test_pdf_de_outro_banco_vira_erro():
    from app.importacao import servico

    c = conta("Dani 2")                    # a conta de exemplo é do Sicoob
    pdf = pdf_na_pasta("x.pdf", cenario_agosto(), pasta=c.pasta)
    a = servico.analisar(c, pdf)
    assert a.erro and "Sicoob" in a.erro.mensagem


def test_pdf_corrompido_vira_erro(tmp_path):
    from app.importacao import servico

    ruim = tmp_path / "ruim.pdf"
    ruim.write_bytes(b"isso nao e um pdf")
    a = servico.analisar(conta(), ruim)
    assert a.erro is not None


def test_rendimento_no_saldo_final():
    """Saldo final = inicial + entradas - saídas + rendimento também é aceito."""
    from app.importacao import servico

    pdf = pdf_na_pasta("x.pdf", [Dia(date(2026, 8, 3), [Mov("Entrada", "Resgate RDB", [], 1000)])],
                       ajustes=Ajustes(rendimento=37))
    a = servico.analisar(conta(), pdf)
    assert not [p for p in a.problemas if "Saldo final" in p.mensagem]


def test_pdf_com_texto_sem_espacos():
    """Alguns PDFs do Nubank vêm com as palavras coladas: '01DESETEMBRODE2026', '05AGO2026', 'Saldododia'."""
    from app.importacao import servico
    from app.leitores import nubank
    from app.leitores.base import conferir

    pdf = pdf_na_pasta("colado.pdf", cenario_agosto(), ajustes=Ajustes(colado=True))
    assert nubank.e_extrato(pdf)
    ext = nubank.ler(pdf)
    assert (ext.periodo_inicio, ext.periodo_fim) == (INICIO, FIM)
    assert ext.tipo_titular == "PF" and ext.numero_conta == "12345678-9" and ext.agencia == "0001"
    assert len(ext.itens) == 12 and not ext.nao_reconhecidas and conferir(ext) == []
    assert ext.itens[0].data == date(2026, 8, 3) and len(ext.saldos_dia) == 6

    a = servico.analisar(conta(), pdf)
    assert a.pode_importar, a.erro or [p.detalhe for p in a.problemas]
    servico.importar(a)
    # as regras também reconhecem o texto colado ("ResgateRDB")
    assert contar("SELECT COUNT(*) FROM movimentacoes m JOIN subcategorias s ON s.id = m.subcategoria_id"
                  " WHERE s.nome LIKE 'Resgate RDB%'") == 2


def test_mesmo_pdf_com_e_sem_espacos_le_igual():
    from app.leitores import nubank
    a = nubank.ler(pdf_na_pasta("normal.pdf", cenario_agosto()))
    b = nubank.ler(pdf_na_pasta("colado.pdf", cenario_agosto(), ajustes=Ajustes(colado=True)))
    assert [(i.data, i.tipo, i.valor) for i in a.itens] == [(i.data, i.tipo, i.valor) for i in b.itens]
    assert (a.saldo_inicial, a.saldo_final, a.total_entradas, a.total_saidas) == \
        (b.saldo_inicial, b.saldo_final, b.total_entradas, b.total_saidas)
    assert a.numero_conta == b.numero_conta == "12345678-9" and a.tipo_titular == b.tipo_titular


@pytest.mark.parametrize("colado", [False, True])
def test_bloco_das_empresas_na_ultima_pagina_nao_vira_movimentacao(colado):
    """'Nu Pagamentos S.A.' (fonte 9) + 'CNPJ: ...' (fonte 8) logo depois das movimentações."""
    from app.leitores import nubank
    from app.leitores.base import conferir
    pdf = pdf_na_pasta("legal.pdf", cenario_agosto(), ajustes=Ajustes(colado=colado, legal_sem_fonte_pequena=True))
    ext = nubank.ler(pdf)
    assert not ext.nao_reconhecidas and len(ext.itens) == 12 and conferir(ext) == []
    assert "CNPJ" not in " ".join(i.contraparte for i in ext.itens if not i.contraparte.startswith(("CELESC", "HORTI", "EMPRESA", "RECEITA")))
