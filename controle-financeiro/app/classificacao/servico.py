"""Classificação das movimentações.

Tudo aqui é pessoal: classificar uma movimentação é escolher a CATEGORIA dela.
Classificação:  Classificada | Revisar
- Classificada → tem subcategoria (a categoria vem da subcategoria) e entra nos números.
- Revisar      → ainda sem categoria; fica fora dos números até você decidir.

Cada categoria tem uma NATUREZA, que diz como ela entra nos números:
    receita · despesa
    investimento (dinheiro que sai da conta para virar patrimônio: corretora,
                  previdência...; fica separado do resultado do mês)
    neutro (dinheiro mudando de lugar: Resgate/Aplicação RDB, entre as suas contas,
            dinheiro de terceiros)

Classificação automática: as REGRAS (tabela `regras`, tela Regras) e um padrão
embutido: Pix/transferência em que a outra ponta tem o nome do titular das contas
→ SUGESTÃO de "Transferência entre minhas contas".
Toda alteração manual vai para a tabela `auditoria`.
"""

import unicodedata
from dataclasses import dataclass

from app.banco.conexao import conectar, transacao

CLASSIFICADA, REVISAR = "Classificada", "Revisar"
CLASSIFICACOES = (CLASSIFICADA, REVISAR)
NATUREZAS = {
    "receita": "Receita",
    "despesa": "Despesa",
    "investimento": "Investimento (fora do resultado do mês)",
    "neutro": "Neutro (não entra no resultado)",
}


class ErroClassificacao(ValueError):
    pass


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).upper().split())


# ------------------------------------------------------------------ categorias

@dataclass
class Subcategoria:
    id: int
    nome: str
    categoria_id: int
    categoria: str
    natureza: str
    ativa: bool

    @property
    def rotulo(self) -> str:
        return f"{self.categoria} › {self.nome}"


def listar_categorias(incluir_inativas: bool = False) -> list[dict]:
    conn = conectar()
    try:
        sql = "SELECT * FROM categorias" + ("" if incluir_inativas else " WHERE ativa = 1")
        return [dict(r) for r in conn.execute(sql + " ORDER BY ordem, nome")]
    finally:
        conn.close()


def listar_subcategorias(categoria_id: int | None = None, incluir_inativas: bool = False) -> list[Subcategoria]:
    sql = (
        "SELECT s.id, s.nome, s.categoria_id, c.nome AS categoria, c.natureza, s.ativa"
        " FROM subcategorias s JOIN categorias c ON c.id = s.categoria_id WHERE 1=1"
    )
    p: list = []
    if not incluir_inativas:
        sql += " AND s.ativa = 1 AND c.ativa = 1"
    if categoria_id:
        sql += " AND s.categoria_id = ?"
        p.append(categoria_id)
    conn = conectar()
    try:
        return [
            Subcategoria(r["id"], r["nome"], r["categoria_id"], r["categoria"], r["natureza"], bool(r["ativa"]))
            for r in conn.execute(sql + " ORDER BY c.ordem, c.nome, s.ordem, s.nome", p)
        ]
    finally:
        conn.close()


def subcategoria_por_nome(categoria: str, nome: str) -> int | None:
    conn = conectar()
    try:
        r = conn.execute(
            "SELECT s.id FROM subcategorias s JOIN categorias c ON c.id = s.categoria_id"
            " WHERE c.nome = ? AND s.nome = ?", (categoria, nome),
        ).fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def criar_categoria(nome: str, natureza: str) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ErroClassificacao("Informe o nome da categoria.")
    if natureza not in NATUREZAS:
        raise ErroClassificacao("Natureza inválida.")
    with transacao() as conn:
        if conn.execute("SELECT 1 FROM categorias WHERE lower(nome) = lower(?)", (nome,)).fetchone():
            raise ErroClassificacao("Já existe uma categoria com esse nome.")
        ordem = conn.execute("SELECT COALESCE(MAX(ordem), 0) + 1 FROM categorias").fetchone()[0]
        return conn.execute(
            "INSERT INTO categorias (nome, natureza, ordem) VALUES (?,?,?)", (nome, natureza, ordem)
        ).lastrowid


