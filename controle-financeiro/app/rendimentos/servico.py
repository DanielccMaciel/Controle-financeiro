"""Caixinhas e rendimentos: analisar (sem gravar), importar e consultar.

O PDF de rendimentos NÃO é um extrato de conta: não gera movimentações nem entra
no resultado do mês. Ele alimenta só a tela Caixinhas (saldo guardado,
rendimento por mês, resgates com IR/IOF). Todas as caixinhas são da mesma pessoa.

Duplicidade: cada linha de resgate/aplicação tem uma chave =
    caixinha + data + tipo + bruto + IR + IOF + líquido + nº da ocorrência no dia
O rendimento é um valor por mês: um PDF mais recente do mesmo mês substitui o anterior.
"""

import hashlib
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app import config
from app.backup.backup import fazer_backup
from app.banco.conexao import conectar, transacao
from app.contas.repositorio import Conta
from app.importacao.servico import _ja_aberta, caminho_relativo, hash_arquivo
from app.leitores.base import ErroLeitura, Problema, formatar_centavos
from app.ocorrencias.registro import registrar
from app.rendimentos import leitor_nubank
from app.rendimentos.leitor_nubank import AplicacaoLida, ExtratoRendimentos, MovLido

SUBPASTA = "caixinhas"


# Um leitor por tipo de PDF de rendimento. Cada um tem: e_extrato_de_rendimentos(caminho, senha),
# ler(caminho, senha) -> ExtratoRendimentos e conferir(extrato) -> list[Problema].
# Para o rendimento de outro banco basta criar app/rendimentos/leitor_<banco>.py com essas três
# funções e acrescentá-lo aqui: importação, tela e totais já funcionam para qualquer banco.
LEITORES = [leitor_nubank]


def leitor_de(caminho: Path, senha: str | None = None):
    for leitor in LEITORES:
        if leitor.e_extrato_de_rendimentos(Path(caminho), senha):
            return leitor
    return None


def e_pdf_de_rendimentos(caminho: Path, senha: str | None = None) -> bool:
    return leitor_de(caminho, senha) is not None


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", "", t)


def _linhas(sql: str, params=()) -> list[dict]:
    conn = conectar()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _chave(nome: str, m: MovLido) -> str:
    base = "|".join([_norm(nome), m.data.isoformat(), _norm(m.tipo), str(m.bruto), str(m.ir),
                     str(m.iof), str(m.liquido)])
    return hashlib.sha1(f"{base}#{m.ordem_no_dia}".encode()).hexdigest()


def _reordenar(ap: AplicacaoLida) -> None:
    """Nº da ocorrência entre linhas IDÊNTICAS do mesmo dia (não a posição no dia),
    para que um PDF parcial e o completo gerem as mesmas chaves."""
    vistos: dict[tuple, int] = {}
    for m in ap.movimentos:
        k = (m.data, _norm(m.tipo), m.bruto, m.ir, m.iof, m.liquido)
        vistos[k] = vistos.get(k, 0) + 1
        m.ordem_no_dia = vistos[k]


# ------------------------------------------------------------------ análise

@dataclass
class AnaliseRendimentos:
    conta: Conta
    caminho: Path
    hash: str
    tamanho: int
    extrato: ExtratoRendimentos | None = None
    erro: ErroLeitura | None = None
    problemas: list[Problema] = field(default_factory=list)
    documento_existente: dict | None = None
    existentes: set[str] = field(default_factory=set)      # chaves já gravadas

    @property
    def movimentos(self) -> list[tuple[AplicacaoLida, MovLido, str]]:
        if not self.extrato:
            return []
        return [(ap, m, _chave(ap.nome, m)) for ap in self.extrato.aplicacoes for m in ap.movimentos]

    @property
    def novas(self) -> list[tuple[AplicacaoLida, MovLido, str]]:
        return [x for x in self.movimentos if x[2] not in self.existentes]

    @property
    def pode_importar(self) -> bool:
        return (self.extrato is not None and self.erro is None and not self.problemas
                and self.documento_existente is None)


