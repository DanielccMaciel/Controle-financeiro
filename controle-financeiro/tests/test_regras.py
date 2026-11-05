"""Testes das regras de classificação."""

from datetime import date

import pytest

from app import config
from tests.ajudas import segunda_conta_no_nubank
from tests.gerador_nubank import Dia, Mov, gerar

INICIO, FIM = date(2026, 8, 1), date(2026, 8, 31)
PIX_ENV, PIX_REC = "Transferência enviada pelo Pix", "Transferência recebida pelo Pix"
DEBITO = "Compra no débito"


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))


def conta(nome="Daniel"):
    from app.contas import repositorio as repo
    return next(c for c in repo.listar() if c.nome == nome)


def importar(nome, dias, conta_nome="Daniel", pasta="Daniel-Nubank", numero="12345678-9"):
    from app.contas import repositorio as repo
    from app.importacao import servico
    repo.garantir_pastas()
    pdf = config.pasta_extratos() / pasta / nome
    gerar(pdf, dias, inicio=INICIO, fim=FIM, saldo_inicial=5000000, itens_por_pagina=12, conta=numero)
    a = servico.analisar(conta(conta_nome), pdf)
    assert a.pode_importar, a.erro or [p.mensagem for p in a.problemas]
    servico.importar(a)


def movs(**kw):
    from app.importacao import consultas
    return consultas.movimentacoes(**kw)


def por_cp(trecho):
    return next(m for m in movs() if trecho in (m["contraparte"] or m["operacao"]))


def sub(cat, nome):
    from app.classificacao.servico import subcategoria_por_nome
    sid = subcategoria_por_nome(cat, nome)
    assert sid, (cat, nome)
    return sid


def agosto_pessoal():
    """Um mês de pessoa física: salário, contas de casa, mercado, apps, corretora (nomes fictícios)."""
    D = lambda d: date(2026, 8, d)
    return [
        Dia(D(1), [Mov("Entrada", PIX_REC, ["EMPRESA EXEMPLO LTDA - 22.333.444/0001-55 - BCO", "BRADESCO S.A. (0237)"], 650000)]),
        Dia(D(3), [
            Mov("Entrada", "Resgate RDB", [], 100000),
            Mov("Saída", PIX_ENV, ["IMOBILIARIA MODELO LTDA -", "82.956.160/0001-73 - ITAÚ"], 180000),
            Mov("Saída", "Aplicação RDB", [], 50000),
        ]),
        Dia(D(5), [
            Mov("Saída", PIX_ENV, ["DANIEL TESTE DA SILVA - ***.123.456-** - BCO", "INTER S.A. (0077)"], 267000),
            Mov("Saída", DEBITO, ["UBER *TRIP"], 2390),
        ]),
        Dia(D(12), [
            Mov("Saída", DEBITO, ["IFOOD *RESTAURANTE EXEMPLO"], 8428),
            Mov("Saída", PIX_ENV, ["CELESC DISTRIBUICAO S.A -", "08.336.783/0001-90 - BCO BRADESCO"], 16367),
            Mov("Saída", DEBITO, ["NETFLIX.COM"], 4490),
            Mov("Saída", PIX_ENV, ["FORNECEDOR DESCONHECIDO LTDA -", "11.222.333/0001-81 - BCO"], 88000),
        ]),
        Dia(D(18), [Mov("Saída", "Pagamento de boleto efetuado", ["CONDOMINIO EDIFICIO EXEMPLO"], 46170)]),
        Dia(D(20), [
            Mov("Saída", DEBITO, ["SPOTIFY"], 2190),
            Mov("Saída", PIX_ENV, ["CORRETORA EXEMPLO S.A. - 00.394.460/0058-87 - BCO", "DO BRASIL S.A. (0001)"], 100000),
        ]),
        Dia(D(28), [
            Mov("Saída", "Pagamento de fatura", [], 111859),
        ]),
        Dia(D(30), [
            # CNPJ quebrado por espaço, como acontece em PDF real
            Mov("Saída", PIX_ENV, ["SUPERMERCADO EXEMPLO - 02.831.172/0001-", "32 - ITAÚ UNIBANCO S.A. (0341)"], 80903),
        ]),
    ]


