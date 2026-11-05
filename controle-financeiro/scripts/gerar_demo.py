"""Gera a base de demonstração FICTÍCIA em `demo_base/` (rode uma vez e faça commit do resultado).

    python scripts/gerar_demo.py

Tudo aqui é inventado: a pessoa "Ana Exemplo da Silva", empresas e valores fictícios. Os extratos
em PDF são gerados com os mesmos geradores dos testes e importados pelo fluxo REAL do programa
(leitura, conferência de saldos, regras, revisão e fechamento).
"""

import os
import shutil
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

DESTINO = RAIZ / "demo_base"
if DESTINO.exists():
    shutil.rmtree(DESTINO)
DESTINO.mkdir()
os.environ["ANALISADOR_RAIZ"] = str(DESTINO)
os.environ.pop("FINANCAS_DEMO", None)

from app.banco.conexao import conectar, transacao                       # noqa: E402
from app.classificacao import regras as regras_repo                      # noqa: E402
from app.classificacao import servico as classif                         # noqa: E402
from app.contas import repositorio as contas_repo                        # noqa: E402
from app.fechamento import servico as fechamento                         # noqa: E402
from app.importacao import lote                                          # noqa: E402
from tests.gerador_nubank import Dia, Mov, gerar                         # noqa: E402

TITULAR = "ANA EXEMPLO DA SILVA"
PIX_ENV, PIX_REC = "Transferência enviada pelo Pix", "Transferência recebida pelo Pix"
BOLETO = "Pagamento de boleto efetuado"


def pix(nome, doc, valor, tipo="Saída"):
    return Mov(tipo, PIX_REC if tipo == "Entrada" else PIX_ENV,
               [f"{nome} - {doc} -", "BCO EXEMPLO S.A. (0000) Agência: 1 Conta:", "00000-0"], valor)


def mes(m: int, salario: int, freela: list[tuple[int, int]], energia: int, fatura: int,
        mercado: list[int], uber: list[int], delivery: list[int], extras: dict[int, list[Mov]] | None = None):
    dias: dict[int, list[Mov]] = {}
    add = lambda d, mov: dias.setdefault(d, []).append(mov)

    add(3, pix("ACADEMIA FORMA FISICA LTDA", "44.555.666/0001-77", 10990))
    add(5, pix("EMPRESA EXEMPLO TECH LTDA", "11.111.111/0001-11", salario, "Entrada"))
    add(6, Mov("Saída", "Aplicação RDB", [], 50000))
    add(8, Mov("Saída", BOLETO, ["IMOBILIARIA MODELO LTDA"], 145000))
    add(9, pix("NETFLIX BRASIL LTDA", "55.111.222/0001-33", 3990))
    add(10, pix("CELESC DISTRIBUICAO S.A", "08.336.783/0001-90", energia))
    add(11, Mov("Saída", BOLETO, ["CASAN COMPANHIA AGUAS"], 7250))
    for d, v in zip((4, 11, 18, 25), mercado):
        add(d, pix("SUPERMERCADO MODELO LTDA", "22.333.444/0001-55", v))
    add(14, pix("PROVEDOR FIBRA NET LTDA", "33.444.555/0001-66", 11990))
    add(15, Mov("Saída", "Pagamento de fatura", [], fatura))
    add(16, pix("SPOTIFY BRASIL LTDA", "66.222.333/0001-44", 2190))
    for d, v in zip((7, 19, 29), delivery):
        add(d, pix("IFOOD RESTAURANTES LTDA", "55.666.777/0001-88", v))
    for d, v in zip((2, 13, 22), uber):
        add(d, pix("UBER DO BRASIL LTDA", "77.888.999/0001-00", v))
    for d, v in freela:
        add(d, pix("CLIENTE FREELA ME", "***.123.456-**", v, "Entrada"))
    add(27, Mov("Entrada", "Resgate RDB", [], 20000))
    add(28, pix("CORRETORA MODELO DTVM LTDA", "66.777.888/0001-99", 30000))
    for d, movs in (extras or {}).items():
        for mov in movs:
            add(d, mov)
    return [Dia(date(2026, m, d), movs) for d, movs in sorted(dias.items())]


