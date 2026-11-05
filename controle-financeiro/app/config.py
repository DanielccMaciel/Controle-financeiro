"""Caminhos e configurações do programa.

Todos os caminhos são relativos à pasta raiz do projeto, para o programa
funcionar em qualquer computador ou HD (a letra da unidade pode mudar).
Para testes, a raiz pode ser trocada pela variável de ambiente ANALISADOR_RAIZ.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

# De quem é este programa. Aparece no título das telas e nos relatórios.
# Para personalizar sem mexer no código: variável de ambiente FINANCAS_NOME_PROGRAMA
# (ou FINANCAS_DONO, que gera "Controle Financeiro de <dono>").
DONO = os.environ.get("FINANCAS_DONO", "").strip()
NOME_PROGRAMA = (os.environ.get("FINANCAS_NOME_PROGRAMA", "").strip()
                 or (f"Controle Financeiro de {DONO}" if DONO else "Controle Financeiro Pessoal"))

RAIZ_PADRAO = Path(__file__).resolve().parent.parent

# Modo demonstração (site público): ligado pelo ponto de entrada `demo.py`.
# Cada visitante recebe uma CÓPIA PRÓPRIA da base fictícia de `demo_base/`, numa pasta
# temporária; nada do que ele fizer afeta outros visitantes nem o disco do projeto.
PASTA_BASE_DEMO = RAIZ_PADRAO / "demo_base"
_PREFIXO_TMP_DEMO = "financas_demo_"
_VALIDADE_TMP_DEMO = 3 * 3600   # segundos; pastas mais velhas são apagadas


def modo_demo() -> bool:
    return os.environ.get("FINANCAS_DEMO") == "1"


def _limpar_demos_antigas() -> None:
    agora = time.time()
    for pasta in Path(tempfile.gettempdir()).glob(_PREFIXO_TMP_DEMO + "*"):
        try:
            if agora - pasta.stat().st_mtime > _VALIDADE_TMP_DEMO:
                shutil.rmtree(pasta, ignore_errors=True)
        except OSError:
            pass


def _nova_raiz_demo() -> Path:
    _limpar_demos_antigas()
    destino = Path(tempfile.mkdtemp(prefix=_PREFIXO_TMP_DEMO))
    shutil.copytree(PASTA_BASE_DEMO, destino, dirs_exist_ok=True)
    for sub in ("dados", "extratos", "backups", "logs"):
        (destino / sub).mkdir(exist_ok=True)
    return destino


def _raiz_demo() -> Path:
    """Uma pasta por sessão do navegador (guardada no st.session_state)."""
    try:
        import streamlit as st
        atual = st.session_state.get("_raiz_demo")
        if not atual or not Path(atual).exists():
            atual = str(_nova_raiz_demo())
            st.session_state["_raiz_demo"] = atual
        return Path(atual)
    except Exception:
        # fora de uma sessão do Streamlit (ex.: script de linha de comando)
        return _nova_raiz_demo()


def raiz() -> Path:
    if os.environ.get("ANALISADOR_RAIZ"):
        return Path(os.environ["ANALISADOR_RAIZ"])
    if modo_demo():
        return _raiz_demo()
    return RAIZ_PADRAO


def pasta_dados() -> Path:
    return raiz() / "dados"


def pasta_extratos() -> Path:
    return raiz() / "extratos"


def pasta_backups() -> Path:
    return raiz() / "backups"


def pasta_logs() -> Path:
    return raiz() / "logs"


def caminho_banco() -> Path:
    return pasta_dados() / "financas.db"


# Os backups em backups/ começam com este prefixo.
PREFIXO_BACKUP = "financas_"
# Quantos backups manter na pasta backups/ (os mais antigos são removidos).
BACKUPS_MANTIDOS = 30
