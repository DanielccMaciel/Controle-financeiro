import pandas as pd
import streamlit as st

from app.analise import indicadores as ind
from app.fechamento import servico as fc
from app.interface.componentes import recarregar_pagina
from app.interface.formato import data_br, reais, reais_md

st.title("🗓️ Meses")
st.caption(
    "Fechar um mês grava o **resultado oficial** daquele momento e trava alterações nele. "
    "Precisa corrigir algo depois? **Reabra** informando o motivo — tudo fica no histórico."
)

meses = ind.meses_com_dados()
if not meses:
    st.info("Nenhuma movimentação importada ainda.")
    st.stop()

resumos = {r.mes: r for r in ind.resumo_por_mes()}
st.dataframe(pd.DataFrame([
    {
        "Mês": ind.rotulo_mes(m),
        "Situação": "🔒 Fechado" if fc.status(m) == "Fechado" else "🟡 Aberto",
        "Receita": reais(resumos[m].receita),
        "Despesas": reais(resumos[m].despesas),
        "Sobrou": reais(resumos[m].resultado),
        "Investido": reais(resumos[m].investimentos),
        "A revisar": resumos[m].revisar_qtd,
        "Fechado em": (data_br(fc.info(m)["fechado_em"]) + " " + fc.info(m)["fechado_em"][11:16])
                      if fc.status(m) == "Fechado" else "",
    }
    for m in reversed(meses)
]), hide_index=True, use_container_width=True)

st.divider()
mes = st.selectbox("Mês", list(reversed(meses)), format_func=lambda m: f"{ind.rotulo_mes(m)} — "
                   + ("🔒 Fechado" if fc.status(m) == "Fechado" else "🟡 Aberto"))
rotulo = ind.rotulo_mes(mes)

# ---------------------------------------------------------------- aberto: checklist + fechar
if fc.status(mes) == "Aberto":
    st.subheader(f"Checklist para fechar {rotulo}")
    itens = fc.checklist(mes)
    for i in itens:
        st.markdown(f"{i.icone} **{i.texto}**" + (f" — {i.detalhe}" if i.detalhe else ""))
    st.caption("❌ impede fechar · ⚠️ só um aviso, dá para fechar assim mesmo")

    if fc.pode_fechar(itens):
        r = resumos[mes]
        st.success(
            f"Pronto para fechar. Resultado que ficará oficial: receita {reais_md(r.receita)} · "
            f"despesas {reais_md(r.despesas)} · sobrou {reais_md(r.resultado)} · investido {reais_md(r.investimentos)}."
        )
        with st.form(f"fechar_{mes}"):
            obs = st.text_input("Observação (opcional)", placeholder="Ex.: conferido com o app do banco")
            if st.form_submit_button(f"🔒 Fechar {rotulo}", type="primary"):
                try:
                    fc.fechar(mes, obs)
                    st.success(f"{rotulo} fechado. Backup feito antes.")
                    recarregar_pagina()
                except fc.ErroFechamento as e:
                    st.error(str(e))
    else:
        st.warning("Resolva os itens com ❌ para poder fechar.")

# ---------------------------------------------------------------- fechado: reabrir
else:
    i = fc.info(mes)
    st.success(f"🔒 {rotulo} está **fechado** desde {data_br(i['fechado_em'])} {i['fechado_em'][11:16]}"
               + (f" — {i['observacao']}" if i["observacao"] else ""))
    st.caption("Enquanto estiver fechado, não dá para classificar, aplicar regras ou importar movimentações "
               "novas deste mês.")
    with st.expander("🔓 Reabrir este mês"):
        with st.form(f"reabrir_{mes}"):
            motivo = st.text_area("Motivo da reabertura (obrigatório)",
                                  placeholder="Ex.: lembrei que aquele Pix foi o conserto do carro, não lazer")
            if st.form_submit_button("Reabrir"):
                try:
                    fc.reabrir(mes, motivo)
                    st.success(f"{rotulo} reaberto.")
                    recarregar_pagina()
                except fc.ErroFechamento as e:
                    st.error(str(e))

# ---------------------------------------------------------------- histórico
hist = fc.historico(mes)
if hist:
    st.subheader("Histórico")
    for h in reversed(hist):
        quando = f"{data_br(h['quando'])} {h['quando'][11:16]}"
        if h["acao"] == "fechamento":
            f = h["retrato"]
            st.markdown(f"🔒 **Fechado** em {quando}" + (f" — _{h['texto']}_" if h["texto"] else ""))
            st.caption(f"Receita {reais_md(f['receita'])} · Despesas {reais_md(f['despesas'])} · "
                       f"Sobrou {reais_md(f['resultado'])} · Investido {reais_md(f['investimentos'])} · "
                       f"{f['movimentacoes']} movimentações")
        else:
            st.markdown(f"🔓 **Reaberto** em {quando} — _{h['texto']}_")

    antes, depois = fc.ultimos_dois_retratos(mes)
    if antes and depois:
        mudancas = fc.comparar(antes, depois)
        st.markdown("**O que mudou entre os dois últimos fechamentos**")
        if not mudancas:
            st.caption("Nenhum número mudou.")
        else:
            NOMES = {"receita": "Receita", "despesas": "Despesas", "resultado": "Sobrou no mês",
                     "investimentos": "Investido", "resgates_rdb": "Resgates RDB", "aplicacoes_rdb": "Aplicações RDB",
                     "saldo": "Saldo em conta", "movimentacoes": "Movimentações"}
            contagem = {"movimentacoes"}
            st.dataframe(pd.DataFrame([
                {"Item": NOMES.get(k, k),
                 "Antes": a if k in contagem else reais(a),
                 "Depois": b if k in contagem else reais(b),
                 "Diferença": (b or 0) - (a or 0) if k in contagem else reais((b or 0) - (a or 0), sinal=True)}
                for k, a, b in mudancas
            ]), hide_index=True, use_container_width=True)
