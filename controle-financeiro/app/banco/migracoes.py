"""Evolução do banco de dados.

Cada migração é aplicada uma única vez, em ordem. Para mudar o banco no
futuro, NUNCA edite uma migração já aplicada: acrescente uma nova no fim.

Este é um programa de uso PESSOAL (uma pessoa controlando as próprias contas):
- todas as contas são da mesma pessoa, e pode haver quantas quiser;
- classificar uma movimentação é só escolher a categoria ('Classificada') —
  o que ainda não tem categoria fica em 'Revisar';
- além de receita, despesa e neutro existe a natureza 'investimento'
  (dinheiro que sai da conta para virar patrimônio; fica fora do resultado do mês).
"""

# (categoria, natureza, [subcategorias]) — na ordem em que aparecem nas telas.
# Só vale para a criação do banco: depois disso, mude as categorias pela tela Categorias.
CATEGORIAS_INICIAIS = [
    ("Renda", "receita", ["Salário", "Freelance / serviços", "13º e férias", "Outras rendas"]),
    ("Receitas financeiras", "receita", ["Rendimentos", "Dividendos e juros"]),
    ("Outras receitas", "receita", ["Reembolsos", "Vendas", "Presentes recebidos", "Outras receitas"]),
    ("Moradia", "despesa", ["Aluguel / financiamento", "Condomínio", "Energia", "Água", "Gás",
                            "Internet e telefone", "Manutenção da casa"]),
    ("Alimentação", "despesa", ["Mercado", "Restaurantes e lanches", "Delivery", "Padaria e feira"]),
    ("Transporte", "despesa", ["Combustível", "Transporte por app / táxi", "Transporte público",
                               "Manutenção do veículo", "Estacionamento e pedágio", "Seguro e IPVA"]),
    ("Saúde", "despesa", ["Plano de saúde", "Farmácia", "Consultas e exames", "Academia e esportes"]),
    ("Educação", "despesa", ["Cursos", "Livros e materiais", "Mensalidade"]),
    ("Lazer", "despesa", ["Viagens", "Bares e festas", "Cinema, shows e eventos", "Hobbies"]),
    ("Compras", "despesa", ["Roupas e calçados", "Eletrônicos", "Casa e decoração", "Presentes"]),
    ("Assinaturas e serviços", "despesa", ["Streaming", "Celular", "Software e apps", "Outras assinaturas"]),
    ("Cuidados pessoais", "despesa", ["Cabelo e barbearia", "Higiene e beleza"]),
    ("Impostos e taxas", "despesa", ["Imposto de renda", "Tarifas bancárias", "Juros e multas",
                                     "Outros impostos"]),
    ("Cartão de crédito", "despesa", ["Fatura do cartão"]),
    ("Outras despesas", "despesa", ["Doações", "Outras despesas"]),
    ("Investimentos", "investimento", ["Corretora / ações e fundos", "Previdência",
                                       "Poupança / outro banco", "Outros investimentos"]),
    ("Movimentação interna", "neutro", ["Resgate RDB / caixinha", "Aplicação RDB / caixinha",
                                        "Transferência entre minhas contas"]),
    ("Dinheiro de terceiros", "neutro", ["Repasse (dinheiro que não é meu)",
                                         "Empréstimo feito / devolvido"]),
]

# (nome, campo, condição, texto, tipo da movimentação, ação, categoria, subcategoria, prioridade, observação)
REGRAS_INICIAIS = [
    ("Resgate RDB", "operacao", "contem", "RESGATE RDB", "Entrada", "aplicar",
     "Movimentação interna", "Resgate RDB / caixinha", 100, "Dinheiro guardado voltando: neutro"),
    ("Aplicação RDB", "operacao", "contem", "APLICACAO RDB", "Saída", "aplicar",
     "Movimentação interna", "Aplicação RDB / caixinha", 100, "Dinheiro sendo guardado: neutro"),
    ("CELESC", "contraparte", "cnpj", "08336783000190", "Saída", "aplicar",
     "Moradia", "Energia", 50, "Conta de luz (Santa Catarina)"),
    ("Fatura do cartão", "operacao", "contem", "PAGAMENTO DE FATURA", "Saída", "sugerir",
     "Cartão de crédito", "Fatura do cartão", 30,
     "Sugestão: a fatura junta compras de vários tipos; confirme ou escolha outra categoria"),
    ("Uber", "contraparte", "contem", "UBER", "Saída", "sugerir",
     "Transporte", "Transporte por app / táxi", 20, "Exemplo de regra por nome: confirme na Revisão"),
    ("iFood", "contraparte", "contem", "IFOOD", "Saída", "sugerir",
     "Alimentação", "Delivery", 20, "Exemplo de regra por nome: confirme na Revisão"),
    ("Netflix", "contraparte", "contem", "NETFLIX", "Saída", "sugerir",
     "Assinaturas e serviços", "Streaming", 20, "Exemplo de regra por nome: confirme na Revisão"),
    ("Spotify", "contraparte", "contem", "SPOTIFY", "Saída", "sugerir",
     "Assinaturas e serviços", "Streaming", 20, "Exemplo de regra por nome: confirme na Revisão"),
]