def criar_subcategoria(categoria_id: int, nome: str) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ErroClassificacao("Informe o nome da subcategoria.")
    with transacao() as conn:
        if conn.execute(
            "SELECT 1 FROM subcategorias WHERE categoria_id = ? AND lower(nome) = lower(?)",
            (categoria_id, nome),
        ).fetchone():
            raise ErroClassificacao("Essa subcategoria já existe nesta categoria.")
        ordem = conn.execute(
            "SELECT COALESCE(MAX(ordem), 0) + 1 FROM subcategorias WHERE categoria_id = ?", (categoria_id,)
        ).fetchone()[0]
        return conn.execute(
            "INSERT INTO subcategorias (categoria_id, nome, ordem) VALUES (?,?,?)",
            (categoria_id, nome, ordem),
        ).lastrowid


def renomear(tabela: str, registro_id: int, novo_nome: str) -> None:
    assert tabela in ("categorias", "subcategorias")
    novo_nome = (novo_nome or "").strip()
    if not novo_nome:
        raise ErroClassificacao("O nome não pode ficar vazio.")
    with transacao() as conn:
        antigo = conn.execute(f"SELECT nome FROM {tabela} WHERE id = ?", (registro_id,)).fetchone()[0]
        if antigo == novo_nome:
            return
        conn.execute(f"UPDATE {tabela} SET nome = ? WHERE id = ?", (novo_nome, registro_id))
        _auditar(conn, tabela, registro_id, "nome", antigo, novo_nome, "renomeada")


def definir_ativa(tabela: str, registro_id: int, ativa: bool) -> None:
    """Categorias/subcategorias não são apagadas: desativadas somem das listas de escolha."""
    assert tabela in ("categorias", "subcategorias")
    with transacao() as conn:
        conn.execute(f"UPDATE {tabela} SET ativa = ? WHERE id = ?", (int(ativa), registro_id))
        _auditar(conn, tabela, registro_id, "ativa", str(int(not ativa)), str(int(ativa)), None)


# ------------------------------------------------------------------ auditoria

def _auditar(conn, tabela, registro_id, campo, antigo, novo, motivo) -> None:
    conn.execute(
        "INSERT INTO auditoria (tabela, registro_id, campo, valor_antigo, valor_novo, motivo)"
        " VALUES (?,?,?,?,?,?)",
        (tabela, registro_id, campo, None if antigo is None else str(antigo),
         None if novo is None else str(novo), motivo),
    )


def historico(movimentacao_id: int) -> list[dict]:
    conn = conectar()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM auditoria WHERE tabela = 'movimentacoes' AND registro_id = ? ORDER BY id",
            (movimentacao_id,),
        )]
    finally:
        conn.close()


# ------------------------------------------------------------------ classificar

def _rotulo_sub(conn, sub_id) -> str | None:
    if not sub_id:
        return None
    r = conn.execute(
        "SELECT c.nome || ' › ' || s.nome FROM subcategorias s JOIN categorias c ON c.id = s.categoria_id"
        " WHERE s.id = ?", (sub_id,),
    ).fetchone()
    return r[0] if r else str(sub_id)