# ---------------------------------------------------------------- utilitários

def test_cnpj_mesmo_quebrado():
    from app.classificacao.regras import cnpjs
    assert cnpjs("SUPERMERCADO - 02.831.172/0001- 32 - ITAÚ") == {"02831172000132"}
    assert cnpjs("LOJA - 20.089.871 /0001-30 - STONE") == {"20089871000130"}
    assert cnpjs("FULANA - •••.672.800-•• - NU") == set()          # CPF mascarado não conta


# ---------------------------------------------------------------- regras iniciais

def test_regras_iniciais_sao_pessoais():
    from app.classificacao import regras as rg
    regras = {r.nome: r for r in rg.listar()}
    assert set(regras) == {"Resgate RDB", "Aplicação RDB", "CELESC", "Fatura do cartão",
                           "Uber", "iFood", "Netflix", "Spotify"}
    assert all(r.origem == "inicial" and r.conta_id is None and r.resultado for r in regras.values())
    # só o que é certeza é aplicado direto; o resto é sugestão para a pessoa confirmar
    assert {n for n, r in regras.items() if r.acao == "aplicar"} == {"Resgate RDB", "Aplicação RDB", "CELESC"}
    assert regras["CELESC"].resultado == "Moradia › Energia"
    assert regras["Fatura do cartão"].descrever_condicao() == 'Operação contém o texto "PAGAMENTO DE FATURA" · saída'


def test_regras_iniciais_no_cenario_de_agosto():
    from app.classificacao.servico import contar_por_classificacao
    importar("ago.pdf", agosto_pessoal())

    aplicadas = {"CELESC": "Energia", "Resgate RDB": "Resgate RDB / caixinha", "Aplicação RDB": "Aplicação RDB / caixinha"}
    for trecho, nome in aplicadas.items():
        m = por_cp(trecho)
        assert (m["classificacao"], m["subcategoria"], m["origem_classificacao"]) == ("Classificada", nome, "regra"), trecho

    # sugestões (você confirma)
    sugeridas = {
        "Pagamento de fatura": "Cartão de crédito › Fatura do cartão",
        "UBER": "Transporte › Transporte por app / táxi", "IFOOD": "Alimentação › Delivery",
        "NETFLIX": "Assinaturas e serviços › Streaming", "SPOTIFY": "Assinaturas e serviços › Streaming",
        "DANIEL TESTE": "Movimentação interna › Transferência entre minhas contas",
    }
    for trecho, rotulo in sugeridas.items():
        m = por_cp(trecho)
        assert (m["classificacao"], m["sugestao_rotulo"]) == ("Revisar", rotulo), trecho
    # sem regra: salário, aluguel, condomínio, corretora, mercado e o fornecedor desconhecido
    for trecho in ("EMPRESA EXEMPLO", "IMOBILIARIA", "CONDOMINIO", "CORRETORA", "SUPERMERCADO", "FORNECEDOR DESCONHECIDO"):
        m = por_cp(trecho)
        assert m["classificacao"] == "Revisar" and m["sugestao_rotulo"] is None, trecho
    assert contar_por_classificacao() == {"Classificada": 3, "Revisar": 12}


def test_contador_de_uso():
    from app.classificacao import regras as rg
    importar("ago.pdf", agosto_pessoal())
    assert next(r for r in rg.listar() if r.nome == "Resgate RDB").vezes_aplicada == 1


# ---------------------------------------------------------------- aprender com correção

def test_criar_regra_a_partir_da_movimentacao_e_reaplicar():
    from app.classificacao import regras as rg
    from app.classificacao import servico as cl
    importar("ago.pdf", agosto_pessoal())
    m = por_cp("FORNECEDOR DESCONHECIDO")
    prop = rg.proposta_a_partir_de(m)
    assert prop["condicao"] == "cnpj" and prop["texto"] == "11222333000181"

    reparo = sub("Moradia", "Manutenção da casa")
    cl.classificar([m["id"]], "Classificada", reparo)
    rg.criar(nome=prop["nome"], campo=prop["campo"], condicao="cnpj", texto=prop["texto"],
             subcategoria_id=reparo, tipo_mov="Saída", origem="correcao")

    # mês seguinte: o mesmo fornecedor é classificado sozinho
    importar("set.pdf", [Dia(date(2026, 8, 31), [
        Mov("Saída", PIX_ENV, ["FORNECEDOR DESCONHECIDO LTDA -", "11.222.333/0001-81 - BCO"], 12345)])])
    nova = next(x for x in movs(busca="DESCONHECIDO") if x["valor"] == 12345)
    assert nova["subcategoria"] == "Manutenção da casa" and nova["origem_classificacao"] == "regra"


