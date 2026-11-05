"""Importação de extratos: analisar (sem gravar) e importar (gravar).

Fluxo:
    analise = analisar(conta, caminho_pdf)   # lê, confere, compara com o banco
    if analise.pode_importar:
        importar(analise)                    # backup + grava + registra ocorrência

Duplicidade: cada movimentação recebe uma chave =
    conta + data + tipo + operação + contraparte + valor + nº da ocorrência no dia
O "nº da ocorrência" diferencia duas movimentações IDÊNTICAS no mesmo dia
(ex.: dois Pix de R$ 50 para a mesma pessoa): a 1ª é #1, a 2ª é #2.
Assim, um PDF atualizado (01–31) reconhece as que já vieram no PDF parcial (01–15)
e importa só as novas, sem perder as classificações já feitas.
"""

import hashlib
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from app import config
from app.backup.backup import fazer_backup
from app.banco.conexao import conectar, transacao
from app.contas.repositorio import Conta
from app.leitores import leitor_para
from app.leitores.base import ErroLeitura, ExtratoLido, ItemLido, Problema, conferir, formatar_centavos
from app.ocorrencias.registro import registrar

RE_PASTA_MES = re.compile(r"^\d{4}-\d{2}$")


# ------------------------------------------------------------------ utilidades

def hash_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", t).strip()


def chaves_duplicidade(conta_id: int, itens: list[ItemLido]) -> list[str]:
    """Uma chave por item, na mesma ordem."""
    vistos: dict[str, int] = {}
    chaves = []
    for i in itens:
        base = "|".join([
            str(conta_id), i.data.isoformat(), i.tipo, _normalizar(i.operacao),
            _normalizar(i.contraparte), str(i.valor),
        ])
        vistos[base] = vistos.get(base, 0) + 1
        chaves.append(hashlib.sha1(f"{base}#{vistos[base]}".encode()).hexdigest())
    return chaves


def caminho_relativo(caminho: Path) -> str:
    try:
        return str(Path(caminho).resolve().relative_to(config.raiz().resolve())).replace("\\", "/")
    except ValueError:
        return str(caminho)


def pdfs_pendentes(conta: Conta) -> list[Path]:
    """PDFs na pasta da conta que ainda não foram importados (pelo conteúdo, não pelo nome)."""
    pasta = config.pasta_extratos() / conta.pasta
    if not pasta.exists():
        return []
    conn = conectar()
    try:
        importados = {r[0] for r in conn.execute("SELECT hash_sha256 FROM documentos")}
        importados |= {r[0] for r in conn.execute("SELECT hash_sha256 FROM rendimento_documentos")}
    finally:
        conn.close()
    return sorted(
        p for p in pasta.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf" and hash_arquivo(p) not in importados
    )


# ------------------------------------------------------------------ análise

@dataclass
class Analise:
    conta: Conta
    caminho: Path
    hash: str
    tamanho: int
    extrato: ExtratoLido | None = None
    erro: ErroLeitura | None = None
    problemas: list[Problema] = field(default_factory=list)
    documento_existente: dict | None = None
    chaves: list[str] = field(default_factory=list)
    existentes: dict[str, int] = field(default_factory=dict)   # chave -> movimentacao_id
    sumidas: list[dict] = field(default_factory=list)          # no banco, mas não neste PDF

    @property
    def novas(self) -> list[tuple[ItemLido, str]]:
        return [(i, k) for i, k in zip(self.extrato.itens, self.chaves) if k not in self.existentes] \
            if self.extrato else []

    @property
    def pode_importar(self) -> bool:
        return (self.extrato is not None and self.erro is None and not self.problemas
                and self.documento_existente is None)


