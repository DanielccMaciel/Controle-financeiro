"""Leitura e gravação de contas bancárias.

Todas as contas são da mesma pessoa (não há PJ/PF). Pode haver quantas quiser.
Contas nunca são apagadas: para deixar de usar, desative (o histórico fica).
"""

import re
from dataclasses import dataclass

from app import config
from app.banco.conexao import conectar, transacao

BANCOS_CONHECIDOS = ("Nubank", "Sicoob")


class ErroValidacao(ValueError):
    pass


@dataclass
class Conta:
    nome: str
    titular: str
    banco: str
    pasta: str
    agencia: str | None = None
    numero_conta: str | None = None
    observacoes: str | None = None
    ativa: bool = True
    id: int | None = None
    criada_em: str | None = None


def _da_linha(linha) -> Conta:
    d = dict(linha)
    d["ativa"] = bool(d["ativa"])
    return Conta(**d)


def listar(somente_ativas: bool = False) -> list[Conta]:
    sql = "SELECT * FROM contas"
    if somente_ativas:
        sql += " WHERE ativa = 1"
    sql += " ORDER BY id"
    conn = conectar()
    try:
        return [_da_linha(l) for l in conn.execute(sql)]
    finally:
        conn.close()


def obter(conta_id: int) -> Conta | None:
    conn = conectar()
    try:
        linha = conn.execute("SELECT * FROM contas WHERE id = ?", (conta_id,)).fetchone()
        return _da_linha(linha) if linha else None
    finally:
        conn.close()


def _limpar(texto: str | None) -> str | None:
    if texto is None:
        return None
    texto = texto.strip()
    return texto or None


def validar(conta: Conta) -> Conta:
    conta.nome = _limpar(conta.nome)
    conta.titular = _limpar(conta.titular)
    conta.banco = _limpar(conta.banco)
    conta.pasta = _limpar(conta.pasta)
    conta.agencia = _limpar(conta.agencia)
    conta.numero_conta = _limpar(conta.numero_conta)
    conta.observacoes = _limpar(conta.observacoes)

    for campo in ("nome", "titular", "banco", "pasta"):
        if not getattr(conta, campo):
            raise ErroValidacao(f"O campo '{campo}' é obrigatório.")
    if conta.pasta.startswith(".") or not re.fullmatch(r"[A-Za-z0-9À-ÿ _.-]+", conta.pasta):
        raise ErroValidacao(
            "Nome da pasta só pode ter letras, números, espaço, hífen, ponto e sublinhado."
        )
    return conta


def _checar_duplicados(conn, conta: Conta) -> None:
    for campo, rotulo in (("nome", "nome"), ("pasta", "pasta")):
        linha = conn.execute(
            f"SELECT id FROM contas WHERE lower({campo}) = lower(?) AND id IS NOT ?",
            (getattr(conta, campo), conta.id),
        ).fetchone()
        if linha:
            raise ErroValidacao(f"Já existe uma conta com esse {rotulo}.")


def criar_pasta_extratos(conta: Conta) -> None:
    (config.pasta_extratos() / conta.pasta).mkdir(parents=True, exist_ok=True)


def inserir(conta: Conta) -> int:
    conta = validar(conta)
    with transacao() as conn:
        _checar_duplicados(conn, conta)
        cur = conn.execute(
            "INSERT INTO contas (nome, titular, banco, agencia, numero_conta,"
            " pasta, ativa, observacoes) VALUES (?,?,?,?,?,?,?,?)",
            (conta.nome, conta.titular, conta.banco, conta.agencia,
             conta.numero_conta, conta.pasta, int(conta.ativa), conta.observacoes),
        )
        conta.id = cur.lastrowid
    criar_pasta_extratos(conta)
    return conta.id


def atualizar(conta: Conta) -> None:
    if conta.id is None:
        raise ErroValidacao("Conta sem ID.")
    conta = validar(conta)
    with transacao() as conn:
        _checar_duplicados(conn, conta)
        conn.execute(
            "UPDATE contas SET nome=?, titular=?, banco=?, agencia=?,"
            " numero_conta=?, pasta=?, ativa=?, observacoes=? WHERE id=?",
            (conta.nome, conta.titular, conta.banco, conta.agencia,
             conta.numero_conta, conta.pasta, int(conta.ativa), conta.observacoes,
             conta.id),
        )
    criar_pasta_extratos(conta)


def garantir_pastas() -> None:
    """Cria em extratos/ a pasta de cada conta que ainda não tem."""
    for conta in listar():
        criar_pasta_extratos(conta)
