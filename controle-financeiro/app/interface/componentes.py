"""Peças de tela reutilizadas em várias páginas."""

import streamlit as st

from app.classificacao import servico as cl
from app.interface.formato import reais

ICONES = {"Classificada": "✅", "Revisar": "❓"}
ICONE_NATUREZA = {"receita": "🟢", "despesa": "🔴", "investimento": "🟣", "neutro": "⚪"}


def valor_com_sinal(m: dict) -> str:
    return reais(m["valor"] if m["tipo"] == "Entrada" else -m["valor"], sinal=True)


def rotulo_classificacao(m: dict) -> str:
    """Como a movimentação aparece nas tabelas: a categoria (com a cor da natureza) ou "Revisar"."""
    if m["classificacao"] == cl.CLASSIFICADA and m.get("categoria"):
        return f"{ICONE_NATUREZA.get(m.get('natureza'), '')} {m['categoria']} › {m['subcategoria']}".strip()
    return f"{ICONES['Revisar']} Revisar"


def escolher_categoria(chave: str, subcategoria_id: int | None = None) -> int | None:
    """Categoria + subcategoria (a subcategoria depende da categoria).

    Devolve o id da subcategoria escolhida, ou None enquanto a pessoa não escolher as duas.
    Não existe mais a pergunta "de quem é?": tudo é pessoal, classificar é escolher a categoria."""
    subs = cl.listar_subcategorias()
    cats: dict[int, str] = {}
    natureza: dict[int, str] = {}
    for s in subs:
        cats.setdefault(s.categoria_id, s.categoria)
        natureza[s.categoria_id] = s.natureza
    ids = list(cats)
    atual = next((s for s in subs if s.id == subcategoria_id), None)
    col1, col2 = st.columns(2)
    cat_id = col1.selectbox(
        "Categoria", ids, index=ids.index(atual.categoria_id) if atual else None,
        format_func=lambda i: f"{ICONE_NATUREZA[natureza[i]]} {cats[i]}",
        placeholder="Escolha a categoria", key=f"{chave}_cat",
    )
    if cat_id is None:
        col2.selectbox("Subcategoria", [], placeholder="Escolha a categoria primeiro",
                       key=f"{chave}_sub_vazio", disabled=True)
        return None
    opcoes = [s for s in subs if s.categoria_id == cat_id]
    idx = next((i for i, s in enumerate(opcoes) if atual and s.id == atual.id), 0 if len(opcoes) == 1 else None)
    escolhida = col2.selectbox(
        "Subcategoria", opcoes, index=idx, format_func=lambda s: s.nome,
        placeholder="Escolha a subcategoria", key=f"{chave}_sub_{cat_id}",
    )
    st.caption(f"Natureza: {ICONE_NATUREZA[natureza[cat_id]]} {cl.NATUREZAS[natureza[cat_id]]}")
    return escolhida.id if escolhida else None


def recarregar_pagina() -> None:
    """Recarrega a página inteira no navegador (em vez de só redesenhar).

    Usado depois de ações que mudam muito a tela (fechar/reabrir mês). Se algum
    tradutor ou extensão do navegador estiver alterando os textos, o redesenho parcial
    pode dar erro 'removeChild'; a recarga completa evita isso.
    """
    import time

    executar_js(f"/* {time.time()} */ window.parent.location.reload();")
    st.stop()


def executar_js(script: str) -> None:
    """Roda um trecho de JavaScript na página.

    O Streamlit está trocando `components.html` por outras funções; aqui tentamos a
    forma antiga e, se ela não existir mais, a nova. Se nenhuma funcionar, segue sem
    o script (ele só faz ajustes de conforto, nunca cálculo).
    """
    import warnings

    try:
        import streamlit.components.v1 as components

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            components.html(f"<script>{script}</script>", height=0)
        return
    except Exception:
        pass
    try:
        st.html(f"<script>{script}</script>", unsafe_allow_javascript=True)
    except Exception:
        pass
