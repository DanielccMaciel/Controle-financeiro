import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import config
from app.analise.indicadores import rotulo_mes
from app.contas.repositorio import BANCOS_CONHECIDOS
from app.interface.formato import data_br, reais, reais_md
from app.rendimentos import servico as rd

# A cor acompanha o banco (sempre a mesma), não a posição no gráfico.
# Nubank roxo, Sicoob verde (par conferido para daltonismo e contraste).
COR_BANCO = {"Nubank": "#8a3fd1", "Sicoob": "#008300"}
COR_OUTRO = "#eb6834"
COR = "#52514e"          # linha do saldo total (soma dos bancos): neutra


def base(fig: go.Figure, altura: int) -> go.Figure:
    fig.update_layout(height=altura, margin=dict(l=10, r=10, t=30, b=10), separators=",.",
                      hovermode="x unified", barcornerradius=4, bargap=0.45,
                      legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0))
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.0f", gridcolor="rgba(128,128,128,0.15)", zeroline=True,
                     zerolinecolor="rgba(128,128,128,0.4)", rangemode="tozero")
    fig.update_xaxes(showgrid=False, type="category")
    return fig


def v(c):
    return reais(c) if c is not None else "—"


st.title("💰 Caixinhas e rendimentos")
st.caption("Dinheiro guardado que rende. Os números vêm dos PDFs de rendimento de cada banco. "
           "O rendimento aparece aqui e no cartão do Dashboard: **não é somado à receita do mês**.")

todas = rd.aplicacoes()
if not todas:
    st.info("Nenhum PDF de rendimentos importado ainda.\n\n"
            "No app do Nubank, gere o **Extrato de Rendimentos** das Caixinhas, coloque o PDF na pasta da conta "
            "dona da caixinha (a mesma dos extratos) e use a tela **Importação** — o programa reconhece sozinho "
            "que é de caixinha.")
    st.page_link("app/interface/paginas/importacao.py", label="Ir para Importação", icon="📥")
    st.stop()

# ---------------------------------------------------------------- filtros (uma linha)
f1, f3, f4 = st.columns([1, 1.2, 3])
bancos = ["Todos os bancos", *dict.fromkeys([*BANCOS_CONHECIDOS, *(a["banco"] for a in todas)])]
banco = f3.selectbox("Banco", bancos)
banco = None if banco == bancos[0] else banco
candidatas = [a for a in todas if a["id"] in rd.filtrar(banco)]
escolhidas = f4.multiselect("Caixinhas", candidatas, placeholder="Todas",
                            format_func=lambda a: f"{rd.nome_exibicao(a)} · {a['conta_nome']}")
ids = [a["id"] for a in (escolhidas or candidatas)]
visiveis = [a for a in todas if a["id"] in ids]

titulo = (f"{len(escolhidas)} escolhida(s)" if escolhidas else "todas") + (f" · {banco}" if banco else "")
if not ids:
    st.info(f"Ainda não há PDF de rendimento do **{banco}** importado. Quando houver, ele aparece aqui e "
            "entra no total de todos os bancos.")
    meses = []
else:
    meses = rd.meses_com_dados(ids)

