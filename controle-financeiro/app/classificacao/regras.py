"""Regras de classificação.

Uma regra = CONDIÇÃO → RESULTADO.
    Condição:  campo (contraparte | operacao | descricao)
               + tipo (contem "texto" | cnpj "14 dígitos")
               + filtros opcionais: tipo da movimentação (Entrada/Saída), conta
    Resultado: categoria › subcategoria
    Ação:      aplicar (classifica direto, confiança Alta) | sugerir (você confirma, confiança Média)

Quando várias regras batem: vence a de MAIOR prioridade; empate → CNPJ ganha de "contém";
se ainda assim duas regras mandam coisas diferentes → CONFLITO: nada é aplicado, fica em
Revisar com a explicação (o programa não escolhe por você).
"""

import re
import unicodedata
from dataclasses import dataclass

from app.banco.conexao import conectar, transacao

RE_CNPJ = re.compile(r"(\d{2})\.(\d{3})\.(\d{3})\s*/\s*(\d{4})\s*-\s*(\d{2})")
CAMPOS = {"contraparte": "Contraparte", "operacao": "Operação", "descricao": "Descrição completa"}
CONDICOES = {"contem": "contém o texto", "cnpj": "tem o CNPJ"}


class ErroRegra(ValueError):
    pass


def normalizar(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).upper().split())


def cnpjs(texto: str | None) -> set[str]:
    """Todos os CNPJs (só dígitos) que aparecem no texto, mesmo quebrados por espaço."""
    return {"".join(m) for m in RE_CNPJ.findall(texto or "")}


def formatar_cnpj(d: str) -> str:
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else d


@dataclass
class Regra:
    id: int
    nome: str
    campo: str
    condicao: str
    texto: str
    tipo_mov: str | None
    conta_id: int | None
    acao: str
    subcategoria_id: int
    prioridade: int
    ativa: bool
    origem: str
    vezes_aplicada: int
    observacoes: str | None
    criada_em: str
    resultado: str | None = None   # "Categoria › Subcategoria" (para exibir)
    conta_nome: str | None = None  # quando a regra vale só para uma conta

    def descrever_condicao(self) -> str:
        alvo = formatar_cnpj(self.texto) if self.condicao == "cnpj" else f'"{self.texto}"'
        partes = [f"{CAMPOS[self.campo]} {CONDICOES[self.condicao]} {alvo}"]
        if self.tipo_mov:
            partes.append(self.tipo_mov.lower())
        if self.conta_id:
            partes.append(f"só na conta {self.conta_nome or self.conta_id}")
        return " · ".join(partes)

    def bate(self, mov: dict) -> bool:
        if self.tipo_mov and mov["tipo"] != self.tipo_mov:
            return False
        if self.conta_id and mov["conta_id"] != self.conta_id:
            return False
        valor = {
            "contraparte": mov.get("contraparte"),
            "operacao": mov.get("operacao"),
            "descricao": mov.get("descricao_original"),
        }[self.campo]
        if self.condicao == "cnpj":
            return self.texto in cnpjs(valor)
        texto_mov = normalizar(valor)
        # alguns PDFs trazem o texto sem espaços ("ResgateRDB"): compara também sem eles
        return self.texto in texto_mov or self.texto.replace(" ", "") in texto_mov.replace(" ", "")


def listar(incluir_inativas: bool = True) -> list[Regra]:
    conn = conectar()
    try:
        sql = (
            "SELECT r.*, c.nome || ' › ' || s.nome AS resultado, ct.nome AS conta_nome FROM regras r"
            " LEFT JOIN subcategorias s ON s.id = r.subcategoria_id"
            " LEFT JOIN categorias c ON c.id = s.categoria_id"
            " LEFT JOIN contas ct ON ct.id = r.conta_id"
        )
        if not incluir_inativas:
            sql += " WHERE r.ativa = 1"
        linhas = conn.execute(sql + " ORDER BY r.prioridade DESC, r.nome").fetchall()
    finally:
        conn.close()
    regras = []
    for r in linhas:
        d = dict(r)
        d["ativa"] = bool(d["ativa"])
        regras.append(Regra(**d))
    return regras


# ------------------------------------------------------------------ avaliação

@dataclass
class Decisao:
    regra: Regra | None = None
    conflito: list[Regra] | None = None


def decidir(mov: dict, regras: list[Regra]) -> Decisao:
    candidatas = [r for r in regras if r.ativa and r.bate(mov)]
    if not candidatas:
        return Decisao()
    candidatas.sort(key=lambda r: (-r.prioridade, 0 if r.condicao == "cnpj" else 1, r.id))
    topo = candidatas[0]
    empatadas = [r for r in candidatas
                 if r.prioridade == topo.prioridade and (r.condicao == "cnpj") == (topo.condicao == "cnpj")]
    resultados = {r.subcategoria_id for r in empatadas}
    if len(resultados) > 1:
        return Decisao(conflito=empatadas)
    return Decisao(regra=topo)


