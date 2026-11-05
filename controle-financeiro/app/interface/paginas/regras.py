import pandas as pd
import streamlit as st

from app.classificacao import regras as rg
from app.classificacao import servico as cl
from app.contas import repositorio as contas_repo
from app.interface.componentes import escolher_categoria, valor_com_sinal
from app.interface.formato import data_br

st.title("⚙️ Regras")
st.caption(
    "Regras classificam sozinhas o que se repete (ex.: CNPJ da CELESC → Moradia › Energia). "
    "**Aplicar** classifica direto; **Sugerir** deixa em Revisão com a sugestão para você confirmar. "
    "Regras nunca mexem no que você já decidiu."
)

with st.expander("Como a regra é escolhida quando mais de uma bate"):
    st.markdown(
        "1. Vence a de **maior prioridade**.\n"
        "2. Empate: regra por **CNPJ** vence regra por **texto**.\n"
        "3. Ainda empatadas e mandando coisas diferentes → **conflito**: nada é aplicado e a movimentação "
        "fica em Revisão com o aviso."
    )

c1, c2 = st.columns([3, 1])
if c2.button("🔄 Reaplicar regras", use_container_width=True,
             help="Aplica as regras a tudo que está em Revisão e que você ainda não decidiu."):
    r = cl.aplicar_padroes(somente_pendentes=False)
    st.success(f"{r['aplicadas']} classificada(s) · {r['sugeridas']} com sugestão · "
               f"{r['conflitos']} conflito(s) · {r['sem_regra']} sem regra.")

todas = rg.listar()
mostrar_inativas = c1.toggle("Mostrar regras desativadas", value=False)
lista = [r for r in todas if r.ativa or mostrar_inativas]

ORIGEM = {"inicial": "Configuração inicial", "usuario": "Criada por você", "correcao": "Aprendida na Revisão"}
st.dataframe(pd.DataFrame([
    {
        "Regra": r.nome,
        "Quando": r.descrever_condicao(),
        "Então": r.resultado or "",
        "Ação": "✅ Aplicar" if r.acao == "aplicar" else "💡 Sugerir",
        "Prioridade": r.prioridade,
        "Usada": r.vezes_aplicada,
        "Origem": ORIGEM.get(r.origem, r.origem),
        "Ativa": "Sim" if r.ativa else "Não",
    }
    for r in lista
]), hide_index=True, use_container_width=True, height=min(35 * len(lista) + 38, 520))

# ---------------------------------------------------------------- detalhe / editar
st.subheader("Detalhe da regra")
regra = st.selectbox("Regra", lista, format_func=lambda r: f"{r.nome} — {r.descrever_condicao()}")
if regra:
    if regra.observacoes:
        st.info(regra.observacoes)
    a, b, c = st.columns(3)
    acao = a.radio("Ação", ["aplicar", "sugerir"], index=0 if regra.acao == "aplicar" else 1,
                   format_func=lambda x: "✅ Aplicar" if x == "aplicar" else "💡 Sugerir",
                   key=f"acao_{regra.id}", horizontal=True)
    prioridade = b.number_input("Prioridade", 0, 1000, regra.prioridade, step=10, key=f"prio_{regra.id}")
    ativa = c.toggle("Ativa", regra.ativa, key=f"ativa_{regra.id}")
    if st.button("Salvar alterações da regra", key=f"salvar_{regra.id}"):
        rg.alterar(regra.id, acao=acao, prioridade=int(prioridade), ativa=ativa)
        st.success("Regra alterada. Use **🔄 Reaplicar regras** para aplicá-la ao que está pendente.")
        st.rerun()

    pegas = rg.testar(regra)
    with st.expander(f"🔎 Testar: esta regra pega {len(pegas)} movimentação(ões) já importadas"):
        if pegas:
            st.dataframe(pd.DataFrame([
                {"Data": data_br(m["data"]), "Conta": m["conta_nome"], "Valor": valor_com_sinal(m),
                 "Contraparte": m["contraparte"] or m["operacao"],
                 "Hoje está": m["categoria_rotulo"] or "❓ Revisar"}
                for m in pegas
            ]), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- nova regra
st.divider()
st.subheader("➕ Nova regra")
st.caption("Dica: o jeito mais fácil é criar a regra direto na tela **Revisão**, ao classificar uma movimentação.")
n1, n2, n3 = st.columns([2, 2, 3])
campo = n1.selectbox("Olhar em", list(rg.CAMPOS), format_func=lambda k: rg.CAMPOS[k])
condicao = n2.selectbox("Condição", list(rg.CONDICOES), format_func=lambda k: rg.CONDICOES[k])
texto = n3.text_input("Texto ou CNPJ", placeholder="Ex.: CELESC  ou  08.336.783/0001-90")
m1, m2, m3 = st.columns(3)
tipo_mov = m1.selectbox("Só para", [None, "Entrada", "Saída"], format_func=lambda x: x or "Entradas e saídas")
conta_regra = m2.selectbox("Contas", [None, *contas_repo.listar(somente_ativas=True)],
                           format_func=lambda c: f"Só {c.nome}" if c else "Todas")
acao_nova = m3.radio("Ação", ["aplicar", "sugerir"], horizontal=True, key="acao_nova",
                     format_func=lambda x: "✅ Aplicar" if x == "aplicar" else "💡 Sugerir")
sub_nova = escolher_categoria("regra_nova")
nome = st.text_input("Nome da regra", placeholder="Ex.: Supermercado Imperatriz")
if st.button("Criar regra", type="primary"):
    try:
        rg.criar(nome=nome, campo=campo, condicao=condicao, texto=texto,
                 subcategoria_id=sub_nova, acao=acao_nova, tipo_mov=tipo_mov,
                 conta_id=conta_regra.id if conta_regra else None)
        r = cl.aplicar_padroes(somente_pendentes=False)
        st.success(f"Regra criada e aplicada ao que estava pendente: {r['aplicadas']} classificada(s), "
                   f"{r['sugeridas']} com sugestão.")
        st.rerun()
    except rg.ErroRegra as e:
        st.error(str(e))
