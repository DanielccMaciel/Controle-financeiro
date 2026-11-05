"""Relatórios em PDF (reportlab). Fonte Helvetica: evitar emojis e caracteres fora do padrão."""

import io

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import config
from app.analise.indicadores import rotulo_mes
from app.interface.formato import data_br, reais
from app.relatorios.dados import RelatorioAnual, RelatorioMensal

AZUL, LARANJA, VERDE = colors.HexColor("#2a78d6"), colors.HexColor("#eb6834"), colors.HexColor("#1baf7a")
CINZA_FUNDO, CINZA_LINHA = colors.HexColor("#E8EEF7"), colors.HexColor("#BBBBBB")

_est = getSampleStyleSheet()
T1 = ParagraphStyle("t1", parent=_est["Title"], fontName="Helvetica-Bold", fontSize=18, spaceAfter=4, alignment=0)
T2 = ParagraphStyle("t2", parent=_est["Heading2"], fontName="Helvetica-Bold", fontSize=12, spaceBefore=12, spaceAfter=6)
TXT = ParagraphStyle("txt", parent=_est["Normal"], fontName="Helvetica", fontSize=9, leading=12)
PEQ = ParagraphStyle("peq", parent=TXT, fontSize=8, textColor=colors.HexColor("#555555"))
SELO_OK = ParagraphStyle("ok", parent=TXT, fontName="Helvetica-Bold", textColor=colors.HexColor("#1b7a43"))
SELO_PRE = ParagraphStyle("pre", parent=TXT, fontName="Helvetica-Bold", textColor=colors.HexColor("#9a6700"))


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}%".replace(".", ",")