if meses:
    mes = f1.selectbox("Mês", list(reversed(meses)), format_func=rotulo_mes)
    r = rd.resumo_do_mes(mes, ids)
    rend = rd.rendimento_por_mes(ids)
    ano = mes[:4]
    acumulado = sum(x for m, x in rend.items() if m[:4] == ano and m <= mes)
    idx = meses.index(mes)
    ant = rd.resumo_do_mes(meses[idx - 1], ids) if idx > 0 else None

    def delta(atual, anterior):
        if atual is None or anterior is None:
            return None
        return reais(atual - anterior, sinal=True) + " vs mês anterior"

    # ------------------------------------------------------------ cartões
    st.subheader(f"{rotulo_mes(mes)} — caixinhas ({titulo})")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldo guardado", v(r.saldo), delta(r.saldo, ant.saldo if ant else None),
              help="Soma do saldo no fim do período de cada caixinha da seleção que tem PDF deste mês.")
    c2.metric("Rendimento do mês", v(r.rendimento), delta(r.rendimento, ant.rendimento if ant else None),
              help="Soma do rendimento informado pelo banco para cada caixinha da seleção.")
    c3.metric(f"Rendimento em {ano}", reais(acumulado),
              help=f"Soma dos meses de {ano} importados, até {rotulo_mes(mes)}.")
    c4.metric("Resgatado no mês", reais(r.resgates_liquido),
              help="Valor líquido dos resgates (o que voltou para a conta).")
    if r.impostos:
        st.caption(f"IR + IOF retidos nos resgates de {rotulo_mes(mes)}: {reais_md(r.impostos)}.")

    # ------------------------------------------------------------ de onde vem
    st.markdown("**De onde vem cada valor**")
    linhas, sem_pdf = [], []
    for a in visiveis:
        x = rd.resumo_do_mes(mes, [a["id"]])
        ate = rd.ultimo_periodo(a["id"])
        if x.saldo is None and x.rendimento is None:
            sem_pdf.append(rd.nome_exibicao(a))
        linhas.append({
            "Banco": a["banco"], "Conta": a["conta_nome"],
            "Caixinha": rd.nome_exibicao(a),
            "Saldo no fim": v(x.saldo), "Rendimento do mês": v(x.rendimento),
            "Resgatado (líquido)": reais(x.resgates_liquido), "PDF até": data_br(ate) if ate else "—",
        })
    por_banco = []
    for b in sorted({a["banco"] for a in visiveis}):
        x = rd.resumo_do_mes(mes, [a["id"] for a in visiveis if a["banco"] == b])
        por_banco.append({"Banco": b, "Caixinhas": sum(1 for a in visiveis if a["banco"] == b),
                          "Saldo no fim": v(x.saldo), "Rendimento do mês": v(x.rendimento)})
    if len(por_banco) > 1:
        por_banco.append({"Banco": "Total", "Caixinhas": len(visiveis), "Saldo no fim": v(r.saldo),
                          "Rendimento do mês": v(r.rendimento)})
        st.dataframe(pd.DataFrame(por_banco), hide_index=True, use_container_width=True)
    st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True)
    if sem_pdf:
        st.caption(f"⚠️ Sem PDF de {rotulo_mes(mes)} para: {', '.join(sem_pdf)}. "
                   "O total do mês não inclui essas caixinhas.")

    # ------------------------------------------------------------ rendimento por mês
    st.divider()
    st.subheader(f"Rendimento por mês — caixinhas ({titulo})")
    if len(rend) < 2:
        st.caption("Com um mês só ainda não há evolução — importe os PDFs dos outros meses para comparar.")
    por_b = rd.rendimento_por_mes_e_banco(ids)
    ms = sorted(rend)
    rot = [rotulo_mes(m) for m in ms]
    fig = go.Figure()
    for b in sorted(por_b, key=lambda n: (list(COR_BANCO).index(n) if n in COR_BANCO else 99, n)):
        vals = [por_b[b].get(m, 0) for m in ms]
        fig.add_bar(name=b, x=rot, y=[x / 100 for x in vals], marker_color=COR_BANCO.get(b, COR_OUTRO),
                    marker_line=dict(width=2, color="white"),
                    customdata=[reais(x) for x in vals], hovertemplate=f"{b}: %{{customdata}}<extra></extra>")
    fig.add_scatter(x=rot, y=[rend[m] / 100 for m in ms], mode="text", showlegend=False, hoverinfo="skip",
                    text=[reais(rend[m]) for m in ms] if len(ms) <= 12 else None, textposition="top center")
    fig = base(fig, 340)
    fig.update_layout(barmode="stack", showlegend=len(por_b) > 1, legend_traceorder="normal")
    st.plotly_chart(fig, use_container_width=True, theme="streamlit", config={"displayModeBar": False})
    if len(por_b) == 1:
        st.caption(f"Todo o rendimento da seleção vem do {next(iter(por_b))}.")

    # ------------------------------------------------------------ saldo guardado
    st.subheader(f"Saldo guardado — caixinhas ({titulo})")
    serie = rd.saldo_total_por_data(ids)
    if len(serie) < 2:
        st.caption("O gráfico aparece quando houver PDFs de dois períodos ou mais.")
    else:
        fig2 = go.Figure(go.Scatter(
            x=[data_br(d) for d, _ in serie], y=[x / 100 for _, x in serie], mode="lines+markers",
            line=dict(color=COR_BANCO.get(next(iter(por_b)), COR_OUTRO) if len(por_b) == 1 else COR, width=2),
            marker=dict(size=9, line=dict(width=2, color="white")),
            customdata=[reais(x) for _, x in serie], hovertemplate="Saldo: %{customdata}<extra></extra>"))
        fig2 = base(fig2, 300)
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True, theme="streamlit", config={"displayModeBar": False})
        st.caption("Soma só as caixinhas que têm PDF até cada data: o saldo também sobe quando uma caixinha "
                   "passa a ter PDF importado.")

    mov_mes = rd.movimentos_por_mes(ids)
    with st.expander("Ver em tabela (mês a mês)"):
        tab = []
        for m in meses:
            x = rd.resumo_do_mes(m, ids)
            tipos = mov_mes.get(m, {})
            linha = {"Mês": rotulo_mes(m), "Saldo no fim": v(x.saldo), "Rendimento": v(x.rendimento)}
            for b in sorted(por_b):
                if len(por_b) > 1:
                    linha[f"Rendimento {b}"] = v(por_b[b].get(m))
            linha.update({
                "Resgates (líquido)": reais(x.resgates_liquido),
                "Outras movimentações (bruto)": reais(sum(t["bruto"] for n, t in tipos.items()
                                                         if not n.upper().startswith("RESGATE"))),
                "IR + IOF": reais(x.impostos),
            })
            tab.append(linha)
        st.dataframe(pd.DataFrame(tab), hide_index=True, use_container_width=True)

    # ------------------------------------------------------------ movimentações
    st.divider()
    st.subheader(f"🔎 Movimentações de {rotulo_mes(mes)}")
    movs = rd.movimentos(ids, mes)
    if not movs:
        st.info("Nenhum resgate ou aplicação listado neste mês.")
    else:
        conta_de = {a["id"]: a for a in todas}
        st.dataframe(pd.DataFrame([
            {"Data": data_br(m["data"]), "Banco": conta_de[m["aplicacao_id"]]["banco"],
             "Conta": conta_de[m["aplicacao_id"]]["conta_nome"], "Caixinha": rd.nome_exibicao(m),
             "Movimentação": m["tipo"], "Valor bruto": reais(m["valor_bruto"]), "IR": reais(m["ir"]),
             "IOF": reais(m["iof"]), "Valor líquido": reais(m["valor_liquido"]),
             "Documento": f"{m['arquivo_nome']} (pág. {m['pagina']})"}
            for m in movs
        ]), hide_index=True, use_container_width=True, height=min(35 * len(movs) + 38, 420))
        st.caption("Os resgates daqui são os mesmos que aparecem como **Resgate RDB** no extrato da conta "
                   "(lá entram pelo valor líquido).")

