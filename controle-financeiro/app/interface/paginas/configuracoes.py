from datetime import datetime

import streamlit as st

from app import config
from app.backup import backup

st.title("⚙️ Configurações")

st.subheader("Backup do banco de dados")
st.caption(
    f"Os backups ficam em `backups/`. São mantidos os {config.BACKUPS_MANTIDOS} mais recentes. "
    "Um backup automático é feito antes de cada importação e de cada fechamento de mês."
)

if st.button("💾 Fazer backup agora", type="primary"):
    destino = backup.fazer_backup("manual")
    st.success(f"Backup criado: {destino.name}")

lista = backup.listar_backups()
if lista:
    st.write(f"**{len(lista)} backup(s):**")
    for arq in lista:
        tamanho_kb = arq.stat().st_size / 1024
        quando = datetime.fromtimestamp(arq.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        st.text(f"{arq.name}   ·   {quando}   ·   {tamanho_kb:.0f} KB")
else:
    st.info("Nenhum backup ainda.")

st.divider()
st.subheader("Caminhos")
st.code(
    f"Raiz:     {config.raiz()}\n"
    f"Banco:    {config.caminho_banco()}\n"
    f"Extratos: {config.pasta_extratos()}\n"
    f"Backups:  {config.pasta_backups()}"
)
