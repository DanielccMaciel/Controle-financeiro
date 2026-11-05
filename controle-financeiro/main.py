"""Ponto de entrada do Controle Financeiro Pessoal.

Rodar com:  streamlit run main.py   (ou dois cliques em iniciar.bat)
Demonstração com dados fictícios:  streamlit run demo.py
"""

import traceback

import streamlit as st

from app import config
from app.banco.conexao import conectar
from app.classificacao.servico import aplicar_padroes, contar_por_classificacao
from app.contas.repositorio import garantir_pastas
from app.interface.componentes import executar_js
from app.ocorrencias import registro

st.set_page_config(page_title=config.NOME_PROGRAMA, page_icon="💰", layout="wide")

# A página já está em português. O Streamlit declara a página como inglês e o tradutor
# automático do Chrome passa a "traduzir" a tela, mexendo nela enquanto o programa a
# atualiza (erro "removeChild"). Aqui dizemos ao navegador: português, não traduzir.
executar_js("""
    const d = window.parent.document;
    d.documentElement.lang = 'pt-BR';
    d.documentElement.setAttribute('translate', 'no');
    d.documentElement.classList.add('notranslate');
    d.body.setAttribute('translate', 'no');
    d.body.classList.add('notranslate');
    if (!d.querySelector('meta[name="google"]')) {
        const m = d.createElement('meta'); m.name = 'google'; m.content = 'notranslate'; d.head.appendChild(m);
    }
    """)

# Na primeira execução cria o banco, as tabelas e as pastas das contas.
conectar().close()
garantir_pastas()
aplicar_padroes()   # só avalia o que ainda não foi avaliado; rápido

abertas = sum(registro.contar_abertas().values())
titulo_ocorrencias = f"Ocorrências ({abertas})" if abertas else "Ocorrências"
a_revisar = contar_por_classificacao()["Revisar"]
titulo_revisao = f"Revisão ({a_revisar})" if a_revisar else "Revisão"

paginas = {
    "Início": [
        st.Page("app/interface/paginas/inicio.py", title="Início", icon="🏠", default=True),
        st.Page("app/interface/paginas/dashboard.py", title="Dashboard", icon="📈"),
        st.Page("app/interface/paginas/caixinhas.py", title="Caixinhas", icon="💰"),
        st.Page("app/interface/paginas/meses.py", title="Meses", icon="🗓️"),
        st.Page("app/interface/paginas/relatorios.py", title="Relatórios", icon="🧾"),
    ],
    "Extratos": [
        st.Page("app/interface/paginas/importacao.py", title="Importação", icon="📥"),
        st.Page("app/interface/paginas/documentos.py", title="Documentos", icon="📄"),
        st.Page("app/interface/paginas/movimentacoes.py", title="Movimentações", icon="💸"),
    ],
    "Classificação": [
        st.Page("app/interface/paginas/revisao.py", title=titulo_revisao, icon="❓"),
        st.Page("app/interface/paginas/regras.py", title="Regras", icon="⚙️"),
    ],
    "Cadastros": [
        st.Page("app/interface/paginas/contas.py", title="Contas", icon="🏦"),
        st.Page("app/interface/paginas/categorias.py", title="Categorias", icon="🗂️"),
    ],
    "Sistema": [
        st.Page("app/interface/paginas/ocorrencias.py", title=titulo_ocorrencias, icon="📋"),
        st.Page("app/interface/paginas/configuracoes.py", title="Configurações", icon="⚙️"),
    ],
}

pagina = st.navigation(paginas)
if config.modo_demo():
    st.sidebar.info(
        "🧪 **Demonstração com dados fictícios.** Cada visitante trabalha numa cópia própria, "
        "que some ao fechar a aba. **Não envie extratos reais.**"
    )
try:
    pagina.run()
except Exception as erro:
    # Streamlit usa exceções internas para st.rerun()/st.stop(); essas passam direto.
    if type(erro).__module__.startswith("streamlit"):
        raise
    registro.registrar(
        "ERRO", "sistema", f"Erro inesperado na tela '{pagina.title}': {type(erro).__name__}",
        detalhe=traceback.format_exc(),
    )
    st.error(
        "Ocorreu um erro inesperado. Ele foi registrado em **Ocorrências** "
        "e no arquivo `logs/programa.log`."
    )
    st.exception(erro)
