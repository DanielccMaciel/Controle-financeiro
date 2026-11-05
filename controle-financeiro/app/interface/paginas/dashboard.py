import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import config
from app.analise import indicadores as ind
from app.contas import repositorio as contas_repo
from app.importacao import consultas
from app.interface.componentes import valor_com_sinal
from app.interface.formato import data_br, reais, reais_md

# Paleta (slots 1–3 da paleta categórica validada para daltonismo em qualquer par)
COR = {"Receita": "#2a78d6", "Despesas": "#eb6834", "Resultado": "#1baf7a"}
BARRA = "#2a78d6"   # gráfico de uma só série: um tom só


def reais_curto(c: int | None) -> str:
    return "—" if c is None else reais(c)


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.1f}%".replace(".", ",")


def layout_base(fig: go.Figure, altura: int) -> go.Figure:
    fig.update_layout(
        height=altura, margin=dict(l=10, r=10, t=10, b=10), separators=",.",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), hovermode="x unified",
        barcornerradius=4, bargap=0.35, bargroupgap=0.08,
    )
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.0f", gridcolor="rgba(128,128,128,0.15)", zeroline=True,
                     zerolinecolor="rgba(128,128,128,0.4)")
    fig.update_xaxes(showgrid=False)
    return fig


st.title("📈 Dashboard")

meses = ind.meses_com_dados()
if not meses:
    st.info("Nenhuma movimentação importada ainda. Use a tela **Importação**.")
    st.stop()

# ---------------------------------------------------------------- filtros (uma linha)
f1, f2 = st.columns([1, 3])
mes = f1.selectbox("Mês", list(reversed(meses)), format_func=ind.rotulo_mes)
contas = contas_repo.listar()
escolhidas = f2.multiselect("Contas", contas, format_func=lambda c: c.nome, placeholder="Todas as contas")
ids = [c.id for c in escolhidas] or None

serie = ind.resumo_por_mes(ids)
por_mes = {r.mes: r for r in serie}
atual = por_mes.get(mes) or ind.ResumoMes(mes)
idx = meses.index(mes)
mes_ant = meses[idx - 1] if idx > 0 else None
ant = por_mes.get(mes_ant) if mes_ant else None

if atual.revisar_qtd:
    st.warning(
        f"❓ **{atual.revisar_qtd} movimentação(ões)** de {atual.rotulo} ainda em Revisão "
        f"({reais_md(atual.revisar_valor)}). Os números abaixo **não as incluem** até você classificar."
    )
    st.page_link("app/interface/paginas/revisao.py", label="Ir para Revisão", icon="❓")


def delta(atual_v, ant_v, *, inverter=False):
    if ant is None or ant_v is None or atual_v is None:
        return None
    d = atual_v - ant_v
    return reais(d, sinal=True) + " vs mês anterior"


# ---------------------------------------------------------------- cartões
from app.fechamento import servico as fc  # noqa: E402

if fc.status(mes) == "Fechado":
    st.subheader(f"Resultado de {atual.rotulo} · 🔒 oficial")
    st.caption(f"Mês fechado em {data_br(fc.info(mes)['fechado_em'])}.")
else:
    st.subheader(f"Resultado de {atual.rotulo} · 🟡 preliminar")
    st.caption("Mês aberto: os números ainda podem mudar. Feche o mês na tela **Meses** quando estiver tudo conferido.")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🟢 Receita", reais(atual.receita), delta(atual.receita, ant and ant.receita))
c2.metric("🔴 Despesas", reais(atual.despesas), delta(atual.despesas, ant and ant.despesas),
          delta_color="inverse")
c3.metric("Sobrou no mês", reais(atual.resultado), delta(atual.resultado, ant and ant.resultado),
          help="Resultado do mês: Receita − Despesas. Negativo = você gastou mais do que recebeu.")
c4.metric("% que sobrou", pct(atual.margem).replace("+", "") if atual.margem is not None else "—",
          help="Quanto da receita sobrou (Resultado ÷ Receita). Vazio quando não há receita no mês.")

d1, d2, d3, d4 = st.columns(4)
d1.metric("🟣 Investido no mês", reais(atual.investimentos),
          help="Aportes em corretora, previdência, outro banco etc., menos os resgates. "
               "Não é despesa: fica separado do resultado do mês.")
