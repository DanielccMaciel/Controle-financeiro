"""Gera extratos FALSOS no mesmo layout do extrato de conta do Nubank.

Usado só nos testes. As posições, tamanhos de fonte e agrupamentos imitam o
layout real do extrato de conta (cabeçalho, grupos por dia, saldo do dia, rodapé).
"""

from dataclasses import dataclass, field
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
MESES_EXT = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO",
             "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
ALTURA = A4[1]


def br(c: int) -> str:
    s = f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d}"
    return ("-" if c < 0 else "") + s


@dataclass
class Mov:
    tipo: str                  # 'Entrada' | 'Saída'
    operacao: str
    contraparte: list[str]     # 1ª linha + continuações
    valor: int                 # centavos


@dataclass
class Dia:
    data: date
    movs: list[Mov]


@dataclass
class Ajustes:
    """Erros de propósito, para testar as travas."""
    saldo_dia_delta: dict = field(default_factory=dict)     # data -> centavos a somar no saldo informado
    total_grupo_delta: dict = field(default_factory=dict)   # (data, tipo) -> centavos
    total_entradas_delta: int = 0
    linha_estranha: str | None = None                        # texto solto no meio das movimentações
    sem_marca_nubank: bool = False
    rendimento: int = 0
    legal_sem_fonte_pequena: bool = False   # última página só com o bloco das empresas (fontes 9 e 8)
    colado: bool = False          # textos sem espaço entre as palavras (como em alguns PDFs reais)


