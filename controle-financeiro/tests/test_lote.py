"""Importação de vários PDFs: o programa descobre a conta de cada um (PDFs FALSOS).

Todas as contas são da mesma pessoa. O que separa uma da outra é o banco, o número da
conta (aprendido na primeira importação) e, para os PDFs de caixinhas, as caixinhas que
cada conta já tem.
"""

from datetime import date

import pytest

from app import config
from tests import gerador_caixinhas as gc
from tests import gerador_nubank as gn
from tests import gerador_sicoob as gs
from tests.ajudas import conta, segunda_conta_no_nubank

AGO = dict(inicio=date(2026, 8, 1), fim=date(2026, 8, 31))
SET = dict(inicio=date(2026, 9, 1), fim=date(2026, 9, 30))
CONTA_1, CONTA_2 = "12345678-9", "22222222-2"


@pytest.fixture(autouse=True)
def raiz_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    from app.contas import repositorio as repo
    repo.garantir_pastas()
    return tmp_path


def entrada(nome):
    from app.importacao import lote
    return lote.pasta_entrada() / nome


def um_pix(dia=date(2026, 8, 10), valor=10_000):
    return [gn.Dia(dia, [gn.Mov("Entrada", "Transferência recebida pelo Pix", ["FULANO"], valor)])]


def por_conta():
    from app.banco.conexao import conectar
    conn = conectar()
    try:
        return dict(conn.execute(
            "SELECT c.nome, COUNT(*) FROM movimentacoes m JOIN contas c ON c.id = m.conta_id GROUP BY c.nome"))
    finally:
        conn.close()


def test_primeiro_uso_identifica_e_importa_tudo_de_uma_vez():
    """Como o programa chega: Daniel (Nubank) e Dani 2 (Sicoob). Nada é perguntado."""
    from app.importacao import lote
    from app.rendimentos import servico as rd
    gn.gerar(entrada("a.pdf"), gn.cenario_agosto(), saldo_inicial=123456, itens_por_pagina=9, **AGO)
    gs.gerar(entrada("b.pdf"), gs.cenario_setembro(), saldo_anterior=50_000, **SET)
    gc.gerar(entrada("f.pdf"), gc.cenario_setembro(), **SET)
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(entrada("boleto.pdf")))
    c.drawString(100, 700, "Boleto de cobranca - nao e extrato")
    c.save()

    itens = {i.nome: i for i in lote.analisar_entrada()}
    assert len(itens) == 4
    for nome, dona in {"a.pdf": "Daniel", "b.pdf": "Dani 2", "f.pdf": "Daniel"}.items():
        assert itens[nome].conta and itens[nome].conta.nome == dona, (nome, itens[nome].mensagem)
        assert itens[nome].situacao == "pronto", (nome, itens[nome].mensagem)
        assert itens[nome].como == "única conta desse banco"
    assert itens["a.pdf"].tipo == lote.TIPO_CONTA and itens["f.pdf"].tipo == lote.TIPO_RENDIMENTOS
    assert itens["b.pdf"].banco == "Sicoob"
    assert itens["boleto.pdf"].situacao == "erro" and "Não reconheci" in itens["boleto.pdf"].mensagem

    feitos, falhas = lote.importar_prontos(list(itens.values()))
    assert len(feitos) == 3 and not falhas
    assert [p.name for p in lote.pdfs_na_entrada()] == ["boleto.pdf"]       # o resto foi guardado nas contas
    assert (config.pasta_extratos() / "Daniel-Nubank" / "2026-08" / "a.pdf").exists()
    assert (config.pasta_extratos() / "Dani-2-Sicoob" / "2026-09" / "b.pdf").exists()
    assert (config.pasta_extratos() / "Daniel-Nubank" / "caixinhas" / "2026-09" / "f.pdf").exists()
    assert por_conta() == {"Daniel": 12, "Dani 2": 9}
    assert [(a["conta_nome"], a["nome"]) for a in rd.aplicacoes()] == [("Daniel", "Reservadeemergencia")]
    # o número da conta foi aprendido na primeira importação
    assert conta().numero_conta == CONTA_1 and conta("Dani 2").numero_conta == "12.345-6"