def test_regra_vale_para_todas_as_contas_ou_so_para_uma():
    """Regra sem conta vale para a conta Daniel e para a Dani 2; com conta, só para ela."""
    from app.classificacao import regras as rg
    from app.classificacao import servico as cl
    mercado = [Dia(date(2026, 8, 30), [Mov("Saída", DEBITO, ["SUPERMERCADO EXEMPLO"], 5000),
                                         Mov("Saída", DEBITO, ["PADARIA EXEMPLO"], 1500)])]
    importar("d1.pdf", mercado)
    importar("d2.pdf", mercado, conta_nome="Dani 2", pasta=segunda_conta_no_nubank().pasta, numero="22222222-2")

    rg.criar(nome="Mercado", campo="contraparte", condicao="contem", texto="supermercado exemplo",
             subcategoria_id=sub("Alimentação", "Mercado"))
    so_dani2 = rg.criar(nome="Padaria (só Dani 2)", campo="contraparte", condicao="contem", texto="padaria exemplo",
                        subcategoria_id=sub("Alimentação", "Padaria e feira"), conta_id=conta("Dani 2").id)
    assert cl.aplicar_padroes(somente_pendentes=False)["aplicadas"] == 3

    por = {(m["conta_nome"], m["contraparte"]): m for m in movs()}
    assert por[("Daniel", "SUPERMERCADO EXEMPLO")]["subcategoria"] == "Mercado"
    assert por[("Dani 2", "SUPERMERCADO EXEMPLO")]["subcategoria"] == "Mercado"
    assert por[("Dani 2", "PADARIA EXEMPLO")]["subcategoria"] == "Padaria e feira"
    assert por[("Daniel", "PADARIA EXEMPLO")]["classificacao"] == "Revisar"
    regra = next(r for r in rg.listar() if r.id == so_dani2)
    assert regra.descrever_condicao().endswith("só na conta Dani 2")


def test_reaplicar_nao_mexe_no_que_voce_decidiu():
    from app.classificacao import regras as rg
    from app.classificacao import servico as cl
    importar("ago.pdf", agosto_pessoal())
    m = por_cp("FORNECEDOR DESCONHECIDO")
    cl.classificar([m["id"]], "Revisar", None, motivo="vou lembrar depois")    # decisão sua
    rg.criar(nome="Teste", campo="contraparte", condicao="contem", texto="FORNECEDOR DESCONHECIDO",
             subcategoria_id=sub("Outras despesas", "Outras despesas"))
    cl.aplicar_padroes(somente_pendentes=False)
    assert por_cp("FORNECEDOR DESCONHECIDO")["classificacao"] == "Revisar"


def test_regra_nova_pega_pendentes_ao_reaplicar():
    from app.classificacao import regras as rg
    from app.classificacao import servico as cl
    importar("ago.pdf", agosto_pessoal())
    rg.criar(nome="Fornecedor X", campo="contraparte", condicao="contem", texto="fornecedor desconhecido",
             subcategoria_id=sub("Compras", "Eletrônicos"))
    r = cl.aplicar_padroes(somente_pendentes=False)
    assert r["aplicadas"] == 1
    assert por_cp("FORNECEDOR DESCONHECIDO")["subcategoria"] == "Eletrônicos"


def test_regra_do_usuario_vence_a_sugestao_inicial():
    """Uber vem como sugestão (prioridade 20); uma regra sua para o mesmo nome passa a valer."""
    from app.classificacao import regras as rg
    from app.classificacao import servico as cl
    importar("ago.pdf", agosto_pessoal())
    assert por_cp("UBER")["classificacao"] == "Revisar"
    rg.criar(nome="Uber é trabalho", campo="contraparte", condicao="contem", texto="uber",
             subcategoria_id=sub("Outras despesas", "Outras despesas"))
    cl.aplicar_padroes(somente_pendentes=False)
    assert por_cp("UBER")["subcategoria"] == "Outras despesas" and por_cp("UBER")["origem_classificacao"] == "regra"


