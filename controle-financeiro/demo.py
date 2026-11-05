"""Ponto de entrada da DEMONSTRAÇÃO pública (dados 100% fictícios).

No Streamlit Community Cloud, use este arquivo como "Main file path".
Localmente:  streamlit run demo.py
"""

import os
import runpy
from pathlib import Path

os.environ["FINANCAS_DEMO"] = "1"
os.environ.setdefault("FINANCAS_NOME_PROGRAMA", "Controle Financeiro Pessoal (demo)")

runpy.run_path(str(Path(__file__).resolve().parent / "main.py"), run_name="__main__")