d2.metric("🏦 Saldo em conta", reais_curto(atual.saldo),
          help="No fim do mês: último 'Saldo do dia' informado pelo banco. O dinheiro guardado no RDB/caixinha "
               "não aparece no extrato, então não está somado aqui.")
d3.metric("⚪ Resgates do RDB", reais(atual.neutro_entradas),
          help="Dinheiro guardado que voltou para a conta. Não é receita.")
d4.metric("⚪ Aplicações no RDB", reais(atual.neutro_saidas),
          help="Dinheiro que foi guardado. Não é despesa.")

if atual.resultado < 0 and atual.neutro_entradas:
    st.caption(
        f"ℹ️ Em {atual.rotulo} você gastou mais do que recebeu, e {reais_md(atual.neutro_entradas)} "
        "vieram de resgates do RDB/caixinha — dinheiro que já estava guardado."
    )

# ---------------------------------------------------------------- caixinhas
from app.rendimentos import servico as rd  # noqa: E402

if rd.tem_dados():
    ids_cx = rd.filtrar(None, ids)       # todas as caixinhas (das contas escolhidas no filtro)
    if ids_cx:
        cx = rd.resumo_do_mes(mes, ids_cx)
        cx_ant = rd.resumo_do_mes(mes_ant, ids_cx) if mes_ant else None
        st.markdown("**💰 Caixinhas**")
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Saldo guardado", reais(cx.saldo) if cx.saldo is not None else "—",
                  delta(cx.saldo, cx_ant.saldo if cx_ant else None),
                  help="Soma de todas as suas caixinhas, em todos os bancos. "
                       "Não está somado ao saldo em conta.")
        e2.metric("Rendimento do mês", reais(cx.rendimento) if cx.rendimento is not None else "—",
                  delta(cx.rendimento, cx_ant.rendimento if cx_ant else None),
                  help="Informado pelos bancos. Mostrado à parte: não entra na receita nem no resultado do mês.")
        if cx.saldo is None and cx.rendimento is None:
            st.caption(f"Ainda não há PDF de rendimentos de {atual.rotulo}. Importe-o na tela **Importação**.")
        e4.page_link("app/interface/paginas/caixinhas.py", label="Ver por banco e caixinha", icon="💰")

# ---------------------------------------------------------------- evolução
st.divider()
st.subheader("Evolução mês a mês")
if len(serie) < 2:
    st.caption("Com um mês só ainda não há evolução — importe outros meses para comparar.")
rot = [r.rotulo for r in serie]
fig = go.Figure()
for nome, valores in (("Receita", [r.receita for r in serie]), ("Despesas", [r.despesas for r in serie])):
    fig.add_bar(name=nome, x=rot, y=[v / 100 for v in valores], marker_color=COR[nome],
                customdata=[reais(v) for v in valores], hovertemplate=f"{nome}: %{{customdata}}<extra></extra>")
res = [r.resultado for r in serie]
fig.add_scatter(name="Resultado", x=rot, y=[v / 100 for v in res], mode="lines+markers",
                line=dict(color=COR["Resultado"], width=2), marker=dict(size=9, line=dict(width=2, color="white")),
                customdata=[reais(v) for v in res], hovertemplate="Resultado: %{customdata}<extra></extra>")
st.plotly_chart(layout_base(fig, 360), use_container_width=True, theme="streamlit",
                config={"displayModeBar": False})

