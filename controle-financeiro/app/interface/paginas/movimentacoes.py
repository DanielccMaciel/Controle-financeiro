from datetime import date

import pandas as pd
import streamlit as st

from app import config
from app.contas import repositorio as contas_repo
from app.classificacao import servico as cl
from app.importacao import consultas
from app.interface.componentes import ICONES, escolher_categoria, rotulo_classificacao, valor_com_sinal
from app.interface.formato import data_br, reais

st.title("💸 Movimentações")
st.caption("Tudo o que foi importado dos extratos. A descrição original nunca é alterada.")

minimo, maximo = consultas.intervalo_datas()
if not minimo:
    st.info("Nenhuma movimentação importada ainda. Use a tela **Importação**.")
    st.stop()

# ---- filtros
contas = contas_repo.listar()
f1, f2 = st.columns([2, 2])
escolhidas = f1.multiselect("Contas", contas, format_func=lambda c: c.nome, placeholder="Todas")
periodo = f2.date_input(
    "Período", value=(date.fromisoformat(minimo), date.fromisoformat(maximo)), format="DD/MM/YYYY"
)
f3, f4, f6, f5 = st.columns([1, 1.6, 1.6, 2])
tipo = f3.selectbox("Tipo", ["Todos", "Entrada", "Saída"])
classes = f4.multiselect("Situação", list(cl.CLASSIFICACOES), placeholder="Todas",
                         format_func=lambda x: f"{ICONES[x]} {x}")
QUEM = {"Todas": None, "Por você": "manual", "Por regra": "regra", "Padrão do programa": "padrao"}
quem = f6.selectbox("Quem classificou", list(QUEM),
                    help="'Por você' mostra só as que você classificou à mão — útil para achar e corrigir um engano.")
busca = f5.text_input("Buscar na descrição", placeholder="Ex.: CELESC, Resgate RDB, mercado...")

inicio = periodo[0].isoformat() if len(periodo) > 0 else None
fim = periodo[1].isoformat() if len(periodo) > 1 else inicio

movs = consultas.movimentacoes(
    contas=[c.id for c in escolhidas] or None, inicio=inicio, fim=fim,
    tipo=None if tipo == "Todos" else tipo, busca=busca.strip() or None,
    classificacoes=classes or None, origem=QUEM[quem],
)

entradas = sum(m["valor"] for m in movs if m["tipo"] == "Entrada")
saidas = sum(m["valor"] for m in movs if m["tipo"] == "Saída")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Movimentações", len(movs))
c2.metric("Entradas", reais(entradas))
c3.metric("Saídas", reais(saidas))
c4.metric("Entradas − Saídas", reais(entradas - saidas))
st.caption(
    "⚠️ Estes totais somam **tudo** o que está filtrado (inclusive Resgate RDB, investimentos e o que está em "
    "Revisão). Receita, despesas e quanto sobrou ficam no Dashboard."
)

if not movs:
    st.info("Nenhuma movimentação com esses filtros.")
    st.stop()

sel = st.dataframe(pd.DataFrame([
    {
        "Data": data_br(m["data"]),
        "Conta": m["conta_nome"],
        "Valor": valor_com_sinal(m),
        "Categoria": rotulo_classificacao(m),
        "Descrição": m["descricao_identificada"] or m["operacao"],
        "Contraparte": m["contraparte"],
        "Documento(s)": m["documentos"],
    }
    for m in movs
]), hide_index=True, use_container_width=True, height=min(35 * len(movs) + 38, 600),
    on_select="rerun", selection_mode="multi-row",
    # a chave muda quando a lista muda → a seleção antiga é descartada
    key="mov_tabela_" + str(hash(tuple((m["id"], m["classificacao"], m["subcategoria_id"]) for m in movs))))

# ---- desfazer classificação das linhas marcadas
linhas_sel = [i for i in (sel.selection.rows if sel else []) if 0 <= i < len(movs)]
marcadas = [movs[i]["id"] for i in linhas_sel if movs[i]["classificacao"] != "Revisar"]
if not linhas_sel:
    st.caption("↩️ **Classificou errado?** Marque as linhas na tabela (caixinha à esquerda) para mandá-las "
               "de volta para a Revisão. Dica: use o filtro *Quem classificou → Por você*.")
elif not marcadas:
    st.info("As linhas marcadas já estão em Revisão.")