def movimentacoes_para_avaliar(somente_novas: bool) -> list[dict]:
    """Só o que está em Revisar e nunca foi decidido por você (origem manual fica de fora)."""
    conn = conectar()
    try:
        sql = (
            "SELECT m.id, m.conta_id, m.tipo, m.operacao, m.contraparte, m.descricao_original"
            " FROM movimentacoes m"
            " WHERE m.status = 'ativa' AND m.classificacao = 'Revisar'"
            " AND (m.origem_classificacao IS NULL OR m.origem_classificacao IN ('regra', 'padrao'))"
        )
        if somente_novas:
            sql += " AND m.padroes_avaliados = 0"
        sql += " AND substr(m.data, 1, 7) NOT IN (SELECT mes FROM meses WHERE status = 'Fechado')"
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def testar(regra: Regra) -> list[dict]:
    """Quais movimentações (de qualquer classificação) esta regra pegaria. Não altera nada."""
    conn = conectar()
    try:
        movs = [dict(r) for r in conn.execute(
            "SELECT m.id, m.data, m.conta_id, m.tipo, m.valor, m.operacao, m.contraparte,"
            " m.descricao_original, m.classificacao, c.nome AS conta_nome,"
            " cat.nome || ' › ' || s.nome AS categoria_rotulo"
            " FROM movimentacoes m JOIN contas c ON c.id = m.conta_id"
            " LEFT JOIN subcategorias s ON s.id = m.subcategoria_id"
            " LEFT JOIN categorias cat ON cat.id = s.categoria_id WHERE m.status = 'ativa'"
            " ORDER BY m.data"
        )]
    finally:
        conn.close()
    return [m for m in movs if regra.bate(m)]


# ------------------------------------------------------------------ criar / alterar

def criar(*, nome: str, campo: str, condicao: str, texto: str,
          subcategoria_id: int | None, acao: str = "aplicar", tipo_mov: str | None = None,
          conta_id: int | None = None, prioridade: int = 50,
          origem: str = "usuario", observacoes: str | None = None) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ErroRegra("Dê um nome para a regra.")
    if campo not in CAMPOS or condicao not in CONDICOES:
        raise ErroRegra("Condição inválida.")
    if acao not in ("aplicar", "sugerir"):
        raise ErroRegra("Ação inválida.")
    if not subcategoria_id:
        raise ErroRegra("A regra precisa de categoria e subcategoria.")
    if condicao == "cnpj":
        texto = re.sub(r"\D", "", texto or "")
        if len(texto) != 14:
            raise ErroRegra("CNPJ deve ter 14 dígitos.")
    else:
        texto = normalizar(texto)
        if len(texto) < 3:
            raise ErroRegra("O texto da regra precisa ter pelo menos 3 letras.")
    with transacao() as conn:
        return conn.execute(
            "INSERT INTO regras (nome, campo, condicao, texto, tipo_mov, conta_id, acao,"
            " subcategoria_id, prioridade, origem, observacoes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (nome, campo, condicao, texto, tipo_mov, conta_id, acao,
             subcategoria_id, prioridade, origem, observacoes),
        ).lastrowid


def alterar(regra_id: int, **campos) -> None:
    permitidos = {"ativa", "acao", "prioridade", "nome", "observacoes"}
    if not set(campos) <= permitidos:
        raise ErroRegra(f"Campos não permitidos: {set(campos) - permitidos}")
    with transacao() as conn:
        antes = dict(conn.execute("SELECT * FROM regras WHERE id = ?", (regra_id,)).fetchone())
        for k, v in campos.items():
            if k == "ativa":
                v = int(bool(v))
            if antes[k] != v:
                conn.execute(f"UPDATE regras SET {k} = ? WHERE id = ?", (v, regra_id))
                conn.execute(
                    "INSERT INTO auditoria (tabela, registro_id, campo, valor_antigo, valor_novo, motivo)"
                    " VALUES ('regras', ?, ?, ?, ?, 'alteração da regra')",
                    (regra_id, k, None if antes[k] is None else str(antes[k]), str(v)),
                )


def proposta_a_partir_de(mov: dict) -> dict:
    """Condição sugerida para 'criar regra a partir desta movimentação'."""
    achados = cnpjs(mov.get("contraparte"))
    if achados:
        cnpj = sorted(achados)[0]
        nome = (mov.get("contraparte") or "").split(" - ")[0].strip()[:60] or formatar_cnpj(cnpj)
        return {"campo": "contraparte", "condicao": "cnpj", "texto": cnpj, "nome": nome}
    if mov.get("contraparte"):
        nome = mov["contraparte"].split(" - ")[0].strip()
        return {"campo": "contraparte", "condicao": "contem", "texto": normalizar(nome)[:60], "nome": nome[:60]}
    return {"campo": "operacao", "condicao": "contem", "texto": normalizar(mov["operacao"]),
            "nome": mov["operacao"]}
