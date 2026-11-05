import streamlit as st

from app import config
from app.contas import repositorio as contas
from app.classificacao.servico import CLASSIFICADA, contar_por_classificacao
from app.importacao import consultas
from app.ocorrencias import registro
from app.ocorrencias.registro import NIVEIS

st.title(f"💰 {config.NOME_PROGRAMA}")
st.caption("Seus extratos do banco viram números: quanto entrou, quanto saiu, para onde foi e quanto sobrou.")

abertas = registro.contar_abertas()
if sum(abertas.values()):
    partes = [f"{NIVEIS[n][0]} {q} {NIVEIS[n][1].lower()}" for n, q in abertas.items() if q]
    st.warning("**Ocorrências abertas:** " + " · ".join(partes))
    st.page_link("app/interface/paginas/ocorrencias.py", label="Ver ocorrências", icon="📋")

todas = contas.listar()
ativas = [c for c in todas if c.ativa]

tot = consultas.totais()
cls = contar_por_classificacao()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Contas ativas", len(ativas), help=" · ".join(c.nome for c in ativas) or None)
c2.metric("Extratos importados", tot["documentos"])
c3.metric("✅ Classificadas", cls[CLASSIFICADA])
c4.metric("❓ Para revisar", cls["Revisar"])
if tot["movimentacoes"]:
    st.page_link("app/interface/paginas/dashboard.py", label="Abrir o Dashboard", icon="📈")
    if cls["Revisar"]:
        st.page_link("app/interface/paginas/revisao.py", label=f"Revisar {cls['Revisar']} movimentação(ões)", icon="❓")
if not tot["documentos"]:
    st.page_link("app/interface/paginas/importacao.py", label="Importar o primeiro extrato", icon="📥")

st.divider()
st.subheader("Como usar, todo mês")
st.markdown(
    """
1. **📥 Importação** — baixe no app do banco o extrato do mês em **PDF** e solte aqui. Pode soltar os PDFs de
   todas as contas de uma vez: o programa descobre de qual conta é cada um e confere os saldos.
2. **❓ Revisão** — diga a **categoria** de cada movimentação (mercado, aluguel, salário...). É isso que faz
   os gráficos funcionarem. Marque *Criar regra* e o programa passa a classificar sozinho o que se repete.
3. **📈 Dashboard** — veja receita, despesas, quanto sobrou, para onde o dinheiro foi e a evolução mês a mês.
4. **🗓️ Meses** — quando estiver tudo conferido, feche o mês: o resultado fica guardado como oficial.
5. **🧾 Relatórios** — baixe o mês ou o ano em PDF, Excel ou CSV.
"""
)

with st.expander("O que mais tem aqui"):
    st.markdown(
        """
- **🏦 Contas** — já vêm duas contas de exemplo, uma do **Nubank** e uma do **Sicoob** (para mostrar que dá para ter mais de uma
  conta). Renomeie, crie outras ou desative as que não usar.
- **🗂️ Categorias** — a lista já vem pronta para uso pessoal; crie, renomeie ou desative como quiser.
- **⚙️ Regras** — o que o programa classifica sozinho. As mais fáceis de criar nascem na tela Revisão.
- **💰 Caixinhas** — o Extrato de Rendimentos das Caixinhas do Nubank mostra quanto está guardado e quanto rendeu.
- **💸 Movimentações** e **📄 Documentos** — tudo o que foi importado, com o PDF de origem de cada linha.
- **📋 Ocorrências** — nada dá errado em silêncio: todo problema de leitura aparece lá.
- **Bancos lidos hoje:** Nubank e Sicoob (extrato da conta em PDF) e Caixinhas do Nubank.
"""
    )

with st.expander("Onde estão os arquivos"):
    st.caption("Tudo fica só neste computador, dentro da pasta do programa. Nada é enviado para a internet.")
    st.code(
        f"Banco:    {config.caminho_banco()}\n"
        f"Extratos: {config.pasta_extratos()}\n"
        f"Backups:  {config.pasta_backups()}"
    )
