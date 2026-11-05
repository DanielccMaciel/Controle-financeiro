"""Testes da classificação: categorias, padrões, auditoria. Tudo é pessoal: classificar = dar a categoria."""

import copy
from datetime import date

import pytest

from app import config
from tests.gerador_nubank import Dia, Mov, cenario_agosto, gerar

INICIO, FIM = date(2026, 8, 1), date(2026, 8, 31)


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    return tmp_path


def conta(nome="Daniel"):
    from app.contas import repositorio as repo
    return next(c for c in repo.listar() if c.nome == nome)


def importar(nome, dias, fim=FIM):
    from app.contas import repositorio as repo
    from app.importacao import servico
    repo.garantir_pastas()
    pdf = config.pasta_extratos() / "Daniel-Nubank" / nome
    gerar(pdf, dias, inicio=INICIO, fim=fim, saldo_inicial=100000, itens_por_pagina=9)
    a = servico.analisar(conta(), pdf)
    assert a.pode_importar, [p.mensagem for p in a.problemas]
    return servico.importar(a)


def movs(**kw):
    from app.importacao import consultas
    return consultas.movimentacoes(**kw)


def sub(cat, nome):
    from app.classificacao.servico import subcategoria_por_nome
    return subcategoria_por_nome(cat, nome)


# ---------------------------------------------------------------- categorias

def test_categorias_iniciais_com_natureza():
    from app.classificacao import servico as cl
    cats = {c["nome"]: c["natureza"] for c in cl.listar_categorias()}
    assert cats["Renda"] == "receita"
    assert cats["Moradia"] == cats["Alimentação"] == cats["Lazer"] == "despesa"
    assert cats["Investimentos"] == "investimento"
    assert cats["Movimentação interna"] == cats["Dinheiro de terceiros"] == "neutro"
    assert set(cats.values()) == set(cl.NATUREZAS) == {"receita", "despesa", "investimento", "neutro"}
    assert len(cats) == 18 and len(cl.listar_subcategorias()) == 64
    # a lista é de pessoa, não de empresa
    nomes = " ".join(list(cats) + [s.nome for s in cl.listar_subcategorias()]).lower()
    assert not any(p in nomes for p in ("hospedagem", "sócio", "socio", "fornecedor", "funcionário", "simples nacional"))


def test_criar_renomear_desativar_categoria():
    from app.classificacao import servico as cl
    cid = cl.criar_categoria("Pets", "despesa")
    sid = cl.criar_subcategoria(cid, "Ração")
    with pytest.raises(cl.ErroClassificacao):
        cl.criar_categoria("pets", "despesa")
    with pytest.raises(cl.ErroClassificacao):
        cl.criar_subcategoria(cid, "ração")
    with pytest.raises(cl.ErroClassificacao):
        cl.criar_categoria("Outra", "retirada")           # natureza que não existe
    cl.renomear("subcategorias", sid, "Ração e petiscos")
    assert any(s.nome == "Ração e petiscos" for s in cl.listar_subcategorias(cid))
    cl.definir_ativa("categorias", cid, False)
    assert "Pets" not in {c["nome"] for c in cl.listar_categorias()}
    assert "Pets" in {c["nome"] for c in cl.listar_categorias(incluir_inativas=True)}


# ---------------------------------------------------------------- padrões

def test_resgate_rdb_vira_neutro_e_fatura_vira_sugestao():
    importar("a.pdf", cenario_agosto())
    rdb = [m for m in movs() if m["operacao"] == "Resgate RDB"]
    assert len(rdb) == 2
    assert all(m["classificacao"] == "Classificada" and m["natureza"] == "neutro"
               and m["origem_classificacao"] == "regra" for m in rdb)

    fatura = next(m for m in movs() if m["operacao"] == "Pagamento de fatura")
    assert fatura["classificacao"] == "Revisar"                     # só sugestão
    assert fatura["sugestao_rotulo"] == "Cartão de crédito › Fatura do cartão"


