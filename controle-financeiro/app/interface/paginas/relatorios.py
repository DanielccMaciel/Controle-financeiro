import pandas as pd
import streamlit as st

from app.analise import indicadores as ind
from app.interface.formato import data_br, reais
from app.relatorios import csv_export, dados, excel, pdf

st.title("🧾 Relatórios")
st.caption(
    "Relatório para guardar ou imprimir. Os números são os mesmos do Dashboard. "
    "Mês **fechado** sai como resultado oficial; mês **aberto**, como preliminar."
)

if not ind.meses_com_dados():
    st.info("Nenhuma movimentação importada ainda.")
    st.stop()

tipo = st.radio("Relatório", ["Mensal", "Anual"], horizontal=True)

# ---------------------------------------------------------------- mensal
if tipo == "Mensal":
    mes = st.selectbox("Mês", list(reversed(ind.meses_com_dados())), format_func=ind.rotulo_mes)
    r = dados.mensal(mes)
    s = r.resumo
    if r.oficial:
        st.success(f"🔒 Resultado **oficial** — mês fechado em {data_br(r.fechado_em)}.")
    else:
        st.warning("🟡 Mês **aberto**: o relatório sai como **preliminar**. Feche o mês na tela Meses para torná-lo oficial.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Receita", reais(s.receita))
    c2.metric("Despesas", reais(s.despesas))
    c3.metric("Sobrou no mês", reais(s.resultado))
    c4.metric("Investido", reais(s.investimentos))

    base = f"relatorio-{mes}"
    b1, b2, b3 = st.columns(3)
    b1.download_button("📄 Baixar PDF", pdf.mensal(r), file_name=f"{base}.pdf", mime="application/pdf",
                       use_container_width=True, type="primary")
    b2.download_button("📊 Baixar Excel", excel.mensal(r), file_name=f"{base}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    b3.download_button("🧾 Baixar movimentações (CSV)", csv_export.movimentacoes(r.movimentacoes),
                       file_name=f"movimentacoes-{mes}.csv", mime="text/csv", use_container_width=True)
    st.caption("PDF: para imprimir ou mandar. Excel: resumo, categorias, variação, documentos e todas as "
               "movimentações (com fórmulas). CSV: só as movimentações, para outros programas.")

    st.subheader("Prévia")
    if r.despesas:
        total = sum(x["valor"] for x in r.despesas)
        st.markdown("**Despesas por categoria**")
        st.dataframe(pd.DataFrame([
            {"Categoria": x["categoria"], "Subcategoria": x["subcategoria"], "Valor": reais(x["valor"]),
             "%": f"{x['valor'] / total * 100:.1f}%".replace(".", ",") if total else "-"}
            for x in r.despesas
        ]), hide_index=True, use_container_width=True)
    if r.pendentes:
        st.warning(f"{len(r.pendentes)} movimentação(ões) em Revisão — aparecem no relatório como pendentes.")
    st.markdown(f"**Documentos utilizados:** {len(r.documentos)} · **Movimentações:** {len(r.movimentacoes)}")

# ---------------------------------------------------------------- anual
else:
    ano = st.selectbox("Ano", list(reversed(dados.anos_com_dados())))
    r = dados.anual(ano)
    t = r.totais
    st.caption(f"{len(r.com_dados)} mês(es) com dados · {len(r.fechados)} fechado(s)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Receita {ano}", reais(t.receita))
    c2.metric(f"Despesas {ano}", reais(t.despesas))
    c3.metric(f"Sobrou em {ano}", reais(t.resultado))
    c4.metric(f"Investido em {ano}", reais(t.investimentos))

    base = f"relatorio-{ano}"
    b1, b2, b3 = st.columns(3)
    b1.download_button("📄 Baixar PDF", pdf.anual(r), file_name=f"{base}.pdf", mime="application/pdf",
                       use_container_width=True, type="primary")
    b2.download_button("📊 Baixar Excel", excel.anual(r), file_name=f"{base}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    b3.download_button("🧾 Baixar movimentações (CSV)", csv_export.movimentacoes(r.movimentacoes),
                       file_name=f"movimentacoes-{ano}.csv", mime="text/csv", use_container_width=True)

    st.subheader("Prévia")
    st.dataframe(pd.DataFrame([
        {"Mês": ind.rotulo_mes(m.mes),
         "Situação": "🔒 Fechado" if m.mes in r.fechados else ("🟡 Aberto" if m.mes in r.com_dados else "—"),
         "Receita": reais(m.receita), "Despesas": reais(m.despesas), "Sobrou": reais(m.resultado),
         "Acumulado": reais(a), "Investido": reais(m.investimentos)}
        for m, a in zip(r.meses, r.acumulado) if m.mes in r.com_dados
    ]), hide_index=True, use_container_width=True)
