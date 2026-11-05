"""Leitor do extrato de conta do Nubank (conta pessoal e conta PJ: mesmo layout).

Layout (analisado em 2026-09-26 — ver PROJETO.md, seção 34.1):

- Cabeçalho (fonte 9): titular, CPF/CNPJ, agência, conta, período, "VALORES EM R$".
- Resumo na página 1 (fonte 9/14, coluna x≈320): Saldo inicial, Rendimento
  líquido, Total de entradas, Total de saídas, Saldo final do período.
- Movimentações (fonte 8), agrupadas por dia:
      DD MMM AAAA  Total de entradas              + valor
                   <operação>  <contraparte>        valor
                   Total de saídas                 - valor
                   <operação>  <contraparte>        valor
                   Saldo do dia                      valor
  Colunas: data x≈58 · operação x≈120 · contraparte x≈262 · valor à direita (x1≈533).
  A contraparte continua nas linhas de baixo. Dias podem continuar na página seguinte.
- Rodapé e texto legal (fonte 7): ignorados — marcam o fim das movimentações da página.
"""

import re
import unicodedata
from datetime import date
from pathlib import Path

import pdfplumber

from app.leitores.base import (
    MESES_EXTENSO, RE_VALOR, ErroLeitura, ExtratoLido, GrupoLido, ItemLido,
    data_abrev, valor_centavos,
)

LAYOUT = "nubank_v1"
BANCO = "Nubank"

# Limites de coluna (pontos), com folga em relação ao medido
X_DATA_MAX = 100      # data começa em ~58
X_OPERACAO_MAX = 250  # operação começa em ~120 e termina antes de ~255
X_VALOR_MIN_FIM = 480 # o valor termina em ~533
X_RESUMO = (300, 345) # rótulos do resumo começam em ~320

TOL_LINHA = 2.0       # palavras com 'top' até 2 pt de diferença estão na mesma linha

# Em alguns PDFs o texto vem sem os espaços entre as palavras ("01DESETEMBRODE2026").
# Por isso datas, período e rótulos são comparados SEM espaços.
RE_DATA = re.compile(r"^(\d{2})([A-Z]{3})(\d{4})$")
_MESES = "JANEIRO|FEVEREIRO|MARCO|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO"
RE_PERIODO = re.compile(
    rf"(\d{{1,2}})DE({_MESES})DE(\d{{4}})A(\d{{1,2}})DE({_MESES})DE(\d{{4}})"
)
RE_AGENCIA_CONTA = re.compile(r"AGENCIA(\d+)CONTA([\d-]+)")
X_OPERACAO_MIN = 112  # a data fica à esquerda disso (a operação começa em ~120)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).upper()


def _linhas(palavras: list[dict]) -> list[list[dict]]:
    """Agrupa palavras em linhas (pelo 'top') e ordena da esquerda para a direita."""
    linhas: list[list[dict]] = []
    for w in sorted(palavras, key=lambda w: (round(w["top"], 1), w["x0"])):
        if linhas and abs(linhas[-1][0]["top"] - w["top"]) <= TOL_LINHA:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in linhas]


def _compacto(s: str) -> str:
    """Sem acentos, maiúsculo e sem espaços: 'Saldo do dia' e 'Saldododia' ficam iguais."""
    return re.sub(r"\s+", "", _norm(s))


def _texto(ws: list[dict]) -> str:
    return " ".join(w["text"] for w in ws)


def _tamanho(w: dict) -> float:
    return round(float(w.get("size", 0)), 1)


def _separar_valor(linha: list[dict]) -> tuple[list[dict], int | None, str | None]:
    """Tira o valor (e o sinal) do fim da linha. Retorna (resto, centavos, sinal)."""
    if not linha:
        return linha, None, None
    ultimo = linha[-1]
    if ultimo["x1"] < X_VALOR_MIN_FIM or not RE_VALOR.match(ultimo["text"]):
        return linha, None, None
    resto = linha[:-1]
    sinal = None
    texto = ultimo["text"]
    if texto[0] in "+-":
        sinal = texto[0]
    elif (resto and resto[-1]["text"] in ("+", "-")
          and resto[-1]["x0"] >= X_VALOR_MIN_FIM
          and ultimo["x0"] - resto[-1]["x1"] < 12):
        # sinal solto logo antes do valor (ex.: "+ 999,99"); um "-" no fim da
        # descrição fica longe do valor e continua fazendo parte do texto
        sinal = resto[-1]["text"]
        resto = resto[:-1]
    return resto, abs(valor_centavos(texto)), sinal


def _data_extenso(dia: str, mes: str, ano: str) -> date:
    return date(int(ano), MESES_EXTENSO[_norm(mes)], int(dia))


# ------------------------------------------------------------------ cabeçalho

