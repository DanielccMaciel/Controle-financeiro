"""Leitor do "Extrato de Rendimentos" das Caixinhas do Nubank.

Layout (analisado em 2026-10-05 a partir de versão mascarada — PROJETO.md, seção 34.3):

- Cabeçalho: "Extrato de Rendimentos" (fonte 15) · "Período: 01 SET 2026 a 30 SET 2026"
  (fonte 11) · "Caixinhas PJ" (fonte 18) · titular e CNPJ (fonte 10,5).
- Produto (fonte 14, x≈27), ex.: "RDB Resgate Imediato Rendimento 30 dias", e a instituição.
- Para cada caixinha: uma linha com o NOME (fonte 12, à esquerda) e
  "Saldo no final do período: R$ 9.999,99" (fonte 10, à direita). Essa linha se
  repete no alto da página seguinte quando a tabela continua.
- Tabela (fonte 7,5), colunas pelo x inicial:
      Data 28 · Movimentação 90 · Rendimento 158 · Valor bruto 241 · IR 322 · IOF 404 · Valor líquido 487
  Linha de movimentação (ex.: Resgate): bruto, IR, IOF e líquido preenchidos.
  Linha de rendimento do mês: só a coluna Rendimento preenchida; o rótulo
  ("Rendimentos de setembro") ocupa duas linhas, uma acima e outra abaixo da data.
- Texto legal (fonte 7) e rodapé (fontes 8 e 9): ignorados.

Os rótulos estavam mascarados na amostra; por isso o leitor se apoia nas COLUNAS
e nos tamanhos de fonte, e só usa como marcas os textos que apareceram sem máscara.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pdfplumber

from app.leitores.base import MESES_ABREV, ErroLeitura, Problema, formatar_centavos

LAYOUT = "nubank_caixinhas_v1"

TOL_LINHA = 2.0
TOL_ROTULO = 8.0          # o rótulo de duas linhas fica até ~6 pt acima/abaixo da data
X_DATA_MAX = 80
COLUNAS = (               # (nome, x mínimo) — vale a última cujo mínimo é <= x0 do texto
    ("rotulo", 80), ("rendimento", 152), ("bruto", 236), ("ir", 318), ("iof", 400), ("liquido", 483),
)

RE_DATA = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
RE_PERIODO = re.compile(r"PERIODO:(\d{1,2})([A-Z]{3})(\d{4})A(\d{1,2})([A-Z]{3})(\d{4})")
RE_DINHEIRO = re.compile(r"^(-?)(?:R\$)?(-?)(\d{1,3}(?:\.\d{3})*,\d{2})$")


@dataclass
class MovLido:
    data: date
    tipo: str               # como está no PDF: Resgate, Aplicação...
    bruto: int
    ir: int
    iof: int
    liquido: int
    pagina: int
    ordem_no_dia: int = 0


@dataclass
class RendimentoLido:
    data: date
    rotulo: str
    valor: int
    pagina: int


@dataclass
class AplicacaoLida:
    nome: str
    produto: str | None
    saldo_final: int
    movimentos: list[MovLido] = field(default_factory=list)
    rendimentos: list[RendimentoLido] = field(default_factory=list)


@dataclass
class ExtratoRendimentos:
    layout: str
    tipo_titular: str | None
    periodo_inicio: date
    periodo_fim: date
    paginas: int
    aplicacoes: list[AplicacaoLida] = field(default_factory=list)
    nao_reconhecidas: list[tuple[int, str]] = field(default_factory=list)
    titular_texto: str = ""
    banco: str = "Nubank"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).upper()


def _compacto(s: str) -> str:
    return re.sub(r"\s+", "", _norm(s))


def _tam(w: dict) -> float:
    return round(float(w.get("size", 0)), 1)


def _linhas(palavras: list[dict]) -> list[list[dict]]:
    linhas: list[list[dict]] = []
    for w in sorted(palavras, key=lambda w: (round(w["top"], 1), w["x0"])):
        if linhas and abs(linhas[-1][0]["top"] - w["top"]) <= TOL_LINHA:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in linhas]


def _dinheiro(texto: str) -> int | None:
    """'R$1.234,56' · 'R$ 1.234,56' · '-R$9,99' -> centavos (ou None se não for dinheiro)."""
    m = RE_DINHEIRO.match(texto.replace(" ", ""))
    if not m:
        return None
    c = int(m.group(3).replace(".", "").replace(",", ""))
    return -c if (m.group(1) or m.group(2)) else c


def _coluna(x0: float) -> str | None:
    nome = None
    for n, minimo in COLUNAS:
        if x0 >= minimo:
            nome = n
    return nome


def e_extrato_de_rendimentos(caminho: Path, senha: str | None = None) -> bool:
    """Reconhece o tipo do PDF sem lançar erro (usado para escolher o leitor)."""
    try:
        with (pdfplumber.open(caminho, password=senha) if senha else pdfplumber.open(caminho)) as pdf:
            texto = _compacto(pdf.pages[0].extract_text() or "")
    except Exception:
        return False
    return "EXTRATODERENDIMENTOS" in texto and "CAIXINHA" in texto


def ler(caminho: Path, senha: str | None = None) -> ExtratoRendimentos:
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
        paginas = [pg.extract_words(extra_attrs=["size"]) for pg in pdf.pages]
        if not any(paginas[:2]):
            raise ErroLeitura("O PDF não tem texto (parece imagem escaneada)")

        cab = _compacto(" ".join(w["text"] for w in paginas[0]))
        faltando = [m for m in ("EXTRATODERENDIMENTOS", "CAIXINHA", "PERIODO:", "SALDONOFINALDOPERIODO")
                    if m not in cab]
        if faltando:
            raise ErroLeitura(
                "Layout não reconhecido: o PDF não parece ser o Extrato de Rendimentos das Caixinhas",
                "Marcas esperadas que não foram encontradas: " + ", ".join(faltando), 1,
            )
        m = RE_PERIODO.search(cab)
        if not m:
            raise ErroLeitura("Não encontrei o período no cabeçalho", cab[:300], 1)
        try:
            inicio = date(int(m.group(3)), MESES_ABREV[m.group(2)], int(m.group(1)))
            fim = date(int(m.group(6)), MESES_ABREV[m.group(5)], int(m.group(4)))
        except (KeyError, ValueError) as e:
            raise ErroLeitura("Período com data inválida", m.group(0), 1) from e

        # PJ ou PF: pelo título ("Caixinhas PJ") ou pelo rótulo ao lado do titular (CNPJ/CPF, no alto
        # da página). O CNPJ da instituição, mais abaixo, aparece nos dois casos e não serve de pista.
        topo = {_norm(w["text"]) for w in paginas[0] if w["top"] < 130}
        if "CAIXINHASPJ" in cab:
            tipo = "PJ"
        elif "CAIXINHASPF" in cab:
            tipo = "PF"
        else:
            tipo = "PF" if "CPF" in topo else ("PJ" if "CNPJ" in topo else None)
        ext = ExtratoRendimentos(LAYOUT, tipo, inicio, fim, len(pdf.pages))
        ext.titular_texto = " ".join(w["text"] for w in sorted(paginas[0], key=lambda w: (w["top"], w["x0"]))
                                     if 80 < w["top"] < 130)
        por_nome: dict[str, AplicacaoLida] = {}
        produto: str | None = None
        ordem: dict[tuple[str, date], int] = {}

        for n, palavras in enumerate(paginas, 1):
            linhas = _linhas(palavras)

            # 1) cabeçalhos de seção desta página: (top, aplicação)
            secoes: list[tuple[float, AplicacaoLida]] = []
            for l in linhas:
                texto = _compacto("".join(w["text"] for w in l))
                if 13.0 <= _tam(l[0]) <= 15.2 and l[0]["x0"] < 60:
                    produto = " ".join(w["text"] for w in l)
                    continue
                if "SALDONOFINALDOPERIODO:" not in texto:
                    continue
                nome_ws = [w for w in l if w["x0"] < 370 and _tam(w) >= 11.0]
                nome = " ".join(w["text"] for w in nome_ws).strip()
                saldo = None
                for i, w in enumerate(l):
                    if w["x0"] < 370:
                        continue
                    saldo = _dinheiro(w["text"])
                    if saldo is None and w["text"] == "R$" and i + 1 < len(l):
                        saldo = _dinheiro(l[i + 1]["text"])
                    if saldo is not None:
                        break
                if not nome or saldo is None:
                    ext.nao_reconhecidas.append((n, " ".join(w["text"] for w in l)))
                    continue
                ap = por_nome.get(_compacto(nome))
                if ap is None:
                    ap = AplicacaoLida(nome=nome, produto=produto, saldo_final=saldo)
                    por_nome[_compacto(nome)] = ap
                    ext.aplicacoes.append(ap)
                elif ap.saldo_final != saldo:
                    ext.nao_reconhecidas.append(
                        (n, f"{nome}: saldo final diferente entre páginas "
                            f"({formatar_centavos(ap.saldo_final)} e {formatar_centavos(saldo)})"))
                secoes.append((l[0]["top"], ap))

            # 2) tabela: textos em fonte 7,5
            tab = [w for w in palavras if 7.2 <= _tam(w) <= 7.8]
            if not tab:
                continue
            ancoras = [w for w in tab if w["x0"] < X_DATA_MAX and RE_DATA.match(w["text"])]
            linhas_tab = _linhas([w for w in tab if w not in ancoras])
            grupos: dict[int, list[dict]] = {id(a): [] for a in ancoras}
            for l in linhas_tab:
                if _compacto("".join(w["text"] for w in l)).startswith("DATAMOVIMENTACAO"):
                    continue                                       # cabeçalho da tabela
                for w in l:
                    perto = min(ancoras, key=lambda a: abs(a["top"] - w["top"]), default=None)
                    if perto is None or abs(perto["top"] - w["top"]) > TOL_ROTULO:
                        ext.nao_reconhecidas.append((n, " ".join(x["text"] for x in l)))
                        break
                    grupos[id(perto)].append(w)

            for a in sorted(ancoras, key=lambda w: w["top"]):
                ws = sorted(grupos[id(a)], key=lambda w: (round(w["top"], 1), w["x0"]))
                descricao = a["text"] + " " + " ".join(w["text"] for w in ws)
                dono = None
                for top, ap in secoes:
                    if top <= a["top"]:
                        dono = ap
                if dono is None:
                    ext.nao_reconhecidas.append((n, descricao + "  (linha fora de qualquer caixinha)"))
                    continue
                md = RE_DATA.match(a["text"])
                try:
                    d = date(int(md.group(3)), int(md.group(2)), int(md.group(1)))
                except ValueError:
                    ext.nao_reconhecidas.append((n, descricao))
                    continue
                rotulo: list[str] = []
                valores: dict[str, int] = {}
                ok = True
                for w in ws:
                    col = _coluna(w["x0"])
                    if col == "rotulo":
                        rotulo.append(w["text"])
                    elif w["text"] == "R$":
                        continue
                    else:
                        v = _dinheiro(w["text"])
                        if v is None or col is None or col in valores:
                            ok = False
                            break
                        valores[col] = v
                texto_rotulo = " ".join(rotulo).strip()
                if not ok or not texto_rotulo or not valores:
                    ext.nao_reconhecidas.append((n, descricao))
                    continue
                if set(valores) == {"rendimento"}:
                    dono.rendimentos.append(RendimentoLido(d, texto_rotulo, valores["rendimento"], n))
                elif "rendimento" not in valores and ("bruto" in valores or "liquido" in valores):
                    bruto = valores.get("bruto", valores.get("liquido"))
                    ir, iof = valores.get("ir", 0), valores.get("iof", 0)
                    liquido = valores.get("liquido", bruto - ir - iof)
                    chave = (_compacto(dono.nome), d)
                    ordem[chave] = ordem.get(chave, 0) + 1
                    dono.movimentos.append(MovLido(d, texto_rotulo, bruto, ir, iof, liquido, n, ordem[chave]))
                else:
                    ext.nao_reconhecidas.append((n, descricao))

        if not ext.aplicacoes:
            raise ErroLeitura("Não encontrei nenhuma caixinha no PDF",
                              "Esperava uma linha com o nome e 'Saldo no final do período'.", 1)
        return ext


def conferir(ext: ExtratoRendimentos) -> list[Problema]:
    """Travas de segurança. Lista vazia = pode importar."""
    f = formatar_centavos
    problemas: list[Problema] = []
    for pagina, texto in ext.nao_reconhecidas:
        problemas.append(Problema("Linha que não consegui interpretar", f"Página {pagina}: {texto}", pagina))
    for ap in ext.aplicacoes:
        for m in ap.movimentos:
            if m.liquido != m.bruto - m.ir - m.iof:
                problemas.append(Problema(
                    f"{ap.nome}: valor líquido de {m.data:%d/%m/%Y} não bate",
                    f"{m.tipo}: bruto {f(m.bruto)} - IR {f(m.ir)} - IOF {f(m.iof)} = {f(m.bruto - m.ir - m.iof)}\n"
                    f"Valor líquido no extrato: {f(m.liquido)}", m.pagina))
        fora = [x for x in [*ap.movimentos, *ap.rendimentos]
                if not (ext.periodo_inicio <= x.data <= ext.periodo_fim)]
        if fora:
            problemas.append(Problema(
                f"{ap.nome}: linhas com data fora do período do extrato",
                "\n".join(f"{x.data:%d/%m/%Y}" for x in fora[:20]), fora[0].pagina))
        meses = [r.data.strftime("%Y-%m") for r in ap.rendimentos]
        if len(meses) != len(set(meses)):
            problemas.append(Problema(
                f"{ap.nome}: mais de uma linha de rendimento no mesmo mês",
                "\n".join(f"{r.data:%d/%m/%Y} {r.rotulo} {f(r.valor)}" for r in ap.rendimentos), None))
    return problemas