def test_pix_entre_as_proprias_contas_sugere_transferencia_interna():
    """A outra ponta tem o nome do titular das contas → sugestão de 'entre minhas contas' (neutro).
    É só sugestão (fica em Revisar), vale para entrada e saída, e xará parcial não conta."""
    pix_env, pix_rec = "Transferência enviada pelo Pix", "Transferência recebida pelo Pix"
    importar("a.pdf", [Dia(date(2026, 8, 5), [
        Mov("Entrada", "Resgate RDB", [], 500000),
        Mov("Entrada", pix_rec, ["DANIEL TESTE DA SILVA - ***.123.456-** - BCO", "INTER S.A. (0077) Agência: 1 Conta: 5-5"], 30000),
        Mov("Saída", pix_env, ["DANIEL TESTE DA SILVA - ***.123.456-** - NU", "PAGAMENTOS - IP (0260) Agência: 1 Conta: 1-1"], 200000),
        Mov("Saída", pix_env, ["DANIELA SOUZA - ***.333.444-** - NU", "PAGAMENTOS - IP (0260) Agência: 1 Conta: 2-2"], 100000),
        Mov("Saída", pix_env, ["JOAO DIARISTA - ***.999.888-** - CAIXA"], 15000),
        Mov("Saída", "Pagamento de boleto efetuado", ["DANIEL TESTE DA SILVA"], 7000),
    ])])
    interna = "Movimentação interna › Transferência entre minhas contas"
    proprias = [m for m in movs() if (m["contraparte"] or "").startswith("DANIEL TESTE") and "Pix" in m["operacao"]]
    assert len(proprias) == 2 and {m["tipo"] for m in proprias} == {"Entrada", "Saída"}
    assert all(m["sugestao_rotulo"] == interna and m["classificacao"] == "Revisar" for m in proprias)
    assert all("titular das contas" in m["sugestao_motivo"] for m in proprias)
    por_nome = {m["contraparte"].split(" - ")[0]: m for m in movs(tipo="Saída") if "Pix" in m["operacao"]}
    assert por_nome["DANIELA SOUZA"]["sugestao_rotulo"] is None        # Daniela não é Daniel
    assert por_nome["JOAO DIARISTA"]["sugestao_rotulo"] is None
    boleto = next(m for m in movs() if m["operacao"].startswith("Pagamento de boleto"))
    assert boleto["sugestao_rotulo"] is None                            # só Pix/transferência


def test_titular_com_nome_completo_evita_sugerir_para_xara():
    from app.classificacao import servico as cl
    from app.contas import repositorio as repo
    for c in repo.listar():
        c.titular = "Daniel Teste da Silva"
        repo.atualizar(c)
    pix = "Transferência enviada pelo Pix"
    importar("a.pdf", [Dia(date(2026, 8, 5), [
        Mov("Entrada", "Resgate RDB", [], 500000),
        Mov("Saída", pix, ["DANIEL TESTE DA SILVA - ***.123.456-** - NU"], 200000),
        Mov("Saída", pix, ["DANIEL OUTRO PEREIRA - ***.777.888-** - NU"], 100000),
    ])])
    por_nome = {m["contraparte"].split(" - ")[0]: m for m in movs(tipo="Saída")}
    assert por_nome["DANIEL TESTE DA SILVA"]["sugestao_rotulo"].endswith("Transferência entre minhas contas")
    assert por_nome["DANIEL OUTRO PEREIRA"]["sugestao_rotulo"] is None
    assert cl.aceitar_sugestao([por_nome["DANIEL TESTE DA SILVA"]["id"]]) == 1
    aceita = next(m for m in movs() if m["id"] == por_nome["DANIEL TESTE DA SILVA"]["id"])
    assert aceita["natureza"] == "neutro"


def test_aceitar_sugestao():
    from app.classificacao import servico as cl
    importar("a.pdf", cenario_agosto())
    fatura = next(m for m in movs() if m["operacao"] == "Pagamento de fatura")
    assert cl.aceitar_sugestao([fatura["id"]]) == 1
    f2 = next(m for m in movs() if m["id"] == fatura["id"])
    assert f2["classificacao"] == "Classificada" and f2["subcategoria"] == "Fatura do cartão"
    assert f2["sugestao_rotulo"] is None
    assert any("sugestão aceita" in (h["motivo"] or "") for h in cl.historico(fatura["id"]))


# ---------------------------------------------------------------- classificar