def analisar(conta: Conta, caminho: Path, senha: str | None = None,
             registrar_ocorrencias: bool = True) -> Analise:
    caminho = Path(caminho)
    a = Analise(conta=conta, caminho=caminho, hash=hash_arquivo(caminho),
                tamanho=caminho.stat().st_size)

    # mesmo arquivo já importado?
    conn = conectar()
    try:
        linha = conn.execute(
            "SELECT d.*, c.nome AS conta_nome FROM documentos d JOIN contas c ON c.id = d.conta_id"
            " WHERE d.hash_sha256 = ?", (a.hash,)
        ).fetchone()
    finally:
        conn.close()
    if linha:
        a.documento_existente = dict(linha)
        return a

    leitor = leitor_para(conta.banco)
    if leitor is None:
        a.erro = ErroLeitura(
            f"Ainda não existe leitor para extratos do banco {conta.banco}",
            "O leitor é construído a partir do layout mascarado do extrato.",
        )
    else:
        try:
            a.extrato = leitor(caminho, senha)
        except ErroLeitura as e:
            a.erro = e

    ext = a.extrato
    if ext and not a.erro:
        # conta certa?
        if conta.numero_conta and ext.numero_conta and \
                re.sub(r"\D", "", conta.numero_conta) != re.sub(r"\D", "", ext.numero_conta):
            a.erro = ErroLeitura(
                "O número da conta no extrato é diferente do cadastrado",
                f"Cadastro: {conta.numero_conta} · Extrato: {ext.numero_conta}",
            )

    if ext and not a.erro:
        a.problemas = conferir(ext)
        a.chaves = chaves_duplicidade(conta.id, ext.itens)
        conn = conectar()
        try:
            if a.chaves:
                marcas = ",".join("?" * len(a.chaves))
                for mid, chave in conn.execute(
                    f"SELECT id, chave_duplicidade FROM movimentacoes"
                    f" WHERE conta_id = ? AND chave_duplicidade IN ({marcas})",
                    [conta.id, *a.chaves],
                ):
                    a.existentes[chave] = mid
            # movimentações já gravadas, no período deste PDF, que não aparecem nele
            conjunto = set(a.chaves)
            for r in conn.execute(
                "SELECT id, data, tipo, valor, operacao, contraparte, chave_duplicidade"
                " FROM movimentacoes WHERE conta_id = ? AND status = 'ativa'"
                " AND data BETWEEN ? AND ?",
                (conta.id, ext.periodo_inicio.isoformat(), ext.periodo_fim.isoformat()),
            ):
                if r["chave_duplicidade"] not in conjunto:
                    a.sumidas.append(dict(r))
        finally:
            conn.close()

    if a.extrato and not a.erro and a.novas:
        from app.analise.indicadores import rotulo_mes
        from app.fechamento.servico import meses_fechados
        fechados = sorted({i.data.strftime("%Y-%m") for i, _ in a.novas} & meses_fechados())
        if fechados:
            nomes = ", ".join(rotulo_mes(m) for m in fechados)
            a.erro = ErroLeitura(
                f"O PDF traz movimentações novas em mês fechado ({nomes})",
                "Reabra o mês na tela Meses (informando o motivo) e importe de novo.",
            )

    if registrar_ocorrencias:
        _registrar_resultado_da_analise(a)
    return a


def _ja_aberta(arquivo: str, mensagem: str) -> bool:
    conn = conectar()
    try:
        return conn.execute(
            "SELECT 1 FROM ocorrencias WHERE arquivo = ? AND mensagem = ?"
            " AND precisa_acao = 1 AND resolvida_em IS NULL", (arquivo, mensagem),
        ).fetchone() is not None
    finally:
        conn.close()


def _registrar_resultado_da_analise(a: Analise) -> None:
    nome = a.caminho.name
    if a.erro:
        msg = f"Não importado: {a.erro.mensagem}"
        if not _ja_aberta(nome, msg):
            registrar("ERRO", "leitura", msg, detalhe=a.erro.detalhe, conta_id=a.conta.id,
                      arquivo=nome, pagina=a.erro.pagina)
    elif a.problemas:
        msg = f"Não importado: {len(a.problemas)} conferência(s) falharam"
        if not _ja_aberta(nome, msg):
            detalhe = "\n\n".join(
                f"• {p.mensagem}" + (f" (página {p.pagina})" if p.pagina else "") + f"\n{p.detalhe}"
                for p in a.problemas
            )
            registrar("CONFERIR", "conferencia_saldo", msg, detalhe=detalhe,
                      conta_id=a.conta.id, arquivo=nome, pagina=a.problemas[0].pagina)


# ------------------------------------------------------------------ importação

def _destino_pdf(conta: Conta, caminho: Path, ext: ExtratoLido, hash_: str) -> Path:
    """Onde o PDF fica guardado: extratos/<conta>/<AAAA-MM>/arquivo.pdf.

    Se já está numa subpasta da conta, fica onde está. Se está solto na pasta da
    conta ou fora dela, vai para a pasta do mês do início do período.
    """
    pasta_conta = (config.pasta_extratos() / conta.pasta).resolve()
    atual = caminho.resolve()
    if pasta_conta in atual.parents and atual.parent != pasta_conta:
        return atual
    pasta_mes = pasta_conta / ext.periodo_inicio.strftime("%Y-%m")
    pasta_mes.mkdir(parents=True, exist_ok=True)
    destino = pasta_mes / caminho.name
    n = 2
    while destino.exists() and hash_arquivo(destino) != hash_:
        destino = pasta_mes / f"{caminho.stem} ({n}){caminho.suffix}"
        n += 1
    return destino


