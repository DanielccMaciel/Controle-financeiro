import pandas as pd
import streamlit as st

from app import config
from app.contas import repositorio as contas_repo
from app.importacao import consultas
from app.interface.formato import data_br, reais

st.title("📄 Documentos")
st.caption("Os PDFs importados. Os originais ficam guardados em `extratos/` e nunca são apagados.")

contas = contas_repo.listar()
conta = st.selectbox("Conta", [None] + contas, format_func=lambda c: "Todas" if c is None else c.nome)
docs = consultas.documentos(conta.id if conta else None)

if not docs:
    st.info("Nenhum documento importado ainda. Use a tela **Importação**.")
    st.stop()

st.dataframe(pd.DataFrame([
    {
        "Nº": d["id"],
        "Conta": d["conta_nome"],
        "Arquivo": d["arquivo_nome"],
        "Período": f"{data_br(d['periodo_inicio'])} a {data_br(d['periodo_fim'])}",
        "Páginas": d["paginas"],
        "Lidas": d["qtd_lidas"],
        "Novas": d["qtd_novas"],
        "Já existentes": d["qtd_existentes"],
        "Saldo final": reais(d["saldo_final"]),
        "Importado em": data_br(d["importado_em"]) + " " + d["importado_em"][11:16],
    }
    for d in docs
]), hide_index=True, use_container_width=True)

st.subheader("Detalhe")
doc = st.selectbox("Documento", docs,
                   format_func=lambda d: f"Nº {d['id']} — {d['conta_nome']} — {d['arquivo_nome']}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Saldo inicial", reais(doc["saldo_inicial"]))
c2.metric("Entradas", reais(doc["total_entradas"]))
c3.metric("Saídas", reais(doc["total_saidas"]))
c4.metric("Saldo final", reais(doc["saldo_final"]))
st.caption(f"Arquivo: `{doc['caminho']}` · leitor: {doc['layout']}")

arquivo = config.raiz() / doc["caminho"]
if arquivo.exists():
    st.download_button("📎 Abrir o PDF original", arquivo.read_bytes(), file_name=doc["arquivo_nome"],
                       mime="application/pdf")
else:
    st.error("O PDF original não foi encontrado no caminho registrado.")

movs = consultas.movimentacoes(documento_id=doc["id"])
st.write(f"**{len(movs)} movimentações neste documento**")
st.dataframe(pd.DataFrame([
    {
        "Data": data_br(m["data"]),
        "Valor": reais(m["valor"] if m["tipo"] == "Entrada" else -m["valor"], sinal=True),
        "Operação": m["operacao"],
        "Contraparte": m["contraparte"],
        "Veio primeiro deste doc.": "Sim" if m["documento_origem_id"] == doc["id"] else "Não",
    }
    for m in movs
]), hide_index=True, use_container_width=True)
