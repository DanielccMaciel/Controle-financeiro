import pandas as pd
import streamlit as st

from app.classificacao import regras as rg
from app.classificacao import servico as cl
from app.contas import repositorio as contas_repo
from app.importacao import consultas
from app.interface.componentes import escolher_categoria, valor_com_sinal
from app.interface.formato import data_br

st.title("❓ Revisão")
st.caption(
    "Movimentações que ainda não têm categoria. Diga a categoria de cada uma — uma por vez ou várias de uma vez. "
    "Enquanto estão aqui, elas **não entram** no Dashboard. Tudo o que você decide fica registrado no histórico."
)

if not consultas.totais()["movimentacoes"]:
    st.warning(
        "Ainda **não há nenhuma movimentação importada**, então não há o que revisar. "
        "Vá em **Importação**, clique em **Ler e conferir** e depois no botão **📥 Importar** "
        "(no fim da página)."
    )
    st.page_link("app/interface/paginas/importacao.py", label="Ir para Importação", icon="📥")
    st.stop()

# ---- filtros
contas = contas_repo.listar()
f1, f2 = st.columns([3, 2])
escolhidas = f1.multiselect("Contas", contas, format_func=lambda c: c.nome, placeholder="Todas")
so_sugestao = f2.toggle("Só as que têm sugestão", value=False)

pendentes = consultas.movimentacoes(contas=[c.id for c in escolhidas] or None, classificacoes=["Revisar"])
if so_sugestao:
    pendentes = [m for m in pendentes if m["sugestao_rotulo"]]

total = cl.contar_por_classificacao()
c1, c2, c3 = st.columns(3)
c1.metric("❓ Para revisar", total["Revisar"])
c2.metric("💡 Com sugestão", sum(1 for m in pendentes if m["sugestao_rotulo"]))
c3.metric("✅ Já classificadas", total[cl.CLASSIFICADA])

if not pendentes:
    st.success("Nada para revisar com esses filtros. ✅")
    st.stop()

aba_uma, aba_varias = st.tabs(["🔎 Uma por vez", "📋 Várias de uma vez"])

