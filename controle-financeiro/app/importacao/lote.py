"""Importação de vários PDFs de uma vez: o programa descobre de qual conta é cada um.

O usuário solta os PDFs na caixa de entrada (extratos/_entrada/). Para cada um:

1. Que tipo de PDF é?  extrato de conta (Nubank, Sicoob) ou rendimentos (Caixinhas).
2. De qual conta?  Entre as contas ATIVAS daquele banco:
     a) número da conta igual ao do cadastro (o cadastro é preenchido sozinho na
        primeira importação de cada conta);
     b) nome do titular do cadastro aparece no cabeçalho do PDF;
     c) PDF de caixinhas (não traz número de conta): a conta que já tem caixinhas
        com esses mesmos nomes.
   Se sobrar exatamente uma conta, é ela. Se não, o programa NÃO chuta: pede
   para o usuário escolher.
3. Mesmas conferências da importação manual. Nada é gravado antes do botão Importar.

Depois de importado, o PDF sai da caixa de entrada e fica guardado na pasta da conta.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from app import config
from app.banco.conexao import conectar
from app.contas import repositorio as contas_repo
from app.contas.repositorio import Conta
from app.importacao import servico
from app.leitores import MODULOS, banco_do_pdf
from app.leitores.base import ErroLeitura
from app.rendimentos import servico as rendimentos

PASTA_ENTRADA = "_entrada"
TIPO_CONTA, TIPO_RENDIMENTOS = "Extrato da conta", "Rendimentos (caixinhas)"


def pasta_entrada() -> Path:
    p = config.pasta_extratos() / PASTA_ENTRADA
    p.mkdir(parents=True, exist_ok=True)
    return p


def pdfs_na_entrada() -> list[Path]:
    return sorted(p for p in pasta_entrada().rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def guardar_na_entrada(nome: str, conteudo: bytes) -> Path:
    """Salva um PDF enviado pela tela (sem sobrescrever outro de mesmo nome e conteúdo diferente)."""
    destino = pasta_entrada() / Path(nome).name
    n = 2
    while destino.exists() and destino.read_bytes() != conteudo:
        destino = pasta_entrada() / f"{Path(nome).stem} ({n}).pdf"
        n += 1
    destino.write_bytes(conteudo)
    return destino


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def _digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def escolher_conta(banco: str | None, numero: str | None,
                   titular_texto: str, contas: list[Conta] | None = None) -> tuple[Conta | None, list[Conta], str]:
    """Devolve (conta ou None, candidatas, como foi decidido)."""
    contas = contas if contas is not None else contas_repo.listar(somente_ativas=True)
    cand = [c for c in contas if c.banco == banco] if banco else list(contas)
    if not cand:
        return None, [], "nenhuma conta ativa desse banco no cadastro"

    sobrou_por_numero = False
    if _digitos(numero):
        pelo_numero = [c for c in cand if _digitos(c.numero_conta) == _digitos(numero)]
        if len(pelo_numero) == 1:
            return pelo_numero[0], cand, "pelo número da conta"
        # contas com OUTRO número cadastrado não podem ser a deste PDF
        sem_numero = [c for c in cand if not _digitos(c.numero_conta)]
        sobrou_por_numero = len(sem_numero) < len(cand)
        cand = sem_numero
        if not cand:
            return None, [], "o número da conta do PDF não é de nenhuma conta cadastrada"

    if len(cand) == 1:
        return cand[0], cand, ("única conta desse banco ainda sem número cadastrado" if sobrou_por_numero
                               else "única conta desse banco")

    texto = _norm(titular_texto)
    palavras = set(re.findall(r"[A-Z0-9]+", texto))

    def bate(c: Conta, exato: bool) -> bool:
        nomes = re.findall(r"[A-Z0-9]+", _norm(c.titular))
        if not nomes:
            return False
        if exato:
            return all(n in palavras for n in nomes)
        colado = "".join(nomes)       # PDF que perde os espaços: o nome é o começo de uma palavra longa
        return len(colado) >= 4 and any(p.startswith(colado) for p in palavras)

    for exato in (True, False):          # primeiro palavra inteira; depois texto colado (PDF sem espaços)
        pelo_nome = [c for c in cand if bate(c, exato)]
        if len(pelo_nome) == 1:
            return pelo_nome[0], cand, "pelo nome do titular"
        if len(pelo_nome) > 1:
            return None, pelo_nome, "mais de uma conta combina com o nome do titular"
    return None, cand, "não achei o nome de nenhum titular cadastrado no PDF"


@dataclass
class ItemLote:
    caminho: Path
    tipo: str | None = None              # TIPO_CONTA | TIPO_RENDIMENTOS
    banco: str | None = None
    conta: Conta | None = None
    como: str = ""                       # como a conta foi identificada
    candidatas: list[Conta] = field(default_factory=list)
    analise: object | None = None        # servico.Analise | rendimentos.AnaliseRendimentos
    erro: ErroLeitura | None = None      # erro antes de chegar à análise (tipo não reconhecido etc.)

    @property
    def nome(self) -> str:
        return self.caminho.name

    @property
    def situacao(self) -> str:
        a = self.analise
        if self.erro or (a and a.erro):
            return "erro"
        if self.conta is None:
            return "sem_conta"
        if a is None:
            return "erro"
        if a.documento_existente:
            return "ja_importado"
        if a.problemas:
            return "conferencia"
        return "pronto" if a.pode_importar else "erro"

    @property
    def mensagem(self) -> str:
        a = self.analise
        e = self.erro or (a.erro if a else None)
        if e:
            return e.mensagem
        if self.conta is None:
            return f"Não identifiquei a conta ({self.como}). Escolha abaixo."
        if a and a.documento_existente:
            return "Este arquivo já foi importado antes."
        if a and a.problemas:
            return f"{len(a.problemas)} conferência(s) falharam: {a.problemas[0].mensagem}"
        return f"Conta identificada {self.como}."

    @property
    def periodo(self) -> tuple | None:
        ext = getattr(self.analise, "extrato", None)
        return (ext.periodo_inicio, ext.periodo_fim) if ext else None

    @property
    def qtd_novas(self) -> int | None:
        a = self.analise
        return len(a.novas) if a is not None and getattr(a, "extrato", None) is not None and not a.erro else None


def _analisar_com(item: ItemLote, conta: Conta, registrar: bool) -> None:
    item.conta = conta
    if item.tipo == TIPO_RENDIMENTOS:
        item.analise = rendimentos.analisar(conta, item.caminho, registrar_ocorrencias=registrar)
    else:
        item.analise = servico.analisar(conta, item.caminho, registrar_ocorrencias=registrar)


def _ja_importado(caminho: Path) -> dict | None:
    """O mesmo arquivo (pelo conteúdo) já está no banco? Devolve o registro, com a conta."""
    h = servico.hash_arquivo(caminho)
    conn = conectar()
    try:
        for tabela in ("documentos", "rendimento_documentos"):
            linha = conn.execute(f"SELECT conta_id FROM {tabela} WHERE hash_sha256 = ?", (h,)).fetchone()
            if linha:
                return {"tabela": tabela, "conta_id": linha["conta_id"]}
    finally:
        conn.close()
    return None


def analisar_arquivo(caminho: Path, conta: Conta | None = None, registrar_ocorrencias: bool = True) -> ItemLote:
    """Identifica o tipo e a conta de um PDF e faz as conferências. `conta` força a escolha (manual)."""
    caminho = Path(caminho)
    item = ItemLote(caminho)

    ja = _ja_importado(caminho)
    try:
        leitor_rend = rendimentos.leitor_de(caminho)
        if leitor_rend is not None:
            item.tipo = TIPO_RENDIMENTOS
            ext = leitor_rend.ler(caminho)
            item.banco = ext.banco
            numero = None
        else:
            item.banco = banco_do_pdf(caminho)
            if item.banco is None:
                # PDF com senha? arquivo corrompido? ou simplesmente um PDF que não é extrato
                try:
                    import pdfplumber
                    with pdfplumber.open(caminho) as pdf:
                        _ = pdf.pages[0].extract_text()
                except Exception as e:
                    raise ErroLeitura("Não consegui abrir o PDF (com senha ou corrompido?)",
                                      "Se tiver senha, importe pelo modo 'Um PDF (manual)'. " + repr(e)) from e
                raise ErroLeitura("Não reconheci este PDF como extrato do Nubank, do Sicoob ou de caixinhas",
                                  "Se for um tipo novo de extrato, envie uma amostra mascarada para criar o leitor.")
            item.tipo = TIPO_CONTA
            ext = MODULOS[item.banco].ler(caminho)
            numero = ext.numero_conta
    except ErroLeitura as e:
        item.erro = e
        if registrar_ocorrencias and not servico._ja_aberta(caminho.name, f"Não importado: {e.mensagem}"):
            servico.registrar("ERRO", "leitura", f"Não importado: {e.mensagem}", detalhe=e.detalhe,
                              arquivo=caminho.name, pagina=e.pagina)
        return item

    todas = contas_repo.listar()
    if ja:                                   # já importado: a conta é a do registro
        conta = next((c for c in todas if c.id == ja["conta_id"]), conta)
        item.como = "arquivo já importado"
    if conta is None:
        conta, item.candidatas, item.como = escolher_conta(item.banco, numero, ext.titular_texto)
        if conta is None and item.tipo == TIPO_RENDIMENTOS and len(item.candidatas) > 1:
            conta = _conta_pelas_caixinhas(ext, item.candidatas)
            if conta is not None:
                item.como = "pelas caixinhas que essa conta já tem"
    elif not ja:
        item.como = "escolhida por você"
    if conta is None:
        if not item.candidatas:
            item.candidatas = [c for c in todas if c.ativa and c.banco == item.banco] or [c for c in todas if c.ativa]
        # guarda o que já se sabe para mostrar o período mesmo sem conta
        item.analise = _SemConta(ext)
        return item
    _analisar_com(item, conta, registrar_ocorrencias)
    return item


def _conta_pelas_caixinhas(ext, candidatas: list[Conta]) -> Conta | None:
    """PDF de caixinhas não traz número de conta. Com duas contas do mesmo banco e do mesmo
    titular, a pista que sobra são as próprias caixinhas: se todas as do PDF já existem em
    exatamente UMA das contas candidatas, é dela. Na primeira vez (nenhuma cadastrada) não
    há como saber, e o programa pergunta."""
    nomes = {ap.nome for ap in ext.aplicacoes}
    if not nomes:
        return None
    ja = rendimentos.aplicacoes()
    donas = [c for c in candidatas if nomes <= {a["nome"] for a in ja if a["conta_id"] == c.id}]
    return donas[0] if len(donas) == 1 else None


@dataclass
class _SemConta:
    """Leitura feita, mas ainda sem conta: só para mostrar período na tabela."""
    extrato: object
    erro: None = None
    problemas: tuple = ()
    documento_existente: None = None
    pode_importar: bool = False
    novas: tuple = ()


def analisar_entrada(registrar_ocorrencias: bool = True) -> list[ItemLote]:
    return [analisar_arquivo(p, registrar_ocorrencias=registrar_ocorrencias) for p in pdfs_na_entrada()]


def _tirar_da_entrada(caminho: Path) -> None:
    try:
        if pasta_entrada().resolve() in caminho.resolve().parents and caminho.exists():
            caminho.unlink()
    except OSError:
        pass


def importar_prontos(itens: list[ItemLote]) -> tuple[list[ItemLote], list[tuple[ItemLote, str]]]:
    """Importa todos os prontos, em ordem de período. Devolve (importados, [(item, erro)])."""
    feitos, falhas = [], []
    prontos = sorted((i for i in itens if i.situacao == "pronto"), key=lambda i: (i.periodo or (None,))[0] or 0)
    for item in prontos:
        try:
            # refaz a análise: um PDF importado agora há pouco pode ter mudado o que é "novo"
            novo = analisar_arquivo(item.caminho, item.conta if item.como == "escolhida por você" else None,
                                    registrar_ocorrencias=True)
            if novo.situacao != "pronto":
                falhas.append((item, novo.mensagem))
                continue
            if novo.tipo == TIPO_RENDIMENTOS:
                rendimentos.importar(novo.analise)
            else:
                servico.importar(novo.analise)
            _tirar_da_entrada(item.caminho)      # a cópia guardada fica na pasta da conta
            item.analise, item.conta = novo.analise, novo.conta
            feitos.append(item)
        except Exception as e:                   # um PDF com problema não impede os outros
            falhas.append((item, f"{type(e).__name__}: {e}"))
    return feitos, falhas


def limpar_ja_importados(itens: list[ItemLote]) -> int:
    """Tira da caixa de entrada os PDFs que já estão guardados na pasta da conta."""
    n = 0
    for item in itens:
        if item.situacao == "ja_importado":
            guardado = config.raiz() / item.analise.documento_existente["caminho"]
            if guardado.exists() and guardado.resolve() != item.caminho.resolve():
                _tirar_da_entrada(item.caminho)
                n += 1
    return n