def analisar(conta: Conta, caminho: Path, senha: str | None = None,
             registrar_ocorrencias: bool = True) -> AnaliseRendimentos:
    caminho = Path(caminho)
    a = AnaliseRendimentos(conta, caminho, hash_arquivo(caminho), caminho.stat().st_size)

    existente = _linhas(
        "SELECT d.*, c.nome AS conta_nome FROM rendimento_documentos d JOIN contas c ON c.id = d.conta_id"
        " WHERE d.hash_sha256 = ?", (a.hash,))
    if existente:
        a.documento_existente = existente[0]
        return a

    leitor = leitor_de(caminho, senha) or leitor_nubank
    try:
        a.extrato = leitor.ler(caminho, senha)
    except ErroLeitura as e:
        a.erro = e

    ext = a.extrato
    if ext and not a.erro:
        for ap in ext.aplicacoes:
            _reordenar(ap)
        a.problemas = leitor.conferir(ext)
        chaves = [k for _, _, k in a.movimentos]
        if chaves:
            marcas = ",".join("?" * len(chaves))
            a.existentes = {r["chave"] for r in _linhas(
                f"SELECT m.chave FROM aplicacao_movimentos m JOIN aplicacoes ap ON ap.id = m.aplicacao_id"
                f" WHERE ap.conta_id = ? AND m.chave IN ({marcas})", [conta.id, *chaves])}

    if registrar_ocorrencias:
        nome = caminho.name
        if a.erro:
            msg = f"Não importado: {a.erro.mensagem}"
            if not _ja_aberta(nome, msg):
                registrar("ERRO", "leitura", msg, detalhe=a.erro.detalhe,
                          conta_id=conta.id, arquivo=nome, pagina=a.erro.pagina)
        elif a.problemas and not _ja_aberta(nome, f"Não importado: {len(a.problemas)} conferência(s) falharam"):
            registrar("CONFERIR", "conferencia_saldo",
                      f"Não importado: {len(a.problemas)} conferência(s) falharam",
                      detalhe="\n\n".join(f"• {p.mensagem}\n{p.detalhe}" for p in a.problemas),
                      conta_id=conta.id, arquivo=nome, pagina=a.problemas[0].pagina)
    return a


# ------------------------------------------------------------------ importação

def _destino(conta: Conta, caminho: Path, ext: ExtratoRendimentos, hash_: str) -> Path:
    """extratos/<conta>/caixinhas/<AAAA-MM>/arquivo.pdf (fica onde está se já estiver numa subpasta)."""
    pasta_conta = (config.pasta_extratos() / conta.pasta).resolve()
    atual = caminho.resolve()
    if pasta_conta in atual.parents and atual.parent != pasta_conta:
        return atual
    pasta = pasta_conta / SUBPASTA / ext.periodo_inicio.strftime("%Y-%m")
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / caminho.name
    n = 2
    while destino.exists() and hash_arquivo(destino) != hash_:
        destino = pasta / f"{caminho.stem} ({n}){caminho.suffix}"
        n += 1
    return destino