# ================================================================ uma por vez
with aba_uma:
    ids = [m["id"] for m in pendentes]
    pos = st.session_state.get("rev_pos", 0)
    atual_id = st.session_state.get("rev_id")
    if atual_id in ids:
        pos = ids.index(atual_id)
    pos = min(pos, len(pendentes) - 1)
    m = pendentes[pos]
    st.session_state["rev_id"] = m["id"]

    st.caption(f"{pos + 1} de {len(pendentes)}")
    with st.container(border=True):
        a, b, c = st.columns([1, 1, 1])
        a.markdown(f"**{data_br(m['data'])}** · {m['conta_nome']}")
        b.markdown(f"**{m['tipo']}**")
        c.markdown(f"### {valor_com_sinal(m)}")
        st.markdown(f"**{m['operacao']}**")
        if m["contraparte"]:
            st.text(m["contraparte"])   # texto puro: asteriscos do CPF não viram negrito
        if m["sugestao_rotulo"]:
            st.info(f"💡 **Sugestão:** {m['sugestao_rotulo']}\n\n"
                    f"_{m['sugestao_motivo']}_")
        elif m["sugestao_motivo"]:
            st.caption(f"💡 {m['sugestao_motivo']}")

    # a sugestão (quando existe) já vem escolhida: é só conferir e salvar
    sub_id = escolher_categoria(f"rev_{m['id']}", m["sugestao_subcategoria_id"])
    desc = st.text_input("Descrição identificada (opcional)", m["descricao_identificada"] or "",
                         placeholder="Ex.: Aluguel de março, presente da mãe", key=f"rev_desc_{m['id']}")

    # aprender com a decisão: criar regra para as próximas
    proposta = rg.proposta_a_partir_de(m)
    alvo = rg.formatar_cnpj(proposta["texto"]) if proposta["condicao"] == "cnpj" else f'"{proposta["texto"]}"'
    criar_regra = st.checkbox(
        f"📌 Criar regra: sempre que {rg.CAMPOS[proposta['campo']].lower()} "
        f"{rg.CONDICOES[proposta['condicao']]} {alvo} ({m['tipo'].lower()}), classificar igual",
        value=False, key=f"rev_regra_{m['id']}",
        help="Vale para os próximos extratos e para o que estiver pendente agora, em todas as contas.",
    )

    def avancar():
        st.session_state["rev_pos"] = pos
        st.session_state.pop("rev_id", None)

    b1, b2, b3 = st.columns([2, 1, 1])
    if b1.button("💾 Salvar e próxima", type="primary", use_container_width=True):
        try:
            cl.classificar([m["id"]], cl.CLASSIFICADA, sub_id, descricao_identificada=desc)
            if criar_regra:
                rg.criar(nome=proposta["nome"], campo=proposta["campo"], condicao=proposta["condicao"],
                         texto=proposta["texto"], subcategoria_id=sub_id,
                         tipo_mov=m["tipo"], origem="correcao",
                         observacoes=f"Criada na Revisão a partir de: {m['descricao_original'][:120]}")
                r = cl.aplicar_padroes(somente_pendentes=False)
                if r["aplicadas"]:
                    st.toast(f"Regra criada: mais {r['aplicadas']} movimentação(ões) classificadas.")
            avancar()
            st.rerun()
        except (cl.ErroClassificacao, rg.ErroRegra) as e:
            st.error(str(e))
    if b2.button("⏭️ Pular", use_container_width=True, help="Deixa esta em Revisão e mostra a próxima."):
        st.session_state["rev_pos"] = (pos + 1) % len(pendentes)
        st.session_state.pop("rev_id", None)
        st.rerun()
    if b3.button("⏮️ Anterior", use_container_width=True, disabled=pos == 0):
        st.session_state["rev_pos"] = pos - 1
        st.session_state.pop("rev_id", None)
        st.rerun()

# ================================================================ várias
with aba_varias:
    st.caption("Marque as linhas na tabela (caixinha à esquerda) e aplique a mesma categoria para todas.")
    tabela = pd.DataFrame([
        {
            "Data": data_br(x["data"]),
            "Conta": x["conta_nome"],
            "Valor": valor_com_sinal(x),
            "Operação": x["operacao"],
            "Contraparte": x["contraparte"],
            "Sugestão": x["sugestao_rotulo"] or "",
        }
        for x in pendentes
    ])
    sel = st.dataframe(tabela, hide_index=True, use_container_width=True, on_select="rerun",
                       selection_mode="multi-row",
                       # a chave muda quando a lista muda → a seleção antiga é descartada
                       key="rev_tabela_" + str(hash(tuple(x["id"] for x in pendentes))),
                       height=min(35 * len(tabela) + 38, 450))
    linhas = [i for i in (sel.selection.rows if sel else []) if 0 <= i < len(pendentes)]
    marcadas = [pendentes[i]["id"] for i in linhas]
    st.write(f"**{len(marcadas)} selecionada(s)**")

    if marcadas:
        com_sug = [pendentes[i]["id"] for i in linhas if pendentes[i]["sugestao_rotulo"]]
        if com_sug and st.button(f"💡 Aceitar a sugestão das {len(com_sug)} que têm sugestão"):
            n = cl.aceitar_sugestao(com_sug)
            st.success(f"{n} classificada(s).")
            st.rerun()
        with st.container(border=True):
            sub_m = escolher_categoria("rev_massa")
            if st.button(f"Aplicar às {len(marcadas)} selecionadas", type="primary"):
                try:
                    n = cl.classificar(marcadas, cl.CLASSIFICADA, sub_m, motivo="classificação em massa")
                    st.success(f"{n} classificada(s).")
                    st.rerun()
                except cl.ErroClassificacao as e:
                    st.error(str(e))
