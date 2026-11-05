"""Ajudas usadas por vários testes."""


def conta(nome="Daniel"):
    from app.contas import repositorio as repo
    return next(c for c in repo.listar() if c.nome == nome)


def segunda_conta_no_nubank():
    """A conta de exemplo "Dani 2" nasce como Sicoob. Aqui ela vira uma segunda conta do Nubank,
    do jeito que a pessoa faria na tela Contas (trocando o banco e a pasta)."""
    from app.contas import repositorio as repo
    c = conta("Dani 2")
    if c.banco != "Nubank":
        c.banco, c.pasta = "Nubank", "Dani-2-Nubank"
        repo.atualizar(c)
    return conta("Dani 2")
