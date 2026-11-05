"""Consultas de leitura para as telas Documentos e Movimentações."""

from app.banco.conexao import conectar


def _todas(sql: str, params=()) -> list[dict]:
    conn = conectar()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def documentos(conta_id: int | None = None) -> list[dict]:
    sql = ("SELECT d.*, c.nome AS conta_nome FROM documentos d JOIN contas c ON c.id = d.conta_id")
    params: list = []
    if conta_id:
        sql += " WHERE d.conta_id = ?"
        params.append(conta_id)
    return _todas(sql + " ORDER BY d.periodo_inicio DESC, d.id DESC", params)


def movimentacoes(*, contas: list[int] | None = None, inicio: str | None = None,
                  fim: str | None = None, tipo: str | None = None, busca: str | None = None,
                  documento_id: int | None = None, classificacoes: list[str] | None = None,
                  categoria_id: int | None = None, origem: str | None = None) -> list[dict]:
    sql = (
        "SELECT m.*, c.nome AS conta_nome,"
        " cat.nome AS categoria, cat.natureza AS natureza, s.nome AS subcategoria,"
        " scat.nome || ' › ' || ss.nome AS sugestao_rotulo,"
        " (SELECT GROUP_CONCAT(d.arquivo_nome, ' · ') FROM movimentacao_documento md"
        "   JOIN documentos d ON d.id = md.documento_id WHERE md.movimentacao_id = m.id) AS documentos"
        " FROM movimentacoes m JOIN contas c ON c.id = m.conta_id"
        " LEFT JOIN subcategorias s ON s.id = m.subcategoria_id"
        " LEFT JOIN categorias cat ON cat.id = s.categoria_id"
        " LEFT JOIN subcategorias ss ON ss.id = m.sugestao_subcategoria_id"
        " LEFT JOIN categorias scat ON scat.id = ss.categoria_id"
        " WHERE m.status = 'ativa'"
    )
    p: list = []
    if contas:
        sql += f" AND m.conta_id IN ({','.join('?' * len(contas))})"
        p += contas
    if inicio:
        sql += " AND m.data >= ?"
        p.append(inicio)
    if fim:
        sql += " AND m.data <= ?"
        p.append(fim)
    if tipo:
        sql += " AND m.tipo = ?"
        p.append(tipo)
    if busca:
        sql += " AND (m.descricao_original LIKE ? OR m.descricao_identificada LIKE ?)"
        p += [f"%{busca}%", f"%{busca}%"]
    if classificacoes:
        sql += f" AND m.classificacao IN ({','.join('?' * len(classificacoes))})"
        p += classificacoes
    if origem:                      # 'manual' | 'regra' | 'padrao'
        sql += " AND m.origem_classificacao = ?"
        p.append(origem)
    if categoria_id:
        sql += " AND cat.id = ?"
        p.append(categoria_id)
    if documento_id:
        sql += " AND m.id IN (SELECT movimentacao_id FROM movimentacao_documento WHERE documento_id = ?)"
        p.append(documento_id)
    return _todas(sql + " ORDER BY m.data, m.conta_id, m.ordem_no_dia", p)


def documentos_da_movimentacao(mov_id: int) -> list[dict]:
    return _todas(
        "SELECT d.*, md.pagina FROM movimentacao_documento md JOIN documentos d ON d.id = md.documento_id"
        " WHERE md.movimentacao_id = ? ORDER BY d.importado_em", (mov_id,),
    )


def totais() -> dict:
    conn = conectar()
    try:
        return {
            "documentos": conn.execute("SELECT COUNT(*) FROM documentos").fetchone()[0],
            "movimentacoes": conn.execute(
                "SELECT COUNT(*) FROM movimentacoes WHERE status='ativa'").fetchone()[0],
        }
    finally:
        conn.close()


def intervalo_datas() -> tuple[str | None, str | None]:
    conn = conectar()
    try:
        r = conn.execute("SELECT MIN(data), MAX(data) FROM movimentacoes").fetchone()
        return r[0], r[1]
    finally:
        conn.close()