def _reconhecer_layout(pdf) -> None:
    def compacto(t: str) -> str:  # sem espaços: não depende do espaçamento entre palavras
        return re.sub(r"\s+", "", _norm(t))

    texto = compacto(pdf.pages[0].extract_text() or "")
    faltando = [
        marca for marca in ("VALORES EM R$", "SALDO INICIAL", "SALDO FINAL DO PERIODO", "MOVIMENTACOES")
        if compacto(marca) not in texto
    ]
    todo = compacto(" ".join((p.extract_text() or "") for p in pdf.pages[:2]))
    if "NUBANK.COM.BR" not in todo:
        faltando.append("nubank.com.br")
    if faltando:
        raise ErroLeitura(
            "Layout não reconhecido: o PDF não parece ser um extrato de conta do Nubank",
            "Marcas esperadas que não foram encontradas: " + ", ".join(faltando),
            1,
        )


def e_extrato(caminho: Path, senha: str | None = None) -> bool:
    """Reconhece o tipo do PDF sem lançar erro (usado na importação de vários PDFs)."""
    try:
        with (pdfplumber.open(caminho, password=senha) if senha else pdfplumber.open(caminho)) as pdf:
            _reconhecer_layout(pdf)
        return True
    except Exception:
        return False


def _ler_cabecalho(pg) -> dict:
    palavras = [w for w in pg.extract_words(extra_attrs=["size"]) if _tamanho(w) >= 8.5]
    linhas = _linhas(palavras)
    texto = _compacto(" ".join(_texto(l) for l in linhas))

    # procura primeiro linha a linha (para não grudar o período no número da conta, que vem antes)
    m = None
    for l in linhas:
        m = RE_PERIODO.search(_compacto(_texto(l)))
        if m:
            break
    m = m or RE_PERIODO.search(texto)
    if not m:
        raise ErroLeitura("Não encontrei o período do extrato no cabeçalho", texto[:300], 1)
    try:
        inicio = _data_extenso(*m.group(1, 2, 3))
        fim = _data_extenso(*m.group(4, 5, 6))
    except (KeyError, ValueError) as e:
        raise ErroLeitura("Período do extrato com data inválida", m.group(0), 1) from e

    # titular, CPF/CNPJ, agência e conta ficam no alto da página (antes do período)
    topo_linhas = [l for l in linhas if l[0]["top"] < 130]
    topo = _compacto(" ".join(_texto(l) for l in topo_linhas))
    tipo = "PJ" if "CNPJ" in topo else ("PF" if "CPF" in topo else None)
    agencia = numero = None
    mc = RE_AGENCIA_CONTA.search(topo)
    if mc:
        agencia, numero = mc.group(1), mc.group(2)
    return {"inicio": inicio, "fim": fim, "tipo": tipo, "agencia": agencia, "numero": numero,
            "titular_texto": " ".join(_texto(l) for l in topo_linhas)}


def _ler_resumo(pg) -> dict:
    rotulos = {
        "SALDOINICIAL": "saldo_inicial",
        "RENDIMENTOLIQUIDO": "rendimento",
        "TOTALDEENTRADAS": "total_entradas",
        "TOTALDESAIDAS": "total_saidas",
        "SALDOFINALDOPERIODO": "saldo_final",
    }
    resumo: dict[str, int] = {}
    palavras = pg.extract_words(extra_attrs=["size"])
    for linha in _linhas(palavras):
        if not (X_RESUMO[0] <= linha[0]["x0"] <= X_RESUMO[1]):
            continue
        resto, valor, sinal = _separar_valor(linha)
        rotulo = _compacto(_texto(resto))
        if rotulo in rotulos and valor is not None:
            resumo[rotulos[rotulo]] = -valor if sinal == "-" else valor
    faltando = [r for r, chave in rotulos.items() if chave not in resumo and chave != "rendimento"]
    if faltando:
        raise ErroLeitura(
            "Não consegui ler o resumo do extrato (página 1)",
            "Itens não encontrados: " + ", ".join(faltando), 1,
        )
    return resumo


# ------------------------------------------------------------------ movimentações

def _linhas_de_movimentacao(pg, numero_pagina: int) -> list[list[dict]]:
    """Só as linhas da área de movimentações desta página (fonte 8, antes do rodapé)."""
    palavras = pg.extract_words(extra_attrs=["size"])
    linhas = _linhas(palavras)

    # início: depois de "Movimentações" (pág. 1) ou depois de "VALORES EM R$" (demais)
    inicio = None
    for idx, l in enumerate(linhas):
        t = _compacto(_texto(l))
        if t == "MOVIMENTACOES":
            inicio = idx + 1
            break
    if inicio is None:
        for idx, l in enumerate(linhas):
            if "VALORESEMR$" in _compacto(_texto(l)):
                inicio = idx + 1
                break
    if inicio is None:
        raise ErroLeitura(
            "Não encontrei o início das movimentações na página",
            "Nem 'Movimentações' nem 'VALORES EM R$' encontrados.", numero_pagina,
        )

    resultado = []
    for l in linhas[inicio:]:
        if any(_tamanho(w) < 7.5 for w in l):   # rodapé / texto legal
            break
        # Depois das movimentações, a última página traz os dados das empresas do Nubank:
        # o nome em fonte 9 e, embaixo, "CNPJ: ..." em fonte 8. Nada na área de
        # movimentações usa fonte 9, então ela marca o fim. (Se por engano cortasse
        # movimentações, as conferências de saldo acusariam.)
        if any(_tamanho(w) > 8.6 for w in l):
            break
        if re.fullmatch(r"CNPJ:?[\d./-]+", _compacto(_texto(l))):
            continue
        if all(abs(_tamanho(w) - 8.0) < 0.6 for w in l):
            resultado.append(l)
    return resultado


