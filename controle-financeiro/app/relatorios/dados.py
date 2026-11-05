"""Dados dos relatórios. Tudo vem dos mesmos cálculos do Dashboard (app/analise)."""

from dataclasses import dataclass, field
from datetime import datetime

from app.analise import indicadores as ind
from app.banco.conexao import conectar
from app.fechamento import servico as fc
from app.importacao import consultas


def _linhas(sql, params=()):
    conn = conectar()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


@dataclass
class RelatorioMensal:
    mes: str
    rotulo: str
    oficial: bool
    fechado_em: str | None
    resumo: ind.ResumoMes
    anterior: ind.ResumoMes | None
    despesas: list[dict]          # por subcategoria: categoria, subcategoria, valor, qtd
    receitas: list[dict]
    investimentos: list[dict]
    variacao: list[ind.Variacao]
    pendentes: list[dict]         # movimentações em Revisar
    documentos: list[dict]
    movimentacoes: list[dict]
    gerado_em: str = field(default_factory=lambda: datetime.now().strftime("%d/%m/%Y %H:%M"))


def mensal(mes: str) -> RelatorioMensal:
    serie = {r.mes: r for r in ind.resumo_por_mes()}
    meses = ind.meses_com_dados()
    ant = meses[meses.index(mes) - 1] if mes in meses and meses.index(mes) > 0 else None
    inicio, fim = f"{mes}-01", ind.fim_do_mes(mes)
    info = fc.info(mes)
    return RelatorioMensal(
        mes=mes, rotulo=ind.rotulo_mes(mes), oficial=info["status"] == "Fechado",
        fechado_em=info.get("fechado_em"),
        resumo=serie.get(mes) or ind.ResumoMes(mes),
        anterior=serie.get(ant) if ant else None,
        despesas=ind.despesas_por_categoria(mes, natureza="despesa"),
        receitas=ind.despesas_por_categoria(mes, natureza="receita"),
        investimentos=ind.despesas_por_categoria(mes, natureza="investimento"),
        variacao=ind.variacao_categorias(mes, ant) if ant else [],
        pendentes=consultas.movimentacoes(inicio=inicio, fim=fim, classificacoes=["Revisar"]),
        documentos=_linhas(
            "SELECT d.*, c.nome AS conta_nome FROM documentos d JOIN contas c ON c.id = d.conta_id"
            " WHERE d.periodo_inicio <= ? AND d.periodo_fim >= ? ORDER BY c.nome, d.periodo_inicio",
            (fim, inicio)),
        movimentacoes=consultas.movimentacoes(inicio=inicio, fim=fim),
    )


@dataclass
class RelatorioAnual:
    ano: str
    meses: list[ind.ResumoMes]          # os 12 meses (zerados se não houver dados)
    com_dados: set[str]
    fechados: set[str]
    categorias: dict[str, dict[str, int]]   # categoria -> {mes: valor}
    movimentacoes: list[dict]
    gerado_em: str = field(default_factory=lambda: datetime.now().strftime("%d/%m/%Y %H:%M"))

    @property
    def totais(self) -> ind.ResumoMes:
        t = ind.ResumoMes(f"{self.ano}-00")
        for r in self.meses:
            t.receita += r.receita
            t.despesas += r.despesas
            t.investimentos += r.investimentos
            t.neutro_entradas += r.neutro_entradas
            t.neutro_saidas += r.neutro_saidas
            t.revisar_qtd += r.revisar_qtd
        return t

    @property
    def acumulado(self) -> list[int]:
        total, lista = 0, []
        for r in self.meses:
            total += r.resultado
            lista.append(total)
        return lista


def anos_com_dados() -> list[str]:
    return sorted({m[:4] for m in ind.meses_com_dados()})


def anual(ano: str) -> RelatorioAnual:
    serie = {r.mes: r for r in ind.resumo_por_mes() if r.mes.startswith(ano)}
    todos = [f"{ano}-{m:02d}" for m in range(1, 13)]
    categorias: dict[str, dict[str, int]] = {}
    for m in serie:
        for cat, v in ind.por_categoria(m).items():
            categorias.setdefault(cat, {})[m] = v
    return RelatorioAnual(
        ano=ano, meses=[serie.get(m) or ind.ResumoMes(m) for m in todos], com_dados=set(serie),
        fechados={m for m in fc.meses_fechados() if m.startswith(ano)},
        categorias=dict(sorted(categorias.items(), key=lambda kv: -sum(kv[1].values()))),
        movimentacoes=consultas.movimentacoes(inicio=f"{ano}-01-01", fim=f"{ano}-12-31"),
    )
