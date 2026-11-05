"""Conexão com o SQLite e criação/atualização automática do banco."""

import sqlite3
from contextlib import contextmanager

from app import config
from app.banco.migracoes import MIGRACOES


def conectar() -> sqlite3.Connection:
    """Abre o banco (criando o arquivo e as tabelas se ainda não existirem)."""
    config.pasta_dados().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.caminho_banco())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    aplicar_migracoes(conn)
    return conn


@contextmanager
def transacao():
    """Uso: `with transacao() as conn:` — confirma no fim ou desfaz se der erro."""
    conn = conectar()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def versao_atual(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_versao ("
        " versao INTEGER PRIMARY KEY,"
        " descricao TEXT NOT NULL,"
        " aplicada_em TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
    )
    linha = conn.execute("SELECT MAX(versao) FROM schema_versao").fetchone()
    return linha[0] or 0


def aplicar_migracoes(conn: sqlite3.Connection) -> None:
    """Aplica, em ordem, as migrações que o banco ainda não tem."""
    atual = versao_atual(conn)
    pendentes = [m for m in MIGRACOES if m[0] > atual]
    if pendentes and atual > 0:
        _backup_antes_de_atualizar(conn, atual, pendentes[-1][0])
    for versao, descricao, sql in MIGRACOES:
        if versao <= atual:
            continue
        try:
            conn.executescript("BEGIN;" + sql)
            conn.execute(
                "INSERT INTO schema_versao (versao, descricao) VALUES (?, ?)",
                (versao, descricao),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _backup_antes_de_atualizar(conn: sqlite3.Connection, de: int, para: int) -> None:
    """Cópia do banco antes de mudar a estrutura (quando o programa é atualizado)."""
    from datetime import datetime

    try:
        config.pasta_backups().mkdir(parents=True, exist_ok=True)
        carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        destino = config.pasta_backups() / f"{config.PREFIXO_BACKUP}{carimbo}_antes-atualizacao-v{de}-para-v{para}.db"
        copia = sqlite3.connect(destino)
        try:
            conn.backup(copia)
        finally:
            copia.close()
    except Exception:
        pass   # o backup é uma proteção extra; as migrações só acrescentam tabelas/colunas