def _tabela(dados, larguras, *, total=False, direita_de=1, fonte=8.5) -> Table:
    t = Table(dados, colWidths=larguras, repeatRows=1)
    estilo = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", fonte),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", fonte),
        ("BACKGROUND", (0, 0), (-1, 0), CINZA_FUNDO),
        ("ALIGN", (direita_de, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, CINZA_LINHA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if total:
        estilo += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", fonte),
                   ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]
    t.setStyle(TableStyle(estilo))
    return t


def _rodape(texto):
    def desenhar(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(doc.leftMargin, 1.0 * cm, texto)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 1.0 * cm, f"Página {doc.page}")
        canvas.restoreState()
    return desenhar


def _por_categoria(linhas: list[dict], total: int) -> list[list]:
    """Linhas agrupadas: categoria (negrito na tela) e subcategorias abaixo."""
    grupos: dict[str, list[dict]] = {}
    for l in linhas:
        grupos.setdefault(l["categoria"], []).append(l)
    ordem = sorted(grupos, key=lambda c: -sum(x["valor"] for x in grupos[c]))
    dados = []
    for cat in ordem:
        soma = sum(x["valor"] for x in grupos[cat])
        dados.append([cat, "", reais(soma), _pct(soma / total * 100 if total else None)])
        for x in grupos[cat]:
            dados.append(["", x["subcategoria"], reais(x["valor"]), ""])
    return dados


# ------------------------------------------------------------------ mensal

def mensal(r: RelatorioMensal) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.8 * cm,
                            title=f"Relatório mensal {r.rotulo}", author=config.NOME_PROGRAMA)
    s, a = r.resumo, r.anterior
    el = [Paragraph(f"Relatório mensal - {r.rotulo}", T1)]
    el.append(Paragraph(f"RESULTADO OFICIAL - mês fechado em {data_br(r.fechado_em)}", SELO_OK) if r.oficial
              else Paragraph("RESULTADO PRELIMINAR - mês ainda aberto, os números podem mudar", SELO_PRE))
    el.append(Spacer(1, 8))

    cab = ["Indicador", r.rotulo] + ([rotulo_mes(a.mes)] if a else [])
    def lin(nome, fn, fmt=reais):
        return [nome, fmt(fn(s))] + ([fmt(fn(a))] if a else [])
    dados = [cab,
             lin("Receita", lambda x: x.receita),
             lin("Despesas", lambda x: x.despesas),
             lin("Resultado (sobrou no mês)", lambda x: x.resultado),
             lin("Margem (% que sobrou)", lambda x: x.margem, _pct),
             lin("Investido no mês (fora do resultado)", lambda x: x.investimentos),
             lin("Resgates do RDB (não é receita)", lambda x: x.neutro_entradas),
             lin("Aplicações no RDB (não é despesa)", lambda x: x.neutro_saidas),
             lin("Saldo em conta no fim do mês", lambda x: x.saldo, lambda v: "-" if v is None else reais(v))]
    t = _tabela(dados, [7.5 * cm, 4 * cm] + ([4 * cm] if a else []))
    t.setStyle(TableStyle([("FONT", (0, 3), (-1, 3), "Helvetica-Bold", 8.5)]))
    el += [t, Spacer(1, 4), Paragraph(
        "Receita e despesas contam só o que já tem categoria. Investimentos e movimentações do RDB/caixinha "
        "ficam fora do resultado do mês. Movimentações em Revisão não entram nos números.", PEQ)]

    if s.revisar_qtd:
        el += [Spacer(1, 6), Paragraph(
            f"ATENÇÃO: {s.revisar_qtd} movimentação(ões) ainda em Revisão ({reais(s.revisar_valor)}) "
            "- não incluídas acima.", SELO_PRE)]

    for titulo, linhas in (("Despesas por categoria", r.despesas), ("Receitas por categoria", r.receitas),
                           ("Investimentos", r.investimentos)):
        if not linhas:
            continue
        total = sum(x["valor"] for x in linhas)
        dados = [["Categoria", "Subcategoria", "Valor", "%"]] + _por_categoria(linhas, total) + \
                [["Total", "", reais(total), "100%" if total else "-"]]
        tb = _tabela(dados, [5.5 * cm, 6 * cm, 3.2 * cm, 2 * cm], total=True, direita_de=2)
        estilos = [("FONT", (0, i), (-1, i), "Helvetica-Bold", 8.5)
                   for i, l in enumerate(dados) if i and l[0] and l[0] != "Total"]
        tb.setStyle(TableStyle(estilos))
        el += [KeepTogether([Paragraph(titulo, T2), tb])]

    if r.variacao:
        dados = [["Categoria", rotulo_mes(a.mes), r.rotulo, "Diferença", "Variação"]]
        for v in r.variacao:
            dados.append([v.categoria, reais(v.anterior), reais(v.atual), reais(v.diferenca, sinal=True),
                          "novo" if v.anterior == 0 else _pct(v.percentual)])
        el += [KeepTogether([Paragraph(f"Variação das despesas em relação a {rotulo_mes(a.mes)}", T2),
                             _tabela(dados, [5.5 * cm, 3 * cm, 3 * cm, 3 * cm, 2.2 * cm])])]

    if r.pendentes:
        dados = [["Data", "Conta", "Valor", "Descrição"]]
        for m in r.pendentes:
            dados.append([data_br(m["data"]), m["conta_nome"],
                          reais(m["valor"] if m["tipo"] == "Entrada" else -m["valor"], sinal=True),
                          Paragraph(m["descricao_original"][:140], PEQ)])
        el += [Paragraph("Movimentações pendentes (em Revisão)", T2),
               _tabela(dados, [2.2 * cm, 2.6 * cm, 2.8 * cm, 9.8 * cm], direita_de=2)]

    if r.documentos:
        dados = [["Conta", "Arquivo", "Período", "Mov."]]
        for d in r.documentos:
            dados.append([d["conta_nome"], Paragraph(d["arquivo_nome"], PEQ),
                          f"{data_br(d['periodo_inicio'])} a {data_br(d['periodo_fim'])}", str(d["qtd_lidas"])])
        el += [KeepTogether([Paragraph("Documentos utilizados", T2),
                             _tabela(dados, [2.8 * cm, 8.4 * cm, 4.6 * cm, 1.6 * cm], direita_de=3)])]

    rod = _rodape(f"{config.NOME_PROGRAMA} - relatório gerado em {r.gerado_em}")
    doc.build(el, onFirstPage=rod, onLaterPages=rod)
    return buf.getvalue()


# ------------------------------------------------------------------ anual

