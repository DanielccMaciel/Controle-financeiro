import pandas as pd
import streamlit as st

from app.contas import repositorio as repo
from app.contas.repositorio import Conta, ErroValidacao

st.title("🏦 Contas")
st.caption(
    "Suas contas bancárias. Pode ter **quantas quiser** — outro banco, conta conjunta, conta antiga. "
    "Contas não são apagadas — para deixar de usar, desative."
)

mostrar_inativas = st.toggle("Mostrar contas inativas", value=False)
contas = repo.listar(somente_ativas=not mostrar_inativas)

if contas:
    tabela = pd.DataFrame(
        [
            {
                "Nome": c.nome,
                "Titular": c.titular,
                "Banco": c.banco,
                "Pasta": c.pasta,
                "Ativa": "Sim" if c.ativa else "Não",
                "Observações": c.observacoes or "",
            }
            for c in contas
        ]
    )
    st.dataframe(tabela, hide_index=True, use_container_width=True)
else:
    st.info("Nenhuma conta cadastrada.")


def formulario(conta: Conta, chave: str, rotulo_botao: str) -> Conta | None:
    with st.form(chave, clear_on_submit=False):
        a, b = st.columns(2)
        nome = a.text_input("Nome *", conta.nome, help="Como a conta aparece nas telas. Ex.: Conta principal, Conta conjunta, Reserva")
        titular = b.text_input(
            "Titular *", conta.titular,
            help="De preferência o nome completo, como aparece no extrato: é por ele que o programa reconhece "
                 "de qual conta é cada PDF e as transferências entre as suas contas.")
        bancos = list(repo.BANCOS_CONHECIDOS)
        if conta.banco and conta.banco not in bancos:
            bancos.append(conta.banco)
        banco = a.selectbox(
            "Banco *", bancos, index=bancos.index(conta.banco) if conta.banco else 0,
            accept_new_options=True,
            help="Hoje o programa lê extratos em PDF do Nubank e do Sicoob. Outro banco pode ser cadastrado, "
                 "mas a importação só funciona quando existir leitor para ele.",
        )
        pasta = b.text_input(
            "Pasta dos extratos *", conta.pasta,
            help="Nome da pasta dentro de extratos/. É criada automaticamente.",
        )
        agencia = a.text_input("Agência (opcional)", conta.agencia or "")
        numero = b.text_input("Número da conta (opcional)", conta.numero_conta or "",
                              help="Pode deixar vazio: o programa preenche sozinho na primeira importação.")
        ativa = st.checkbox("Conta ativa", conta.ativa)
        obs = st.text_area("Observações", conta.observacoes or "")
        if st.form_submit_button(rotulo_botao, type="primary"):
            return Conta(
                id=conta.id, nome=nome, titular=titular, banco=banco,
                pasta=pasta, ativa=ativa, agencia=agencia, numero_conta=numero,
                observacoes=obs,
            )
    return None


aba_nova, aba_editar = st.tabs(["➕ Nova conta", "✏️ Editar conta"])

with aba_nova:
    nova = formulario(
        Conta(nome="", titular="", banco="Nubank", pasta=""),
        "form_nova", "Cadastrar",
    )
    if nova:
        try:
            repo.inserir(nova)
            st.success(f"Conta '{nova.nome}' cadastrada.")
            st.rerun()
        except ErroValidacao as e:
            st.error(str(e))

with aba_editar:
    todas = repo.listar()
    if todas:
        escolhida = st.selectbox(
            "Conta", todas, format_func=lambda c: f"{c.nome} ({'ativa' if c.ativa else 'inativa'})"
        )
        editada = formulario(escolhida, f"form_editar_{escolhida.id}", "Salvar alterações")
        if editada:
            try:
                repo.atualizar(editada)
                st.success("Alterações salvas.")
                st.rerun()
            except ErroValidacao as e:
                st.error(str(e))