def classificar(movimentacao_ids: list[int], classificacao: str, subcategoria_id: int | None = None,
                *, descricao_identificada: str | None = None, motivo: str | None = None,
                origem: str = "manual", confianca: str = "Alta", regra_id: int | None = None) -> int:
    """Classifica uma ou várias movimentações. Retorna quantas mudaram.

    `descricao_identificada`: None = não mexe; "" = apaga; texto = grava.
    """
    if classificacao not in CLASSIFICACOES:
        raise ErroClassificacao("Classificação inválida.")
    if classificacao == CLASSIFICADA and not subcategoria_id:
        raise ErroClassificacao("Escolha a categoria e a subcategoria.")
    if classificacao != CLASSIFICADA:
        subcategoria_id = None
    if not movimentacao_ids:
        return 0

    from app.fechamento.servico import ErroFechamento, verificar_aberto
    conn0 = conectar()
    try:
        marcas = ",".join("?" * len(movimentacao_ids))
        meses = {r[0] for r in conn0.execute(
            f"SELECT DISTINCT substr(data, 1, 7) FROM movimentacoes WHERE id IN ({marcas})", movimentacao_ids)}
    finally:
        conn0.close()
    try:
        verificar_aberto(meses, "alterar a categoria")
    except ErroFechamento as e:
        raise ErroClassificacao(str(e)) from e

    mudaram = 0
    with transacao() as conn:
        if subcategoria_id and not conn.execute(
                "SELECT 1 FROM subcategorias WHERE id = ?", (subcategoria_id,)).fetchone():
            raise ErroClassificacao("Subcategoria não encontrada.")
        for mid in movimentacao_ids:
            atual = conn.execute(
                "SELECT classificacao, subcategoria_id, descricao_identificada FROM movimentacoes WHERE id = ?",
                (mid,),
            ).fetchone()
            if atual is None:
                raise ErroClassificacao(f"Movimentação {mid} não encontrada.")
            mudou = False
            if atual["classificacao"] != classificacao:
                _auditar(conn, "movimentacoes", mid, "classificacao", atual["classificacao"], classificacao,
                         motivo or origem)
                mudou = True
            if atual["subcategoria_id"] != subcategoria_id:
                _auditar(conn, "movimentacoes", mid, "categoria", _rotulo_sub(conn, atual["subcategoria_id"]),
                         _rotulo_sub(conn, subcategoria_id), motivo or origem)
                mudou = True
            nova_desc = atual["descricao_identificada"]
            if descricao_identificada is not None:
                nova_desc = descricao_identificada.strip() or None
                if nova_desc != atual["descricao_identificada"]:
                    _auditar(conn, "movimentacoes", mid, "descricao_identificada",
                             atual["descricao_identificada"], nova_desc, motivo or origem)
                    mudou = True
            conn.execute(
                "UPDATE movimentacoes SET classificacao = ?, subcategoria_id = ?, descricao_identificada = ?,"
                " confianca = ?, origem_classificacao = ?, classificada_em = datetime('now','localtime'),"
                " sugestao_subcategoria_id = NULL, sugestao_motivo = NULL,"
                " regra_id = ?, padroes_avaliados = 1"
                " WHERE id = ?",
                (classificacao, subcategoria_id, nova_desc,
                 None if classificacao == "Revisar" else confianca, origem, regra_id, mid),
            )
            mudaram += int(mudou)
    return mudaram


def aceitar_sugestao(movimentacao_ids: list[int]) -> int:
    """Aplica a sugestão de cada movimentação (as que não têm sugestão são ignoradas)."""
    conn = conectar()
    try:
        linhas = conn.execute(
            f"SELECT id, sugestao_subcategoria_id, sugestao_motivo FROM movimentacoes"
            f" WHERE id IN ({','.join('?' * len(movimentacao_ids))}) AND sugestao_subcategoria_id IS NOT NULL",
            movimentacao_ids,
        ).fetchall() if movimentacao_ids else []
    finally:
        conn.close()
    n = 0
    for r in linhas:
        n += classificar([r["id"]], CLASSIFICADA, r["sugestao_subcategoria_id"],
                         motivo=f"sugestão aceita: {r['sugestao_motivo']}")
    return n


# ------------------------------------------------------------------ regras e padrões

CATEGORIA_INTERNA, SUB_ENTRE_CONTAS = "Movimentação interna", "Transferência entre minhas contas"


def _palavras(texto: str | None) -> list[str]:
    return "".join(c if c.isalnum() else " " for c in _norm(texto)).split()


def _titulares() -> dict[tuple[str, ...], str]:
    """Nome normalizado (em palavras) -> titular, das contas cadastradas e ativas."""
    conn = conectar()
    try:
        return {
            tuple(_palavras(r["titular"])): r["titular"]
            for r in conn.execute("SELECT DISTINCT titular FROM contas WHERE ativa = 1")
            if _palavras(r["titular"])
        }
    finally:
        conn.close()


def _sugestao_entre_contas(m: dict, titulares: dict[tuple[str, ...], str]):
    """Pix/transferência em que a outra ponta tem o nome do titular das contas
    → sugere "Transferência entre minhas contas" (neutro). É só SUGESTÃO: se o titular
    estiver cadastrado só com o primeiro nome, um xará também cai aqui — você confirma."""
    op, cp = _palavras(m["operacao"]), set(_palavras(m["contraparte"]))
    # a operação pode vir com as palavras coladas ("PIXEMITIDOOUTRAIF", "TransferênciaenviadapeloPix")
    if not cp or not any(p.startswith(("PIX", "TRANSFER")) or p.endswith("PIX") or p in ("TED", "DOC") for p in op):
        return None
    for nomes, titular in titulares.items():
        if all(n in cp for n in nomes):
            sid = subcategoria_por_nome(CATEGORIA_INTERNA, SUB_ENTRE_CONTAS)
            de_para = "para" if m["tipo"] == "Saída" else "de"
            return (sid, f"Transferência {de_para} {titular}, titular das contas → entre suas contas") if sid else None
    return None


