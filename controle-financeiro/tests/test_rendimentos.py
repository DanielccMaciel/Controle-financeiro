"""Testes das caixinhas (Extrato de Rendimentos do Nubank) com PDFs FALSOS."""

from datetime import date

import pytest

from app import config
from tests.ajudas import segunda_conta_no_nubank
from tests.gerador_caixinhas import AjustesC, Caixinha, MovC, cenario_setembro, gerar

INICIO, FIM = date(2026, 9, 1), date(2026, 9, 30)


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    return tmp_path


def conta(nome="Daniel"):
    from app.contas import repositorio as repo
    repo.garantir_pastas()
    return next(c for c in repo.listar() if c.nome == nome)


def pdf(nome, caixinhas, **kw):
    conta()
    destino = config.pasta_extratos() / "Daniel-Nubank" / nome
    params = dict(inicio=INICIO, fim=FIM)
    params.update(kw)
    gerar(destino, caixinhas, **params)
    return destino


def test_le_o_extrato_de_rendimentos():
    from app.rendimentos import leitor_nubank as L
    arq = pdf("cx.pdf", cenario_setembro())
    assert L.e_extrato_de_rendimentos(arq)
    ext = L.ler(arq)
    assert (ext.periodo_inicio, ext.periodo_fim, ext.tipo_titular) == (INICIO, FIM, "PF")
    assert len(ext.aplicacoes) == 1 and not ext.nao_reconhecidas
    ap = ext.aplicacoes[0]
    assert ap.nome == "Reservadeemergencia" and ap.saldo_final == 4_512_345
    assert ap.produto.startswith("RDB Resgate")
    assert len(ap.movimentos) == 6
    m = ap.movimentos[4]
    assert (m.data, m.tipo, m.bruto, m.ir, m.iof, m.liquido) == (date(2026, 9, 18), "Resgate", 500_000, 2_210, 35, 497_755)
    assert [(r.data, r.valor) for r in ap.rendimentos] == [(FIM, 41_233)]
    assert "setembro" in ap.rendimentos[0].rotulo
    assert L.conferir(ext) == []


def test_tabela_continua_na_pagina_seguinte_e_duas_caixinhas():
    from app.rendimentos import leitor_nubank as L
    movs = [MovC(date(2026, 9, 1 + i % 28), "Resgate", 10_000 + i * 111, i, 0) for i in range(40)]
    cxs = [Caixinha("Reserva", 1_000_000, movs, 12_345),
           Caixinha("Viagem 2027", 250_000, [MovC(date(2026, 9, 9), "Aplicação", 50_000)], 2_000)]
    arq = pdf("duas.pdf", cxs)
    ext = L.ler(arq)
    assert ext.paginas >= 3 and L.conferir(ext) == []
    assert [(a.nome, len(a.movimentos), a.saldo_final) for a in ext.aplicacoes] == \
        [("Reserva", 40, 1_000_000), ("Viagem 2027", 1, 250_000)]
    assert ext.aplicacoes[1].movimentos[0].tipo == "Aplicação"
    assert sum(r.valor for a in ext.aplicacoes for r in a.rendimentos) == 14_345


def test_extrato_de_conta_nao_e_confundido():
    from app.rendimentos import servico
    from tests.gerador_nubank import cenario_agosto, gerar as gerar_conta
    conta()
    arq = config.pasta_extratos() / "Daniel-Nubank" / "conta.pdf"
    gerar_conta(arq, cenario_agosto(), inicio=date(2026, 8, 1), fim=date(2026, 8, 31), saldo_inicial=1000)
    assert not servico.e_pdf_de_rendimentos(arq)
    assert servico.e_pdf_de_rendimentos(pdf("cx.pdf", cenario_setembro()))


