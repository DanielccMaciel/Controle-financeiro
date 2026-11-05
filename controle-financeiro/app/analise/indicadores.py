"""Indicadores financeiros. Todos os cálculos são determinísticos e em centavos.

Fórmulas (só movimentações CLASSIFICADAS; o que está em Revisar é contado à parte):
    Receita       = entradas de categorias 'receita'  − saídas de categorias 'receita'  (estornos)
    Despesas      = saídas de categorias 'despesa'    − entradas de categorias 'despesa' (reembolsos)
    Resultado     = Receita − Despesas                       (quanto sobrou no mês)
    Margem        = Resultado / Receita × 100                (% da renda que sobrou; vazia se Receita ≤ 0)
    Investimentos = saídas 'investimento' − entradas 'investimento'   (fora do resultado)
    Neutro        = Resgate/Aplicação RDB, entre contas      (não entra em nada; só informativo)
    Saldo         = soma, por conta, do último "Saldo do dia" informado pelo banco até o fim do mês
                    (saldo em conta corrente; o que está guardado no RDB não aparece no extrato)
"""

import calendar
from dataclasses import dataclass, field

from app.banco.conexao import conectar

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rotulo_mes(mes: str) -> str:
    """'2026-08' -> 'ago/2026'."""
    a, m = mes.split("-")
    return f"{MESES[int(m) - 1]}/{a}"


def fim_do_mes(mes: str) -> str:
    a, m = map(int, mes.split("-"))
    return f"{mes}-{calendar.monthrange(a, m)[1]:02d}"


def _linhas(sql: str, params=()) -> list[dict]:
    conn = conectar()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def meses_com_dados() -> list[str]:
    return [r["mes"] for r in _linhas(
        "SELECT DISTINCT substr(data, 1, 7) AS mes FROM movimentacoes WHERE status = 'ativa' ORDER BY mes"
    )]


@dataclass
class ResumoMes:
    mes: str
    receita: int = 0
    despesas: int = 0
    investimentos: int = 0
    neutro_entradas: int = 0
    neutro_saidas: int = 0
    revisar_qtd: int = 0
    revisar_valor: int = 0
    saldo: int | None = None
    contas_com_saldo: list[str] = field(default_factory=list)

    @property
    def resultado(self) -> int:
        return self.receita - self.despesas

    @property
    def margem(self) -> float | None:
        return self.resultado / self.receita * 100 if self.receita > 0 else None

    @property
    def rotulo(self) -> str:
        return rotulo_mes(self.mes)


def _filtro_contas(contas: list[int] | None, alias: str = "m") -> tuple[str, list]:
    if not contas:
        return "", []
    return f" AND {alias}.conta_id IN ({','.join('?' * len(contas))})", list(contas)


def resumo_por_mes(contas: list[int] | None = None) -> list[ResumoMes]:
    """Um ResumoMes por mês com movimentações, em ordem cronológica."""
    filtro, params = _filtro_contas(contas)
    linhas = _linhas(
        "SELECT substr(m.data, 1, 7) AS mes, m.classificacao, m.tipo, cat.natureza,"
        " COUNT(*) AS qtd, SUM(m.valor) AS total"
        " FROM movimentacoes m"
        " LEFT JOIN subcategorias s ON s.id = m.subcategoria_id"
        " LEFT JOIN categorias cat ON cat.id = s.categoria_id"
        " WHERE m.status = 'ativa'" + filtro +
        " GROUP BY mes, m.classificacao, m.tipo, cat.natureza ORDER BY mes", params,
    )
    meses: dict[str, ResumoMes] = {}
    for r in linhas:
        rm = meses.setdefault(r["mes"], ResumoMes(r["mes"]))
        entrada = r["tipo"] == "Entrada"
        if r["classificacao"] == "Revisar":
            rm.revisar_qtd += r["qtd"]
            rm.revisar_valor += r["total"]
        elif r["natureza"] == "receita":
            rm.receita += r["total"] if entrada else -r["total"]
        elif r["natureza"] == "despesa":
            rm.despesas += -r["total"] if entrada else r["total"]
        elif r["natureza"] == "investimento":
            rm.investimentos += -r["total"] if entrada else r["total"]
        elif r["natureza"] == "neutro":
            if entrada:
                rm.neutro_entradas += r["total"]
            else:
                rm.neutro_saidas += r["total"]
    for rm in meses.values():
        rm.saldo, rm.contas_com_saldo = saldo_no_fim_do_mes(rm.mes, contas)
    return [meses[k] for k in sorted(meses)]


