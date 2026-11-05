"""Formatação para exibição (dinheiro e datas no padrão brasileiro)."""

from datetime import date


def reais(centavos: int | None, sinal: bool = False) -> str:
    if centavos is None:
        return ""
    s = f"{abs(centavos) // 100:,}".replace(",", ".") + f",{abs(centavos) % 100:02d}"
    if centavos < 0:
        return f"- R$ {s}"
    return f"+ R$ {s}" if sinal else f"R$ {s}"


def data_br(valor) -> str:
    if not valor:
        return ""
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    a, m, d = str(valor)[:10].split("-")
    return f"{d}/{m}/{a}"


def reais_md(centavos: int | None, sinal: bool = False) -> str:
    """Igual a reais(), mas para textos em markdown: o '$' é protegido, senão o
    Streamlit entende 'R$ ... R$' como fórmula matemática."""
    return reais(centavos, sinal).replace("$", "\\$")