def test_importa_e_consulta():
    from app.banco.conexao import conectar
    from app.importacao.servico import pdfs_pendentes
    from app.rendimentos import servico
    arq = pdf("cx.pdf", cenario_setembro())
    assert arq in pdfs_pendentes(conta())
    a = servico.analisar(conta(), arq)
    assert a.pode_importar, a.erro or [p.detalhe for p in a.problemas]
    assert len(a.novas) == 6
    servico.importar(a)
    assert not arq.exists()                                    # foi para extratos/Daniel-Nubank/caixinhas/2026-09/
    guardado = config.pasta_extratos() / "Daniel-Nubank" / "caixinhas" / "2026-09" / "cx.pdf"
    assert guardado.exists() and guardado not in pdfs_pendentes(conta())

    aps = servico.aplicacoes()
    assert len(aps) == 1 and aps[0]["conta_nome"] == "Daniel"
    assert servico.rendimento_por_mes() == {"2026-09": 41_233}
    r = servico.resumo_do_mes("2026-09")
    assert r.rendimento == 41_233 and r.saldo == 4_512_345 and r.saldo_em == "2026-09-30"
    assert r.impostos == 12 + 1_034 * 2 + 2_210 + 35 + 310
    assert r.resgates_liquido == sum(m["valor_liquido"] for m in servico.movimentos())
    assert len(servico.movimentos(mes="2026-09")) == 6 and servico.meses_com_dados() == ["2026-09"]
    assert servico.resumo_do_mes("2026-10").saldo is None
    # nada disso vira movimentação da conta nem documento de extrato
    conn = conectar()
    try:
        assert conn.execute("SELECT COUNT(*) FROM movimentacoes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM documentos").fetchone()[0] == 0
    finally:
        conn.close()
    # o mesmo arquivo de novo: já importado
    assert servico.analisar(conta(), guardado).documento_existente is not None


def test_pdf_parcial_e_depois_completo_nao_duplica():
    from app.rendimentos import servico
    cx = cenario_setembro()[0]
    parcial = Caixinha(cx.nome, 4_900_000, cx.movs[:3], 20_000)
    a = servico.analisar(conta(), pdf("parcial.pdf", [parcial], fim=date(2026, 9, 15)))
    servico.importar(a)
    assert servico.rendimento_por_mes() == {"2026-09": 20_000}
    b = servico.analisar(conta(), pdf("completo.pdf", [cx]))
    assert b.pode_importar and len(b.novas) == 3 and len(b.existentes) == 3
    servico.importar(b)
    assert len(servico.movimentos()) == 6
    assert servico.rendimento_por_mes() == {"2026-09": 41_233}      # o do PDF completo substitui
    assert [s["data"] for s in servico.saldos()] == ["2026-09-15", "2026-09-30"]
    assert servico.resumo_do_mes("2026-09").saldo == 4_512_345
    assert servico.saldo_total_por_data() == [("2026-09-15", 4_900_000), ("2026-09-30", 4_512_345)]


def test_varios_meses_e_apelido():
    from app.rendimentos import servico
    cx = cenario_setembro()[0]
    servico.importar(servico.analisar(conta(), pdf("set.pdf", [cx])))
    out = Caixinha(cx.nome, 4_700_000, [MovC(date(2026, 10, 5), "Aplicação", 150_000)], 37_655)
    servico.importar(servico.analisar(conta(), pdf("out.pdf", [out], inicio=date(2026, 10, 1), fim=date(2026, 10, 31))))
    assert servico.rendimento_por_mes() == {"2026-09": 41_233, "2026-10": 37_655}
    assert len(servico.aplicacoes()) == 1
    assert servico.resumo_do_mes("2026-10").resgates_liquido == 0
    ap = servico.aplicacoes()[0]
    servico.definir_apelido(ap["id"], "Reserva de emergência")
    assert servico.nome_exibicao(servico.aplicacoes()[0]) == "Reserva de emergência"
    assert servico.rendimento_por_mes([ap["id"]]) == servico.rendimento_por_mes()


def test_liquido_errado_e_linha_estranha_bloqueiam():
    from app.ocorrencias import registro
    from app.rendimentos import servico
    cx = cenario_setembro()[0]
    cx.movs[1].liquido_delta = 100
    a = servico.analisar(conta(), pdf("erro.pdf", [cx]))
    assert not a.pode_importar and any("valor líquido" in p.mensagem for p in a.problemas)
    b = servico.analisar(conta(), pdf("estranho.pdf", cenario_setembro(), ajustes=AjustesC(linha_estranha="Estorno")))
    assert not b.pode_importar and any("não consegui interpretar" in p.mensagem for p in b.problemas)
    assert sum(registro.contar_abertas().values()) == 2
    with pytest.raises(ValueError):
        servico.importar(b)