def _sql(texto: str | None) -> str:
    return "NULL" if texto is None else "'" + texto.replace("'", "''") + "'"


def _sql_categorias() -> str:
    linhas = []
    for ordem, (cat, natureza, subs) in enumerate(CATEGORIAS_INICIAIS, 1):
        linhas.append(f"INSERT INTO categorias (nome, natureza, ordem) VALUES ({_sql(cat)}, {_sql(natureza)}, {ordem});")
        for i, sub in enumerate(subs, 1):
            linhas.append(
                "INSERT INTO subcategorias (categoria_id, nome, ordem) VALUES "
                f"((SELECT id FROM categorias WHERE nome = {_sql(cat)}), {_sql(sub)}, {i});")
    return "\n".join(linhas)


def _sql_regras() -> str:
    linhas = []
    for nome, campo, condicao, texto, tipo_mov, acao, cat, sub, prioridade, obs in REGRAS_INICIAIS:
        linhas.append(
            "INSERT INTO regras (nome, campo, condicao, texto, tipo_mov, acao, subcategoria_id, prioridade,"
            " origem, observacoes) VALUES ("
            f"{_sql(nome)}, {_sql(campo)}, {_sql(condicao)}, {_sql(texto)}, {_sql(tipo_mov)}, {_sql(acao)}, "
            "(SELECT s.id FROM subcategorias s JOIN categorias c ON c.id = s.categoria_id"
            f" WHERE c.nome = {_sql(cat)} AND s.nome = {_sql(sub)}), {prioridade}, 'inicial', {_sql(obs)});")
    return "\n".join(linhas)