def aplicar_padroes(somente_pendentes: bool = True) -> dict[str, int]:
    """Aplica as REGRAS (e a sugestão de transferência entre contas) às movimentações em Revisar
    que você ainda não decidiu. `somente_pendentes=False` reavalia todas elas
    (use depois de criar ou mudar regras)."""
    from app.classificacao import regras as rg

    todas = rg.listar(incluir_inativas=False)
    titulares = _titulares()
    contagem = {"aplicadas": 0, "sugeridas": 0, "conflitos": 0, "sem_regra": 0}

    for m in rg.movimentacoes_para_avaliar(somente_novas=somente_pendentes):
        d = rg.decidir(m, todas)
        sugestao = None
        if d.regra and d.regra.acao == "aplicar":
            classificar([m["id"]], CLASSIFICADA, d.regra.subcategoria_id,
                        motivo=f"regra: {d.regra.nome}", origem="regra", confianca="Alta",
                        regra_id=d.regra.id)
            _contar_uso(d.regra.id)
            contagem["aplicadas"] += 1
            continue
        if d.regra:   # sugerir
            sugestao = (d.regra.subcategoria_id, f"regra: {d.regra.nome}")
            _contar_uso(d.regra.id)
        elif d.conflito:
            nomes = " × ".join(r.nome for r in d.conflito)
            sugestao = (None, f"conflito entre regras: {nomes}")
            contagem["conflitos"] += 1
        else:
            sugestao = _sugestao_entre_contas(m, titulares)

        with transacao() as conn:
            if sugestao and sugestao[0]:
                conn.execute(
                    "UPDATE movimentacoes SET sugestao_subcategoria_id = ?,"
                    " sugestao_motivo = ?, confianca = 'Média', padroes_avaliados = 1 WHERE id = ?",
                    (*sugestao, m["id"]),
                )
                contagem["sugeridas"] += 1
            else:
                conn.execute(
                    "UPDATE movimentacoes SET sugestao_subcategoria_id = NULL,"
                    " sugestao_motivo = ?, confianca = 'Baixa', padroes_avaliados = 1 WHERE id = ?",
                    (sugestao[1] if sugestao else None, m["id"]),
                )
                if not sugestao:
                    contagem["sem_regra"] += 1
    return contagem


# ------------------------------------------------------------------ desfazer

