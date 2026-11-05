"""Testes dos relatórios (PDF, Excel, CSV)."""

import csv
import io
from datetime import date

import pytest
from openpyxl import load_workbook

from app import config
from tests.gerador_nubank import Dia, Mov, gerar

PIX_ENV, PIX_REC = "Transferência enviada pelo Pix", "Transferência recebida pelo Pix"


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALISADOR_RAIZ", str(tmp_path))
    from app.contas import repositorio as repo
    from app.importacao import servico
    repo.garantir_pastas()
    conta = next(c for c in repo.listar() if c.nome == "Daniel")
    for nome, mes, dias in (
        ("jul.pdf", 7, [Dia(date(2026, 7, 5), [Mov("Entrada", PIX_REC, ["EMPRESA EXEMPLO LTDA -", "19.468.242/0001-32"], 500000),
                                               Mov("Saída", PIX_ENV, ["CELESC DISTRIBUICAO S.A -", "08.336.783/0001-90"], 60000)])]),
        ("ago.pdf", 8, [Dia(date(2026, 8, 5), [Mov("Entrada", PIX_REC, ["EMPRESA EXEMPLO LTDA -", "19.468.242/0001-32"], 200000),
                                               Mov("Saída", PIX_ENV, ["CELESC DISTRIBUICAO S.A -", "08.336.783/0001-90"], 90000),
                                               Mov("Saída", PIX_ENV, ["CORRETORA EXEMPLO S.A. -", "33.444.555/0001-06"], 30000),
                                               Mov("Saída", PIX_ENV, ["DESCONHECIDO LTDA -", "11.222.333/0001-81"], 1234)])]),
    ):
        pdf = config.pasta_extratos() / "Daniel-Nubank" / nome
        gerar(pdf, dias, inicio=date(2026, mes, 1), fim=date(2026, mes, 31 if mes in (7, 8) else 30),
              saldo_inicial=100000)
        servico.importar(servico.analisar(conta, pdf))
    # a luz entra sozinha pela regra da CELESC; salário e corretora a pessoa classifica; 1 fica pendente
    from app.classificacao import servico as cl
    from app.importacao import consultas
    cl.classificar([m["id"] for m in consultas.movimentacoes(busca="EMPRESA EXEMPLO")], "Classificada",
                   cl.subcategoria_por_nome("Renda", "Salário"))
    cl.classificar([m["id"] for m in consultas.movimentacoes(busca="CORRETORA")], "Classificada",
                   cl.subcategoria_por_nome("Investimentos", "Corretora / ações e fundos"))


def test_dados_mensal():
    from app.relatorios import dados
    r = dados.mensal("2026-08")
    assert not r.oficial and r.anterior.mes == "2026-07"
    assert r.resumo.receita == 200000 and r.resumo.despesas == 90000
    assert r.resumo.investimentos == 30000 and r.resumo.resultado == 110000       # investir não é gastar
    assert [(x["categoria"], x["valor"]) for x in r.investimentos] == [("Investimentos", 30000)]
    assert len(r.pendentes) == 1 and len(r.documentos) == 1 and len(r.movimentacoes) == 4
    assert r.variacao[0].categoria == "Moradia" and r.variacao[0].anterior == 60000


def test_dados_anual():
    from app.relatorios import dados
    r = dados.anual("2026")
    assert len(r.meses) == 12 and r.com_dados == {"2026-07", "2026-08"}
    assert r.totais.receita == 700000 and r.totais.despesas == 150000 and r.totais.investimentos == 30000
    assert r.acumulado[6] == 440000 and r.acumulado[7] == 440000 + 110000 and r.acumulado[11] == 550000


def test_excel_mensal_tem_formulas_e_valores():
    from app.relatorios import dados, excel
    wb = load_workbook(io.BytesIO(excel.mensal(dados.mensal("2026-08"))))
    assert wb.sheetnames[:4] == ["Resumo", "Despesas por categoria", "Receitas por categoria", "Investimentos"]
    r = wb["Resumo"]
    assert r["B5"].value == 2000 and r["B6"].value == 900
    assert r["B7"].value == "=B5-B6" and r["B8"].value.startswith("=IF(B5>0")
    assert r["A7"].value.startswith("Resultado") and r["A7"].font.bold
    assert r["A8"].value.startswith("Margem") and "%" in r["B8"].number_format
    assert r["A9"].value.startswith("Investido") and r["B9"].value == 300 and r["C9"].value == 0
    assert config.NOME_PROGRAMA in r["A3"].value
    assert wb["Investimentos"]["A2"].value == "Investimentos" and wb["Investimentos"]["C2"].value == 300
    textos = " ".join(str(c.value) for ws in wb for linha in ws.iter_rows() for c in linha if c.value)
    assert not any(p in textos for p in ("Particular", "sócios", "Retirada", "operacional"))
    assert "PRELIMINAR" in r["A2"].value
    assert r["A1"].font.name == "Arial"
    assert "Movimentações" in wb.sheetnames and "Pendentes" in wb.sheetnames


def test_excel_anual_acumulado_por_formula():
    from app.relatorios import dados, excel
    wb = load_workbook(io.BytesIO(excel.anual(dados.anual("2026"))))
    ws = wb["Resumo anual"]
    assert ws["G5"].value == "=E5" and ws["G6"].value == "=G5+E6"
    assert ws["C17"].value == "=SUM(C5:C16)"
    assert ws["H4"].value == "Investido (R$)" and ws["H12"].value == 300        # agosto
    assert "Investimentos" in ws["A19"].value


def test_pdf_gerado():
    from app.relatorios import dados, pdf
    import pdfplumber
    for b in (pdf.mensal(dados.mensal("2026-08")), pdf.anual(dados.anual("2026"))):
        assert b[:4] == b"%PDF" and len(b) > 2000
        with pdfplumber.open(io.BytesIO(b)) as doc:
            texto = " ".join(pg.extract_text() or "" for pg in doc.pages)
        assert config.NOME_PROGRAMA in texto and "Invest" in texto
        assert not any(p in texto for p in ("Particular", "sócios", "Retirada", "operacional"))
    with pdfplumber.open(io.BytesIO(pdf.mensal(dados.mensal("2026-08")))) as doc:
        texto = " ".join(pg.extract_text() or "" for pg in doc.pages)
    assert "Investido no mês (fora do resultado) R$ 300,00" in texto
    assert "Resultado (sobrou no mês) R$ 1.100,00" in texto


def test_pdf_oficial_depois_de_fechar():
    from app.classificacao import servico as cl
    from app.fechamento import servico as fc
    from app.importacao import consultas
    from app.relatorios import dados
    pend = consultas.movimentacoes(classificacoes=["Revisar"])
    cl.classificar([m["id"] for m in pend], "Classificada", cl.subcategoria_por_nome("Outras despesas", "Outras despesas"))
    fc.fechar("2026-08")
    r = dados.mensal("2026-08")
    assert r.oficial and r.fechado_em and not r.pendentes


def test_csv_padrao_brasileiro():
    from app.relatorios import csv_export, dados
    b = csv_export.movimentacoes(dados.mensal("2026-08").movimentacoes)
    assert b.startswith("﻿".encode("utf-8"))
    linhas = list(csv.reader(io.StringIO(b.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0][0] == "Data" and linhas[0][4] == "Situação" and len(linhas) == 5
    assert {l[4] for l in linhas[1:]} == {"Classificada", "Revisar"}
    assert linhas[1][0] == "05/08/2026" and linhas[1][3] == "2000,00"
    assert any(l[3] == "-900,00" for l in linhas[1:])