def _grafico(r: RelatorioAnual) -> Drawing:
    d = Drawing(24 * cm, 6.5 * cm)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 1.8 * cm, 0.9 * cm, 21 * cm, 5 * cm
    ch.data = [[m.receita / 100 for m in r.meses], [m.despesas / 100 for m in r.meses]]
    ch.categoryAxis.categoryNames = [rotulo_mes(m.mes)[:3] for m in r.meses]
    ch.categoryAxis.labels.fontName = ch.valueAxis.labels.fontName = "Helvetica"
    ch.categoryAxis.labels.fontSize = ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.valueMin = 0
    ch.valueAxis.labelTextFormat = lambda v: f"R$ {v:,.0f}".replace(",", ".")
    ch.valueAxis.gridStrokeColor = colors.HexColor("#DDDDDD")
    ch.valueAxis.visibleGrid = True
    ch.bars[0].fillColor, ch.bars[1].fillColor = AZUL, LARANJA
    ch.bars.strokeColor = None
    ch.barSpacing, ch.groupSpacing = 1, 6
    d.add(ch)
    lg = Legend()
    lg.x, lg.y = 2 * cm, 6.3 * cm
    lg.fontName, lg.fontSize, lg.alignment = "Helvetica", 8, "right"
    lg.columnMaximum, lg.dx, lg.dy, lg.deltax = 1, 8, 8, 70
    lg.colorNamePairs = [(AZUL, "Receita"), (LARANJA, "Despesas")]
    d.add(lg)
    return d


def anual(r: RelatorioAnual) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.6 * cm,
                            title=f"Relatório anual {r.ano}", author=config.NOME_PROGRAMA)
    el = [Paragraph(f"Relatório anual - {r.ano}", T1),
          Paragraph(f"{len(r.fechados)} mês(es) fechado(s) = oficial · demais = preliminar", PEQ),
          Spacer(1, 6)]

    dados = [["Mês", "Situação", "Receita", "Despesas", "Resultado", "Margem", "Acumulado",
              "Investido", "Resgates RDB", "Revisar"]]
    for m, acum in zip(r.meses, r.acumulado):
        tem = m.mes in r.com_dados
        dados.append([rotulo_mes(m.mes),
                      "Fechado" if m.mes in r.fechados else ("Aberto" if tem else "-"),
                      reais(m.receita) if tem else "-", reais(m.despesas) if tem else "-",
                      reais(m.resultado) if tem else "-", _pct(m.margem) if tem else "-",
                      reais(acum) if tem else "-", reais(m.investimentos) if tem else "-",
                      reais(m.neutro_entradas) if tem else "-", str(m.revisar_qtd) if tem else "-"])
    t = r.totais
    dados.append([f"Total {r.ano}", "", reais(t.receita), reais(t.despesas), reais(t.resultado), _pct(t.margem),
                  "", reais(t.investimentos), reais(t.neutro_entradas), str(t.revisar_qtd)])
    el += [_tabela(dados, [2.2 * cm, 1.9 * cm, 2.9 * cm, 2.9 * cm, 3 * cm, 1.8 * cm, 3 * cm, 2.7 * cm, 2.9 * cm,
                           1.6 * cm], total=True, direita_de=2),
           Spacer(1, 10), _grafico(r)]

    if r.categorias:
        meses_dados = [m for m in r.meses if m.mes in r.com_dados]
        cab = ["Categoria"] + [rotulo_mes(m.mes)[:3] for m in meses_dados] + ["Total"]
        linhas = [cab]
        for cat, valores in r.categorias.items():
            linhas.append([cat] + [reais(valores.get(m.mes, 0)).replace("R$ ", "") for m in meses_dados]
                          + [reais(sum(valores.values())).replace("R$ ", "")])
        linhas.append(["Total"] + [reais(sum(v.get(m.mes, 0) for v in r.categorias.values())).replace("R$ ", "")
                                   for m in meses_dados]
                      + [reais(sum(sum(v.values()) for v in r.categorias.values())).replace("R$ ", "")])
        resto = (26.9 - 5.5) / (len(meses_dados) + 1)
        el += [KeepTogether([Paragraph("Despesas por categoria (R$)", T2),
                             _tabela(linhas, [5.5 * cm] + [resto * cm] * (len(meses_dados) + 1),
                                     total=True, fonte=7.5)])]

    el += [Spacer(1, 6), Paragraph(
        "Resultado = Receita - Despesas (só o que tem categoria). Investimentos e RDB ficam fora do resultado. "
        "Movimentações em Revisão não entram nos números.", PEQ)]
    rod = _rodape(f"{config.NOME_PROGRAMA} - relatório gerado em {r.gerado_em}")
    doc.build(el, onFirstPage=rod, onLaterPages=rod)
    return buf.getvalue()