def saldo_no_fim_do_mes(mes: str, contas: list[int] | None = None) -> tuple[int | None, list[str]]:
    """Último saldo do dia informado pelo banco, até o fim do mês, somado por conta."""
    filtro, params = _filtro_contas(contas, "sd")
    linhas = _linhas(
        "SELECT c.nome, sd.saldo FROM saldos_diarios sd JOIN contas c ON c.id = sd.conta_id"
        " WHERE sd.data = (SELECT MAX(s2.data) FROM saldos_diarios s2"
        "                  WHERE s2.conta_id = sd.conta_id AND s2.data <= ?)" + filtro +
        " GROUP BY sd.conta_id", [fim_do_mes(mes), *params],
    )
    if not linhas:
        return None, []
    return sum(r["saldo"] for r in linhas), [r["nome"] for r in linhas]


def despesas_por_categoria(mes: str, contas: list[int] | None = None,
                           natureza: str = "despesa") -> list[dict]:
    """[{categoria_id, categoria, subcategoria_id, subcategoria, valor, qtd}] do mês (líquido)."""
    filtro, params = _filtro_contas(contas)
    sinal = ("CASE WHEN m.tipo = 'Saída' THEN m.valor ELSE -m.valor END" if natureza != "receita"
             else "CASE WHEN m.tipo = 'Entrada' THEN m.valor ELSE -m.valor END")
    return _linhas(
        f"SELECT cat.id AS categoria_id, cat.nome AS categoria, s.id AS subcategoria_id,"
        f" s.nome AS subcategoria, SUM({sinal}) AS valor, COUNT(*) AS qtd"
        " FROM movimentacoes m JOIN subcategorias s ON s.id = m.subcategoria_id"
        " JOIN categorias cat ON cat.id = s.categoria_id"
        " WHERE m.status = 'ativa' AND m.classificacao = 'Classificada' AND cat.natureza = ?"
        " AND substr(m.data, 1, 7) = ?" + filtro +
        " GROUP BY cat.id, s.id ORDER BY valor DESC", [natureza, mes, *params],
    )


def por_categoria(mes: str, contas: list[int] | None = None, natureza: str = "despesa") -> dict[str, int]:
    total: dict[str, int] = {}
    for r in despesas_por_categoria(mes, contas, natureza):
        total[r["categoria"]] = total.get(r["categoria"], 0) + r["valor"]
    return total


@dataclass
class Variacao:
    categoria: str
    anterior: int
    atual: int

    @property
    def diferenca(self) -> int:
        return self.atual - self.anterior

    @property
    def percentual(self) -> float | None:
        return self.diferenca / self.anterior * 100 if self.anterior > 0 else None


def variacao_categorias(mes: str, mes_anterior: str | None, contas: list[int] | None = None) -> list[Variacao]:
    atual = por_categoria(mes, contas)
    anterior = por_categoria(mes_anterior, contas) if mes_anterior else {}
    nomes = set(atual) | set(anterior)
    lista = [Variacao(n, anterior.get(n, 0), atual.get(n, 0)) for n in nomes]
    return sorted(lista, key=lambda v: -max(v.atual, v.anterior))


def movimentacoes_da_subcategoria(mes: str, subcategoria_id: int, contas: list[int] | None = None) -> list[dict]:
    from app.importacao import consultas
    inicio, fim = f"{mes}-01", fim_do_mes(mes)
    return [m for m in consultas.movimentacoes(contas=contas, inicio=inicio, fim=fim, classificacoes=["Classificada"])
            if m["subcategoria_id"] == subcategoria_id]