else:
    previa = cl.previa_desfazer(marcadas)
    with st.container(border=True):
        st.markdown(f"**↩️ Voltar {len(marcadas)} movimentação(ões) para a Revisão**")
        st.caption("Elas ficam sem categoria e aparecem de novo na tela Revisão, para você classificar certo.")
        if previa["regras"]:
            st.markdown("**Regras que serão excluídas** (foram criadas na Revisão a partir dessa classificação):")
            for r in previa["regras"]:
                st.markdown(f"- 📌 **{r.nome}** → {r.resultado or ''}")
            if previa["arrastadas"]:
                st.warning(f"Essas regras também classificaram outras **{len(previa['arrastadas'])}** "
                           "movimentação(ões). Elas voltam para a Revisão junto.")
                with st.expander("Ver quais"):
                    st.dataframe(pd.DataFrame([
                        {"Data": data_br(x["data"]), "Tipo": x["tipo"], "Valor": reais(x["valor"]),
                         "Operação": x["operacao"], "Contraparte": x["contraparte"]}
                        for x in previa["arrastadas"]]), hide_index=True, use_container_width=True)
        else:
            st.caption("Nenhuma regra foi criada a partir dessas classificações; só elas mudam.")
        if st.button("↩️ Voltar para a Revisão" + (f" e excluir {len(previa['regras'])} regra(s)"
                                                   if previa["regras"] else ""), type="primary"):
            try:
                r = cl.desfazer_classificacao(marcadas)
                st.session_state["mov_desfeito"] = (
                    f"{r['voltaram']} movimentação(ões) voltaram para a Revisão"
                    + (f" (+{r['arrastadas']} que a regra tinha classificado)" if r["arrastadas"] else "")
                    + (f". Regra(s) excluída(s): {', '.join(r['regras'])}" if r["regras"] else "") + ".")
                st.rerun()
            except cl.ErroClassificacao as e:
                st.error(str(e))
if st.session_state.get("mov_desfeito"):
    st.success(st.session_state.pop("mov_desfeito"))
    st.page_link("app/interface/paginas/revisao.py", label="Ir para a Revisão", icon="❓")

# ---- detalhe
st.subheader("Detalhe")
mov = st.selectbox(
    "Movimentação", movs,
    format_func=lambda m: f"{data_br(m['data'])} · {m['conta_nome']} · "
                          f"{valor_com_sinal(m)} · {m['descricao_identificada'] or m['operacao']}",
)
ORIGENS = {"manual": "decidida por você", "regra": "por regra", "padrao": "padrão do programa"}
st.markdown(f"**Categoria atual:** {rotulo_classificacao(mov)}"
            + (f" · {ORIGENS.get(mov['origem_classificacao'], mov['origem_classificacao'])}"
               if mov["origem_classificacao"] else ""))
if mov["sugestao_motivo"]:
    st.caption(f"💡 {mov['sugestao_motivo']}")

with st.expander("✏️ Alterar categoria"):
    sid = escolher_categoria(f"mov_{mov['id']}", mov["subcategoria_id"] or mov["sugestao_subcategoria_id"])
    desc = st.text_input("Descrição identificada", mov["descricao_identificada"] or "", key=f"mov_desc_{mov['id']}")
    motivo = st.text_input("Motivo da alteração (opcional)", key=f"mov_mot_{mov['id']}")
    if st.button("Salvar alteração", type="primary", key=f"mov_salvar_{mov['id']}"):
        try:
            n = cl.classificar([mov["id"]], cl.CLASSIFICADA, sid, descricao_identificada=desc,
                               motivo=motivo or None)
            st.success("Alterado." if n else "Nada mudou.")
            st.rerun()
        except cl.ErroClassificacao as e:
            st.error(str(e))

hist = cl.historico(mov["id"])
if hist:
    with st.expander(f"🕓 Histórico ({len(hist)} alteração(ões))"):
        st.dataframe(pd.DataFrame([
            {"Quando": data_br(h["quando"]) + " " + h["quando"][11:16], "Campo": h["campo"],
             "Antes": h["valor_antigo"] or "—", "Depois": h["valor_novo"] or "—", "Motivo": h["motivo"] or ""}
            for h in hist
        ]), hide_index=True, use_container_width=True)

st.markdown("**De onde veio?**")
st.markdown("**Descrição original (como veio do banco):**")
st.code(mov["descricao_original"], language=None)
for d in consultas.documentos_da_movimentacao(mov["id"]):
    col1, col2 = st.columns([3, 1])
    col1.write(
        f"📄 **{d['arquivo_nome']}** — página {d['pagina']} · período "
        f"{data_br(d['periodo_inicio'])} a {data_br(d['periodo_fim'])}"
    )
    arq = config.raiz() / d["caminho"]
    if arq.exists():
        col2.download_button("Abrir PDF", arq.read_bytes(), file_name=d["arquivo_nome"],
                             mime="application/pdf", key=f"dl_{mov['id']}_{d['id']}")