MESES = {
    7: dict(salario=480000, freela=[(12, 85000)], energia=17840, fatura=132000,
            mercado=[31250, 28990, 36410, 27300], uber=[2290, 3120, 2760], delivery=[5490, 7150, 4890]),
    8: dict(salario=480000, freela=[(12, 120000)], energia=19210, fatura=148500,
            mercado=[35100, 30220, 33840, 29970], uber=[2490, 4870, 2150], delivery=[6290, 5990, 8120]),
    9: dict(salario=495000, freela=[(12, 90000), (24, 60000)], energia=18530, fatura=121000,
            mercado=[29980, 34120, 31770, 28450], uber=[3190, 2580, 3640], delivery=[4990, 6890, 5320],
            extras={
                # estas ficam SEM categoria de propósito, para mostrar a tela de Revisão
                21: [pix("BARBEARIA DO ZE", "***.222.111-**", 5500)],
                22: [pix("FARMACIA SAUDE LTDA", "88.999.000/0001-11", 8740)],
                26: [pix("CARLOS AMIGO PEREIRA", "***.333.444-**", 12000, "Entrada")],
            }),
}


def main():
    # contas: a pessoa fictícia e a segunda conta (exemplo) desativada
    conectar().close()
    for c in contas_repo.listar():
        if c.banco == "Nubank":
            c.nome, c.titular, c.pasta = "Conta Nubank", TITULAR, "Conta-Nubank"
        else:
            c.nome, c.titular, c.pasta, c.ativa = "Conta Sicoob (exemplo)", TITULAR, "Conta-Sicoob", False
        contas_repo.atualizar(c)

    # regras de classificação
    sub = classif.subcategoria_por_nome
    for nome, texto, cat, subn, tipo in [
        ("Salário", "EMPRESA EXEMPLO TECH", "Renda", "Salário", "Entrada"),
        ("Freelance", "CLIENTE FREELA", "Renda", "Freelance / serviços", "Entrada"),
        ("Aluguel", "IMOBILIARIA MODELO", "Moradia", "Aluguel / financiamento", "Saída"),
        ("Água (CASAN)", "CASAN", "Moradia", "Água", "Saída"),
        ("Internet", "PROVEDOR FIBRA NET", "Moradia", "Internet e telefone", "Saída"),
        ("Supermercado", "SUPERMERCADO MODELO", "Alimentação", "Mercado", "Saída"),
        ("Academia", "ACADEMIA FORMA FISICA", "Saúde", "Academia e esportes", "Saída"),
        ("Corretora", "CORRETORA MODELO", "Investimentos", "Corretora / ações e fundos", "Saída"),
    ]:
        regras_repo.criar(nome=nome, campo="contraparte", condicao="contem", texto=texto,
                          subcategoria_id=sub(cat, subn), acao="aplicar", tipo_mov=tipo)

    # extratos fictícios -> pasta de entrada -> importação real, em lote
    entrada = lote.pasta_entrada()
    entrada.mkdir(parents=True, exist_ok=True)
    saldo = 150000
    for m, params in MESES.items():
        dias = mes(m, **params)
        ultimo = 31 if m != 9 else 30
        pdf = entrada / f"NU_000000000_01{['','','','','','','','JUL','AGO','SET'][m]}2026_{ultimo}{['','','','','','','','JUL','AGO','SET'][m]}2026.pdf"
        res = gerar(pdf, dias, inicio=date(2026, m, 1), fim=date(2026, m, ultimo), saldo_inicial=saldo,
                    titular=TITULAR, conta="12345678-9", itens_por_pagina=9)
        saldo = res["saldo_final"]
    itens = lote.analisar_entrada()
    nao_prontos = [(i.caminho.name, i.situacao, i.mensagem) for i in itens if i.situacao != "pronto"]
    assert not nao_prontos, nao_prontos
    feitos, falhas = lote.importar_prontos(itens)
    assert len(feitos) == len(MESES) and not falhas, falhas

    # classificação: regras aplicam; sugestões (fatura, Uber, iFood, Netflix, Spotify) são aceitas
    classif.aplicar_padroes()
    conn = conectar()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM movimentacoes WHERE classificacao='Revisar' AND sugestao_subcategoria_id IS NOT NULL")]
    finally:
        conn.close()
    classif.aceitar_sugestao(ids)

    # fecha julho e agosto; setembro fica aberto, com 3 itens em Revisão
    for mm in ("2026-07", "2026-08"):
        fechamento.fechar(mm, "Mês de demonstração")

    cls = classif.contar_por_classificacao()
    print("Importados:", len(feitos), "| classificação:", cls)
    assert cls["Revisar"] == 3, cls

    # limpeza: nada de logs/backups/pastas vazias na base
    for pasta in ("backups", "logs"):
        shutil.rmtree(DESTINO / pasta, ignore_errors=True)
    shutil.rmtree(DESTINO / "extratos" / "_entrada", ignore_errors=True)
    for p in sorted(DESTINO.rglob("__pycache__")):
        shutil.rmtree(p, ignore_errors=True)
    print("Base de demonstração pronta em", DESTINO)


if __name__ == "__main__":
    main()