with st.expander("Ver em tabela"):
    st.dataframe(pd.DataFrame([
        {"Mês": r.rotulo, "Receita": reais(r.receita), "Despesas": reais(r.despesas),
         "Resultado": reais(r.resultado), "Margem": pct(r.margem).replace("+", "") if r.margem is not None else "—",
         "Investido": reais(r.investimentos), "Resgates RDB": reais(r.neutro_entradas),
         "Saldo fim do mês": reais_curto(r.saldo), "A revisar": r.revisar_qtd}
        for r in serie
    ]), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- despesas por categoria
st.divider()
st.subheader(f"Despesas por categoria — {atual.rotulo}")
cats = ind.por_categoria(mes, ids)
if not cats:
    st.info("Nenhuma despesa classificada neste mês.")
else:
    ordem = sorted(cats.items(), key=lambda kv: kv[1])
    total = sum(cats.values())
    fig2 = go.Figure(go.Bar(
        x=[v / 100 for _, v in ordem], y=[k for k, _ in ordem], orientation="h", marker_color=BARRA,
        text=[f"{reais(v)} · {v / total * 100:.0f}%" if total else reais(v) for _, v in ordem],
        textposition="outside", cliponaxis=False,
        customdata=[reais(v) for _, v in ordem], hovertemplate="%{y}: %{customdata}<extra></extra>",
    ))
    fig2 = layout_base(fig2, 60 + 38 * len(ordem))
    fig2.update_layout(hovermode="closest", showlegend=False, margin=dict(l=10, r=150, t=10, b=10))
    fig2.update_xaxes(tickprefix="R$ ", tickformat=",.0f", gridcolor="rgba(128,128,128,0.15)")
    fig2.update_yaxes(tickprefix="", tickformat="", showgrid=False)
    st.plotly_chart(fig2, use_container_width=True, theme="streamlit", config={"displayModeBar": False})

    st.markdown(f"**Variação em relação a {ind.rotulo_mes(mes_ant)}**" if mes_ant else
                "**Variação** — sem mês anterior para comparar ainda.")
    if mes_ant:
        st.dataframe(pd.DataFrame([
            {"Categoria": v.categoria, ind.rotulo_mes(mes_ant): reais(v.anterior), atual.rotulo: reais(v.atual),
             "Diferença": reais(v.diferenca, sinal=True),
             "Variação": ("novo" if v.anterior == 0 else pct(v.percentual))}
            for v in ind.variacao_categorias(mes, mes_ant, ids)
        ]), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- drill-down
st.divider()
st.subheader("🔎 De onde veio esse número?")
tipo_dd = st.radio("Olhar", ["Despesas", "Receitas", "Investimentos"], horizontal=True)
natureza = {"Despesas": "despesa", "Receitas": "receita", "Investimentos": "investimento"}[tipo_dd]
linhas = ind.despesas_por_categoria(mes, ids, natureza)
if not linhas:
    st.info(f"Nenhum valor em {tipo_dd.lower()} neste mês.")
    st.stop()

categorias = sorted({(r["categoria_id"], r["categoria"]) for r in linhas},
                    key=lambda c: -sum(r["valor"] for r in linhas if r["categoria_id"] == c[0]))
g1, g2 = st.columns(2)
cat = g1.selectbox("Categoria", categorias, format_func=lambda c: f"{c[1]} — "
                   f"{reais(sum(r['valor'] for r in linhas if r['categoria_id'] == c[0]))}")
subs = [r for r in linhas if r["categoria_id"] == cat[0]]
sub = g2.selectbox("Subcategoria", subs, format_func=lambda r: f"{r['subcategoria']} — {reais(r['valor'])} "
                   f"({r['qtd']} mov.)")

movs = ind.movimentacoes_da_subcategoria(mes, sub["subcategoria_id"], ids)
st.dataframe(pd.DataFrame([
    {"Data": data_br(m["data"]), "Conta": m["conta_nome"], "Valor": valor_com_sinal(m),
     "Descrição": m["descricao_identificada"] or m["operacao"], "Contraparte": m["contraparte"],
     "Documento": m["documentos"]}
    for m in movs
]), hide_index=True, use_container_width=True)

mov = st.selectbox("Abrir o documento de origem de", movs,
                   format_func=lambda m: f"{data_br(m['data'])} · {valor_com_sinal(m)} · "
                                         f"{(m['contraparte'] or m['operacao'])[:50]}")
st.code(mov["descricao_original"], language=None)
for d in consultas.documentos_da_movimentacao(mov["id"]):
    a, b = st.columns([3, 1])
    a.write(f"📄 **{d['arquivo_nome']}** — página {d['pagina']}")
    arq = config.raiz() / d["caminho"]
    if arq.exists():
        b.download_button("Abrir PDF", arq.read_bytes(), file_name=d["arquivo_nome"], mime="application/pdf",
                          key=f"dd_{mov['id']}_{d['id']}")
