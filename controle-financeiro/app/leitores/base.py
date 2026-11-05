"""Estruturas comuns a todos os leitores de extrato e as conferências.

Um leitor transforma um PDF em um `ExtratoLido`. Ele NUNCA grava nada:
quem decide importar é o serviço de importação, depois das conferências.
"""

import re
from dataclasses import dataclass, field
from datetime import date

MESES_ABREV = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}
MESES_EXTENSO = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "MARÇO": 3, "ABRIL": 4, "MAIO": 5,
    "JUNHO": 6, "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10,
    "NOVEMBRO": 11, "DEZEMBRO": 12,
}

RE_VALOR = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})*,\d{2}$")


class ErroLeitura(Exception):
    """O arquivo não pôde ser lido com segurança (vira ocorrência ERRO)."""

    def __init__(self, mensagem: str, detalhe: str | None = None, pagina: int | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.detalhe = detalhe
        self.pagina = pagina


def valor_centavos(texto: str) -> int:
    """'1.234,56' -> 123456 · '-9,99' -> -999 · '+ 10,00' -> 1000."""
    t = texto.replace(" ", "")
    if not RE_VALOR.match(t):
        raise ValueError(f"Valor inválido: {texto!r}")
    negativo = t.startswith("-")
    t = t.lstrip("+-").replace(".", "").replace(",", "")
    return -int(t) if negativo else int(t)


def formatar_centavos(c: int) -> str:
    """123456 -> '1.234,56' (com sinal se negativo)."""
    sinal = "-" if c < 0 else ""
    c = abs(c)
    inteiro = f"{c // 100:,}".replace(",", ".")
    return f"{sinal}{inteiro},{c % 100:02d}"


def data_abrev(dia: str, mes: str, ano: str) -> date:
    return date(int(ano), MESES_ABREV[mes.upper()], int(dia))


@dataclass
class ItemLido:
    data: date
    tipo: str                 # 'Entrada' | 'Saída'
    valor: int                # centavos, > 0
    operacao: str             # ex.: Transferência enviada pelo Pix
    contraparte: str          # ex.: FULANO - CPF - BANCO ...
    pagina: int
    ordem_no_dia: int         # 1, 2, 3... na ordem do extrato

    @property
    def descricao_original(self) -> str:
        return f"{self.operacao} {self.contraparte}".strip()


@dataclass
class GrupoLido:
    """Bloco 'Total de entradas' ou 'Total de saídas' de um dia."""
    data: date
    tipo: str
    total_declarado: int
    pagina: int
    soma_itens: int = 0
    qtd_itens: int = 0


@dataclass
class ExtratoLido:
    layout: str
    banco: str
    tipo_titular: str | None          # 'PF' | 'PJ' (pelo CPF/CNPJ do cabeçalho)
    agencia: str | None
    numero_conta: str | None
    periodo_inicio: date
    periodo_fim: date
    saldo_inicial: int
    saldo_final: int
    total_entradas: int
    total_saidas: int
    rendimento: int | None
    paginas: int
    itens: list[ItemLido] = field(default_factory=list)
    grupos: list[GrupoLido] = field(default_factory=list)
    saldos_dia: dict[date, tuple[int, int]] = field(default_factory=dict)  # data -> (saldo, página)
    nao_reconhecidas: list[tuple[int, str]] = field(default_factory=list)  # (página, texto)
    titular_texto: str = ""           # texto do cabeçalho (nome do titular etc.), para achar a conta


@dataclass
class Problema:
    """Uma conferência que falhou (vira ocorrência CONFERIR)."""
    mensagem: str
    detalhe: str
    pagina: int | None = None


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def conferir(ext: ExtratoLido) -> list[Problema]:
    """Todas as travas de segurança. Lista vazia = extrato confiável."""
    f = formatar_centavos
    problemas: list[Problema] = []

    # 1. Linhas que o leitor não soube interpretar
    for pagina, texto in ext.nao_reconhecidas:
        problemas.append(Problema(
            "Linha que não consegui interpretar",
            f"Página {pagina}: {texto}", pagina,
        ))

    # 2. Cada bloco 'Total de entradas/saídas' = soma dos itens dele
    for g in ext.grupos:
        if g.soma_itens != g.total_declarado:
            problemas.append(Problema(
                f"Total de {'entradas' if g.tipo == 'Entrada' else 'saídas'} do dia {_br(g.data)} não bate",
                f"Total informado no extrato: {f(g.total_declarado)}\n"
                f"Soma dos {g.qtd_itens} itens lidos: {f(g.soma_itens)}\n"
                f"Diferença: {f(g.total_declarado - g.soma_itens)}",
                g.pagina,
            ))

    # 3. Totais do resumo = soma dos itens
    entradas = sum(i.valor for i in ext.itens if i.tipo == "Entrada")
    saidas = sum(i.valor for i in ext.itens if i.tipo == "Saída")
    if entradas != ext.total_entradas:
        problemas.append(Problema(
            "Total de entradas do período não bate",
            f"Resumo do extrato: {f(ext.total_entradas)}\nSoma dos itens lidos: {f(entradas)}\n"
            f"Diferença: {f(ext.total_entradas - entradas)}", 1,
        ))
    if saidas != ext.total_saidas:
        problemas.append(Problema(
            "Total de saídas do período não bate",
            f"Resumo do extrato: {f(ext.total_saidas)}\nSoma dos itens lidos: {f(saidas)}\n"
            f"Diferença: {f(ext.total_saidas - saidas)}", 1,
        ))

    # 4. Saldo dia a dia: saldo anterior + entradas - saídas = saldo do dia
    saldo = ext.saldo_inicial
    por_dia: dict[date, list[ItemLido]] = {}
    for i in ext.itens:
        por_dia.setdefault(i.data, []).append(i)
    for dia in sorted(set(por_dia) | set(ext.saldos_dia)):
        itens = por_dia.get(dia, [])
        ent = sum(i.valor for i in itens if i.tipo == "Entrada")
        sai = sum(i.valor for i in itens if i.tipo == "Saída")
        calculado = saldo + ent - sai
        if dia in ext.saldos_dia:
            informado, pagina = ext.saldos_dia[dia]
            if calculado != informado:
                problemas.append(Problema(
                    f"Saldo do dia {_br(dia)} não bate",
                    f"Saldo anterior {f(saldo)} + entradas {f(ent)} - saídas {f(sai)} = {f(calculado)}\n"
                    f"Saldo do dia no extrato: {f(informado)}\n"
                    f"Diferença: {f(informado - calculado)}",
                    pagina,
                ))
            saldo = informado  # segue a partir do valor do banco para não repetir o erro
        else:
            saldo = calculado

    # 5. Saldo final do período
    calculado_final = ext.saldo_inicial + ext.total_entradas - ext.total_saidas
    candidatos = {calculado_final}
    if ext.rendimento:
        candidatos.add(calculado_final + ext.rendimento)
    if ext.saldo_final not in candidatos:
        problemas.append(Problema(
            "Saldo final do período não bate",
            f"Saldo inicial {f(ext.saldo_inicial)} + entradas {f(ext.total_entradas)} "
            f"- saídas {f(ext.total_saidas)} = {f(calculado_final)}\n"
            + (f"(com rendimento {f(ext.rendimento)}: {f(calculado_final + ext.rendimento)})\n"
               if ext.rendimento else "")
            + f"Saldo final no extrato: {f(ext.saldo_final)}", 1,
        ))

    # 6. Datas dentro do período
    fora = [i for i in ext.itens if not (ext.periodo_inicio <= i.data <= ext.periodo_fim)]
    if fora:
        problemas.append(Problema(
            "Movimentações com data fora do período do extrato",
            "\n".join(f"{_br(i.data)} {i.operacao} {f(i.valor)}" for i in fora[:20]),
            fora[0].pagina,
        ))

    # 7. Extrato com totais mas sem nenhum item lido
    if not ext.itens and (ext.total_entradas or ext.total_saidas):
        problemas.append(Problema(
            "Nenhuma movimentação encontrada, mas o resumo tem valores",
            f"Entradas {f(ext.total_entradas)} · Saídas {f(ext.total_saidas)}", 1,
        ))

    return problemas
