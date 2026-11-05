"""Testes do fechamento mensal."""

import copy
from datetime import date

import pytest

from app import config
from tests.gerador_nubank import Dia, Mov, gerar

PIX_ENV, PIX_REC = "Transferência enviada pelo Pix", "Transferência recebida pelo Pix"
MES = "2026-08"


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))


def conta():
    from app.contas import repositorio as repo
    return next(c for c in repo.listar() if c.nome == "Daniel")


def dias_agosto():
    D = lambda d: date(2026, 8, d)
    return [
        Dia(D(3), [Mov("Entrada", PIX_REC, ["EMPRESA EXEMPLO LTDA -", "19.468.242/0001-32"], 300000),
                   Mov("Saída", PIX_ENV, ["CELESC DISTRIBUICAO S.A -", "08.336.783/0001-90 - BCO"], 50000)]),
        Dia(D(10), [Mov("Saída", PIX_ENV, ["FORNECEDOR X LTDA -", "11.222.333/0001-81"], 20000)]),
    ]


def importar(nome, dias, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)):
    from app.contas import repositorio as repo
    from app.importacao import servico
    repo.garantir_pastas()
    pdf = config.pasta_extratos() / "Daniel-Nubank" / nome
    gerar(pdf, dias, inicio=inicio, fim=fim, saldo_inicial=100000, itens_por_pagina=12)
    a = servico.analisar(conta(), pdf)
    if a.pode_importar:
        servico.importar(a)
    return a


def classificar_pendentes():
    from app.classificacao import servico as cl
    from app.importacao import consultas
    for m in consultas.movimentacoes(classificacoes=["Revisar"]):
        destino = ("Renda", "Salário") if m["tipo"] == "Entrada" else ("Outras despesas", "Outras despesas")
        cl.classificar([m["id"]], "Classificada", cl.subcategoria_por_nome(*destino))


def item(itens, trecho):
    return next(i for i in itens if trecho in i.texto)


# ---------------------------------------------------------------- checklist

def test_checklist_bloqueia_com_pendente():
    from app.fechamento import servico as fc
    importar("ago.pdf", dias_agosto())
    itens = fc.checklist(MES)
    assert not item(itens, "Revisão").ok and item(itens, "Revisão").bloqueia
    assert not fc.pode_fechar(itens)
    with pytest.raises(fc.ErroFechamento):
        fc.fechar(MES)


def test_checklist_extrato_parcial_bloqueia():
    from app.fechamento import servico as fc
    importar("parcial.pdf", dias_agosto(), fim=date(2026, 8, 15))
    classificar_pendentes()
    it = item(fc.checklist(MES), "cobrem o mês inteiro")
    assert not it.ok and "16–31/08" in it.detalhe


def test_conta_sem_extrato_so_avisa():
    from app.fechamento import servico as fc
    importar("ago.pdf", dias_agosto())
    classificar_pendentes()
    itens = fc.checklist(MES)
    aviso = item(itens, "Todas as contas ativas")
    # a segunda conta (o exemplo "Dani 2") não teve extrato: avisa, mas não impede fechar
    assert not aviso.ok and not aviso.bloqueia and "Dani 2" in aviso.detalhe
    assert fc.pode_fechar(itens)


# ---------------------------------------------------------------- fechar / travas

@pytest.fixture
def agosto_fechado():
    from app.fechamento import servico as fc
    importar("ago.pdf", dias_agosto())
    classificar_pendentes()
    fc.fechar(MES, "Fechamento de agosto")
    return fc


def test_fechar_grava_retrato_backup_e_log(agosto_fechado):
    fc = agosto_fechado
    from app.backup import backup
    from app.ocorrencias import registro
    assert fc.status(MES) == "Fechado"
    foto = fc.historico(MES)[-1]["retrato"]
    assert foto["receita"] == 300000 and foto["despesas"] == 70000 and foto["resultado"] == 230000
    assert foto["despesas_por_categoria"] == {"Moradia": 50000, "Outras despesas": 20000}
    assert foto["receitas_por_categoria"] == {"Renda": 300000}
    assert foto["investimentos"] == 0 and "retiradas" not in foto and "particular_qtd" not in foto
    assert any("fechamento-2026-08" in b.name for b in backup.listar_backups())
    assert registro.listar(niveis=["INFO"])[0].mensagem == "ago/2026 fechado"
    with pytest.raises(fc.ErroFechamento):
        fc.fechar(MES)                                                 # já fechado


def test_mes_fechado_nao_aceita_classificacao(agosto_fechado):
    from app.classificacao import servico as cl
    from app.importacao import consultas
    m = consultas.movimentacoes()[0]
    with pytest.raises(cl.ErroClassificacao, match="fechado"):
        cl.classificar([m["id"]], "Classificada", cl.subcategoria_por_nome("Lazer", "Hobbies"))


def test_mes_fechado_nao_aceita_movimentacoes_novas(agosto_fechado):
    novo = copy.deepcopy(dias_agosto())
    novo.append(Dia(date(2026, 8, 20), [Mov("Saída", PIX_ENV, ["OUTRO LTDA -", "33.444.555/0001-81"], 999)]))
    a = importar("ago-v2.pdf", novo)
    assert a.erro and "mês fechado" in a.erro.mensagem


def test_pdf_repetindo_so_o_que_ja_existe_passa(agosto_fechado):
    """Um PDF do mesmo período sem nada novo só registra o documento (não altera o mês)."""
    from app.importacao import consultas
    a = importar("ago-copia.pdf", dias_agosto())
    assert a.erro is None and not a.novas
    assert len(consultas.movimentacoes()) == 3


def test_regras_nao_mexem_em_mes_fechado(agosto_fechado):
    from app.classificacao import regras as rg
    rgs = rg.movimentacoes_para_avaliar(somente_novas=False)
    assert rgs == []


# ---------------------------------------------------------------- reabrir

def test_reabrir_exige_motivo_e_compara(agosto_fechado):
    fc = agosto_fechado
    from app.classificacao import servico as cl
    from app.importacao import consultas
    with pytest.raises(fc.ErroFechamento):
        fc.reabrir(MES, "")
    fc.reabrir(MES, "Descobri que o Fornecedor X era o conserto do carro")
    assert fc.status(MES) == "Aberto"

    fx = consultas.movimentacoes(busca="FORNECEDOR X")[0]
    cl.classificar([fx["id"]], "Classificada", cl.subcategoria_por_nome("Transporte", "Manutenção do veículo"))
    fc.fechar(MES, "Fechado de novo")

    antes, depois = fc.ultimos_dois_retratos(MES)
    mudancas = {k: (a, b) for k, a, b in fc.comparar(antes, depois)}
    assert mudancas == {"Despesa: Transporte": (0, 20000), "Despesa: Outras despesas": (20000, 0)}
    acoes = [h["acao"] for h in fc.historico(MES)]
    assert acoes == ["fechamento", "reabertura", "fechamento"]


def test_reabrir_mes_aberto_da_erro():
    from app.fechamento import servico as fc
    with pytest.raises(fc.ErroFechamento):
        fc.reabrir(MES, "motivo qualquer")


def test_faixas_de_dias():
    from app.fechamento.servico import _faixas
    D = lambda d: date(2026, 8, d)
    assert _faixas([D(1), D(2), D(3), D(7), D(9), D(10)]) == "01–03/08, 07/08, 09–10/08"
