"""Fechamento mensal.

Aberto   → pode importar, classificar, criar regras, revisar (números preliminares).
Fechado  → resultado OFICIAL daquele mês naquele momento. Nada muda nas movimentações
           do mês (classificação, regras, importação de movimentações novas) até reabrir.

Fechar  : só com o checklist sem bloqueios. Grava um RETRATO dos números (JSON) e faz backup.
Reabrir : exige motivo. O retrato anterior fica no histórico; ao fechar de novo, a tela
          compara o retrato novo com o anterior (o que mudou por causa da reabertura).
"""

import calendar
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from app.banco.conexao import conectar, transacao


class ErroFechamento(ValueError):
    pass


def _linhas(sql, params=()):
    conn = conectar()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


# ------------------------------------------------------------------ situação

def status(mes: str) -> str:
    r = _linhas("SELECT status FROM meses WHERE mes = ?", (mes,))
    return r[0]["status"] if r else "Aberto"


def meses_fechados() -> set[str]:
    return {r["mes"] for r in _linhas("SELECT mes FROM meses WHERE status = 'Fechado'")}


def mes_de(data_iso: str) -> str:
    return str(data_iso)[:7]


def verificar_aberto(meses: set[str] | list[str], acao: str = "alterar") -> None:
    """Levanta ErroFechamento se algum dos meses estiver fechado."""
    from app.analise.indicadores import rotulo_mes
    fechados = sorted(set(meses) & meses_fechados())
    if fechados:
        nomes = ", ".join(rotulo_mes(m) for m in fechados)
        raise ErroFechamento(
            f"Não é possível {acao}: {nomes} está fechado. Reabra o mês na tela Meses (com o motivo) antes."
        )


def info(mes: str) -> dict:
    r = _linhas("SELECT * FROM meses WHERE mes = ?", (mes,))
    return r[0] if r else {"mes": mes, "status": "Aberto", "fechado_em": None, "observacao": None}


# ------------------------------------------------------------------ checklist

@dataclass
class ItemChecklist:
    texto: str
    ok: bool
    bloqueia: bool          # se não estiver ok, impede fechar
    detalhe: str = ""

    @property
    def icone(self) -> str:
        return "✅" if self.ok else ("❌" if self.bloqueia else "⚠️")


def _dias_cobertos(conta_id: int, mes: str) -> set[date]:
    a, m = map(int, mes.split("-"))
    ini, fim = date(a, m, 1), date(a, m, calendar.monthrange(a, m)[1])
    dias: set[date] = set()
    for d in _linhas(
        "SELECT periodo_inicio, periodo_fim FROM documentos WHERE conta_id = ?"
        " AND periodo_inicio <= ? AND periodo_fim >= ?", (conta_id, fim.isoformat(), ini.isoformat()),
    ):
        di = max(ini, date.fromisoformat(d["periodo_inicio"]))
        df = min(fim, date.fromisoformat(d["periodo_fim"]))
        while di <= df:
            dias.add(di)
            di += timedelta(days=1)
    return dias


def _faixas(dias: list[date]) -> str:
    """[1,2,3,7,8] (datas) -> '01–03/08, 07–08/08'."""
    if not dias:
        return ""
    partes, ini, ant = [], dias[0], dias[0]
    for d in dias[1:] + [None]:
        if d is not None and d == ant + timedelta(days=1):
            ant = d
            continue
        partes.append(ini.strftime("%d/%m") if ini == ant else f"{ini:%d}–{ant:%d/%m}")
        if d is not None:
            ini = ant = d
    return ", ".join(partes)


