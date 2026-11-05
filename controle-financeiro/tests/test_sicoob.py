"""Testes do leitor do Sicoob com extratos FALSOS no layout analisado."""

from datetime import date

import pytest

from app import config
from tests.gerador_sicoob import AjustesS, DiaS, Lanc, cenario_setembro, gerar

INICIO, FIM = date(2026, 9, 1), date(2026, 9, 30)
SALDO = 123456


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    return tmp_path


def conta():
    from app.contas import repositorio as repo
    repo.garantir_pastas()
    return next(c for c in repo.listar() if c.nome == "Dani 2")     # a conta de exemplo é do Sicoob


def pdf(nome, dias, **kw):
    conta()
    destino = config.pasta_extratos() / "Dani-2-Sicoob" / nome
    params = dict(inicio=INICIO, fim=FIM, saldo_anterior=SALDO)
    params.update(kw)
    return destino, gerar(destino, dias, **params)


def test_le_e_confere_o_mes():
    from app.leitores import sicoob
    from app.leitores.base import conferir
    arq, info = pdf("set.pdf", cenario_setembro())
    ext = sicoob.ler(arq)
    assert ext.layout == "sicoob_v1" and ext.numero_conta == "12.345-6"
    assert (ext.periodo_inicio, ext.periodo_fim) == (INICIO, FIM)
    assert ext.saldo_inicial == SALDO and ext.saldo_final == info["saldo_final"]
    assert len(ext.itens) == 9 and not ext.nao_reconhecidas
    assert {d: s for d, (s, _) in ext.saldos_dia.items()} == info["saldos"]
    assert conferir(ext) == []
    primeiro = ext.itens[0]
    assert (primeiro.data, primeiro.tipo, primeiro.valor) == (date(2026, 9, 2), "Entrada", 45000)
    assert primeiro.operacao == "CR.COMPRAS" and primeiro.contraparte == "SIPAG_Cre._Visa DOC.:1000000001"
    pix = next(i for i in ext.itens if i.tipo == "Saída" and i.valor == 500000)
    assert "DANIEL_TESTE_DA_SILVA" in pix.contraparte and pix.data == date(2026, 9, 18)


def test_valor_largo_com_letra_na_linha_de_baixo():
    """1.850,00 e 2.500,00 têm a letra C em outra linha; 5.000,00 D também."""
    from app.leitores import sicoob
    arq, _ = pdf("set.pdf", cenario_setembro())
    ext = sicoob.ler(arq)
    valores = sorted(i.valor for i in ext.itens)
    assert 185000 in valores and 250000 in valores and 500000 in valores
    assert [i.tipo for i in ext.itens if i.valor == 500000] == ["Saída"]


def test_varias_paginas():
    from app.leitores import sicoob
    from app.leitores.base import conferir
    dias = [DiaS(date(2026, 9, d), [
        Lanc("C", "CR.COMPRAS", ["SIPAG_Cre._Visa", f"DOC.:{d}{k}"], 10000 * k + d * 137) for k in range(1, 5)
    ]) for d in range(1, 29)]
    arq, info = pdf("longo.pdf", dias)
    ext = sicoob.ler(arq)
    assert ext.paginas >= 3 and len(ext.itens) == 28 * 4
    assert conferir(ext) == [] and ext.saldo_final == info["saldo_final"]


def test_importa_e_nao_duplica_e_distingue_identicas():
    from app.banco.conexao import conectar
    from app.importacao import servico
    arq, _ = pdf("set.pdf", cenario_setembro())
    a = servico.analisar(conta(), arq)
    assert a.pode_importar, [p.detalhe for p in a.problemas] or a.erro
    assert len(a.novas) == 9          # as duas idênticas do dia 05 contam como duas
    servico.importar(a)
    # um PDF parcial do mesmo mês (até o dia 10) não acrescenta nada
    arq2, _ = pdf("parcial.pdf", cenario_setembro()[:3], fim=date(2026, 9, 10))
    b = servico.analisar(conta(), arq2)
    assert b.pode_importar and len(b.novas) == 0 and len(b.existentes) == 6
    conn = conectar()
    try:
        assert conn.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0] == 9
        assert conn.execute("SELECT COUNT(*) FROM saldos_diarios").fetchone()[0] == 5
    finally:
        conn.close()


def test_saldo_do_dia_errado_bloqueia():
    from app.importacao import servico
    arq, _ = pdf("erro.pdf", cenario_setembro(), ajustes=AjustesS(saldo_dia_delta={date(2026, 9, 10): 100}))
    a = servico.analisar(conta(), arq)
    assert not a.pode_importar
    assert any("Saldo do dia 10/09/2026" in p.mensagem for p in a.problemas)


def test_linha_estranha_bloqueia():
    from app.importacao import servico
    arq, _ = pdf("estranho.pdf", cenario_setembro(), ajustes=AjustesS(linha_estranha="LANCAMENTOFUTURO"))
    a = servico.analisar(conta(), arq)
    assert not a.pode_importar and any("não consegui interpretar" in p.mensagem for p in a.problemas)


def test_sem_saldo_anterior_e_pdf_de_outro_banco():
    from app.leitores import sicoob
    from app.leitores.base import ErroLeitura
    arq, _ = pdf("sem.pdf", cenario_setembro(), ajustes=AjustesS(sem_saldo_anterior=True))
    with pytest.raises(ErroLeitura, match="SALDO ANTERIOR"):
        sicoob.ler(arq)
    arq2, _ = pdf("outro.pdf", cenario_setembro(), ajustes=AjustesS(sem_marca=True))
    with pytest.raises(ErroLeitura, match="Layout não reconhecido"):
        sicoob.ler(arq2)


def test_periodo_virando_o_ano():
    from app.leitores import sicoob
    from app.leitores.base import conferir
    dias = [DiaS(date(2026, 12, 30), [Lanc("C", "CR.COMPRAS", ["SIPAG_Cre._Visa"], 10000)]),
            DiaS(date(2027, 1, 2), [Lanc("D", "DEB.TARIFA", [], 990)])]
    arq, _ = pdf("virada.pdf", dias, inicio=date(2026, 12, 15), fim=date(2027, 1, 15))
    ext = sicoob.ler(arq)
    assert [i.data for i in ext.itens] == [date(2026, 12, 30), date(2027, 1, 2)]
    assert conferir(ext) == []
