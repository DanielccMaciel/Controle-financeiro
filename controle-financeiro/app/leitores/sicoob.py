"""Leitor do extrato de conta corrente do Sicoob (PDF do app / internet banking).

Layout (analisado em 2026-10-05 a partir de versão mascarada — PROJETO.md, seção 34.2):

- Tudo em fonte 9. Cabeçalho: SICOOB, ... SISBR, data/hora, cooperativa,
  "CONTA: 12.345-6/TITULAR", "PERÍODO: dd/mm/aaaa-dd/mm/aaaa".
- Tabela com três colunas: DATA (x≈115) · HISTÓRICO (x≈154) · VALOR (à direita, x1≈479).
      dd/mm  SALDO ANTERIOR                    1.234,56C
      dd/mm  <histórico>                         250,00C     <- C = crédito, D = débito
             <linhas de detalhe>
             DOC.:1234567890
      dd/mm  SALDO DO DIA                      1.484,56C
  A data vem sem ano (o ano sai do período).
- Quando o valor é largo, a letra C/D cai para a linha de baixo, e o número pode
  ficar meia linha acima da data. Por isso o valor é ligado à data mais próxima.
- Depois da tabela vem "RESUMO" (saldos, limites, taxas): ignorado.

Os rótulos estavam mascarados na amostra; por isso o leitor se apoia na ESTRUTURA
(colunas, datas, C/D) e só exige que as linhas de saldo comecem com "SALDO".
A prova de que leu certo é a conferência: saldo anterior + créditos - débitos
tem de bater com cada "SALDO DO DIA".
"""

import re
import unicodedata
from datetime import date
from pathlib import Path

import pdfplumber

from app.leitores.base import ErroLeitura, ExtratoLido, ItemLido, valor_centavos

LAYOUT = "sicoob_v1"
BANCO = "Sicoob"

X_DATA_MAX = 150       # datas começam em ~115
X_VALOR_MIN = 425      # valores começam em ~433 ou mais
TOL_LINHA = 2.0        # mesma linha
TOL_VALOR = 7.0        # distância máxima entre a data e o número do valor
TOL_LETRA = 14.0       # distância máxima entre o número e a letra C/D que caiu de linha

RE_DATA = re.compile(r"^(\d{2})/(\d{2})$")
RE_NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
RE_NUM_LETRA = re.compile(r"^(\d{1,3}(?:\.\d{3})*,\d{2})([CD*])$")
RE_PERIODO = re.compile(r"PERIODO:(\d{2})/(\d{2})/(\d{4})-(\d{2})/(\d{2})/(\d{4})")
RE_CONTA = re.compile(r"CONTA:([\d.]+-[\dXx])")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).upper()


def _compacto(s: str) -> str:
    return re.sub(r"\s+", "", _norm(s))


def _abrir(caminho: Path, senha: str | None):
    try:
        pdf = pdfplumber.open(caminho, password=senha) if senha else pdfplumber.open(caminho)
        _ = pdf.pages
        return pdf
    except Exception as erro:
        if b"/Encrypt" in Path(caminho).read_bytes()[:200_000] or "password" in repr(erro).lower():
            raise ErroLeitura("O PDF está protegido por senha", repr(erro)) from erro
        raise ErroLeitura("Não consegui abrir o PDF (arquivo corrompido?)", repr(erro)) from erro


def _linhas(palavras: list[dict]) -> list[list[dict]]:
    linhas: list[list[dict]] = []
    for w in sorted(palavras, key=lambda w: (round(w["top"], 1), w["x0"])):
        if linhas and abs(linhas[-1][0]["top"] - w["top"]) <= TOL_LINHA:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in linhas]


def _ano_da_data(dia: int, mes: int, inicio: date, fim: date) -> date:
    """A tabela traz só dd/mm; o ano vem do período (que pode virar o ano)."""
    for ano in range(inicio.year, fim.year + 1):
        try:
            d = date(ano, mes, dia)
        except ValueError:
            continue
        if inicio <= d <= fim:
            return d
    # fora do período (ex.: saldo anterior do dia que antecede): ano mais próximo do início
    try:
        d = date(inicio.year, mes, dia)
    except ValueError:
        d = date(inicio.year, mes, 28)
    if d > fim:
        try:
            d = date(inicio.year - 1, mes, dia)
        except ValueError:
            pass
    return d


MARCAS = ("SICOOB", "PERIODO:", "HISTORICO", "VALOR")


