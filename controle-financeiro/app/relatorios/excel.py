"""Relatórios em Excel (.xlsx). Totais, resultado, margem e percentuais são FÓRMULAS,
para a planilha recalcular se alguém alterar um valor."""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app import config
from app.analise.indicadores import rotulo_mes
from app.interface.formato import data_br
from app.relatorios.dados import RelatorioAnual, RelatorioMensal

FONTE = "Arial"
MOEDA = '"R$" #,##0.00;[Red]-"R$" #,##0.00;"-"'
PCT = '0.0%;[Red]-0.0%;"-"'
TITULO = Font(name=FONTE, size=14, bold=True)
NEGRITO = Font(name=FONTE, bold=True)
NORMAL = Font(name=FONTE)
CINZA = Font(name=FONTE, size=9, color="666666")
CABEC_FILL = PatternFill("solid", fgColor="E8EEF7")
LINHA = Border(top=Side(style="thin", color="999999"))


def _moeda(c: int | None) -> float | None:
    return None if c is None else c / 100


def _cabecalho(ws, linha: int, titulos: list[str]) -> None:
    for i, t in enumerate(titulos, 1):
        cel = ws.cell(linha, i, t)
        cel.font, cel.fill = NEGRITO, CABEC_FILL
        cel.alignment = Alignment(vertical="center")


def _larguras(ws, larguras: list[int]) -> None:
    for i, w in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _fonte_padrao(ws) -> None:
    for linha in ws.iter_rows():
        for c in linha:
            if c.font is None or c.font.name != FONTE:
                c.font = Font(name=FONTE, bold=c.font.b if c.font else False,
                              size=c.font.sz if c.font else 11, color=c.font.color if c.font else None)


def _aba_movimentacoes(wb: Workbook, movs: list[dict]) -> None:
    ws = wb.create_sheet("Movimentações")
    _cabecalho(ws, 1, ["Data", "Conta", "Tipo", "Valor (R$)", "Situação", "Categoria", "Subcategoria",
                       "Descrição identificada", "Descrição original", "Documento(s)"])
    for i, m in enumerate(movs, 2):
        a, mm, d = m["data"].split("-")
        valor = m["valor"] / 100 * (1 if m["tipo"] == "Entrada" else -1)
        vals = [f"{d}/{mm}/{a}", m["conta_nome"], m["tipo"], valor, m["classificacao"], m["categoria"] or "",
                m["subcategoria"] or "", m["descricao_identificada"] or "", m["descricao_original"],
                m["documentos"] or ""]
        for j, v in enumerate(vals, 1):
            ws.cell(i, j, v).font = NORMAL
        ws.cell(i, 4).number_format = MOEDA
    _larguras(ws, [12, 14, 9, 15, 13, 26, 30, 30, 80, 40])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:J{max(len(movs) + 1, 1)}"


# ------------------------------------------------------------------ mensal