def checklist(mes: str) -> list[ItemChecklist]:
    from app.analise.indicadores import fim_do_mes
    itens: list[ItemChecklist] = []
    ini, fim = f"{mes}-01", fim_do_mes(mes)

    total = _linhas("SELECT COUNT(*) n FROM movimentacoes WHERE status='ativa' AND data BETWEEN ? AND ?",
                    (ini, fim))[0]["n"]
    itens.append(ItemChecklist("Há movimentações importadas no mês", total > 0, True,
                               f"{total} movimentação(ões)"))

    rev = _linhas("SELECT COUNT(*) n, COALESCE(SUM(valor),0) v FROM movimentacoes WHERE status='ativa'"
                  " AND classificacao='Revisar' AND data BETWEEN ? AND ?", (ini, fim))[0]
    itens.append(ItemChecklist("Nenhuma movimentação em Revisão", rev["n"] == 0, True,
                               "" if rev["n"] == 0 else f"{rev['n']} pendente(s) — classifique na tela Revisão"))

    # extratos cobrindo o mês inteiro, para cada conta que teve movimento no mês
    a, m = map(int, mes.split("-"))
    todos = [date(a, m, d) for d in range(1, calendar.monthrange(a, m)[1] + 1)]
    contas_mov = _linhas(
        "SELECT DISTINCT c.id, c.nome FROM movimentacoes mv JOIN contas c ON c.id = mv.conta_id"
        " WHERE mv.status='ativa' AND mv.data BETWEEN ? AND ?", (ini, fim))
    faltas = []
    for c in contas_mov:
        faltando = [d for d in todos if d not in _dias_cobertos(c["id"], mes)]
        if faltando:
            faltas.append(f"{c['nome']}: faltam {_faixas(faltando)}")
    itens.append(ItemChecklist("Extratos cobrem o mês inteiro", not faltas, True,
                               "; ".join(faltas) or "Todos os dias do mês estão em algum extrato conferido"))

    # contas ativas sem nenhum extrato no mês (aviso, não bloqueia: ex. conta sem uso)
    sem = _linhas(
        "SELECT nome FROM contas c WHERE ativa = 1 AND NOT EXISTS (SELECT 1 FROM documentos d WHERE"
        " d.conta_id = c.id AND d.periodo_inicio <= ? AND d.periodo_fim >= ?)", (fim, ini))
    itens.append(ItemChecklist("Todas as contas ativas têm extrato do mês", not sem, False,
                               ("Sem extrato: " + ", ".join(r["nome"] for r in sem) +
                                ". Se a conta não teve movimento, pode fechar assim mesmo.") if sem else ""))

    ab = _linhas("SELECT COUNT(*) n FROM ocorrencias WHERE precisa_acao = 1 AND resolvida_em IS NULL"
                 " AND nivel IN ('ERRO','CONFERIR')")[0]["n"]
    itens.append(ItemChecklist("Nenhuma ocorrência de erro/conferência aberta", ab == 0, False,
                               "" if ab == 0 else f"{ab} aberta(s) em Ocorrências — confira se afetam este mês"))
    return itens


def pode_fechar(itens: list[ItemChecklist]) -> bool:
    return all(i.ok or not i.bloqueia for i in itens)


# ------------------------------------------------------------------ retrato

def retrato(mes: str) -> dict:
    from app.analise import indicadores as ind
    r = next((x for x in ind.resumo_por_mes() if x.mes == mes), ind.ResumoMes(mes))
    return {
        "receita": r.receita, "despesas": r.despesas, "resultado": r.resultado,
        "margem": None if r.margem is None else round(r.margem, 2),
        "investimentos": r.investimentos, "resgates_rdb": r.neutro_entradas, "aplicacoes_rdb": r.neutro_saidas,
        "saldo": r.saldo,
        "movimentacoes": _linhas("SELECT COUNT(*) n FROM movimentacoes WHERE status='ativa' AND substr(data,1,7)=?",
                                 (mes,))[0]["n"],
        "despesas_por_categoria": ind.por_categoria(mes),
        "receitas_por_categoria": ind.por_categoria(mes, natureza="receita"),
    }