def test_layout_desconhecido_e_qualquer_conta_aceita_o_pdf():
    """O PDF de caixinhas entra na conta que a pessoa escolher, seja de CPF ou de CNPJ."""
    from app.leitores.base import ErroLeitura
    from app.rendimentos import leitor_nubank as L, servico
    arq = pdf("cx.pdf", cenario_setembro())
    assert servico.analisar(segunda_conta_no_nubank(), arq).pode_importar
    de_empresa = pdf("pj.pdf", cenario_setembro(), titular="PJ", nome_titular="DANIEL SERVICOS LTDA")
    a = servico.analisar(conta(), de_empresa)
    assert a.extrato.tipo_titular == "PJ" and a.pode_importar
    outro = pdf("outro.pdf", cenario_setembro(), ajustes=AjustesC(sem_marca=True))
    assert not L.e_extrato_de_rendimentos(outro)
    with pytest.raises(ErroLeitura, match="Layout não reconhecido"):
        L.ler(outro)


def test_todas_as_caixinhas_sao_da_pessoa_e_da_para_filtrar_por_banco_e_conta():
    """Não existe mais "de quem é a caixinha": todas somam. Filtros: banco e conta."""
    from app.rendimentos import servico
    from tests.gerador_caixinhas import gerar as g
    cx = cenario_setembro()[0]
    servico.importar(servico.analisar(conta(), pdf("d1.pdf", [cx])))
    dani2 = segunda_conta_no_nubank()
    arq = config.pasta_extratos() / dani2.pasta / "d2.pdf"
    g(arq, [Caixinha("Viagem", 300_000, [], 2_500), Caixinha("Carro", 100_000, [], 700)], inicio=INICIO, fim=FIM)
    a = servico.analisar(dani2, arq)
    assert a.pode_importar, a.erro or a.problemas
    servico.importar(a)

    aps = {x["nome"]: x for x in servico.aplicacoes()}
    assert set(aps) == {"Reservadeemergencia", "Viagem", "Carro"}
    assert "finalidade" not in aps["Viagem"] and aps["Viagem"]["conta_nome"] == "Dani 2"
    assert aps["Reservadeemergencia"]["conta_nome"] == "Daniel" and aps["Carro"]["banco"] == "Nubank"
    todas = servico.filtrar()
    assert sorted(todas) == sorted(x["id"] for x in aps.values())
    assert servico.rendimento_por_mes(todas) == servico.rendimento_por_mes() == {"2026-09": 41_233 + 3_200}
    assert servico.resumo_do_mes("2026-09", todas).saldo == 4_512_345 + 400_000
    # por conta (é o que o filtro de contas do Dashboard usa)
    so_dani2 = servico.filtrar(None, [dani2.id])
    assert sorted(so_dani2) == sorted([aps["Viagem"]["id"], aps["Carro"]["id"]])
    assert servico.rendimento_por_mes(so_dani2) == {"2026-09": 3_200}

    # o apelido não é desfeito por uma nova importação
    servico.definir_apelido(aps["Carro"]["id"], "Troca do carro")
    arq2 = config.pasta_extratos() / dani2.pasta / "d2-out.pdf"
    g(arq2, [Caixinha("Viagem", 310_000, [], 2_600), Caixinha("Carro", 101_000, [], 710)],
      inicio=date(2026, 10, 1), fim=date(2026, 10, 31))
    servico.importar(servico.analisar(dani2, arq2))
    aps = {x["nome"]: x for x in servico.aplicacoes()}
    assert aps["Carro"]["apelido"] == "Troca do carro" and servico.nome_exibicao(aps["Carro"]) == "Troca do carro"
    servico.definir_apelido(aps["Carro"]["id"], "  ")
    assert servico.nome_exibicao({x["nome"]: x for x in servico.aplicacoes()}["Carro"]) == "Carro"

    # por banco: tudo Nubank por enquanto; Sicoob vazio não vira "todas"
    assert set(servico.rendimento_por_mes_e_banco(todas)) == {"Nubank"}
    assert servico.filtrar("Sicoob") == [] and sorted(servico.filtrar("Nubank")) == sorted(todas)
    assert servico.rendimento_por_mes([]) == {} and servico.resumo_do_mes("2026-09", []).saldo is None
    assert servico.ultimo_periodo(aps["Viagem"]["id"]) == "2026-10-31"
    assert not hasattr(servico, "FINALIDADES")          # não há mais "de quem é a caixinha"