def test_classificar_manual_com_auditoria():
    from app.classificacao import servico as cl
    importar("a.pdf", cenario_agosto())
    celesc = next(m for m in movs() if "CELESC" in (m["contraparte"] or ""))
    cl.classificar([celesc["id"]], "Classificada", sub("Moradia", "Energia"),
                   descricao_identificada="Conta de luz agosto")
    m = next(x for x in movs() if x["id"] == celesc["id"])
    assert (m["classificacao"], m["categoria"], m["subcategoria"]) == ("Classificada", "Moradia", "Energia")
    assert m["descricao_identificada"] == "Conta de luz agosto"
    assert m["descricao_original"].startswith("Transferência enviada pelo Pix CELESC")   # nunca muda
    campos = [h["campo"] for h in cl.historico(celesc["id"])]
    assert campos == ["classificacao", "categoria", "descricao_identificada"]

    # trocar de categoria registra só a categoria
    cl.classificar([celesc["id"]], "Classificada", sub("Moradia", "Condomínio"), motivo="era o condomínio")
    m = next(x for x in movs() if x["id"] == celesc["id"])
    assert m["subcategoria"] == "Condomínio" and m["origem_classificacao"] == "manual"
    assert [h["campo"] for h in cl.historico(celesc["id"])][3:] == ["categoria"]

    # voltar para Revisar apaga a categoria e registra
    cl.classificar([celesc["id"]], "Revisar", sub("Moradia", "Energia"))
    m = next(x for x in movs() if x["id"] == celesc["id"])
    assert m["classificacao"] == "Revisar" and m["subcategoria_id"] is None
    assert len(cl.historico(celesc["id"])) == 6


def test_classificar_exige_categoria_e_so_ha_dois_estados():
    from app.classificacao import servico as cl
    importar("a.pdf", cenario_agosto())
    assert cl.CLASSIFICACOES == ("Classificada", "Revisar")
    with pytest.raises(cl.ErroClassificacao):
        cl.classificar([movs()[0]["id"]], "Classificada", None)
    for invalida in ("Pessoal", "Particular", "Talvez"):
        with pytest.raises(cl.ErroClassificacao):
            cl.classificar([movs()[0]["id"]], invalida, sub("Moradia", "Energia"))


def test_classificacao_em_massa():
    from app.classificacao import servico as cl
    importar("a.pdf", cenario_agosto())
    diaristas = [m["id"] for m in movs(busca="DIARISTA")]
    assert len(diaristas) == 2
    assert cl.classificar(diaristas, "Classificada", sub("Moradia", "Manutenção da casa")) == 2
    assert all(m["subcategoria"] == "Manutenção da casa" for m in movs(busca="DIARISTA"))
    # reclassificar igual não conta como mudança
    assert cl.classificar(diaristas, "Classificada", sub("Moradia", "Manutenção da casa")) == 0


def test_pdf_atualizado_preserva_classificacao():
    """Requisito da especificação: um PDF novo (01–31) não pode desfazer a classificação feita no parcial."""
    from app.classificacao import servico as cl
    mes = cenario_agosto()
    importar("p.pdf", [d for d in mes if d.data.day <= 8], fim=date(2026, 8, 10))
    celesc = next(m for m in movs() if "CELESC" in (m["contraparte"] or ""))
    cl.classificar([celesc["id"]], "Classificada", sub("Moradia", "Condomínio"))

    importar("c.pdf", mes)
    m = next(x for x in movs() if x["id"] == celesc["id"])
    assert m["subcategoria"] == "Condomínio" and m["origem_classificacao"] == "manual"
    assert len(movs()) == 12


def test_contagem_por_classificacao():
    from app.classificacao import servico as cl
    importar("a.pdf", cenario_agosto())
    c = cl.contar_por_classificacao()
    # 2 RDB + CELESC (por CNPJ) aplicadas; o resto fica para revisar (a fatura, com sugestão)
    assert c == {"Classificada": 3, "Revisar": 9}


def test_padroes_nao_reavaliam_o_que_voce_decidiu():
    from app.classificacao import servico as cl
    importar("a.pdf", cenario_agosto())
    rdb = next(m for m in movs() if m["operacao"] == "Resgate RDB")
    cl.classificar([rdb["id"]], "Revisar", None, motivo="quero olhar de novo")
    cl.aplicar_padroes()                                   # já avaliada → não mexe
    assert next(m for m in movs() if m["id"] == rdb["id"])["classificacao"] == "Revisar"


def test_filtro_quem_classificou():
    """Movimentações > 'Quem classificou': acha só as decididas à mão."""
    from app.classificacao import servico as cl
    from app.importacao import consultas
    importar("ago.pdf", cenario_agosto())
    todas = consultas.movimentacoes()
    assert todas
    alvo = [m["id"] for m in todas if m["classificacao"] == "Revisar"][:2]
    assert len(alvo) == 2
    cl.classificar(alvo, "Classificada", sub("Outras despesas", "Outras despesas"))
    manuais = consultas.movimentacoes(origem="manual")
    assert sorted(m["id"] for m in manuais) == sorted(alvo)
    assert all(m["origem_classificacao"] == "regra" for m in consultas.movimentacoes(origem="regra"))
    assert len(consultas.movimentacoes(origem="manual", classificacoes=["Classificada"])) == 2
    assert len(consultas.movimentacoes(origem="manual", classificacoes=["Revisar"])) == 0