# ---------------------------------------------------------------- configurar e documentos
st.divider()
with st.expander("⚙️ Dar apelido às caixinhas"):
    st.caption("**Banco e conta** vêm da conta em que o PDF foi importado. O apelido só muda como a caixinha "
               "aparece aqui (o nome original vem do PDF, às vezes sem espaços). "
               "Ex.: \"Reserva de emergência\", \"Viagem\".")
    antes = pd.DataFrame([
        {"id": a["id"], "Banco": a["banco"], "Conta": a["conta_nome"],
         "Nome no PDF": a["nome"], "Apelido": a["apelido"] or ""}
        for a in todas
    ])
    depois = st.data_editor(
        antes, hide_index=True, use_container_width=True, key="editor_caixinhas",
        disabled=["Banco", "Conta", "Nome no PDF"],
        column_config={
            "id": None,
            "Apelido": st.column_config.TextColumn("Apelido", max_chars=60),
        },
    )
    if st.button("💾 Salvar", type="primary"):
        for _, linha in depois.iterrows():
            rd.definir_apelido(int(linha["id"]), linha["Apelido"] or None)
        st.rerun()

with st.expander("📄 PDFs de rendimentos importados"):
    for d in rd.documentos():
        a, b = st.columns([4, 1])
        a.write(f"**{d['arquivo_nome']}** — {d['conta_nome']} · {data_br(d['periodo_inicio'])} a "
                f"{data_br(d['periodo_fim'])} · importado em {data_br(d['importado_em'])}")
        arq = config.raiz() / d["caminho"]
        if arq.exists():
            b.download_button("Abrir PDF", arq.read_bytes(), file_name=d["arquivo_nome"], mime="application/pdf",
                              key=f"rd_{d['id']}")
