import pandas as pd
import streamlit as st

from app.contas import repositorio as contas_repo
from app.ocorrencias import registro
from app.ocorrencias.registro import NIVEIS, NIVEIS_COM_ACAO, data_br, nome_etapa

st.title("📋 Ocorrências")
st.caption(
    "Tudo o que o programa não conseguiu fazer sozinho com segurança. "
    "Nada é apagado: ao resolver, fica registrado quando e como."
)

# ---- resumo
abertas = registro.contar_abertas()
colunas = st.columns(len(NIVEIS_COM_ACAO))
for col, nivel in zip(colunas, NIVEIS_COM_ACAO):
    icone, rotulo = NIVEIS[nivel]
    col.metric(f"{icone} {rotulo}", abertas[nivel])

with st.expander("O que significa cada nível"):
    st.markdown(
        """
- 🔴 **Não consegui ler** — o arquivo não pôde ser lido (layout desconhecido, arquivo corrompido, senha). **Nada foi importado dele.**
- 🟠 **Tive dificuldade para confirmar** — li o arquivo, mas uma verificação falhou (ex.: o saldo do dia não bate, linha que não soube interpretar). **O documento não é importado** até ser resolvido.
- 🟡 **Precisa da sua decisão** — li certo, mas a escolha é sua (ex.: movimentação que pode ser duplicada, transferência ambígua).
- 🔵 **Registro** — o que aconteceu (ex.: "extrato importado: 247 lidas, 16 novas, saldo conferido"). Não precisa de ação.
"""
    )

st.divider()

# ---- filtros
f1, f2, f3 = st.columns([1, 2, 2])
situacao = f1.radio("Situação", ["Abertas", "Todas"], horizontal=True)
niveis = f2.multiselect(
    "Nível", list(NIVEIS), default=list(NIVEIS) if situacao == "Todas" else list(NIVEIS_COM_ACAO),
    format_func=lambda n: f"{NIVEIS[n][0]} {NIVEIS[n][1]}",
)
todas_contas = contas_repo.listar()
conta = f3.selectbox(
    "Conta", [None] + todas_contas, format_func=lambda c: "Todas" if c is None else c.nome
)

lista = registro.listar(
    somente_abertas=(situacao == "Abertas"),
    niveis=niveis or None,
    conta_id=conta.id if conta else None,
)

if not lista:
    st.success("Nenhuma ocorrência com esses filtros. ✅")
    st.stop()

tabela = pd.DataFrame(
    [
        {
            "Nº": o.id,
            "Quando": data_br(o.criada_em),
            "Nível": f"{NIVEIS[o.nivel][0]} {NIVEIS[o.nivel][1]}",
            "Etapa": nome_etapa(o.etapa),
            "Mensagem": o.mensagem,
            "Conta": o.conta_nome or "",
            "Arquivo": o.arquivo or "",
            "Situação": "—" if not o.precisa_acao else ("✅ Resolvida" if o.resolvida_em else "Aberta"),
        }
        for o in lista
    ]
)
st.dataframe(tabela, hide_index=True, use_container_width=True)

# ---- detalhe e resolução
st.subheader("Detalhe")
escolhida = st.selectbox(
    "Ocorrência", lista, format_func=lambda o: f"Nº {o.id} — {o.mensagem}"
)
icone, rotulo = NIVEIS[escolhida.nivel]
st.markdown(f"**{icone} {rotulo}** · {nome_etapa(escolhida.etapa)} · {data_br(escolhida.criada_em)}")
st.markdown(f"**{escolhida.mensagem}**")
info = []
if escolhida.conta_nome:
    info.append(f"Conta: {escolhida.conta_nome}")
if escolhida.arquivo:
    info.append(f"Arquivo: {escolhida.arquivo}")
if escolhida.pagina:
    info.append(f"Página: {escolhida.pagina}")
if info:
    st.caption(" · ".join(info))
if escolhida.detalhe:
    st.code(escolhida.detalhe, language=None)

if escolhida.resolvida_em:
    st.success(f"Resolvida em {data_br(escolhida.resolvida_em)}: {escolhida.resolucao}")
elif escolhida.precisa_acao:
    with st.form(f"resolver_{escolhida.id}"):
        texto = st.text_area("Como foi resolvida?", placeholder="Ex.: baixei o PDF de novo e reimportei.")
        if st.form_submit_button("Marcar como resolvida", type="primary"):
            try:
                registro.resolver(escolhida.id, texto)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
