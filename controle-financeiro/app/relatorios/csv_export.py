"""Movimentações em CSV no padrão brasileiro (abre direto no Excel em pt-BR):
separador ';', vírgula decimal, UTF-8 com BOM."""

import csv
import io


def movimentacoes(movs: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Data", "Conta", "Tipo", "Valor", "Situação", "Categoria", "Subcategoria",
                "Descrição identificada", "Descrição original", "Documento(s)"])
    for m in movs:
        a, mm, d = m["data"].split("-")
        centavos = m["valor"] if m["tipo"] == "Entrada" else -m["valor"]
        valor = f"{centavos / 100:.2f}".replace(".", ",")
        w.writerow([f"{d}/{mm}/{a}", m["conta_nome"], m["tipo"], valor, m["classificacao"],
                    m["categoria"] or "", m["subcategoria"] or "", m["descricao_identificada"] or "",
                    m["descricao_original"], m["documentos"] or ""])
    return ("﻿" + buf.getvalue()).encode("utf-8")