def mensal(r: RelatorioMensal) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws["A1"] = f"Relatório mensal — {r.rotulo}"
    ws["A1"].font = TITULO
    ws["A2"] = (f"Resultado OFICIAL — mês fechado em {data_br(r.fechado_em)}" if r.oficial
                else "Resultado PRELIMINAR — mês ainda aberto")
    ws["A2"].font = NEGRITO
    ws["A3"] = f"Gerado em {r.gerado_em} pelo {config.NOME_PROGRAMA}"
    ws["A3"].font = CINZA

    s = r.resumo
    linhas = [
        ("Receita", _moeda(s.receita)),                                   # B5
        ("Despesas", _moeda(s.despesas)),                                 # B6
        ("Resultado (sobrou no mês)", "=B5-B6"),                          # B7
        ("Margem (% que sobrou)", '=IF(B5>0,B7/B5,"")'),                  # B8
        ("Investido no mês (fora do resultado)", _moeda(s.investimentos)),  # B9
        ("Resgates do RDB (não é receita)", _moeda(s.neutro_entradas)),  # B10
        ("Aplicações no RDB (não é despesa)", _moeda(s.neutro_saidas)),  # B11
        ("Saldo em conta no fim do mês", _moeda(s.saldo)),               # B12
        ("Movimentações ainda em Revisão", s.revisar_qtd),               # B13
    ]
    _cabecalho(ws, 4, ["Indicador", r.rotulo] + ([rotulo_mes(r.anterior.mes)] if r.anterior else []))
    for i, (rot, val) in enumerate(linhas, 5):
        ws.cell(i, 1, rot).font = NEGRITO if rot.startswith("Resultado") else NORMAL
        c = ws.cell(i, 2, val)
        c.font = NEGRITO if rot.startswith("Resultado") else NORMAL
        c.number_format = PCT if rot.startswith("Margem") else ("0" if "Revisão" in rot else MOEDA)
    if r.anterior:
        a = r.anterior
        ant = [_moeda(a.receita), _moeda(a.despesas), "=C5-C6", '=IF(C5>0,C7/C5,"")', _moeda(a.investimentos),
               _moeda(a.neutro_entradas), _moeda(a.neutro_saidas), _moeda(a.saldo), a.revisar_qtd]
        for i, val in enumerate(ant, 5):
            c = ws.cell(i, 3, val)
            c.font = NORMAL
            c.number_format = ws.cell(i, 2).number_format
    ws["A15"] = ("Receita e despesas contam só movimentações que já têm categoria. "
                 "Resgates/aplicações no RDB e investimentos ficam fora do resultado do mês. "
                 "Movimentações em Revisão não entram nos números.")
    ws["A15"].font = CINZA
    _larguras(ws, [38, 18, 18])

    # despesas por categoria (com % por fórmula)
    for nome, dados in (("Despesas por categoria", r.despesas), ("Receitas por categoria", r.receitas),
                        ("Investimentos", r.investimentos)):
        w = wb.create_sheet(nome)
        _cabecalho(w, 1, ["Categoria", "Subcategoria", "Valor (R$)", "Movimentações", "% do total"])
        n = len(dados)
        for i, d in enumerate(dados, 2):
            for j, v in enumerate([d["categoria"], d["subcategoria"], d["valor"] / 100, d["qtd"]], 1):
                w.cell(i, j, v).font = NORMAL
            w.cell(i, 3).number_format = MOEDA
            w.cell(i, 5, f"=IF($C${n + 2}=0,\"\",C{i}/$C${n + 2})").number_format = PCT
            w.cell(i, 5).font = NORMAL
        t = n + 2
        w.cell(t, 1, "Total").font = NEGRITO
        w.cell(t, 3, f"=SUM(C2:C{t - 1})" if n else 0).number_format = MOEDA
        w.cell(t, 4, f"=SUM(D2:D{t - 1})" if n else 0)
        for j in range(1, 6):
            w.cell(t, j).font = NEGRITO
            w.cell(t, j).border = LINHA
        _larguras(w, [30, 34, 16, 16, 12])

    if r.variacao:
        w = wb.create_sheet("Variação")
        ant = rotulo_mes(r.anterior.mes)
        _cabecalho(w, 1, ["Categoria", ant, r.rotulo, "Diferença", "Variação"])
        for i, v in enumerate(r.variacao, 2):
            w.cell(i, 1, v.categoria)
            w.cell(i, 2, v.anterior / 100).number_format = MOEDA
            w.cell(i, 3, v.atual / 100).number_format = MOEDA
            w.cell(i, 4, f"=C{i}-B{i}").number_format = MOEDA
            w.cell(i, 5, f'=IF(B{i}>0,D{i}/B{i},"novo")').number_format = PCT
            for j in range(1, 6):
                w.cell(i, j).font = NORMAL
        _larguras(w, [30, 16, 16, 16, 12])

    if r.pendentes:
        w = wb.create_sheet("Pendentes")
        _cabecalho(w, 1, ["Data", "Conta", "Valor (R$)", "Descrição"])
        for i, m in enumerate(r.pendentes, 2):
            a, mm, d = m["data"].split("-")
            w.cell(i, 1, f"{d}/{mm}/{a}")
            w.cell(i, 2, m["conta_nome"])
            w.cell(i, 3, m["valor"] / 100 * (1 if m["tipo"] == "Entrada" else -1)).number_format = MOEDA
            w.cell(i, 4, m["descricao_original"])
        _larguras(w, [12, 14, 16, 90])

    w = wb.create_sheet("Documentos")
    _cabecalho(w, 1, ["Conta", "Arquivo", "Período", "Movimentações", "Importado em"])
    for i, d in enumerate(r.documentos, 2):
        per = f"{d['periodo_inicio'][8:10]}/{d['periodo_inicio'][5:7]} a {d['periodo_fim'][8:10]}/{d['periodo_fim'][5:7]}/{d['periodo_fim'][:4]}"
        for j, v in enumerate([d["conta_nome"], d["arquivo_nome"], per, d["qtd_lidas"], d["importado_em"][:16]], 1):
            w.cell(i, j, v).font = NORMAL
    _larguras(w, [14, 60, 22, 15, 18])

    _aba_movimentacoes(wb, r.movimentacoes)
    for w in wb.worksheets:
        _fonte_padrao(w)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ anual

