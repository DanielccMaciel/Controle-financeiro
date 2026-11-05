"""Gera extratos FALSOS no layout do extrato de conta corrente do Sicoob.

Usado só nos testes. Posições e quebras imitam o layout real: tudo em fonte 9, data x≈115, histórico x≈154, valor
alinhado à direita em x≈479; quando o valor é largo a letra C/D cai para a linha
de baixo (e, nas linhas de saldo, o número sobe meia linha).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ALTURA = A4[1]
X_DATA, X_HIST, X_VALOR = 114.8, 153.8, 479.2


def br(c: int) -> str:
    return f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d}"


@dataclass
class Lanc:
    tipo: str                    # 'C' | 'D'
    historico: str               # ex.: CR.COMPRAS
    detalhes: list[str]          # ex.: ["SIPAG_Cre._Visa", "DOC.:1234567890"]
    valor: int


@dataclass
class DiaS:
    data: date
    lancs: list[Lanc]


@dataclass
class AjustesS:
    saldo_dia_delta: dict = field(default_factory=dict)
    linha_estranha: str | None = None
    sem_saldo_anterior: bool = False
    sem_marca: bool = False


def gerar(caminho, dias: list[DiaS], *, inicio: date, fim: date, saldo_anterior: int,
          conta="12.345-6", titular="DANIELTESTEDASILVA", ajustes: AjustesS | None = None,
          linhas_por_pagina: int = 46):
    aj = ajustes or AjustesS()
    c = canvas.Canvas(str(caminho), pagesize=A4)

    def txt(x, top, s, direita=False):
        c.setFont("Helvetica", 9)
        y = ALTURA - top - 7.2
        (c.drawRightString if direita else c.drawString)(x, y, s)

    def valor(top, centavos, letra, saldo=False):
        """Devolve quanto as linhas de baixo devem descer."""
        s = br(centavos)
        if len(s) < 8:                       # cabe com a letra: "999,99C"
            txt(X_VALOR, top, s + letra, direita=True)
            return 0.0
        if saldo:                            # número meia linha acima, letra meia abaixo
            txt(X_VALOR, top - 5.3, s, direita=True)
            txt(X_VALOR, top + 5.2, letra, direita=True)
            return 5.5
        txt(X_VALOR, top, s, direita=True)   # número na linha, letra na de baixo
        txt(X_VALOR, top + 9.7, letra, direita=True)
        return 9.7

    def cabecalho():
        txt(279.8, 52.5, "EXEMPLO" if aj.sem_marca else "SICOOB")
        txt(177.8, 65.3, "SISTEMADECOOPERATIVASDECREDITODOBRASIL")
        txt(156.8, 77.3, "PLATAFORMADESERVICOSFINANCEIROSDOSICOOB-" if not aj.sem_marca else "PLATAFORMA-")
        txt(389.4, 77.3, "SISBR")
        txt(114.8, 139.5, "05/10/2026")
        txt(231.8, 140.3, "EXTRATOCONTACORRENTE")
        txt(444.8, 139.5, "10:57:00")
        txt(114.8, 152.3, "COOP.:3069-4/" + ("EXEMPLO" if aj.sem_marca else "SICOOB") + "-TESTE/SC")
        txt(114.8, 164.3, "CONTA:")
        txt(149.2, 164.3, f"{conta}/{titular}")
        txt(114.8, 176.3, "PERÍODO:")
        txt(157.5, 176.3, f"{inicio:%d/%m/%Y}-{fim:%d/%m/%Y}")
        txt(225.8, 198.0, "HISTÓRICODEMOVIMENTAÇÃO")
        txt(114.8, 210.0, "DATA")
        txt(153.8, 210.0, "HISTÓRICO")
        txt(448.5, 210.0, "VALOR")

    # linhas lógicas
    blocos = []   # cada bloco = lista de funções de desenho que recebem top e devolvem altura
    saldo = saldo_anterior
    ant = inicio - timedelta(days=1)

    def linha_saldo(d, rotulo, v, letra=None):
        def desenha(top):
            desloc = valor(top, abs(v), letra or ("C" if v >= 0 else "D"), saldo=True)
            txt(X_DATA, top, f"{d:%d/%m}")
            txt(X_HIST, top, rotulo)
            return 17.2 if desloc else 11.3
        return desenha

    def linha_lanc(d, l: Lanc):
        def desenha(top):
            txt(X_DATA, top, f"{d:%d/%m}")
            txt(X_HIST, top, l.historico)
            desloc = valor(top, l.valor, l.tipo)
            t = top + 12 + desloc
            for det in l.detalhes:
                txt(X_HIST, t, det)
                t += 12
            return t - top
        return desenha

    if not aj.sem_saldo_anterior:
        blocos.append(linha_saldo(ant, "SALDOANTERIOR", saldo_anterior))
    blocos.append(linha_saldo(ant, "SALDOBLOQ.ANTERIOR", 0, letra="*"))
    saldos = {}
    for i, d in enumerate(dias):
        for l in d.lancs:
            blocos.append(linha_lanc(d.data, l))
            saldo += l.valor if l.tipo == "C" else -l.valor
        if aj.linha_estranha and i == len(dias) // 2:
            def estranha(top, s=aj.linha_estranha):
                txt(X_DATA, top, s)
                return 12
            blocos.append(estranha)
        saldos[d.data] = saldo
        blocos.append(linha_saldo(d.data, "SALDODODIA", saldo + aj.saldo_dia_delta.get(d.data, 0)))

    top = None
    primeira = True
    for b in blocos:
        if top is None or top > 760:
            if top is not None:
                c.showPage()
            if primeira:
                cabecalho()
                top = 227.3
                primeira = False
            else:
                top = 45.0
        top += b(top)

    if top > 620:
        c.showPage()
        top = 40.0
    txt(277.5, top + 10, "RESUMO")
    txt(114.8, top + 22, "(+)SALDOEMC.CORRENTE:")
    txt(478.9, top + 22, br(abs(saldo)) + ("C" if saldo >= 0 else "D"), direita=True)
    txt(114.8, top + 34, "(-)SALDOBLOQUEADO:")
    txt(478.9, top + 34, "0,00D", direita=True)
    txt(114.8, top + 46, "TAXADEJUROSCHEQUEESPECIAL(a.m.):")
    txt(478.0, top + 46, "7,99%", direita=True)
    txt(114.8, top + 58, "SAC:")
    txt(136.5, top + 58, "08007242220")
    c.showPage()
    c.save()
    return {"saldo_final": saldo, "saldos": saldos}


def cenario_setembro() -> list[DiaS]:
    D = lambda d: date(2026, 9, d)
    doc = lambda n: f"DOC.:{n}"
    return [
        DiaS(D(2), [
            Lanc("C", "CR.COMPRAS", ["SIPAG_Cre._Visa", doc(1000000001)], 45000),
            Lanc("C", "CR.COMPRASDEBITO", ["SIPAG_Deb._MastMaestro", doc(1000000002)], 32050),
            Lanc("C", "CR.COMPRAS", ["SIPAG_Cre._Mastercard", doc(1000000003)], 185000),
        ]),
        DiaS(D(5), [
            Lanc("C", "CR.COMPRASDEBITO", ["SIPAG_Deb._MastMaestro", doc(1000000004)], 32050),
            Lanc("C", "CR.COMPRASDEBITO", ["SIPAG_Deb._MastMaestro", doc(1000000004)], 32050),
        ]),
        DiaS(D(10), [
            Lanc("D", "DEB.TARIFAPACOTE", [doc(123)], 4990),
        ]),
        DiaS(D(18), [
            Lanc("C", "CR.COMPRAS", ["SIPAG_Cred._Elo", doc(1000000005)], 250000),
            Lanc("D", "PIXEMITIDOOUTRAIF", ["Pagamento_Pix", "DANIEL_TESTE_DA_SILVA", "***.123.456-**", doc("Pix")], 500000),
        ]),
        DiaS(D(30), [
            Lanc("C", "CR.COMPRAS", ["SIPAG_Cre._Visa", doc(1000000006)], 99990),
        ]),
    ]