def _movs_com_conta(conn, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    marcas = ",".join("?" * len(ids))
    return [dict(r) for r in conn.execute(f"SELECT m.* FROM movimentacoes m WHERE m.id IN ({marcas})", ids)]


def previa_desfazer(movimentacao_ids: list[int]) -> dict:
    """O que acontece se estas movimentações voltarem para a Revisão.

    Regras a excluir: as criadas na Revisão ("📌 Criar regra") que classificaram a movimentação
    ou que batem com ela e mandam a mesma categoria que ela tem hoje. Regras iniciais ou
    criadas na tela Regras nunca são excluídas por aqui.
    Arrastadas: outras movimentações classificadas por essas regras — voltam junto.
    """
    from app.classificacao import regras as rg

    conn = conectar()
    try:
        movs = _movs_com_conta(conn, movimentacao_ids)
        da_revisao = [r for r in rg.listar() if r.origem == "correcao"]
        excluir: dict[int, object] = {}
        for m in movs:
            if m["classificacao"] == "Revisar":
                continue
            for r in da_revisao:
                mesma = r.subcategoria_id == m["subcategoria_id"]
                if m["regra_id"] == r.id or (mesma and r.bate(m)):
                    excluir[r.id] = r
        arrastadas: list[dict] = []
        if excluir:
            marcas = ",".join("?" * len(excluir))
            arrastadas = [dict(x) for x in conn.execute(
                f"SELECT id, data, tipo, valor, operacao, contraparte FROM movimentacoes"
                f" WHERE regra_id IN ({marcas}) AND status = 'ativa'", list(excluir))
                if x["id"] not in set(movimentacao_ids)]
    finally:
        conn.close()
    return {"movs": [m for m in movs if m["classificacao"] != "Revisar"],
            "regras": list(excluir.values()), "arrastadas": arrastadas}


def desfazer_classificacao(movimentacao_ids: list[int]) -> dict:
    """Volta as movimentações para a Revisão e exclui as regras criadas a partir delas.

    As outras movimentações que essas regras tinham classificado voltam junto (a regra era
    a única razão da classificação delas). Mês fechado bloqueia tudo, antes de qualquer mudança.
    """
    from app.fechamento.servico import ErroFechamento, verificar_aberto
    from app.ocorrencias.registro import registrar

    p = previa_desfazer(movimentacao_ids)
    ids_sel = [m["id"] for m in p["movs"]]
    ids_arr = [m["id"] for m in p["arrastadas"]]
    if not ids_sel:
        return {"voltaram": 0, "regras": [], "arrastadas": 0}
    conn = conectar()
    try:
        todos = ids_sel + ids_arr
        marcas = ",".join("?" * len(todos))
        meses = {r[0] for r in conn.execute(
            f"SELECT DISTINCT substr(data, 1, 7) FROM movimentacoes WHERE id IN ({marcas})", todos)}
    finally:
        conn.close()
    try:
        verificar_aberto(meses, "desfazer a classificação")
    except ErroFechamento as e:
        raise ErroClassificacao(str(e)) from e

    nomes = [r.nome for r in p["regras"]]
    motivo = "desfeita por você" + (f" (regra excluída: {', '.join(nomes)})" if nomes else "")
    with transacao() as conn:
        for grupo, reavaliar in ((ids_sel, 0), (ids_arr, 1)):
            for mid in grupo:
                atual = conn.execute("SELECT classificacao, subcategoria_id FROM movimentacoes WHERE id = ?",
                                     (mid,)).fetchone()
                _auditar(conn, "movimentacoes", mid, "classificacao", atual["classificacao"], "Revisar", motivo)
                if atual["subcategoria_id"]:
                    _auditar(conn, "movimentacoes", mid, "categoria", _rotulo_sub(conn, atual["subcategoria_id"]),
                             None, motivo)
                # as escolhidas ficam na Revisão até você decidir (nenhuma regra mexe nelas);
                # as arrastadas são reavaliadas pelas regras que sobraram
                conn.execute(
                    "UPDATE movimentacoes SET classificacao = 'Revisar', subcategoria_id = NULL, confianca = NULL,"
                    " origem_classificacao = NULL, classificada_em = NULL, regra_id = NULL,"
                    " sugestao_subcategoria_id = NULL, sugestao_motivo = NULL,"
                    " padroes_avaliados = ? WHERE id = ?", (0 if reavaliar else 1, mid))
        for r in p["regras"]:
            conn.execute("UPDATE movimentacoes SET regra_id = NULL WHERE regra_id = ?", (r.id,))
            conn.execute("DELETE FROM regras WHERE id = ?", (r.id,))
    if p["regras"]:
        registrar("INFO", "sistema", f"{len(p['regras'])} regra(s) excluída(s) ao desfazer classificação",
                  detalhe="\n".join(f"{r.nome}: {r.descrever_condicao()}" for r in p["regras"]))
    if ids_arr:
        aplicar_padroes()
    return {"voltaram": len(ids_sel), "regras": nomes, "arrastadas": len(ids_arr)}


def _contar_uso(regra_id: int) -> None:
    with transacao() as conn:
        conn.execute("UPDATE regras SET vezes_aplicada = vezes_aplicada + 1 WHERE id = ?", (regra_id,))


# ------------------------------------------------------------------ resumo

def contar_por_classificacao() -> dict[str, int]:
    conn = conectar()
    try:
        d = {c: 0 for c in CLASSIFICACOES}
        for r in conn.execute(
            "SELECT classificacao, COUNT(*) FROM movimentacoes WHERE status = 'ativa' GROUP BY classificacao"
        ):
            d[r[0]] = r[1]
        return d
    finally:
        conn.close()