def test_duas_contas_do_mesmo_banco_pergunta_na_primeira_vez_e_depois_vai_sozinho():
    """Duas contas do Nubank, do mesmo titular, ainda sem número: o programa não chuta.
    Depois que a pessoa escolhe uma vez, o número guardado resolve os meses seguintes."""
    from app.importacao import lote
    dani2 = segunda_conta_no_nubank()
    gn.gerar(entrada("um.pdf"), um_pix(), saldo_inicial=5_000, conta=CONTA_1, **AGO)
    item = lote.analisar_entrada()[0]
    assert item.situacao == "sem_conta" and item.conta is None
    assert [c.nome for c in item.candidatas] == ["Daniel", "Dani 2"]
    assert "Escolha abaixo" in item.mensagem and item.periodo == (AGO["inicio"], AGO["fim"])
    assert lote.importar_prontos([item]) == ([], [])

    escolhido = lote.analisar_arquivo(item.caminho, conta())
    assert escolhido.situacao == "pronto" and escolhido.como == "escolhida por você"
    feitos, falhas = lote.importar_prontos([escolhido])
    assert len(feitos) == 1 and not falhas and not lote.pdfs_na_entrada()
    assert conta().numero_conta == CONTA_1

    # mês seguinte: o da conta 1 entra pelo número; o da outra conta só pode ser da Dani 2
    gn.gerar(entrada("set-1.pdf"), um_pix(date(2026, 9, 10), 7_000), saldo_inicial=15_000, conta=CONTA_1, **SET)
    gn.gerar(entrada("set-2.pdf"), um_pix(date(2026, 9, 11), 3_000), saldo_inicial=1_000, conta=CONTA_2, **SET)
    itens = {i.nome: i for i in lote.analisar_entrada()}
    assert (itens["set-1.pdf"].conta.nome, itens["set-1.pdf"].como) == ("Daniel", "pelo número da conta")
    assert (itens["set-2.pdf"].conta.nome, itens["set-2.pdf"].como) == \
        ("Dani 2", "única conta desse banco ainda sem número cadastrado")
    feitos, falhas = lote.importar_prontos(list(itens.values()))
    assert len(feitos) == 2 and not falhas
    assert por_conta() == {"Daniel": 2, "Dani 2": 1}
    assert conta("Dani 2").numero_conta == CONTA_2 and conta("Dani 2").id == dani2.id


def test_reconhece_pelo_numero_mesmo_com_nome_diferente_no_cabecalho():
    from app.importacao import lote
    segunda_conta_no_nubank()
    gn.gerar(entrada("ago.pdf"), um_pix(), saldo_inicial=5_000, conta=CONTA_2, **AGO)
    primeiro = lote.analisar_arquivo(entrada("ago.pdf"), conta("Dani 2"))
    lote.importar_prontos([primeiro])
    gn.gerar(entrada("set.pdf"), um_pix(date(2026, 9, 10), 7_000), saldo_inicial=15_000,
             titular="D. T. S. (nome abreviado)", conta=CONTA_2, **SET)
    item = lote.analisar_entrada()[0]
    assert item.conta.nome == "Dani 2" and item.como == "pelo número da conta" and item.situacao == "pronto"


def test_pdf_de_conta_que_nao_esta_cadastrada_nao_entra_em_nenhuma():
    from app.importacao import lote
    segunda_conta_no_nubank()
    for arq, numero, dona in (("um.pdf", CONTA_1, "Daniel"), ("dois.pdf", CONTA_2, "Dani 2")):
        gn.gerar(entrada(arq), um_pix(), saldo_inicial=5_000, conta=numero, **AGO)
        lote.importar_prontos([lote.analisar_arquivo(entrada(arq), conta(dona))])
    gn.gerar(entrada("quem.pdf"), um_pix(), saldo_inicial=5_000, conta="99999999-9", **AGO)
    item = lote.analisar_entrada()[0]
    assert item.situacao == "sem_conta" and "não é de nenhuma conta cadastrada" in item.mensagem
    assert por_conta() == {"Daniel": 1, "Dani 2": 1}


def test_caixinhas_de_duas_contas_do_mesmo_banco():
    """PDF de caixinhas não traz número de conta. Na 1ª vez o programa pergunta; depois reconhece
    cada conta pelas caixinhas que ela já tem."""
    from app.importacao import lote
    from app.rendimentos import servico as rd
    dani2 = segunda_conta_no_nubank()
    gc.gerar(entrada("cx1.pdf"), [gc.Caixinha("Reserva", 500_000, [], 4_000)], **SET)
    gc.gerar(entrada("cx2.pdf"), [gc.Caixinha("Viagem", 300_000, [], 2_500), gc.Caixinha("Carro", 100_000, [], 700)], **SET)
    itens = {i.nome: i for i in lote.analisar_entrada()}
    assert all(i.situacao == "sem_conta" and len(i.candidatas) == 2 for i in itens.values())
    lote.importar_prontos([lote.analisar_arquivo(entrada("cx1.pdf"), conta()),
                           lote.analisar_arquivo(entrada("cx2.pdf"), dani2)])
    assert not lote.pdfs_na_entrada()

    OUT = dict(inicio=date(2026, 10, 1), fim=date(2026, 10, 31))
    gc.gerar(entrada("out1.pdf"), [gc.Caixinha("Reserva", 510_000, [], 4_100)], **OUT)
    gc.gerar(entrada("out2.pdf"), [gc.Caixinha("Viagem", 310_000, [], 2_600), gc.Caixinha("Carro", 101_000, [], 710)], **OUT)
    gc.gerar(entrada("nova.pdf"), [gc.Caixinha("Casamento", 50_000, [], 300)], **OUT)   # caixinha que ninguém tem
    itens = {i.nome: i for i in lote.analisar_entrada()}
    assert (itens["out1.pdf"].conta.nome, itens["out2.pdf"].conta.nome) == ("Daniel", "Dani 2")
    assert itens["out1.pdf"].como == itens["out2.pdf"].como == "pelas caixinhas que essa conta já tem"
    assert itens["nova.pdf"].situacao == "sem_conta"                         # sem pista: não chuta
    feitos, falhas = lote.importar_prontos(list(itens.values()))
    assert len(feitos) == 2 and not falhas
    assert rd.rendimento_por_mes() == {"2026-09": 7_200, "2026-10": 7_410}
    assert rd.rendimento_por_mes(rd.filtrar(None, [dani2.id])) == {"2026-09": 3_200, "2026-10": 3_310}