def e_extrato(caminho: Path, senha: str | None = None) -> bool:
    """Reconhece o tipo do PDF sem lançar erro (usado na importação de vários PDFs)."""
    try:
        with (pdfplumber.open(caminho, password=senha) if senha else pdfplumber.open(caminho)) as pdf:
            cab = _compacto(pdf.pages[0].extract_text() or "")
        return all(m in cab for m in MARCAS)
    except Exception:
        return False


def ler(caminho: Path, senha: str | None = None) -> ExtratoLido:
    pdf = _abrir(caminho, senha)
    with pdf:
        if not pdf.pages:
            raise ErroLeitura("O PDF não tem páginas")
        paginas = [pg.extract_words() for pg in pdf.pages]
        if not any(paginas[:2]):
            raise ErroLeitura("O PDF não tem texto (parece imagem escaneada)")

        cab = _compacto(" ".join(w["text"] for w in paginas[0]))
        faltando = [m for m in MARCAS if m not in cab]
        if faltando:
            raise ErroLeitura(
                "Layout não reconhecido: o PDF não parece ser um extrato de conta do Sicoob",
                "Marcas esperadas que não foram encontradas: " + ", ".join(faltando), 1,
            )
        m = RE_PERIODO.search(cab)
        if not m:
            raise ErroLeitura("Não encontrei o período do extrato no cabeçalho", cab[:300], 1)
        try:
            inicio = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            fim = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
        except ValueError as e:
            raise ErroLeitura("Período do extrato com data inválida", m.group(0), 1) from e
        mc = RE_CONTA.search(cab)
        numero = mc.group(1) if mc else None

        ext = ExtratoLido(
            layout=LAYOUT, banco=BANCO, tipo_titular=None, agencia=None, numero_conta=numero,
            periodo_inicio=inicio, periodo_fim=fim, saldo_inicial=0, saldo_final=0,
            total_entradas=0, total_saidas=0, rendimento=None, paginas=len(pdf.pages),
            titular_texto=" ".join(w["text"] for w in paginas[0] if 150 < w["top"] < 190),
        )

        # ---- separa, página a página, as três colunas da tabela
        ancoras: list[dict] = []    # {pos, pagina, data, historico: [..], detalhes: [..], valores: [..]}
        valores: list[dict] = []    # {pos, pagina, centavos, letra}
        textos: list[tuple[float, int, str, float]] = []   # (pos, página, texto da linha, top)
        achou_tabela = False
        terminou = False

        for n, palavras in enumerate(paginas, 1):
            if terminou:
                break
            base = n * 100_000.0
            linhas = _linhas(palavras)
            # início da tabela nesta página: depois da linha "DATA HISTÓRICO VALOR", se houver
            comeco = 0
            for idx, l in enumerate(linhas):
                if _compacto("".join(w["text"] for w in l)) == "DATAHISTORICOVALOR":
                    comeco = idx + 1
                    achou_tabela = True
                    break
            else:
                if not achou_tabela:
                    continue    # página sem tabela antes de a tabela começar
            pendente_num: dict | None = None
            for l in linhas[comeco:]:
                rotulo = _compacto("".join(w["text"] for w in l))
                if rotulo == "RESUMO":
                    terminou = True
                    break
                top = l[0]["top"]
                esq = [w for w in l if w["x0"] < X_VALOR_MIN]
                dir_ = [w for w in l if w["x0"] >= X_VALOR_MIN]

                for w in dir_:
                    t = w["text"]
                    mm = RE_NUM_LETRA.match(t)
                    if mm:
                        valores.append({"pos": base + w["top"], "pagina": n,
                                        "centavos": valor_centavos(mm.group(1)), "letra": mm.group(2)})
                        pendente_num = None
                    elif RE_NUM.match(t):
                        pendente_num = {"pos": base + w["top"], "pagina": n,
                                        "centavos": valor_centavos(t), "letra": None}
                        valores.append(pendente_num)
                    elif t in ("C", "D", "*") and pendente_num is not None \
                            and 0 < (base + w["top"]) - pendente_num["pos"] <= TOL_LETRA:
                        pendente_num["letra"] = t
                        pendente_num = None
                    else:
                        ext.nao_reconhecidas.append((n, " ".join(x["text"] for x in l)))

                if not esq:
                    continue
                if esq[0]["x0"] < X_DATA_MAX:
                    md = RE_DATA.match(esq[0]["text"])
                    if not md:
                        ext.nao_reconhecidas.append((n, " ".join(x["text"] for x in l)))
                        continue
                    try:
                        d = _ano_da_data(int(md.group(1)), int(md.group(2)), inicio, fim)
                    except ValueError:
                        ext.nao_reconhecidas.append((n, " ".join(x["text"] for x in l)))
                        continue
                    ancoras.append({"pos": base + top, "pagina": n, "data": d,
                                    "historico": " ".join(w["text"] for w in esq[1:]),
                                    "detalhes": [], "valores": []})
                else:
                    textos.append((base + top, n, " ".join(w["text"] for w in esq), top))

        if not achou_tabela:
            raise ErroLeitura("Não encontrei a tabela de movimentações (DATA · HISTÓRICO · VALOR)", None, 1)
        if not ancoras:
            raise ErroLeitura("Não encontrei nenhuma linha com data na tabela do extrato", None, 1)

        # ---- linhas de detalhe pertencem à data imediatamente acima
        for pos, n, texto, _top in textos:
            dono = None
            for a in ancoras:
                if a["pos"] <= pos + TOL_LINHA:
                    dono = a
                else:
                    break
            if dono is None:
                ext.nao_reconhecidas.append((n, texto))
            else:
                dono["detalhes"].append(texto)

        # ---- cada valor pertence à data mais próxima
        for v in valores:
            if v["letra"] is None:
                ext.nao_reconhecidas.append((v["pagina"], f"valor sem C/D: {v['centavos'] / 100:.2f}"))
                continue
            perto = min(ancoras, key=lambda a: abs(a["pos"] - v["pos"]))
            if abs(perto["pos"] - v["pos"]) > TOL_VALOR:
                ext.nao_reconhecidas.append((v["pagina"], f"valor sem data: {v['centavos'] / 100:.2f}{v['letra']}"))
            else:
                perto["valores"].append(v)

        # ---- interpreta cada linha
        saldo_anterior: int | None = None
        ordem: dict[date, int] = {}
        for a in ancoras:
            descricao = f"{a['data']:%d/%m} {a['historico']}".strip()
            if len(a["valores"]) != 1:
                ext.nao_reconhecidas.append(
                    (a["pagina"], f"{descricao} ({len(a['valores'])} valores encontrados para esta linha)"))
                continue
            v = a["valores"][0]
            hist = _compacto(a["historico"])
            if hist.startswith("SALDO"):
                if v["letra"] == "*" or "BLOQ" in hist:
                    continue                                   # saldo bloqueado: informativo
                saldo = v["centavos"] if v["letra"] == "C" else -v["centavos"]
                if "ANTERIOR" in hist:
                    saldo_anterior = saldo
                elif hist.replace(".", "") in ("SALDODODIA", "SALDODIA"):
                    ext.saldos_dia[a["data"]] = (saldo, a["pagina"])
                else:
                    ext.nao_reconhecidas.append((a["pagina"], descricao))
                continue
            if v["letra"] not in ("C", "D") or not a["historico"]:
                ext.nao_reconhecidas.append((a["pagina"], descricao))
                continue
            if v["centavos"] == 0:
                continue                                       # lançamento informativo de valor zero
            ordem[a["data"]] = ordem.get(a["data"], 0) + 1
            ext.itens.append(ItemLido(
                data=a["data"], tipo="Entrada" if v["letra"] == "C" else "Saída", valor=v["centavos"],
                operacao=a["historico"], contraparte=" ".join(a["detalhes"]),
                pagina=a["pagina"], ordem_no_dia=ordem[a["data"]],
            ))

        if saldo_anterior is None:
            raise ErroLeitura("Não encontrei o SALDO ANTERIOR no extrato",
                              "Sem ele não dá para conferir os saldos do dia.", 1)

        ext.saldo_inicial = saldo_anterior
        ext.total_entradas = sum(i.valor for i in ext.itens if i.tipo == "Entrada")
        ext.total_saidas = sum(i.valor for i in ext.itens if i.tipo == "Saída")
        if ext.saldos_dia:
            ext.saldo_final = ext.saldos_dia[max(ext.saldos_dia)][0]
        else:
            ext.saldo_final = saldo_anterior
            if ext.itens:
                ext.nao_reconhecidas.append(
                    (1, "O extrato tem movimentações mas nenhuma linha 'SALDO DO DIA' para conferir"))
        return ext