MIGRACOES = [
    (
        1,
        "Contas",
        """
        CREATE TABLE contas (
            id            INTEGER PRIMARY KEY,
            nome          TEXT    NOT NULL UNIQUE,
            titular       TEXT    NOT NULL,
            banco         TEXT    NOT NULL,
            agencia       TEXT,
            numero_conta  TEXT,
            pasta         TEXT    NOT NULL UNIQUE,
            ativa         INTEGER NOT NULL DEFAULT 1 CHECK (ativa IN (0, 1)),
            observacoes   TEXT,
            criada_em     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );
        """,
    ),
    (
        2,
        "Contas iniciais (Daniel + uma segunda conta de exemplo)",
        """
        INSERT INTO contas (nome, titular, banco, pasta, observacoes) VALUES
            ('Daniel', 'Daniel', 'Nubank', 'Daniel-Nubank',
             'Conta principal. Em Contas dá para trocar o nome, o banco e pôr o nome completo do titular.'),
            ('Dani 2', 'Daniel', 'Sicoob', 'Dani-2-Sicoob',
             'Exemplo: você pode ter quantas contas quiser (outro banco, conta conjunta, conta antiga...). '
             || 'Troque o nome e o banco para uma conta sua, ou desative se não for usar.');
        """,
    ),
    (
        3,
        "Log de ocorrências",
        """
        CREATE TABLE ocorrencias (
            id            INTEGER PRIMARY KEY,
            criada_em     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            nivel         TEXT    NOT NULL
                          CHECK (nivel IN ('ERRO', 'CONFERIR', 'REVISAR', 'INFO')),
            etapa         TEXT    NOT NULL,
            mensagem      TEXT    NOT NULL,
            detalhe       TEXT,
            conta_id      INTEGER REFERENCES contas(id),
            arquivo       TEXT,
            documento_id  INTEGER,
            pagina        INTEGER,
            precisa_acao  INTEGER NOT NULL CHECK (precisa_acao IN (0, 1)),
            resolvida_em  TEXT,
            resolucao     TEXT
        );
        CREATE INDEX idx_ocorrencias_abertas ON ocorrencias (precisa_acao, resolvida_em);
        CREATE INDEX idx_ocorrencias_data ON ocorrencias (criada_em);
        """,
    ),
    (
        4,
        "Documentos, movimentações e saldos",
        """
        -- Cada PDF importado com sucesso. PDFs recusados ficam só em ocorrencias.
        CREATE TABLE documentos (
            id                  INTEGER PRIMARY KEY,
            conta_id            INTEGER NOT NULL REFERENCES contas(id),
            arquivo_nome        TEXT    NOT NULL,
            caminho             TEXT    NOT NULL,   -- relativo à pasta do programa
            hash_sha256         TEXT    NOT NULL UNIQUE,
            tamanho_bytes       INTEGER NOT NULL,
            layout              TEXT    NOT NULL,   -- ex.: nubank_v1
            periodo_inicio      TEXT    NOT NULL,   -- AAAA-MM-DD
            periodo_fim         TEXT    NOT NULL,
            saldo_inicial       INTEGER NOT NULL,   -- centavos
            saldo_final         INTEGER NOT NULL,
            total_entradas      INTEGER NOT NULL,
            total_saidas        INTEGER NOT NULL,
            rendimento          INTEGER,
            qtd_lidas           INTEGER NOT NULL,
            qtd_novas           INTEGER NOT NULL,
            qtd_existentes      INTEGER NOT NULL,
            paginas             INTEGER NOT NULL,
            importado_em        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            observacoes         TEXT
        );
        CREATE INDEX idx_documentos_conta ON documentos (conta_id, periodo_inicio);

        -- A entidade financeira principal. Valor sempre positivo; o sinal vem do tipo.
        CREATE TABLE movimentacoes (
            id                     INTEGER PRIMARY KEY,
            conta_id               INTEGER NOT NULL REFERENCES contas(id),
            data                   TEXT    NOT NULL,          -- AAAA-MM-DD
            tipo                   TEXT    NOT NULL CHECK (tipo IN ('Entrada', 'Saída')),
            valor                  INTEGER NOT NULL CHECK (valor > 0),   -- centavos
            operacao               TEXT    NOT NULL,          -- ex.: Transferência enviada pelo Pix
            contraparte            TEXT,                      -- nome, documento, banco...
            descricao_original     TEXT    NOT NULL,          -- como veio do banco; nunca muda
            descricao_identificada TEXT,                      -- editável
            ordem_no_dia           INTEGER NOT NULL,          -- posição no extrato naquele dia
            chave_duplicidade      TEXT    NOT NULL,
            documento_origem_id    INTEGER NOT NULL REFERENCES documentos(id),
            status                 TEXT    NOT NULL DEFAULT 'ativa'
                                   CHECK (status IN ('ativa', 'invalidada')),
            importada_em           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE (conta_id, chave_duplicidade)
        );
        CREATE INDEX idx_mov_conta_data ON movimentacoes (conta_id, data);

        -- Em quais PDFs cada movimentação aparece (um PDF atualizado repete as antigas).
        CREATE TABLE movimentacao_documento (
            movimentacao_id  INTEGER NOT NULL REFERENCES movimentacoes(id),
            documento_id     INTEGER NOT NULL REFERENCES documentos(id),
            pagina           INTEGER,
            PRIMARY KEY (movimentacao_id, documento_id)
        );

        -- Saldo do dia informado pelo banco em cada documento.
        CREATE TABLE saldos_diarios (
            conta_id      INTEGER NOT NULL REFERENCES contas(id),
            data          TEXT    NOT NULL,
            saldo         INTEGER NOT NULL,   -- centavos
            documento_id  INTEGER NOT NULL REFERENCES documentos(id),
            PRIMARY KEY (conta_id, data, documento_id)
        );
        """,
    ),
    (
        5,
        "Categorias, classificação e histórico de alterações",
        """
        CREATE TABLE categorias (
            id        INTEGER PRIMARY KEY,
            nome      TEXT    NOT NULL UNIQUE,
            natureza  TEXT    NOT NULL CHECK (natureza IN ('receita', 'despesa', 'investimento', 'neutro')),
            ordem     INTEGER NOT NULL DEFAULT 0,
            ativa     INTEGER NOT NULL DEFAULT 1 CHECK (ativa IN (0, 1))
        );
        CREATE TABLE subcategorias (
            id            INTEGER PRIMARY KEY,
            categoria_id  INTEGER NOT NULL REFERENCES categorias(id),
            nome          TEXT    NOT NULL,
            ordem         INTEGER NOT NULL DEFAULT 0,
            ativa         INTEGER NOT NULL DEFAULT 1 CHECK (ativa IN (0, 1)),
            UNIQUE (categoria_id, nome)
        );

        -- Classificação de cada movimentação: 'Classificada' (tem subcategoria) ou 'Revisar'
        ALTER TABLE movimentacoes ADD COLUMN classificacao TEXT NOT NULL DEFAULT 'Revisar'
            CHECK (classificacao IN ('Classificada', 'Revisar'));
        ALTER TABLE movimentacoes ADD COLUMN subcategoria_id INTEGER REFERENCES subcategorias(id);
        ALTER TABLE movimentacoes ADD COLUMN confianca TEXT
            CHECK (confianca IS NULL OR confianca IN ('Alta', 'Média', 'Baixa'));
        ALTER TABLE movimentacoes ADD COLUMN origem_classificacao TEXT;   -- manual | padrao | regra
        ALTER TABLE movimentacoes ADD COLUMN classificada_em TEXT;
        -- Sugestão (o programa propõe a categoria, você confirma)
        ALTER TABLE movimentacoes ADD COLUMN sugestao_subcategoria_id INTEGER REFERENCES subcategorias(id);
        ALTER TABLE movimentacoes ADD COLUMN sugestao_motivo TEXT;
        ALTER TABLE movimentacoes ADD COLUMN padroes_avaliados INTEGER NOT NULL DEFAULT 0;
        CREATE INDEX idx_mov_classificacao ON movimentacoes (classificacao);

        -- Histórico de toda alteração manual importante
        CREATE TABLE auditoria (
            id           INTEGER PRIMARY KEY,
            quando       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            tabela       TEXT    NOT NULL,
            registro_id  INTEGER NOT NULL,
            campo        TEXT    NOT NULL,
            valor_antigo TEXT,
            valor_novo   TEXT,
            motivo       TEXT
        );
        CREATE INDEX idx_auditoria_registro ON auditoria (tabela, registro_id);

        """ + _sql_categorias(),
    ),
    (
        6,
        "Regras de classificação + regras iniciais",
        """
        CREATE TABLE regras (
            id              INTEGER PRIMARY KEY,
            nome            TEXT    NOT NULL,
            campo           TEXT    NOT NULL CHECK (campo IN ('contraparte', 'operacao', 'descricao')),
            condicao        TEXT    NOT NULL CHECK (condicao IN ('contem', 'cnpj')),
            texto           TEXT    NOT NULL,          -- normalizado (maiúsculas, sem acento) ou 14 dígitos
            tipo_mov        TEXT    CHECK (tipo_mov IS NULL OR tipo_mov IN ('Entrada', 'Saída')),
            conta_id        INTEGER REFERENCES contas(id),   -- NULL = vale para todas as contas
            acao            TEXT    NOT NULL CHECK (acao IN ('aplicar', 'sugerir')),
            subcategoria_id INTEGER NOT NULL REFERENCES subcategorias(id),
            prioridade      INTEGER NOT NULL DEFAULT 50,
            ativa           INTEGER NOT NULL DEFAULT 1 CHECK (ativa IN (0, 1)),
            origem          TEXT    NOT NULL DEFAULT 'usuario',   -- inicial | usuario | correcao
            vezes_aplicada  INTEGER NOT NULL DEFAULT 0,
            observacoes     TEXT,
            criada_em       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );
        ALTER TABLE movimentacoes ADD COLUMN regra_id INTEGER REFERENCES regras(id);

        """ + _sql_regras(),
    ),
    (
        7,
        "Fechamento mensal",
        """
        CREATE TABLE meses (
            mes         TEXT PRIMARY KEY,            -- AAAA-MM
            status      TEXT NOT NULL DEFAULT 'Aberto' CHECK (status IN ('Aberto', 'Fechado')),
            fechado_em  TEXT,
            observacao  TEXT
        );
        -- Histórico: cada fechamento guarda um retrato dos números; cada reabertura, o motivo.
        CREATE TABLE fechamentos (
            id         INTEGER PRIMARY KEY,
            mes        TEXT NOT NULL,
            acao       TEXT NOT NULL CHECK (acao IN ('fechamento', 'reabertura')),
            quando     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            texto      TEXT,                         -- observação (fechamento) ou motivo (reabertura)
            retrato    TEXT,                         -- JSON com os números no momento do fechamento
            checklist  TEXT                          -- JSON do checklist no momento do fechamento
        );
        CREATE INDEX idx_fechamentos_mes ON fechamentos (mes, id);
        """,
    ),
    (
        8,
        "Caixinhas e rendimentos",
        """
        -- PDFs de rendimento importados (ex.: Extrato de Rendimentos das Caixinhas do Nubank).
        -- Ficam separados de `documentos` porque não são extratos de conta.
        CREATE TABLE rendimento_documentos (
            id              INTEGER PRIMARY KEY,
            conta_id        INTEGER NOT NULL REFERENCES contas(id),
            arquivo_nome    TEXT    NOT NULL,
            caminho         TEXT    NOT NULL,          -- relativo à pasta do programa
            hash_sha256     TEXT    NOT NULL UNIQUE,
            tamanho_bytes   INTEGER NOT NULL,
            layout          TEXT    NOT NULL,
            periodo_inicio  TEXT    NOT NULL,
            periodo_fim     TEXT    NOT NULL,
            paginas         INTEGER NOT NULL,
            qtd_lidas       INTEGER NOT NULL,
            qtd_novas       INTEGER NOT NULL,
            importado_em    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );
        -- Cada caixinha / aplicação que rende (uma conta pode ter várias).
        CREATE TABLE aplicacoes (
            id         INTEGER PRIMARY KEY,
            conta_id   INTEGER NOT NULL REFERENCES contas(id),
            nome       TEXT    NOT NULL,               -- como vem no PDF
            apelido    TEXT,                           -- nome para mostrar (editável)
            produto    TEXT,
            criada_em  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE (conta_id, nome)
        );
        -- Resgates e aplicações listados no extrato de rendimentos.
        CREATE TABLE aplicacao_movimentos (
            id             INTEGER PRIMARY KEY,
            aplicacao_id   INTEGER NOT NULL REFERENCES aplicacoes(id),
            data           TEXT    NOT NULL,
            tipo           TEXT    NOT NULL,
            valor_bruto    INTEGER NOT NULL,
            ir             INTEGER NOT NULL DEFAULT 0,
            iof            INTEGER NOT NULL DEFAULT 0,
            valor_liquido  INTEGER NOT NULL,
            ordem_no_dia   INTEGER NOT NULL,
            chave          TEXT    NOT NULL,
            documento_id   INTEGER NOT NULL REFERENCES rendimento_documentos(id),
            pagina         INTEGER,
            UNIQUE (aplicacao_id, chave)
        );
        CREATE INDEX idx_aplicacao_movimentos_data ON aplicacao_movimentos (aplicacao_id, data);
        -- Rendimento informado pelo banco, um valor por mês.
        CREATE TABLE aplicacao_rendimentos (
            id            INTEGER PRIMARY KEY,
            aplicacao_id  INTEGER NOT NULL REFERENCES aplicacoes(id),
            mes           TEXT    NOT NULL,            -- AAAA-MM
            data          TEXT    NOT NULL,            -- até que dia vale o valor
            valor         INTEGER NOT NULL,
            rotulo        TEXT,
            documento_id  INTEGER NOT NULL REFERENCES rendimento_documentos(id),
            UNIQUE (aplicacao_id, mes)
        );
        -- Saldo no fim do período de cada PDF.
        CREATE TABLE aplicacao_saldos (
            aplicacao_id  INTEGER NOT NULL REFERENCES aplicacoes(id),
            data          TEXT    NOT NULL,
            saldo         INTEGER NOT NULL,
            documento_id  INTEGER NOT NULL REFERENCES rendimento_documentos(id),
            PRIMARY KEY (aplicacao_id, data)
        );
        """,
    ),
]
