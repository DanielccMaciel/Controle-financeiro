import streamlit as st

from app.classificacao import servico as cl
from app.interface.componentes import ICONE_NATUREZA

st.title("🗂️ Categorias")
st.caption(
    "Toda movimentação recebe uma categoria. A **natureza** diz como a categoria entra nos números: "
    "receita, despesa, investimento (separado do resultado do mês) ou neutro (não entra). "
    "Nada é apagado — desative o que não usar."
)

EXPLICACAO = {
    "receita": "dinheiro que entrou de verdade: salário, serviços, rendimentos.",
    "despesa": "dinheiro gasto: moradia, mercado, transporte, lazer...",
    "investimento": "dinheiro que saiu da conta mas continua seu (corretora, previdência, outro banco). "
                    "Não é gasto: aparece à parte, em \"Investido no mês\".",
    "neutro": "dinheiro só mudando de lugar: caixinha/RDB, transferência entre as suas contas, "
              "dinheiro de outra pessoa que só passou pela conta.",
}
with st.expander("O que é cada natureza"):
    for k, v in cl.NATUREZAS.items():
        st.markdown(f"- {ICONE_NATUREZA[k]} **{v}** — {EXPLICACAO[k]}")

mostrar_inativas = st.toggle("Mostrar inativas", value=False)
categorias = cl.listar_categorias(incluir_inativas=mostrar_inativas)
subs = cl.listar_subcategorias(incluir_inativas=mostrar_inativas)

for natureza, rotulo in cl.NATUREZAS.items():
    grupo = [c for c in categorias if c["natureza"] == natureza]
    if not grupo:
        continue
    st.subheader(f"{ICONE_NATUREZA[natureza]} {rotulo}")
    for cat in grupo:
        filhas = [s for s in subs if s.categoria_id == cat["id"]]
        titulo = f"**{cat['nome']}** — {len(filhas)} subcategoria(s)" + ("" if cat["ativa"] else " · _inativa_")
        with st.expander(titulo):
            for s in filhas:
                a, b = st.columns([4, 1])
                a.write(("• " if s.ativa else "• ~~") + s.nome + ("" if s.ativa else "~~ (inativa)"))
                if b.button("Desativar" if s.ativa else "Reativar", key=f"sub_at_{s.id}"):
                    cl.definir_ativa("subcategorias", s.id, not s.ativa)
                    st.rerun()
            st.divider()
            c1, c2 = st.columns([3, 1])
            nova = c1.text_input("Nova subcategoria", key=f"nova_sub_{cat['id']}", label_visibility="collapsed",
                                 placeholder="Nova subcategoria")
            if c2.button("Adicionar", key=f"add_sub_{cat['id']}"):
                try:
                    cl.criar_subcategoria(cat["id"], nova)
                    st.rerun()
                except cl.ErroClassificacao as e:
                    st.error(str(e))
            c1, c2, c3 = st.columns([3, 1, 1])
            novo_nome = c1.text_input("Renomear categoria", cat["nome"], key=f"ren_{cat['id']}",
                                      label_visibility="collapsed")
            if c2.button("Renomear", key=f"ren_b_{cat['id']}"):
                try:
                    cl.renomear("categorias", cat["id"], novo_nome)
                    st.rerun()
                except cl.ErroClassificacao as e:
                    st.error(str(e))
            if c3.button("Desativar" if cat["ativa"] else "Reativar", key=f"cat_at_{cat['id']}"):
                cl.definir_ativa("categorias", cat["id"], not cat["ativa"])
                st.rerun()

st.divider()
st.subheader("➕ Nova categoria")
with st.form("nova_cat", clear_on_submit=True):
    a, b = st.columns([3, 2])
    nome = a.text_input("Nome")
    natureza = b.selectbox("Natureza", list(cl.NATUREZAS), format_func=lambda k: cl.NATUREZAS[k])
    if st.form_submit_button("Criar categoria", type="primary"):
        try:
            cl.criar_categoria(nome, natureza)
            st.success("Categoria criada. Agora adicione as subcategorias nela.")
            st.rerun()
        except cl.ErroClassificacao as e:
            st.error(str(e))