def importar(a: AnaliseRendimentos) -> int:
    if not a.pode_importar:
        raise ValueError("Esta análise não permite importação.")
    ext = a.extrato
    fazer_backup("antes-importacao")

    destino = _destino(a.conta, a.caminho, ext, a.hash)
    if destino != a.caminho.resolve():
        pasta_conta = (config.pasta_extratos() / a.conta.pasta).resolve()
        if a.caminho.resolve().parent == pasta_conta:
            shutil.move(str(a.caminho), destino)
        elif not destino.exists():
            shutil.copy2(a.caminho, destino)

    novas = a.novas
    with transacao() as conn:
        doc_id = conn.execute(
            "INSERT INTO rendimento_documentos (conta_id, arquivo_nome, caminho, hash_sha256, tamanho_bytes,"
            " layout, periodo_inicio, periodo_fim, paginas, qtd_lidas, qtd_novas) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (a.conta.id, destino.name, caminho_relativo(destino), a.hash, a.tamanho, ext.layout,
             ext.periodo_inicio.isoformat(), ext.periodo_fim.isoformat(), ext.paginas,
             len(a.movimentos), len(novas)),
        ).lastrowid

        for ap in ext.aplicacoes:
            linha = conn.execute("SELECT id FROM aplicacoes WHERE conta_id = ? AND nome = ?",
                                 (a.conta.id, ap.nome)).fetchone()
            ap_id = linha["id"] if linha else conn.execute(
                "INSERT INTO aplicacoes (conta_id, nome, produto) VALUES (?,?,?)",
                (a.conta.id, ap.nome, ap.produto)).lastrowid

            for m in ap.movimentos:
                conn.execute(
                    "INSERT OR IGNORE INTO aplicacao_movimentos (aplicacao_id, data, tipo, valor_bruto, ir, iof,"
                    " valor_liquido, ordem_no_dia, chave, documento_id, pagina) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (ap_id, m.data.isoformat(), m.tipo, m.bruto, m.ir, m.iof, m.liquido, m.ordem_no_dia,
                     _chave(ap.nome, m), doc_id, m.pagina))

            for r in ap.rendimentos:
                mes = r.data.strftime("%Y-%m")
                atual = conn.execute("SELECT data FROM aplicacao_rendimentos WHERE aplicacao_id = ? AND mes = ?",
                                     (ap_id, mes)).fetchone()
                if atual is None:
                    conn.execute(
                        "INSERT INTO aplicacao_rendimentos (aplicacao_id, mes, data, valor, rotulo, documento_id)"
                        " VALUES (?,?,?,?,?,?)", (ap_id, mes, r.data.isoformat(), r.valor, r.rotulo, doc_id))
                elif r.data.isoformat() >= atual["data"]:      # PDF mais completo do mesmo mês
                    conn.execute(
                        "UPDATE aplicacao_rendimentos SET data = ?, valor = ?, rotulo = ?, documento_id = ?"
                        " WHERE aplicacao_id = ? AND mes = ?",
                        (r.data.isoformat(), r.valor, r.rotulo, doc_id, ap_id, mes))

            conn.execute(
                "INSERT OR REPLACE INTO aplicacao_saldos (aplicacao_id, data, saldo, documento_id) VALUES (?,?,?,?)",
                (ap_id, ext.periodo_fim.isoformat(), ap.saldo_final, doc_id))

    f = formatar_centavos
    registrar(
        "INFO", "importacao",
        f"Rendimentos importados ({ext.periodo_inicio:%d/%m/%Y} a {ext.periodo_fim:%d/%m/%Y}): "
        f"{len(ext.aplicacoes)} caixinha(s), {len(a.movimentos)} linha(s), {len(novas)} nova(s)",
        detalhe="\n".join(
            f"{ap.nome}: saldo final {f(ap.saldo_final)} · rendimento "
            f"{f(sum(r.valor for r in ap.rendimentos))} · {len(ap.movimentos)} movimentação(ões)"
            for ap in ext.aplicacoes),
        conta_id=a.conta.id, arquivo=destino.name,
    )
    return doc_id


# ------------------------------------------------------------------ consultas

def nome_exibicao(ap: dict) -> str:
    return ap.get("apelido") or ap["nome"]


def aplicacoes() -> list[dict]:
    return _linhas(
        "SELECT ap.*, c.nome AS conta_nome, c.banco, c.titular FROM aplicacoes ap"
        " JOIN contas c ON c.id = ap.conta_id ORDER BY c.banco, c.id, ap.nome")


