"""Gera "Extratos de Rendimentos" FALSOS das Caixinhas do Nubank (só para testes).

Posições e tamanhos de fonte imitam o layout real do PDF.
"""

from dataclasses import dataclass, field
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from tests.gerador_nubank import MESES

ALTURA = A4[1]
MESES_MIN = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]


def rs(c: int) -> str:
    return "R$" + f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d}"


@dataclass
class MovC:
    data: date
    tipo: str        # Resgate | Aplicação
    bruto: int
    ir: int = 0
    iof: int = 0
    liquido_delta: int = 0     # erro de propósito


@dataclass
class Caixinha:
    nome: str
    saldo_final: int
    movs: list[MovC]
    rendimento: int | None      # linha "Rendimentos de <mês>" no último dia do período
    produto: str = "RDB Resgate Imediato Rendimento 30 dias"


@dataclass
class AjustesC:
    linha_estranha: str | None = None
    sem_marca: bool = False


def gerar(caminho, caixinhas: list[Caixinha], *, inicio: date, fim: date, titular="PF",
          nome_titular="DANIEL TESTE DA SILVA",
          ajustes: AjustesC | None = None, linhas_por_pagina: int = 18):
    aj = ajustes or AjustesC()
    c = canvas.Canvas(str(caminho), pagesize=A4)

    def txt(x, top, s, size):
        c.setFont("Helvetica", size)
        c.drawString(x, ALTURA - top - size * 0.8, s)

    def cabecalho():
        txt(81, 31.1, "Extrato de Rendimentos" if not aj.sem_marca else "Extrato de Conta", 15)
        txt(379.5, 43.9, "Período:", 11)
        txt(426.1, 43.9, f"{inicio.day:02d}{MESES[inicio.month - 1]}", 11)
        txt(463.7, 43.9, f"{inicio.year}a", 11)
        txt(500.2, 43.9, f"{fim.day:02d}{MESES[fim.month - 1]}", 11)
        txt(537.7, 43.9, f"{fim.year}", 11)
        txt(81, 51.8, f"Caixinhas {titular}", 18)
        txt(27, 91.1, "Informaçõesdotitular", 10.5)
        txt(542.3, 91.1, "CNPJ" if titular == "PJ" else "CPF", 10.5)
        txt(27, 108.3, nome_titular, 10.5)
        txt(464.3, 108.3, "12.345.678/0001-90", 10.5)

    def rodape(p, total):
        txt(84, 782.3, f"Documento{titular}" if aj.sem_marca else f"ExtratodeRendimentos{titular}", 9)
        txt(536.3, 790.4, str(p), 8)
        txt(555.0, 790.4, str(total), 8)
        txt(84, 797.3, "Emitidoem05outubro2026às10:57", 9)

    # linhas lógicas: (caixinha, tipo, dados)
    paginas: list[list] = [[]]
    for cx in caixinhas:
        linhas = [("mov", m) for m in cx.movs]
        if aj.linha_estranha and cx is caixinhas[0]:
            linhas.insert(len(linhas) // 2, ("estranha", aj.linha_estranha))
        if cx.rendimento is not None:
            linhas.append(("rend", cx.rendimento))
        primeira = True
        for l in linhas or [None]:
            if len(paginas[-1]) >= linhas_por_pagina:
                paginas.append([])
                primeira_da_pagina = True
            else:
                primeira_da_pagina = False
            if primeira or primeira_da_pagina:
                paginas[-1].append(("secao", cx, primeira))
                primeira = False
            if l:
                paginas[-1].append(("linha", cx, l))

    total = len(paginas)
    for p, itens in enumerate(paginas, 1):
        cabecalho()
        top = 169.7
        for it in itens:
            if it[0] == "secao":
                _, cx, com_produto = it
                if com_produto:
                    txt(27, top, cx.produto, 14)
                    txt(27, top + 32.3, "Instituição", 10)
                    txt(138, top + 31.5, "260-Nu FinanceiraS.A.", 10)
                    txt(444.8, top + 32.3, "CNPJ30.680.829/0001-43", 10)
                    top += 76.1
                else:
                    top += 2.6
                txt(27.8, top, cx.nome, 12)
                txt(384.8, top - 0.3, "Saldo no final do período:", 10)
                txt(510.0, top - 0.3, rs(cx.saldo_final), 10)
                top += 35.2
                for x, s in ((27.8, "Data"), (90, "Movimentação"), (158.3, "Rendimento"), (240.8, "Valorbruto"),
                             (322.5, "IR"), (404.3, "IOF"), (486.8, "ValorLíquido")):
                    txt(x, top, s, 7.5)
                top += 23.3
            else:
                _, cx, (tipo, dado) = it
                if tipo == "mov":
                    m = dado
                    txt(27.8, top, f"{m.data:%d/%m/%Y}", 7.5)
                    txt(90, top, m.tipo, 7.5)
                    txt(240.8, top, rs(m.bruto), 7.5)
                    txt(322.5, top, rs(m.ir), 7.5)
                    txt(404.3, top, rs(m.iof), 7.5)
                    txt(486.8, top, rs(m.bruto - m.ir - m.iof + m.liquido_delta), 7.5)
                elif tipo == "rend":
                    txt(90, top - 5.2, "Rendimentosde", 7.5)
                    txt(27.8, top, f"{fim:%d/%m/%Y}", 7.5)
                    txt(158.3, top, rs(dado), 7.5)
                    txt(90, top + 6.0, MESES_MIN[fim.month - 1], 7.5)
                else:
                    txt(90, top, dado, 7.5)
                top += 26.25
        if p == total:
            txt(27.8, top + 30, "Informações complementares", 12)
            txt(58.5, top + 76, "Rendimentoscalculadosatéadatadeemissão.", 7)
            txt(73.5, top + 110, "Fale", 8)
            txt(103.7, top + 110, "com o Nubank:", 8)
            txt(165, top + 110.6, "Ouvidoria08008870463(atendimentoemdiasúteis).", 7)
        rodape(p, total)
        c.showPage()
    c.save()


def cenario_setembro() -> list[Caixinha]:
    D = lambda d: date(2026, 9, d)
    return [Caixinha(
        nome="Reservadeemergencia", saldo_final=4_512_345, rendimento=41_233,
        movs=[
            MovC(D(1), "Resgate", 30_000, 12, 0),
            MovC(D(3), "Resgate", 250_000, 1_034, 0),
            MovC(D(3), "Resgate", 250_000, 1_034, 0),       # duas idênticas no mesmo dia
            MovC(D(10), "Resgate", 9_990, 0, 0),
            MovC(D(18), "Resgate", 500_000, 2_210, 35),
            MovC(D(25), "Resgate", 84_219, 310, 0),
        ],
    )]