def gerar(caminho, dias: list[Dia], *, inicio: date, fim: date, saldo_inicial: int,
          titular="DANIEL TESTE DA SILVA", documento="CPF ***.123.456-**",
          agencia="0001", conta="12345678-9", ajustes: Ajustes | None = None,
          itens_por_pagina: int = 14):
    aj = ajustes or Ajustes()
    c = canvas.Canvas(str(caminho), pagesize=A4)

    ent_total = sum(m.valor for d in dias for m in d.movs if m.tipo == "Entrada")
    sai_total = sum(m.valor for d in dias for m in d.movs if m.tipo == "Saída")
    saldo_final = saldo_inicial + ent_total - sai_total + aj.rendimento

    def txt(x, top, s, size, bold=False, direita=False):
        if aj.colado and size >= 8 and not (s[:1] in "+-" or s[:1].isdigit() and "," in s):
            s = s.replace(" ", "")
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        y = ALTURA - top - size * 0.8
        (c.drawRightString if direita else c.drawString)(x, y, s)

    periodo = (f"{inicio.day:02d} DE {MESES_EXT[inicio.month-1]} DE {inicio.year} a "
               f"{fim.day:02d} DE {MESES_EXT[fim.month-1]} DE {fim.year}")

    def cabecalho():
        txt(535.8, 59.7, titular, 9, direita=True)
        txt(535.8, 72.2, f"{documento} Agência {agencia} Conta", 9, direita=True)
        txt(538.2, 84.6, conta, 9, direita=True)
        txt(57, 135.4, periodo, 9, bold=True)
        txt(538.3, 135.1, "VALORES EM R$", 9, direita=True)

    def rodape(pag, total):
        txt(57, 727.7, "Tem alguma dúvida? Mande uma mensagem para nosso time de atendimento pelo chat do app", 7)
        txt(57, 737.1, "ou ligue 4020 0185 (capitais e regiões metropolitanas). Atendimento 24h.", 7)
        marca = "www.exemplo.com.br" if aj.sem_marca_nubank else "nubank.com.br/contatos#ouvidoria"
        txt(57, 754.3, f"Caso a solução não seja satisfatória, fale com a Ouvidoria em {marca}", 7)
        txt(102.6, 780, f"Extrato gerado dia 20 de setembro de 2026 às 10:00", 7)
        txt(533.1, 780, f"{pag} de {total}", 8, direita=True)

    # monta as linhas lógicas
    linhas = []  # (tipo_linha, dados)
    for d in dias:
        data_txt = f"{d.data.day:02d} {MESES[d.data.month-1]} {d.data.year}"
        primeira = True
        for tipo, rotulo in (("Entrada", "Total de entradas"), ("Saída", "Total de saídas")):
            movs = [m for m in d.movs if m.tipo == tipo]
            if not movs:
                continue
            total = sum(m.valor for m in movs) + aj.total_grupo_delta.get((d.data, tipo), 0)
            linhas.append(("grupo", data_txt if primeira else None, rotulo,
                           ("+ " if tipo == "Entrada" else "- ") + br(total)))
            primeira = False
            for m in movs:
                linhas.append(("item", m))
        if aj.linha_estranha and d is dias[len(dias) // 2]:
            linhas.append(("estranha", aj.linha_estranha))
        linhas.append(("saldo", d.data))

    # calcula saldos do dia
    saldo = saldo_inicial
    saldo_por_dia = {}
    for d in dias:
        saldo += sum(m.valor if m.tipo == "Entrada" else -m.valor for m in d.movs)
        saldo_por_dia[d.data] = saldo + aj.saldo_dia_delta.get(d.data, 0)

    # paginação simples por quantidade de linhas lógicas
    paginas = [linhas[i:i + itens_por_pagina] for i in range(0, len(linhas), itens_por_pagina)] or [[]]
    total_pag = len(paginas)

    for p, bloco in enumerate(paginas, 1):
        cabecalho()
        if p == 1:
            txt(57, 189.9, "Saldo final do período", 9, bold=True)
            txt(57, 206.6, f"R$ {br(saldo_final)}", 14, bold=True)
            resumo = [
                ("Saldo inicial", br(saldo_inicial)),
                ("Rendimento líquido", "+" + br(aj.rendimento)),
                ("Total de entradas", "+" + br(ent_total + aj.total_entradas_delta)),
                ("Total de saídas", "-" + br(sai_total)),
                ("Saldo final do período", br(saldo_final)),
            ]
            for k, (rot, val) in enumerate(resumo):
                top = 164.3 + 20 * k
                txt(320.1, top, rot, 9)
                txt(535.8, top, val, 9, direita=True)
            txt(57, 274.7, "Movimentações", 8, bold=True)
            top = 296.7
        else:
            top = 161.6

        for linha in bloco:
            if linha[0] == "grupo":
                _, data_txt, rotulo, valor = linha
                if data_txt:
                    txt(58, top, data_txt, 8)
                txt(120, top, rotulo, 8, bold=True)
                txt(533.1, top, valor, 8, bold=True, direita=True)  # "+ 1.234,56"
                top += 21
            elif linha[0] == "item":
                m = linha[1]
                txt(120, top, m.operacao, 8)
                if m.contraparte:
                    txt(262.3, top, m.contraparte[0], 8)
                txt(533.1, top, br(m.valor), 8, direita=True)
                for cont in m.contraparte[1:]:
                    top += 20
                    txt(262.3, top, cont, 8)
                top += 21
            elif linha[0] == "estranha":
                txt(120, top, linha[1], 8)
                top += 21
            elif linha[0] == "saldo":
                txt(120, top, "Saldo do dia", 8, bold=True)
                txt(533.1, top, br(saldo_por_dia[linha[1]]), 8, bold=True, direita=True)
                top += 32

        if p == total_pag:
            if not aj.legal_sem_fonte_pequena:
                txt(57, top + 10, "O saldo líquido corresponde ao total de depósitos e rendimentos em conta.", 7)
            txt(57, top + 25, "Nu Pagamentos S.A. - Instituição de Pagamento", 9, bold=True)
            txt(57, top + 37, "CNPJ: 18.236.120/0001-58", 8)
            txt(57, top + 52, "Nu Financeira S.A. - Sociedade de Crédito, Financiamento e Investimento", 9, bold=True)
            txt(57, top + 64, "CNPJ: 30.680.829/0001-43", 8)
        rodape(p, total_pag)
        c.showPage()
    c.save()
    return {"saldo_final": saldo_final, "entradas": ent_total, "saidas": sai_total,
            "saldos": saldo_por_dia}


# ------------------------------------------------------------------ cenário padrão

def cenario_agosto() -> list[Dia]:
    """Um mês com Pix, resgates RDB, boleto, fatura e duas movimentações idênticas no mesmo dia."""
    D = lambda d: date(2026, 8, d)
    pix_env = "Transferência enviada pelo Pix"
    pix_rec = "Transferência recebida pelo Pix"
    return [
        Dia(D(3), [
            Mov("Entrada", pix_rec, ["MARIA CLIENTE SOUZA - ***.123.456-** - BCO", "BRADESCO S.A. (0237) Agência: 1234", "Conta: 123456-7"], 85000),
        ]),
        Dia(D(5), [
            Mov("Entrada", "Resgate RDB", [], 300000),
            Mov("Saída", pix_env, ["CELESC DISTRIBUICAO S.A - 08.336.783/0001-90 -", "BCO BRADESCO S.A. (0237) Agência: 3420 Conta:", "123-4"], 84219),
            Mov("Saída", pix_env, ["HORTIFRUTI EMBAU LTDA - 11.222.333/0001-44 - STONE", "IP S.A. (0197) Agência: 1 Conta: 1234567-8"], 31050),
        ]),
        Dia(D(8), [
            Mov("Saída", pix_env, ["JOAO DIARISTA - ***.999.888-** - NU", "PAGAMENTOS - IP (0260) Agência: 1 Conta:", "12345678-9"], 15000),
            Mov("Saída", pix_env, ["JOAO DIARISTA - ***.999.888-** - NU", "PAGAMENTOS - IP (0260) Agência: 1 Conta:", "12345678-9"], 15000),
            Mov("Saída", "Pagamento de boleto efetuado", ["CASAN COMPANHIA AGUAS"], 21033),
        ]),
        Dia(D(12), [
            Mov("Entrada", pix_rec, ["EMPRESA EXEMPLO SERVICOS LTDA - 11.111.111/0001-", "11 - ITAÚ UNIBANCO S.A. (0341) Agência: 1", "Conta: 9999-9"], 412345),
            Mov("Saída", "Pagamento de fatura", [], 250000),
        ]),
        Dia(D(20), [
            Mov("Saída", pix_env, ["RECEITA FEDERAL - 00.394.460/0058-87 - BCO", "DO BRASIL S.A. (0001) Agência: 1607 Conta:", "333666-1"], 98765),
        ]),
        Dia(D(28), [
            Mov("Entrada", "Resgate RDB", [], 50000),
            Mov("Saída", pix_env, ["MARIA LIMPEZA - ***.555.444-** - CAIXA", "ECONOMICA FEDERAL (0104) Agência: 1234 Conta:", "0001234567890123-4"], 45000),
        ]),
    ]