def definir_apelido(aplicacao_id: int, apelido: str | None) -> None:
    """Nome para mostrar na tela (ex.: "Reserva de emergência"). Vazio = usa o nome do PDF."""
    with transacao() as conn:
        conn.execute("UPDATE aplicacoes SET apelido = ? WHERE id = ?",
                     ((apelido or "").strip() or None, aplicacao_id))


def filtrar(banco: str | None = None, conta_ids: list[int] | None = None) -> list[int]:
    """Ids das caixinhas que passam nos filtros (None = não filtra por aquele critério)."""
    saida = []
    for ap in aplicacoes():
        if banco and ap["banco"] != banco:
            continue
        if conta_ids and ap["conta_id"] not in conta_ids:
            continue
        saida.append(ap["id"])
    return saida


def rendimento_por_mes_e_banco(ids: list[int] | None = None) -> dict[str, dict[str, int]]:
    """{banco: {AAAA-MM: centavos}} — para o gráfico empilhado por banco."""
    f, p = _filtro(ids, "r.aplicacao_id")
    saida: dict[str, dict[str, int]] = {}
    for r in _linhas(
        f"SELECT c.banco, r.mes, SUM(r.valor) AS v FROM aplicacao_rendimentos r"
        f" JOIN aplicacoes ap ON ap.id = r.aplicacao_id JOIN contas c ON c.id = ap.conta_id"
        f" WHERE 1=1{f} GROUP BY c.banco, r.mes ORDER BY r.mes", p):
        saida.setdefault(r["banco"], {})[r["mes"]] = r["v"]
    return saida


def ultimo_periodo(aplicacao_id: int) -> str | None:
    """Data do último saldo informado para a caixinha (até quando temos PDF)."""
    linhas = _linhas("SELECT MAX(data) AS d FROM aplicacao_saldos WHERE aplicacao_id = ?", (aplicacao_id,))
    return linhas[0]["d"] if linhas else None


def _filtro(ids: list[int] | None, coluna: str) -> tuple[str, list]:
    if ids is None:           # None = todas
        return "", []
    if not ids:               # lista vazia = nenhuma
        return " AND 0", []
    return f" AND {coluna} IN ({','.join('?' * len(ids))})", list(ids)


def rendimento_por_mes(ids: list[int] | None = None) -> dict[str, int]:
    """{AAAA-MM: centavos} somando as caixinhas escolhidas."""
    f, p = _filtro(ids, "aplicacao_id")
    return {r["mes"]: r["v"] for r in _linhas(
        f"SELECT mes, SUM(valor) AS v FROM aplicacao_rendimentos WHERE 1=1{f} GROUP BY mes ORDER BY mes", p)}


def movimentos_por_mes(ids: list[int] | None = None) -> dict[str, dict]:
    """{AAAA-MM: {tipo: {'qtd', 'bruto', 'ir', 'iof', 'liquido'}}}"""
    f, p = _filtro(ids, "aplicacao_id")
    saida: dict[str, dict] = {}
    for r in _linhas(
        f"SELECT substr(data,1,7) AS mes, tipo, COUNT(*) AS qtd, SUM(valor_bruto) AS bruto, SUM(ir) AS ir,"
        f" SUM(iof) AS iof, SUM(valor_liquido) AS liquido FROM aplicacao_movimentos WHERE 1=1{f}"
        f" GROUP BY mes, tipo ORDER BY mes", p):
        saida.setdefault(r["mes"], {})[r["tipo"]] = r
    return saida


def saldos(ids: list[int] | None = None) -> list[dict]:
    """Todos os saldos informados, por caixinha e data."""
    f, p = _filtro(ids, "s.aplicacao_id")
    return _linhas(
        f"SELECT s.aplicacao_id, s.data, s.saldo, ap.nome, ap.apelido FROM aplicacao_saldos s"
        f" JOIN aplicacoes ap ON ap.id = s.aplicacao_id WHERE 1=1{f} ORDER BY s.data", p)