# ---------------------------------------------------------------- prioridade e conflito

def test_prioridade_e_conflito():
    from app.classificacao import regras as rg
    from app.classificacao import servico as cl
    importar("ago.pdf", agosto_pessoal())
    rg.criar(nome="A", campo="contraparte", condicao="contem", texto="FORNECEDOR",
             subcategoria_id=sub("Compras", "Eletrônicos"), prioridade=60)
    rg.criar(nome="B", campo="contraparte", condicao="contem", texto="DESCONHECIDO",
             subcategoria_id=sub("Compras", "Casa e decoração"), prioridade=60)
    cl.aplicar_padroes(somente_pendentes=False)
    m = por_cp("FORNECEDOR DESCONHECIDO")
    assert m["classificacao"] == "Revisar" and "conflito" in m["sugestao_motivo"]
    assert m["sugestao_rotulo"] is None                 # no conflito o programa não escolhe por você

    b = next(r for r in rg.listar() if r.nome == "B")
    rg.alterar(b.id, prioridade=70)                      # B passa a valer mais
    cl.aplicar_padroes(somente_pendentes=False)
    assert por_cp("FORNECEDOR DESCONHECIDO")["subcategoria"] == "Casa e decoração"


def test_desativar_regra():
    from app.classificacao import regras as rg
    celesc = next(r for r in rg.listar() if r.nome == "CELESC")
    rg.alterar(celesc.id, ativa=False)
    importar("ago.pdf", agosto_pessoal())
    assert por_cp("CELESC")["classificacao"] == "Revisar"


def test_validacoes_da_regra():
    from app.classificacao import regras as rg
    um = sub("Outras despesas", "Outras despesas")
    with pytest.raises(rg.ErroRegra):
        rg.criar(nome="x", campo="contraparte", condicao="cnpj", texto="123", subcategoria_id=um)
    with pytest.raises(rg.ErroRegra):
        rg.criar(nome="x", campo="contraparte", condicao="contem", texto="ab", subcategoria_id=um)
    with pytest.raises(rg.ErroRegra):                    # toda regra precisa dizer a categoria
        rg.criar(nome="x", campo="contraparte", condicao="contem", texto="abc", subcategoria_id=None)
    with pytest.raises(rg.ErroRegra):
        rg.criar(nome=" ", campo="contraparte", condicao="contem", texto="abc", subcategoria_id=um)


def test_testar_regra_nao_altera_nada():
    from app.classificacao import regras as rg
    importar("ago.pdf", agosto_pessoal())
    antes = [m["classificacao"] for m in movs()]
    celesc = next(r for r in rg.listar() if r.nome == "CELESC")
    pegas = rg.testar(celesc)
    assert len(pegas) == 1 and pegas[0]["categoria_rotulo"] == "Moradia › Energia"
    uber = next(r for r in rg.listar() if r.nome == "Uber")
    assert [m["categoria_rotulo"] for m in rg.testar(uber)] == [None]      # ainda em Revisar
    assert [m["classificacao"] for m in movs()] == antes


def CENARIO():
    from tests.gerador_nubank import cenario_agosto
    return cenario_agosto()


