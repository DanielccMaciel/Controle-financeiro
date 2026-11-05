"""Testes dos indicadores (receita, despesas, quanto sobrou, investido, saldo)."""

from datetime import date

import pytest

from app import config
from tests.ajudas import segunda_conta_no_nubank
from tests.gerador_nubank import Dia, Mov, gerar

PIX_ENV, PIX_REC = "Transferência enviada pelo Pix", "Transferência recebida pelo Pix"


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))


def conta(nome="Daniel"):
    from app.contas import repositorio as repo
    return next(c for c in repo.listar() if c.nome == nome)


def importar(nome, dias, inicio, fim, saldo_inicial):
    from app.contas import repositorio as repo
    from app.importacao import servico
    repo.garantir_pastas()
    pdf = config.pasta_extratos() / "Daniel-Nubank" / nome
    gerar(pdf, dias, inicio=inicio, fim=fim, saldo_inicial=saldo_inicial, itens_por_pagina=12)
    a = servico.analisar(conta(), pdf)
    assert a.pode_importar, [p.mensagem for p in a.problemas]
    servico.importar(a)


def sub(cat, nome):
    from app.classificacao.servico import subcategoria_por_nome
    sid = subcategoria_por_nome(cat, nome)
    assert sid, (cat, nome)
    return sid


def classificar_por_texto(trecho, cat, nome):
    from app.classificacao import servico as cl
    from app.importacao import consultas
    ids = [m["id"] for m in consultas.movimentacoes(busca=trecho)]
    assert ids, trecho
    cl.classificar(ids, "Classificada", sub(cat, nome))


@pytest.fixture
def dois_meses():
    """Julho: salário + luz. Agosto: salário, freela, RDB, mercado, luz, corretora, Pix para si mesmo
    (neutro) e 1 pendente."""
    D7, D8 = (lambda d: date(2026, 7, d)), (lambda d: date(2026, 8, d))
    importar("jul.pdf", [
        Dia(D7(10), [Mov("Entrada", PIX_REC, ["EMPRESA EXEMPLO LTDA -", "19.468.242/0001-32"], 500000)]),
        Dia(D7(12), [Mov("Saída", PIX_ENV, ["CELESC DISTRIBUICAO S.A -", "08.336.783/0001-90 - BCO"], 60000)]),
    ], date(2026, 7, 1), date(2026, 7, 31), 100000)
    importar("ago.pdf", [
        Dia(D8(1), [Mov("Entrada", PIX_REC, ["CLIENTE FREELA - ***.1-**"], 30000)]),
        Dia(D8(3), [
            Mov("Entrada", "Resgate RDB", [], 1000000),
            Mov("Saída", PIX_ENV, ["SUPERMERCADO EXEMPLO -", "82.956.160/0001-73"], 61857),
        ]),
        Dia(D8(5), [Mov("Saída", PIX_ENV, ["CORRETORA EXEMPLO S.A. -", "33.444.555/0001-06"], 267000)]),
        Dia(D8(12), [
            Mov("Saída", PIX_ENV, ["CELESC DISTRIBUICAO S.A -", "08.336.783/0001-90 - BCO"], 77197),
            Mov("Saída", PIX_ENV, ["FORNECEDOR X LTDA -", "11.222.333/0001-81"], 100000),
            Mov("Saída", PIX_ENV, ["DANIEL TESTE DA SILVA - ***.123.456-** - INTER"], 5000),
        ]),
        Dia(D8(29), [Mov("Entrada", PIX_REC, ["EMPRESA EXEMPLO LTDA -", "19.468.242/0001-32"], 250000)]),
    ], date(2026, 8, 1), date(2026, 8, 31), 540000)

    from app.classificacao import servico as cl
    from app.importacao import consultas
    classificar_por_texto("EMPRESA EXEMPLO", "Renda", "Salário")
    classificar_por_texto("CLIENTE FREELA", "Renda", "Freelance / serviços")
    classificar_por_texto("SUPERMERCADO", "Alimentação", "Mercado")
    classificar_por_texto("CORRETORA", "Investimentos", "Corretora / ações e fundos")
    # Pix para a própria conta em outro banco: o programa sugere "entre minhas contas" (neutro)
    assert cl.aceitar_sugestao([m["id"] for m in consultas.movimentacoes(busca="DANIEL TESTE")]) == 1
    # CELESC foi classificada pela regra inicial; FORNECEDOR X fica em Revisar de propósito


def test_formulas_do_mes(dois_meses):
    from app.analise import indicadores as ind
    jul, ago = ind.resumo_por_mes()
    assert [jul.mes, ago.mes] == ["2026-07", "2026-08"]

    assert jul.receita == 500000 and jul.despesas == 60000 and jul.resultado == 440000
    assert round(jul.margem, 1) == 88.0

    assert ago.receita == 30000 + 250000                          # freela + salário
    assert ago.despesas == 61857 + 77197                          # mercado + CELESC
    assert ago.resultado == 280000 - 139054                       # quanto sobrou
    assert ago.investimentos == 267000                            # fora do resultado
    assert ago.neutro_entradas == 1000000                         # RDB não é receita
    assert ago.neutro_saidas == 5000                              # Pix para a própria conta não é despesa
    assert (ago.revisar_qtd, ago.revisar_valor) == (1, 100000)    # pendente, avisado à parte
    assert not hasattr(ago, "retiradas") and not hasattr(ago, "particular_qtd")


