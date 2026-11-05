"""Leitores de extrato por banco. O campo `banco` da conta escolhe o leitor."""

from app.leitores import nubank, sicoob

LEITORES = {
    "Nubank": nubank.ler,
    "Sicoob": sicoob.ler,
}


def leitor_para(banco: str):
    return LEITORES.get(banco)


# Módulos, para reconhecer de qual banco é um PDF (cada um tem e_extrato(caminho, senha)).
MODULOS = {"Nubank": nubank, "Sicoob": sicoob}


def banco_do_pdf(caminho, senha=None) -> str | None:
    for banco, modulo in MODULOS.items():
        if modulo.e_extrato(caminho, senha):
            return banco
    return None