def test_desfazer_classificacao_volta_para_revisao_e_exclui_a_regra():
    """Classifiquei errado e criei regra: desfazer devolve tudo para a Revisão e apaga só essa regra."""
    from app.banco.conexao import conectar
    from app.classificacao import regras as rg, servico as cl
    from app.importacao import consultas

    def um(sql, *p):
        conn = conectar()
        try:
            return conn.execute(sql, p).fetchone()[0]
        finally:
            conn.close()

    importar("ago.pdf", CENARIO())
    todas = consultas.movimentacoes()
    diaristas = [m for m in todas if "JOAO DIARISTA" in (m["contraparte"] or "")]
    limpeza = next(m for m in todas if "MARIA LIMPEZA" in (m["contraparte"] or ""))
    assert len(diaristas) == 2 and all(m["classificacao"] == "Revisar" for m in diaristas + [limpeza])
    regras_antes = um("SELECT COUNT(*) FROM regras")
    por_regra_antes = um("SELECT COUNT(*) FROM movimentacoes WHERE regra_id IS NOT NULL")
    errada = sub("Lazer", "Bares e festas")

    # erro 1: classifica o 1º diarista na categoria errada e cria regra -> o 2º vai junto pela regra
    primeiro = diaristas[0]
    cl.classificar([primeiro["id"]], "Classificada", errada)
    prop = rg.proposta_a_partir_de(primeiro)
    rid = rg.criar(nome=prop["nome"], campo=prop["campo"], condicao=prop["condicao"], texto=prop["texto"],
                   subcategoria_id=errada, tipo_mov="Saída", origem="correcao")
    cl.aplicar_padroes(somente_pendentes=False)
    # erro 2: classifica a limpeza na categoria errada, sem criar regra
    cl.classificar([limpeza["id"]], "Classificada", errada)
    assert um("SELECT COUNT(*) FROM movimentacoes WHERE subcategoria_id = ?", errada) == 3

    previa = cl.previa_desfazer([primeiro["id"], limpeza["id"]])
    assert [r.id for r in previa["regras"]] == [rid]
    assert [x["id"] for x in previa["arrastadas"]] == [diaristas[1]["id"]]

    r = cl.desfazer_classificacao([primeiro["id"], limpeza["id"]])
    assert r["voltaram"] == 2 and r["arrastadas"] == 1 and len(r["regras"]) == 1
    assert um("SELECT COUNT(*) FROM movimentacoes WHERE subcategoria_id = ?", errada) == 0
    assert um("SELECT COUNT(*) FROM regras") == regras_antes                       # só a regra errada saiu
    assert um("SELECT COUNT(*) FROM movimentacoes WHERE regra_id IS NOT NULL") == por_regra_antes
    for mid in (primeiro["id"], diaristas[1]["id"], limpeza["id"]):
        assert um("SELECT classificacao FROM movimentacoes WHERE id = ?", mid) == "Revisar"
        assert um("SELECT origem_classificacao FROM movimentacoes WHERE id = ?", mid) is None
    assert not consultas.movimentacoes(origem="manual")
    assert any("desfeita por você" in (h["motivo"] or "") for h in cl.historico(primeiro["id"]))
    # as regras iniciais continuam valendo e não foram tocadas (ex.: CELESC continua classificada)
    assert um("SELECT COUNT(*) FROM movimentacoes m JOIN subcategorias s ON s.id = m.subcategoria_id"
              " WHERE s.nome = 'Energia'") == 1
    # depois dá para classificar de novo, agora certo
    assert cl.classificar([primeiro["id"]], "Classificada", sub("Moradia", "Manutenção da casa")) == 1


def test_desfazer_nao_exclui_regra_inicial_e_respeita_mes_fechado():
    from app.banco.conexao import conectar
    from app.classificacao import servico as cl
    from app.fechamento import servico as fc
    from app.importacao import consultas
    importar("ago.pdf", CENARIO())
    todas = consultas.movimentacoes()
    celesc = next(m for m in todas if "CELESC" in (m["contraparte"] or ""))
    assert celesc["origem_classificacao"] == "regra"
    previa = cl.previa_desfazer([celesc["id"]])
    assert previa["regras"] == [] and previa["arrastadas"] == []
    r = cl.desfazer_classificacao([celesc["id"]])
    assert r == {"voltaram": 1, "regras": [], "arrastadas": 0}
    cl.aplicar_padroes()        # a regra inicial não reaplica sozinha: você mandou para a Revisão
    conn = conectar()
    try:
        assert conn.execute("SELECT classificacao FROM movimentacoes WHERE id = ?", (celesc["id"],)).fetchone()[0] == "Revisar"
    finally:
        conn.close()
    # mês fechado: bloqueia
    pend = consultas.movimentacoes(classificacoes=["Revisar"])
    cl.classificar([m["id"] for m in pend], "Classificada", sub("Outras despesas", "Outras despesas"))
    fc.fechar("2026-08")
    with pytest.raises(cl.ErroClassificacao):
        cl.desfazer_classificacao([pend[0]["id"]])
