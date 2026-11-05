"""Log de ocorrências do programa.

Duas camadas:

1. **Ocorrências (no banco)** — o que você precisa ver. Aparecem na tela
   Ocorrências. Nunca são apagadas: quando resolvidas, ficam com data e
   descrição de como foram resolvidas.

2. **Log técnico (arquivo logs/programa.log)** — detalhes para depuração
   (erros do Python etc.). Todo registro de ocorrência também vai para lá.

Níveis:
    ERRO      Não consegui ler         (arquivo não lido; nada foi importado)
    CONFERIR  Tive dificuldade         (li, mas uma verificação falhou)
    REVISAR   Precisa da sua decisão   (li certo, mas a escolha é humana)
    INFO      Registro                 (o que aconteceu, sem ação necessária)
"""

import logging
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler

from app import config
from app.banco.conexao import conectar, transacao

NIVEIS = {
    "ERRO": ("🔴", "Não consegui ler"),
    "CONFERIR": ("🟠", "Tive dificuldade para confirmar"),
    "REVISAR": ("🟡", "Precisa da sua decisão"),
    "INFO": ("🔵", "Registro"),
}
NIVEIS_COM_ACAO = ("ERRO", "CONFERIR", "REVISAR")

ETAPAS = {
    "leitura": "Leitura do PDF",
    "conferencia_saldo": "Conferência de saldo",
    "duplicidade": "Duplicidade",
    "importacao": "Importação",
    "transferencia": "Transferências",
    "backup": "Backup",
    "fechamento": "Fechamento do mês",
    "sistema": "Sistema",
}


def nome_etapa(etapa: str) -> str:
    return ETAPAS.get(etapa, etapa)


def data_br(iso: str | None) -> str:
    """'2026-09-26 17:48:41' -> '26/09/2026 17:48'."""
    if not iso:
        return ""
    data, _, hora = iso.partition(" ")
    a, m, d = data.split("-")
    return f"{d}/{m}/{a} {hora[:5]}".strip()

_NIVEL_PARA_LOGGING = {
    "ERRO": logging.ERROR,
    "CONFERIR": logging.WARNING,
    "REVISAR": logging.WARNING,
    "INFO": logging.INFO,
}

_logger: logging.Logger | None = None


def logger_tecnico() -> logging.Logger:
    """Logger que grava em logs/programa.log (até 5 arquivos de 1 MB)."""
    global _logger
    destino = config.pasta_logs() / "programa.log"
    if _logger is not None and getattr(_logger, "_destino", None) == destino:
        return _logger
    config.pasta_logs().mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger("analisador")
    for h in list(lg.handlers):
        lg.removeHandler(h)
        h.close()
    handler = RotatingFileHandler(destino, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg._destino = destino  # type: ignore[attr-defined]
    _logger = lg
    return lg


@dataclass
class Ocorrencia:
    id: int
    criada_em: str
    nivel: str
    etapa: str
    mensagem: str
    detalhe: str | None
    conta_id: int | None
    arquivo: str | None
    documento_id: int | None
    pagina: int | None
    precisa_acao: bool
    resolvida_em: str | None
    resolucao: str | None
    conta_nome: str | None = None

    @property
    def aberta(self) -> bool:
        return self.precisa_acao and self.resolvida_em is None


def registrar(
    nivel: str,
    etapa: str,
    mensagem: str,
    *,
    detalhe: str | None = None,
    conta_id: int | None = None,
    arquivo: str | None = None,
    documento_id: int | None = None,
    pagina: int | None = None,
) -> int:
    """Registra uma ocorrência. Ex.:

    registrar("ERRO", "leitura", "Layout não reconhecido", arquivo="extrato.pdf", conta_id=1)
    """
    if nivel not in NIVEIS:
        raise ValueError(f"Nível inválido: {nivel}")
    with transacao() as conn:
        cur = conn.execute(
            "INSERT INTO ocorrencias (nivel, etapa, mensagem, detalhe, conta_id, arquivo,"
            " documento_id, pagina, precisa_acao) VALUES (?,?,?,?,?,?,?,?,?)",
            (nivel, etapa, mensagem, detalhe, conta_id, arquivo, documento_id, pagina,
             int(nivel in NIVEIS_COM_ACAO)),
        )
        novo_id = cur.lastrowid

    partes = [f"#{novo_id}", nivel, etapa, mensagem]
    if arquivo:
        partes.append(f"arquivo={arquivo}")
    if pagina:
        partes.append(f"pagina={pagina}")
    if detalhe:
        partes.append(f"detalhe={detalhe}")
    logger_tecnico().log(_NIVEL_PARA_LOGGING[nivel], " | ".join(partes))
    return novo_id


def _da_linha(linha) -> Ocorrencia:
    d = dict(linha)
    d["precisa_acao"] = bool(d["precisa_acao"])
    return Ocorrencia(**d)


def listar(
    *,
    somente_abertas: bool = False,
    niveis: list[str] | None = None,
    conta_id: int | None = None,
    limite: int = 500,
) -> list[Ocorrencia]:
    sql = (
        "SELECT o.*, c.nome AS conta_nome FROM ocorrencias o"
        " LEFT JOIN contas c ON c.id = o.conta_id WHERE 1=1"
    )
    params: list = []
    if somente_abertas:
        sql += " AND o.precisa_acao = 1 AND o.resolvida_em IS NULL"
    if niveis:
        sql += f" AND o.nivel IN ({','.join('?' * len(niveis))})"
        params += niveis
    if conta_id is not None:
        sql += " AND o.conta_id = ?"
        params.append(conta_id)
    sql += " ORDER BY o.id DESC LIMIT ?"
    params.append(limite)
    conn = conectar()
    try:
        return [_da_linha(l) for l in conn.execute(sql, params)]
    finally:
        conn.close()


def contar_abertas() -> dict[str, int]:
    conn = conectar()
    try:
        linhas = conn.execute(
            "SELECT nivel, COUNT(*) FROM ocorrencias"
            " WHERE precisa_acao = 1 AND resolvida_em IS NULL GROUP BY nivel"
        ).fetchall()
    finally:
        conn.close()
    contagem = {n: 0 for n in NIVEIS_COM_ACAO}
    contagem.update({n: q for n, q in linhas})
    return contagem


def resolver(ocorrencia_id: int, resolucao: str) -> None:
    """Marca como resolvida. A ocorrência continua no histórico."""
    resolucao = (resolucao or "").strip()
    if not resolucao:
        raise ValueError("Descreva como foi resolvida.")
    with transacao() as conn:
        linha = conn.execute(
            "SELECT precisa_acao, resolvida_em FROM ocorrencias WHERE id = ?", (ocorrencia_id,)
        ).fetchone()
        if linha is None:
            raise ValueError("Ocorrência não encontrada.")
        if not linha["precisa_acao"]:
            raise ValueError("Esta ocorrência é só um registro; não precisa ser resolvida.")
        if linha["resolvida_em"]:
            raise ValueError("Esta ocorrência já foi resolvida.")
        conn.execute(
            "UPDATE ocorrencias SET resolvida_em = datetime('now','localtime'), resolucao = ?"
            " WHERE id = ?",
            (resolucao, ocorrencia_id),
        )
    logger_tecnico().info(f"#{ocorrencia_id} resolvida | {resolucao}")