def importar(a: Analise) -> int:
    if not a.pode_importar:
        raise ValueError("Esta análise não permite importação.")
    ext = a.extrato
    fazer_backup("antes-importacao")

    destino = _destino_pdf(a.conta, a.caminho, ext, a.hash)
    if destino != a.caminho.resolve():
        pasta_conta = (config.pasta_extratos() / a.conta.pasta).resolve()
        if a.caminho.resolve().parent == pasta_conta:
            shutil.move(str(a.caminho), destino)      # arruma na pasta do mês
        elif not destino.exists():
            shutil.copy2(a.caminho, destino)          # veio de fora: guarda uma cópia

    novas = a.novas
    with transacao() as conn:
        cur = conn.execute(
            "INSERT INTO documentos (conta_id, arquivo_nome, caminho, hash_sha256, tamanho_bytes,"
            " layout, periodo_inicio, periodo_fim, saldo_inicial, saldo_final, total_entradas,"
            " total_saidas, rendimento, qtd_lidas, qtd_novas, qtd_existentes, paginas)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a.conta.id, destino.name, caminho_relativo(destino), a.hash, a.tamanho, ext.layout,
             ext.periodo_inicio.isoformat(), ext.periodo_fim.isoformat(), ext.saldo_inicial,
             ext.saldo_final, ext.total_entradas, ext.total_saidas, ext.rendimento,
             len(ext.itens), len(novas), len(ext.itens) - len(novas), ext.paginas),
        )
        doc_id = cur.lastrowid

        for item, chave in zip(ext.itens, a.chaves):
            mov_id = a.existentes.get(chave)
            if mov_id is None:
                mov_id = conn.execute(
                    "INSERT INTO movimentacoes (conta_id, data, tipo, valor, operacao, contraparte,"
                    " descricao_original, ordem_no_dia, chave_duplicidade, documento_origem_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (a.conta.id, item.data.isoformat(), item.tipo, item.valor, item.operacao,
                     item.contraparte, item.descricao_original, item.ordem_no_dia, chave, doc_id),
                ).lastrowid
                a.existentes[chave] = mov_id
            conn.execute(
                "INSERT OR IGNORE INTO movimentacao_documento (movimentacao_id, documento_id, pagina)"
                " VALUES (?,?,?)", (mov_id, doc_id, item.pagina),
            )

        # primeira importação da conta: guarda o número que veio no extrato, para as próximas
        # serem reconhecidas (e conferidas) por ele
        if ext.numero_conta and not a.conta.numero_conta:
            conn.execute("UPDATE contas SET numero_conta = ? WHERE id = ? AND (numero_conta IS NULL OR numero_conta = '')",
                         (ext.numero_conta, a.conta.id))

        for dia, (saldo, _pag) in ext.saldos_dia.items():
            conn.execute(
                "INSERT OR REPLACE INTO saldos_diarios (conta_id, data, saldo, documento_id)"
                " VALUES (?,?,?,?)", (a.conta.id, dia.isoformat(), saldo, doc_id),
            )

    from app.classificacao.servico import aplicar_padroes  # import aqui evita ciclo
    aplicar_padroes()

    periodo = f"{ext.periodo_inicio:%d/%m/%Y} a {ext.periodo_fim:%d/%m/%Y}"
    registrar(
        "INFO", "importacao",
        f"Extrato importado ({periodo}): {len(ext.itens)} lidas, "
        f"{len(ext.itens) - len(novas)} já existentes, {len(novas)} novas",
        detalhe=(f"Saldo inicial {formatar_centavos(ext.saldo_inicial)} · "
                 f"Entradas {formatar_centavos(ext.total_entradas)} · "
                 f"Saídas {formatar_centavos(ext.total_saidas)} · "
                 f"Saldo final {formatar_centavos(ext.saldo_final)}\n"
                 f"Todas as conferências de saldo passaram."),
        conta_id=a.conta.id, arquivo=destino.name, documento_id=doc_id,
    )
    if a.sumidas:
        registrar(
            "REVISAR", "duplicidade",
            f"{len(a.sumidas)} movimentação(ões) de extratos anteriores não aparecem neste PDF",
            detalhe="Estavam em um PDF anterior do mesmo período, mas não neste:\n" + "\n".join(
                f"{r['data']} {r['tipo']} {formatar_centavos(r['valor'])} {r['operacao']} {r['contraparte'] or ''}"
                for r in a.sumidas[:50]
            ),
            conta_id=a.conta.id, arquivo=destino.name, documento_id=doc_id,
        )
    return doc_id