def saldo_total_em(data_limite: str, ids: list[int] | None = None) -> tuple[int | None, str | None]:
    """Soma do último saldo conhecido de cada caixinha até a data. Retorna (total, data mais antiga usada)."""
    f, p = _filtro(ids, "s.aplicacao_id")
    linhas = _linhas(
        f"SELECT s.aplicacao_id, s.saldo, s.data FROM aplicacao_saldos s WHERE s.data <= ?{f}"
        f" AND s.data = (SELECT MAX(x.data) FROM aplicacao_saldos x"
        f"               WHERE x.aplicacao_id = s.aplicacao_id AND x.data <= ?)", [data_limite, *p, data_limite])
    if not linhas:
        return None, None
    return sum(r["saldo"] for r in linhas), min(r["data"] for r in linhas)


def saldo_total_por_data(ids: list[int] | None = None) -> list[tuple[str, int]]:
    """Série para o gráfico: em cada data com saldo informado, a soma do último saldo de cada caixinha."""
    datas = sorted({r["data"] for r in saldos(ids)})
    return [(d, saldo_total_em(d, ids)[0]) for d in datas]


def movimentos(ids: list[int] | None = None, mes: str | None = None) -> list[dict]:
    f, p = _filtro(ids, "m.aplicacao_id")
    if mes:
        f += " AND substr(m.data,1,7) = ?"
        p.append(mes)
    return _linhas(
        f"SELECT m.*, ap.nome, ap.apelido, d.arquivo_nome FROM aplicacao_movimentos m"
        f" JOIN aplicacoes ap ON ap.id = m.aplicacao_id"
        f" JOIN rendimento_documentos d ON d.id = m.documento_id WHERE 1=1{f}"
        f" ORDER BY m.data, m.id", p)


def documentos() -> list[dict]:
    return _linhas(
        "SELECT d.*, c.nome AS conta_nome FROM rendimento_documentos d JOIN contas c ON c.id = d.conta_id"
        " ORDER BY d.periodo_inicio DESC, d.id DESC")


def meses_com_dados(ids: list[int] | None = None) -> list[str]:
    meses = set(rendimento_por_mes(ids)) | set(movimentos_por_mes(ids)) | {r["data"][:7] for r in saldos(ids)}
    return sorted(meses)


@dataclass
class ResumoCaixinhas:
    mes: str
    rendimento: int | None       # None = sem PDF de rendimentos desse mês
    saldo: int | None
    saldo_em: str | None
    resgates_liquido: int
    impostos: int                # IR + IOF retidos nos resgates


def resumo_do_mes(mes: str, ids: list[int] | None = None) -> ResumoCaixinhas:
    ano, m = int(mes[:4]), int(mes[5:7])
    fim = date(ano + (m == 12), (m % 12) + 1, 1).isoformat()   # 1º dia do mês seguinte (exclusivo)
    f, p = _filtro(ids, "s.aplicacao_id")
    linhas = _linhas(
        f"SELECT s.saldo, s.data FROM aplicacao_saldos s WHERE s.data < ?{f}"
        f" AND s.data = (SELECT MAX(x.data) FROM aplicacao_saldos x"
        f"               WHERE x.aplicacao_id = s.aplicacao_id AND x.data < ?)", [fim, *p, fim])
    do_mes = [r for r in linhas if r["data"][:7] == mes]
    mov = movimentos_por_mes(ids).get(mes, {})
    resg = [v for t, v in mov.items() if _norm(t).startswith("RESGATE")]
    return ResumoCaixinhas(
        mes=mes,
        rendimento=rendimento_por_mes(ids).get(mes),
        saldo=sum(r["saldo"] for r in do_mes) if do_mes else None,
        saldo_em=max(r["data"] for r in do_mes) if do_mes else None,
        resgates_liquido=sum(v["liquido"] for v in resg),
        impostos=sum(v["ir"] + v["iof"] for v in mov.values()),
    )


def tem_dados() -> bool:
    return bool(_linhas("SELECT 1 FROM aplicacoes LIMIT 1"))