def comparar(anterior: dict, novo: dict) -> list[tuple[str, int | float | None, int | float | None]]:
    """Lista (item, antes, depois) só do que mudou."""
    mudou = []
    for k in ("receita", "despesas", "resultado", "investimentos", "resgates_rdb", "aplicacoes_rdb", "saldo",
              "movimentacoes"):
        if anterior.get(k) != novo.get(k):
            mudou.append((k, anterior.get(k), novo.get(k)))
    for grupo in ("despesas_por_categoria", "receitas_por_categoria"):
        a, b = anterior.get(grupo, {}), novo.get(grupo, {})
        for cat in sorted(set(a) | set(b)):
            if a.get(cat, 0) != b.get(cat, 0):
                mudou.append((f"{'Despesa' if grupo.startswith('desp') else 'Receita'}: {cat}",
                              a.get(cat, 0), b.get(cat, 0)))
    return mudou


# ------------------------------------------------------------------ ações

def fechar(mes: str, observacao: str | None = None) -> int:
    if status(mes) == "Fechado":
        raise ErroFechamento("Este mês já está fechado.")
    itens = checklist(mes)
    if not pode_fechar(itens):
        faltam = [i.texto for i in itens if not i.ok and i.bloqueia]
        raise ErroFechamento("Ainda não dá para fechar: " + "; ".join(faltam))

    from app.backup.backup import fazer_backup
    fazer_backup(f"fechamento-{mes}")
    foto = retrato(mes)
    with transacao() as conn:
        conn.execute(
            "INSERT INTO meses (mes, status, fechado_em, observacao) VALUES (?, 'Fechado', datetime('now','localtime'), ?)"
            " ON CONFLICT(mes) DO UPDATE SET status='Fechado', fechado_em=datetime('now','localtime'),"
            " observacao=excluded.observacao", (mes, (observacao or "").strip() or None),
        )
        fid = conn.execute(
            "INSERT INTO fechamentos (mes, acao, texto, retrato, checklist) VALUES (?, 'fechamento', ?, ?, ?)",
            (mes, (observacao or "").strip() or None, json.dumps(foto, ensure_ascii=False),
             json.dumps([asdict(i) for i in itens], ensure_ascii=False)),
        ).lastrowid

    from app.analise.indicadores import rotulo_mes
    from app.interface.formato import reais
    from app.ocorrencias.registro import registrar
    registrar("INFO", "fechamento", f"{rotulo_mes(mes)} fechado",
              detalhe=f"Receita {reais(foto['receita'])} · Despesas {reais(foto['despesas'])} · "
                      f"Resultado {reais(foto['resultado'])} · Investimentos {reais(foto['investimentos'])}")
    return fid


def reabrir(mes: str, motivo: str) -> int:
    motivo = (motivo or "").strip()
    if status(mes) != "Fechado":
        raise ErroFechamento("Este mês não está fechado.")
    if len(motivo) < 5:
        raise ErroFechamento("Descreva o motivo da reabertura.")
    with transacao() as conn:
        conn.execute("UPDATE meses SET status = 'Aberto' WHERE mes = ?", (mes,))
        fid = conn.execute(
            "INSERT INTO fechamentos (mes, acao, texto) VALUES (?, 'reabertura', ?)", (mes, motivo),
        ).lastrowid
    from app.analise.indicadores import rotulo_mes
    from app.ocorrencias.registro import registrar
    registrar("INFO", "fechamento", f"{rotulo_mes(mes)} reaberto", detalhe=f"Motivo: {motivo}")
    return fid


def historico(mes: str) -> list[dict]:
    lista = _linhas("SELECT * FROM fechamentos WHERE mes = ? ORDER BY id", (mes,))
    for h in lista:
        h["retrato"] = json.loads(h["retrato"]) if h["retrato"] else None
        h["checklist"] = json.loads(h["checklist"]) if h["checklist"] else None
    return lista


def ultimos_dois_retratos(mes: str) -> tuple[dict | None, dict | None]:
    fotos = [h["retrato"] for h in historico(mes) if h["acao"] == "fechamento"]
    if len(fotos) < 2:
        return None, (fotos[-1] if fotos else None)
    return fotos[-2], fotos[-1]