def anual(r: RelatorioAnual) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo anual"
    ws["A1"] = f"Relatório anual — {r.ano}"
    ws["A1"].font = TITULO
    ws["A2"] = f"Gerado em {r.gerado_em} · Fechado = resultado oficial · Aberto = preliminar"
    ws["A2"].font = CINZA
    _cabecalho(ws, 4, ["Mês", "Situação", "Receita (R$)", "Despesas (R$)", "Resultado (R$)", "Margem",
                       "Resultado acumulado (R$)", "Investido (R$)", "Resgates RDB (R$)", "A revisar"])
    for i, m in enumerate(r.meses, 5):
        tem = m.mes in r.com_dados
        sit = "Fechado" if m.mes in r.fechados else ("Aberto" if tem else "sem dados")
        ws.cell(i, 1, rotulo_mes(m.mes))
        ws.cell(i, 2, sit)
        ws.cell(i, 3, m.receita / 100)
        ws.cell(i, 4, m.despesas / 100)
        ws.cell(i, 5, f"=C{i}-D{i}")
        ws.cell(i, 6, f'=IF(C{i}>0,E{i}/C{i},"")')
        ws.cell(i, 7, f"=E{i}" if i == 5 else f"=G{i - 1}+E{i}")
        ws.cell(i, 8, m.investimentos / 100)
        ws.cell(i, 9, m.neutro_entradas / 100)
        ws.cell(i, 10, m.revisar_qtd)
        for j in (3, 4, 5, 7, 8, 9):
            ws.cell(i, j).number_format = MOEDA
        ws.cell(i, 6).number_format = PCT
    t = 17
    ws.cell(t, 1, f"Total {r.ano}")
    for j, col in ((3, "C"), (4, "D"), (5, "E"), (8, "H"), (9, "I"), (10, "J")):
        ws.cell(t, j, f"=SUM({col}5:{col}16)").number_format = "0" if j == 10 else MOEDA
    ws.cell(t, 6, f'=IF(C{t}>0,E{t}/C{t},"")').number_format = PCT
    for j in range(1, 11):
        ws.cell(t, j).font = NEGRITO
        ws.cell(t, j).border = LINHA
    ws["A19"] = ("Resultado = Receita − Despesas (só o que tem categoria). Investimentos e RDB ficam fora do resultado. "
                 "Movimentações em Revisão não entram nos números.")
    ws["A19"].font = CINZA
    _larguras(ws, [12, 12, 16, 16, 16, 10, 22, 16, 18, 10])
    ws.freeze_panes = "B5"

    w = wb.create_sheet("Despesas por categoria")
    _cabecalho(w, 1, ["Categoria"] + [rotulo_mes(m.mes) for m in r.meses] + [f"Total {r.ano}"])
    cats = list(r.categorias)
    for i, cat in enumerate(cats, 2):
        w.cell(i, 1, cat)
        for j, m in enumerate(r.meses, 2):
            w.cell(i, j, r.categorias[cat].get(m.mes, 0) / 100).number_format = MOEDA
        w.cell(i, 14, f"=SUM(B{i}:M{i})").number_format = MOEDA
        w.cell(i, 14).font = NEGRITO
    t = len(cats) + 2
    w.cell(t, 1, "Total")
    for j in range(2, 15):
        col = get_column_letter(j)
        w.cell(t, j, f"=SUM({col}2:{col}{t - 1})" if cats else 0).number_format = MOEDA
    for j in range(1, 15):
        w.cell(t, j).font = NEGRITO
        w.cell(t, j).border = LINHA
    _larguras(w, [30] + [13] * 12 + [16])
    w.freeze_panes = "B2"

    _aba_movimentacoes(wb, r.movimentacoes)
    for w in wb.worksheets:
        _fonte_padrao(w)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
