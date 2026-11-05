# Controle Financeiro Pessoal — como funciona por dentro

Aplicativo local (Python + SQLite + Streamlit + Plotly) para **uma pessoa** controlar as próprias
contas a partir dos extratos bancários em PDF. Sem IA e sem internet: tudo é leitura de PDF,
regras e contas determinísticas, em centavos.

Uso do dia a dia: ver `README.md`.

---

## 1. Princípios

1. **O extrato é a verdade.** A descrição original de cada movimentação nunca muda, e toda linha
   sabe de qual PDF e de qual página veio.
2. **Nada é gravado sem conferir.** O PDF só é importado se os totais e os saldos do dia baterem.
3. **O programa não chuta.** Quando não tem certeza (de qual conta é um PDF, qual regra vale),
   ele pergunta ou deixa em Revisão com a explicação.
4. **Nada é apagado.** Contas e categorias são desativadas; alterações manuais ficam na auditoria.
5. **Nada dá errado em silêncio.** Todo problema vira uma ocorrência (tela Ocorrências + `logs/`).
6. **Mês fechado não muda.** Para corrigir, reabre-se com motivo, e o histórico guarda os dois retratos.

## 2. O modelo

### Contas (`contas`)
Todas são da mesma pessoa; pode haver quantas quiser. Campos: nome, titular, banco, agência,
número, pasta dos extratos, ativa, observações. O banco inicial traz duas contas de exemplo: uma do
Nubank e uma do Sicoob (desativável). O número da conta é preenchido sozinho na primeira importação.

### Movimentações (`movimentacoes`)
Uma linha por lançamento do extrato: data, tipo (Entrada/Saída), valor em centavos (sempre
positivo), operação, contraparte, descrição original, documento de origem.

Classificação — só dois estados:

| Estado | Significa |
|---|---|
| `Classificada` | tem subcategoria; entra nos números conforme a natureza da categoria |
| `Revisar` | ainda sem categoria; fica fora dos números e aparece na tela Revisão |

Colunas de apoio: `origem_classificacao` (manual / regra), `confianca`, `regra_id`,
`sugestao_subcategoria_id` + `sugestao_motivo` (o programa propõe, a pessoa confirma).

### Categorias e naturezas (`categorias`, `subcategorias`)
Cada categoria tem uma **natureza**: `receita`, `despesa`, `investimento` ou `neutro`.

```
Receita       = entradas 'receita'  − saídas 'receita'      (estornos)
Despesas      = saídas 'despesa'    − entradas 'despesa'    (reembolsos)
Resultado     = Receita − Despesas                          ("sobrou no mês")
Margem        = Resultado ÷ Receita                         ("% que sobrou")
Investimentos = saídas 'investimento' − entradas 'investimento'   (fora do resultado)
Neutro        = caixinha/RDB, entre contas, terceiros       (não entra em nada)
Saldo         = último "saldo do dia" do banco, por conta, até o fim do mês
```
Código: `app/analise/indicadores.py`. As categorias iniciais ficam em `CATEGORIAS_INICIAIS`
(`app/banco/migracoes.py`) e só valem para a criação do banco.

## 3. Importação (`app/importacao/`, `app/leitores/`)

- `leitores/nubank.py` e `leitores/sicoob.py` leem o extrato da conta; cada um tem
  `e_extrato(caminho)` e `ler(caminho)`, e devolve um `ExtratoLido` (`leitores/base.py`).
  `base.conferir()` faz as conferências de saldo.
- `rendimentos/leitor_nubank.py` lê o Extrato de Rendimentos das Caixinhas (não gera
  movimentações: alimenta só a tela Caixinhas).
- **Duplicidade:** cada movimentação tem uma chave = conta + data + tipo + operação + contraparte
  + valor + nº da ocorrência no dia. Um PDF mais completo do mesmo período importa só o que é novo
  e preserva as classificações já feitas.
- **Vários PDFs de uma vez** (`importacao/lote.py`): para cada PDF o programa descobre o tipo, o
  banco e a conta. A conta é escolhida, entre as ativas daquele banco, por: (a) número da conta
  igual ao do cadastro; (b) nome do titular no cabeçalho; (c) para PDF de caixinhas, a conta que já
  tem caixinhas com os mesmos nomes. Sobrando dúvida, a tela pergunta.

Para ler outro banco: criar `app/leitores/<banco>.py` com `e_extrato` e `ler`, registrar em
`app/leitores/__init__.py` e acrescentar o nome em `BANCOS_CONHECIDOS` (`app/contas/repositorio.py`).

## 4. Regras (`app/classificacao/regras.py`)

Regra = condição → categoria.

- Condição: campo (contraparte / operação / descrição) + "contém o texto" ou "tem o CNPJ"
  + filtros opcionais (só entradas ou só saídas; só uma conta).
- Ação: **aplicar** (classifica direto) ou **sugerir** (fica em Revisão com a sugestão).
- Quando várias batem: vence a de maior prioridade; empate → CNPJ vence texto; se ainda assim
  mandam categorias diferentes → conflito, nada é aplicado.
- Regras nunca mexem no que a pessoa decidiu à mão nem em mês fechado.
- A forma mais fácil de criar uma regra é na tela Revisão ("📌 Criar regra"). Desfazer uma
  classificação na tela Movimentações também exclui a regra criada a partir dela.

Padrão embutido (`classificacao/servico.py`): Pix/transferência em que a outra ponta tem o nome do
titular das contas → **sugestão** de "Movimentação interna › Transferência entre minhas contas".

Regras iniciais (`REGRAS_INICIAIS`): Resgate/Aplicação RDB (neutro, aplicar), CELESC (energia,
aplicar) e sugestões para fatura do cartão, Uber, iFood, Netflix e Spotify.

## 5. Fechamento (`app/fechamento/servico.py`)

Fechar exige o checklist sem bloqueios (há movimentações, nada em Revisão, extratos cobrem o mês
inteiro). Grava um retrato dos números em JSON e faz backup. Reabrir exige motivo; ao fechar de
novo a tela Meses compara os dois retratos.

## 6. Estrutura do código

```
main.py                     ponto de entrada (navegação do Streamlit)
app/config.py               caminhos, nome do dono, prefixo dos backups
app/banco/                  conexão SQLite e migrações
app/contas/                 cadastro de contas
app/leitores/               leitores de extrato por banco
app/importacao/             analisar/importar um PDF, lote, consultas
app/classificacao/          categorias, classificação, regras, auditoria
app/analise/                indicadores
app/fechamento/             meses, checklist, retrato
app/rendimentos/            caixinhas
app/relatorios/             PDF (reportlab), Excel (openpyxl), CSV
app/ocorrencias/            log de ocorrências
app/backup/                 backup do banco
app/interface/paginas/      uma tela por arquivo
tests/                      testes com extratos falsos (geradores em tests/gerador_*.py)
```

## 7. Testes

`python -m pytest` na pasta do programa. Cada teste roda numa pasta temporária (variável
`ANALISADOR_RAIZ`), nunca no banco real. Os PDFs dos testes são gerados na hora, com nomes
fictícios, imitando o layout dos extratos reais.
