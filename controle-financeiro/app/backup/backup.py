"""Backup do banco de dados.

Usa a API de backup do SQLite, que gera uma cópia consistente mesmo com o
programa aberto. Mantém os BACKUPS_MANTIDOS mais recentes.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from app import config
from app.banco.conexao import conectar

PREFIXO = config.PREFIXO_BACKUP


def fazer_backup(motivo: str = "manual") -> Path:
    config.pasta_backups().mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    motivo_limpo = "".join(c for c in motivo if c.isalnum() or c in "-_") or "manual"
    destino = config.pasta_backups() / f"{PREFIXO}{carimbo}_{motivo_limpo}.db"

    origem = conectar()
    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()

    limpar_antigos()

    from app.ocorrencias.registro import registrar  # import aqui evita ciclo

    registrar("INFO", "backup", f"Backup criado ({motivo_limpo})", arquivo=destino.name)
    return destino


def listar_backups() -> list[Path]:
    pasta = config.pasta_backups()
    if not pasta.exists():
        return []
    return sorted(pasta.glob(f"{PREFIXO}*.db"), reverse=True)


def limpar_antigos(manter: int = config.BACKUPS_MANTIDOS) -> None:
    for antigo in listar_backups()[manter:]:
        antigo.unlink(missing_ok=True)