def test_resgate_de_investimento_abate_o_investido(dois_meses):
    """Investido = aportes − resgates: dinheiro voltando da corretora reduz o total, e não vira receita."""
    from app.analise import indicadores as ind
    importar("ago2.pdf", [Dia(date(2026, 8, 30), [
        Mov("Entrada", PIX_REC, ["CORRETORA EXEMPLO S.A. -", "33.444.555/0001-06"], 67000)])],
        date(2026, 8, 30), date(2026, 8, 31), 0)
    classificar_por_texto("CORRETORA", "Investimentos", "Corretora / ações e fundos")
    ago = ind.resumo_por_mes()[1]
    assert ago.investimentos == 267000 - 67000 and ago.receita == 280000
    linhas = ind.despesas_por_categoria("2026-08", natureza="investimento")
    assert [(r["categoria"], r["valor"], r["qtd"]) for r in linhas] == [("Investimentos", 200000, 2)]


def test_saldo_no_fim_do_mes(dois_meses):
    from app.analise import indicadores as ind
    jul, ago = ind.resumo_por_mes()
    assert jul.saldo == 100000 + 500000 - 60000
    esperado_ago = 540000 + 30000 + 1000000 - 61857 - 267000 - 77197 - 100000 - 5000 + 250000
    assert ago.saldo == esperado_ago
    assert ago.contas_com_saldo == ["Daniel"]


def test_margem_vazia_sem_receita():
    from app.analise.indicadores import ResumoMes
    assert ResumoMes("2026-08", receita=0, despesas=100).margem is None
    assert ResumoMes("2026-08", receita=-50, despesas=0).margem is None


def test_por_categoria_e_variacao(dois_meses):
    from app.analise import indicadores as ind
    cats = ind.por_categoria("2026-08")
    assert cats == {"Moradia": 77197, "Alimentação": 61857}
    var = {v.categoria: v for v in ind.variacao_categorias("2026-08", "2026-07")}
    assert var["Moradia"].anterior == 60000 and var["Moradia"].atual == 77197
    assert round(var["Moradia"].percentual, 1) == 28.7
    assert var["Alimentação"].percentual is None   # não existia no mês anterior


def test_receita_por_subcategoria(dois_meses):
    from app.analise import indicadores as ind
    rec = ind.despesas_por_categoria("2026-08", natureza="receita")
    assert sum(r["valor"] for r in rec) == 280000
    assert {r["subcategoria"]: r["valor"] for r in rec} == {"Salário": 250000, "Freelance / serviços": 30000}


def test_estorno_reduz_receita(dois_meses):
    """Uma devolução (saída classificada numa categoria de receita) reduz a receita."""
    from app.analise import indicadores as ind
    from app.classificacao import servico as cl
    from app.importacao import consultas
    fx = consultas.movimentacoes(busca="FORNECEDOR X")[0]
    cl.classificar([fx["id"]], "Classificada", sub("Renda", "Freelance / serviços"))
    ago = ind.resumo_por_mes()[1]
    assert ago.receita == 280000 - 100000 and ago.revisar_qtd == 0


def test_drill_down_ate_a_movimentacao(dois_meses):
    from app.analise import indicadores as ind
    movs = ind.movimentacoes_da_subcategoria("2026-08", sub("Moradia", "Energia"))
    assert len(movs) == 1 and "CELESC" in movs[0]["contraparte"] and movs[0]["documentos"] == "ago.pdf"


def test_filtro_por_conta(dois_meses):
    from app.analise import indicadores as ind
    outra = conta("Dani 2")
    assert ind.resumo_por_mes([outra.id]) == []
    assert len(ind.resumo_por_mes([conta().id])) == 2


def test_duas_contas_somam_no_total_e_separam_no_filtro(dois_meses):
    """A segunda conta entra no total geral e pode ser vista sozinha."""
    from app.analise import indicadores as ind
    from app.contas import repositorio as repo
    from app.importacao import servico
    dani2 = segunda_conta_no_nubank()
    pdf = config.pasta_extratos() / dani2.pasta / "ago-2.pdf"
    gerar(pdf, [Dia(date(2026, 8, 10), [
        Mov("Entrada", PIX_REC, ["EMPRESA EXEMPLO LTDA -", "19.468.242/0001-32"], 40000),
        Mov("Saída", PIX_ENV, ["SUPERMERCADO EXEMPLO -", "82.956.160/0001-73"], 10000)])],
        inicio=date(2026, 8, 1), fim=date(2026, 8, 31), saldo_inicial=20000, conta="22222222-2")
    servico.importar(servico.analisar(dani2, pdf))
    classificar_por_texto("EMPRESA EXEMPLO", "Renda", "Salário")
    classificar_por_texto("SUPERMERCADO", "Alimentação", "Mercado")

    tudo = ind.resumo_por_mes()[1]
    so_2 = ind.resumo_por_mes([dani2.id])[0]
    so_1 = ind.resumo_por_mes([conta().id])[1]
    assert (so_2.receita, so_2.despesas, so_2.saldo) == (40000, 10000, 50000)
    assert tudo.receita == so_1.receita + so_2.receita == 280000 + 40000
    assert tudo.despesas == so_1.despesas + so_2.despesas
    assert tudo.saldo == so_1.saldo + so_2.saldo and tudo.contas_com_saldo == ["Daniel", "Dani 2"]
    assert repo.obter(dani2.id).numero_conta == "22222222-2"


def test_rotulos():
    from app.analise.indicadores import fim_do_mes, rotulo_mes
    assert rotulo_mes("2026-08") == "ago/2026"
    assert fim_do_mes("2026-02") == "2026-02-28" and fim_do_mes("2028-02") == "2028-02-29"
