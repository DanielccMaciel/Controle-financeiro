# 💰 Controle Financeiro Pessoal

Aplicativo web que transforma **extratos bancários em PDF** em um painel financeiro: quanto entrou, quanto saiu,
para onde foi o dinheiro e quanto sobrou, mês a mês. Feito em Python, roda 100% local (sem enviar dados para a internet).

> **🔗 Demonstração online:** `COLE-AQUI-O-LINK-DO-STREAMLIT`
> (dados 100% fictícios — cada visitante recebe uma cópia própria que some ao fechar a aba)

## O que ele faz

- **Leitura de extratos em PDF** do Nubank e do Sicoob (conta e caixinhas), com detecção automática do banco e da conta.
- **Conferência antes de gravar:** o PDF só é importado se os totais e os saldos de cada dia baterem.
- **Sem duplicidade:** reimportar um PDF mais completo do mesmo período adiciona só o que é novo.
- **Classificação com regras:** o usuário categoriza uma vez e cria uma regra (por nome ou CNPJ) para o que se repete;
  conflitos entre regras nunca são resolvidos "no chute".
- **Dashboard:** receita, despesas, resultado, % que sobrou, investido, saldo, evolução e despesas por categoria,
  com rastreabilidade até a linha do PDF de origem.
- **Fechamento de mês** com checklist, retrato oficial dos números e histórico de reaberturas.
- **Relatórios** mensais e anuais em PDF, Excel (com fórmulas) e CSV.
- **Auditoria e log de ocorrências:** nada dá errado em silêncio; nada é apagado, só desativado.

## Tecnologias

Python 3.11+ · Streamlit · SQLite (com sistema de migrações) · pandas · Plotly · pdfplumber · ReportLab · openpyxl · pytest (115 testes)

## Decisões de projeto que valem destacar

- Valores em **centavos inteiros** (sem erro de ponto flutuante em dinheiro).
- **O extrato é a fonte da verdade:** a descrição original nunca muda e cada linha sabe de qual PDF e página veio.
- **Banco versionado por migrações** (`app/banco/migracoes.py`), com backup automático antes de atualizar a estrutura.
- Testes com **extratos falsos gerados na hora** (`tests/gerador_*.py`), nunca com dados reais.
- Arquitetura em camadas: leitores por banco → importação → classificação → análise → fechamento → relatórios → interface.

## Como rodar

Requisito: Python 3.11 ou mais novo.

```bash
git clone <seu-repositorio>
cd <pasta>
pip install -r requirements.txt

streamlit run demo.py   # demonstração com dados fictícios
streamlit run main.py   # uso real, com seus próprios extratos (dados ficam só no seu computador)
```

No Windows, o uso real também pode ser aberto com dois cliques em `iniciar.bat`.

Testes: `python -m pytest`

## Uso real, todo mês

1. **Importação** — solte os PDFs de extrato do mês (de todas as contas, juntos, se quiser).
2. **Revisão** — escolha a categoria de cada movimentação; marque *Criar regra* para o que se repete.
3. **Dashboard** — acompanhe os números do mês.
4. **Meses** — com tudo conferido, feche o mês.
5. **Relatórios** — exporte em PDF, Excel ou CSV.

### Como os números são calculados

Cada categoria tem uma **natureza**:

| Natureza | Exemplos | Entra em |
|---|---|---|
| 🟢 Receita | salário, freela, rendimentos | Receita |
| 🔴 Despesa | moradia, mercado, transporte, lazer | Despesas |
| 🟣 Investimento | corretora, previdência | "Investido no mês" (fora do resultado) |
| ⚪ Neutro | caixinha/RDB, Pix entre as próprias contas | nada (só muda de lugar) |

`Sobrou no mês = Receita − Despesas` · `% que sobrou = Sobrou ÷ Receita`

Detalhes internos: [`PROJETO.md`](PROJETO.md).

## Publicar a demonstração (Streamlit Community Cloud)

1. Suba este repositório para o GitHub (público).
2. Em [share.streamlit.io](https://share.streamlit.io), clique em **Create app** e escolha o repositório.
3. Em **Main file path**, informe **`demo.py`** (e não `main.py`).
4. Publique e copie o link para o topo deste README e para o currículo.

## Privacidade

- O uso real guarda tudo em `dados/`, `extratos/`, `backups/` e `logs/`, pastas **ignoradas pelo Git**.
- O `.gitignore` também bloqueia qualquer `.pdf`, `.db`, `.xlsx` ou `.csv` solto. A única exceção é `demo_base/`,
  que contém apenas dados inventados (pessoa fictícia "Ana Exemplo da Silva").
- Para regenerar a base fictícia: `python scripts/gerar_demo.py`.