def test_repetido_erro_de_conferencia_e_envio_pela_tela():
    from app.importacao import lote
    from app.ocorrencias import registro
    gn.gerar(entrada("a.pdf"), gn.cenario_agosto(), saldo_inicial=123456, itens_por_pagina=9, **AGO)
    lote.importar_prontos(lote.analisar_entrada())
    # o mesmo PDF de novo, com outro nome, enviado pela tela
    guardado = config.pasta_extratos() / "Daniel-Nubank" / "2026-08" / "a.pdf"
    lote.guardar_na_entrada("de novo.pdf", guardado.read_bytes())
    gs.gerar(entrada("ruim.pdf"), gs.cenario_setembro(), saldo_anterior=1,
             ajustes=gs.AjustesS(saldo_dia_delta={date(2026, 9, 10): 100}), **SET)
    itens = {i.nome: i for i in lote.analisar_entrada()}
    assert itens["de novo.pdf"].situacao == "ja_importado" and itens["de novo.pdf"].conta.nome == "Daniel"
    assert itens["ruim.pdf"].situacao == "conferencia" and itens["ruim.pdf"].conta.nome == "Dani 2"
    assert lote.importar_prontos(list(itens.values())) == ([], [])
    assert lote.limpar_ja_importados(list(itens.values())) == 1
    assert [p.name for p in lote.pdfs_na_entrada()] == ["ruim.pdf"]
    assert registro.contar_abertas().get("CONFERIR") == 1


def test_conta_desativada_nao_recebe_pdf():
    """Quem desativa a conta de exemplo não a vê mais como destino."""
    from app.contas import repositorio as repo
    from app.importacao import lote
    dani2 = conta("Dani 2")
    dani2.ativa = False
    repo.atualizar(dani2)
    gs.gerar(entrada("b.pdf"), gs.cenario_setembro(), saldo_anterior=50_000, **SET)
    item = lote.analisar_entrada()[0]
    assert item.situacao == "sem_conta" and "nenhuma conta ativa desse banco" in item.mensagem
    assert [c.nome for c in item.candidatas] == ["Daniel"]            # só sobra a ativa, para escolha manual


def test_escolher_conta_regras():
    from app.contas.repositorio import Conta
    from app.importacao.lote import escolher_conta
    cs = [Conta("Daniel", "Daniel Teste", "Nubank", "a", id=1, numero_conta="111-1"),
          Conta("Conjunta", "Daniel Teste e Ana Souza", "Nubank", "b", id=2),
          Conta("Da Ana", "Ana", "Nubank", "c", id=3),
          Conta("Cooperativa", "Daniel Teste", "Sicoob", "d", id=4)]
    assert escolher_conta("Sicoob", "99.999-9", "", cs)[0].id == 4                 # única desse banco
    assert escolher_conta("Nubank", "111-1", "NOME QUE NAO BATE", cs)[0].id == 1   # pelo número
    assert escolher_conta("Nubank", "222-2", "ANA LIMA", cs)[0].id == 3            # pelo nome do titular
    assert escolher_conta("Nubank", None, "MARIANA LIMA", cs)[0] is None           # "Ana" não é "Mariana"
    assert escolher_conta("Nubank", "222-2", "DANIEL TESTE E ANA SOUZA", cs)[0] is None   # duas combinam
    assert escolher_conta("Nubank", "333-3", "ANALIMA", cs)[0] is None             # colado e curto demais: não arrisca
    assert escolher_conta("Nubank", None, "DANIELTESTE", cs)[0].id == 1            # PDF sem espaços
    assert escolher_conta("Inter", None, "", cs)[0] is None
    # PDF com número que não é o da conta 1: ela sai das candidatas
    conta_, cand, como = escolher_conta("Nubank", "222-2", "DANIEL TESTE", cs)
    assert conta_ is None and {c.id for c in cand} <= {2, 3}