def ler(caminho: Path, senha: str | None = None) -> ExtratoLido:
    try:
        pdf = pdfplumber.open(caminho, password=senha) if senha else pdfplumber.open(caminho)
        _ = pdf.pages
    except Exception as erro:
        if b"/Encrypt" in Path(caminho).read_bytes()[:200_000] or "password" in repr(erro).lower():
            raise ErroLeitura("O PDF está protegido por senha", repr(erro)) from erro
        raise ErroLeitura("Não consegui abrir o PDF (arquivo corrompido?)", repr(erro)) from erro

    with pdf:
        if not pdf.pages:
            raise ErroLeitura("O PDF não tem páginas")
        if not any((p.extract_words()) for p in pdf.pages[:2]):
            raise ErroLeitura("O PDF não tem texto (parece imagem escaneada)")

        _reconhecer_layout(pdf)
        cab = _ler_cabecalho(pdf.pages[0])
        resumo = _ler_resumo(pdf.pages[0])

        ext = ExtratoLido(
            layout=LAYOUT, banco=BANCO, tipo_titular=cab["tipo"],
            agencia=cab["agencia"], numero_conta=cab["numero"],
            periodo_inicio=cab["inicio"], periodo_fim=cab["fim"],
            saldo_inicial=resumo["saldo_inicial"], saldo_final=resumo["saldo_final"],
            total_entradas=abs(resumo["total_entradas"]), total_saidas=abs(resumo["total_saidas"]),
            rendimento=resumo.get("rendimento"), paginas=len(pdf.pages),
            titular_texto=cab["titular_texto"],
        )

        dia: date | None = None
        grupo: GrupoLido | None = None
        item: ItemLido | None = None
        ordem = 0

        for n, pg in enumerate(pdf.pages, 1):
            for linha in _linhas_de_movimentacao(pg, n):
                texto_linha = _texto(linha)

                # data no começo da linha
                if linha[0]["x0"] < X_DATA_MAX:
                    palavras_data = [w for w in linha if w["x0"] < X_OPERACAO_MIN]
                    m = RE_DATA.match(_compacto(_texto(palavras_data)))
                    if not m:
                        ext.nao_reconhecidas.append((n, texto_linha))
                        continue
                    try:
                        dia = data_abrev(*m.group(1, 2, 3))
                    except (KeyError, ValueError):
                        ext.nao_reconhecidas.append((n, texto_linha))
                        continue
                    ordem, grupo, item = 0, None, None
                    linha = [w for w in linha if w["x0"] >= X_OPERACAO_MIN]
                    if not linha:
                        continue

                resto, valor, sinal = _separar_valor(linha)
                x_inicio = resto[0]["x0"] if resto else linha[0]["x0"]
                rotulo = _compacto(_texto(resto))

                if dia is None:
                    ext.nao_reconhecidas.append((n, texto_linha))
                    continue

                # Total de entradas / saídas
                if rotulo in ("TOTALDEENTRADAS", "TOTALDESAIDAS") and valor is not None:
                    tipo = "Entrada" if rotulo.endswith("ENTRADAS") else "Saída"
                    grupo = GrupoLido(dia, tipo, valor, n)
                    ext.grupos.append(grupo)
                    item = None
                    continue

                # Saldo do dia
                if rotulo == "SALDODODIA" and valor is not None:
                    ext.saldos_dia[dia] = (-valor if sinal == "-" else valor, n)
                    grupo, item = None, None
                    continue

                # Item: operação (x<250) + contraparte (x>=250) + valor
                if valor is not None and x_inicio < X_OPERACAO_MAX and grupo is not None:
                    operacao = _texto([w for w in resto if w["x0"] < X_OPERACAO_MAX])
                    contraparte = _texto([w for w in resto if w["x0"] >= X_OPERACAO_MAX])
                    ordem += 1
                    item = ItemLido(dia, grupo.tipo, valor, operacao, contraparte, n, ordem)
                    ext.itens.append(item)
                    grupo.soma_itens += valor
                    grupo.qtd_itens += 1
                    continue

                # Continuação da contraparte (sem valor, na coluna da contraparte).
                # Linha sem valor na coluna da operação NÃO é aceita: no layout
                # analisado a operação nunca quebra linha; se aparecer, é algo novo.
                if valor is None and item is not None and x_inicio >= X_OPERACAO_MAX:
                    item.contraparte = f"{item.contraparte} {texto_linha}".strip()
                    continue

                ext.nao_reconhecidas.append((n, texto_linha))

    return ext
