from pathlib import Path

import pandas as pd
import streamlit as st

from app import config
from app.contas import repositorio as contas_repo
from app.importacao import servico
from app.interface.formato import data_br, reais
from app.leitores import LEITORES
from app.rendimentos import servico as rendimentos


def mostrar_rendimentos(a, chave: str) -> None:
    """Resultado da leitura de um Extrato de Rendimentos das Caixinhas."""
    st.subheader("2. Resultado da leitura — rendimentos das caixinhas")
    if a.documento_existente:
        d = a.documento_existente
        st.info(f"Este arquivo **já foi importado** em {data_br(d['importado_em'])} "
                f"(período {data_br(d['periodo_inicio'])} a {data_br(d['periodo_fim'])}). Nada a fazer.")
        return
    if a.erro:
        st.error(f"🔴 **Não consegui ler:** {a.erro.mensagem}")
        if a.erro.detalhe:
            st.code(a.erro.detalhe, language=None)
        st.caption("Registrado em **Ocorrências**. Nada foi importado.")
        return
    ext = a.extrato
    st.markdown(f"**Período:** {data_br(ext.periodo_inicio)} a {data_br(ext.periodo_fim)} · "
                f"**Páginas:** {ext.paginas}")
    for ap in ext.aplicacoes:
        ja = next((x for x in rendimentos.aplicacoes() if x["conta_id"] == a.conta.id and x["nome"] == ap.nome), None)
        st.markdown(f"**{ap.nome}**" + (f" — {ap.produto}" if ap.produto else "")
                    + ("" if ja else " *(caixinha nova; dá para dar um apelido na tela Caixinhas)*"))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Saldo no fim do período", reais(ap.saldo_final))
        c2.metric("Rendimento informado", reais(sum(r.valor for r in ap.rendimentos)) if ap.rendimentos else "—")
        c3.metric("Movimentações lidas", len(ap.movimentos))
        c4.metric("IR + IOF retidos", reais(sum(m.ir + m.iof for m in ap.movimentos)))
    if a.problemas:
        st.error(f"🟠 **Tive dificuldade para confirmar:** {len(a.problemas)} conferência(s) falharam. "
                 "O PDF **não será importado**.")
        for p in a.problemas:
            with st.expander(p.mensagem + (f" — página {p.pagina}" if p.pagina else "")):
                st.code(p.detalhe, language=None)
        st.caption("Registrado em **Ocorrências**.")
    else:
        st.success("✅ Conferências passaram: todas as linhas foram entendidas, cada valor líquido bate com "
                   "bruto − IR − IOF e as datas estão dentro do período.")
        st.info("⬇️ **Ainda não foi gravado.** Confira a lista abaixo e clique em **📥 Importar** no fim da página.")
    novas = {k for _, _, k in a.novas}
    linhas = [{"Caixinha": ap.nome, "Data": data_br(m.data), "Movimentação": m.tipo, "Valor bruto": reais(m.bruto),
               "IR": reais(m.ir), "IOF": reais(m.iof), "Valor líquido": reais(m.liquido), "Pág.": m.pagina,
               "Situação": "🆕 Nova" if k in novas else "Já existe"} for ap, m, k in a.movimentos]
    linhas += [{"Caixinha": ap.nome, "Data": data_br(r.data), "Movimentação": r.rotulo, "Valor bruto": "",
                "IR": "", "IOF": "", "Valor líquido": reais(r.valor), "Pág.": r.pagina, "Situação": "Rendimento"}
               for ap in ext.aplicacoes for r in ap.rendimentos]
    if linhas:
        st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True,
                     height=min(35 * len(linhas) + 38, 500))
    if a.pode_importar:
        st.subheader("3. Importar")
        if st.button("📥 Importar rendimentos das caixinhas", type="primary"):
            rendimentos.importar(a)
            del st.session_state[chave]
            st.success("Importado. Backup feito antes. Veja em **Caixinhas**.")
            st.balloons()

st.title("📥 Importação")
if config.modo_demo():
    st.warning("Esta é uma **demonstração pública**: não envie extratos reais. "
               "Para testar, use os PDFs fictícios da pasta `demo_base/extratos/` do repositório.")
st.caption(
    "Leia os extratos em PDF, confira o resultado e só então importe. "
    "Nada é gravado antes de você clicar em Importar."
)

SITUACAO = {"pronto": "✅ Pronto para importar", "ja_importado": "☑️ Já importado", "sem_conta": "❓ Escolha a conta",
            "conferencia": "🟠 Conferência falhou", "erro": "🔴 Não consegui ler"}


def tela_lote() -> None:
    """Vários PDFs de uma vez: o programa descobre a conta de cada um."""
    from app.importacao import lote

    st.subheader("1. Coloque os PDFs do mês")
    st.caption("Extratos de conta (Nubank, Sicoob) e Extratos de Rendimentos das Caixinhas, de qualquer conta, "
               "todos juntos. Envie por aqui **ou** copie os arquivos para a pasta `extratos/_entrada/`.")
    n_envio = st.session_state.get("lote_envio", 0)
    enviados = st.file_uploader("Arquivos PDF", type=["pdf"], accept_multiple_files=True, key=f"lote_up_{n_envio}")
    if enviados and st.button(f"Guardar {len(enviados)} PDF(s) na caixa de entrada"):
        for arq in enviados:
            lote.guardar_na_entrada(arq.name, arq.getvalue())
        st.session_state["lote_envio"] = n_envio + 1
        st.session_state.pop("lote", None)
        st.rerun()

    pdfs = lote.pdfs_na_entrada()
    if not pdfs:
        st.info("A caixa de entrada está vazia.")
        ultimo = st.session_state.get("lote_resultado")
        if ultimo:
            st.success(ultimo)
        return
    st.markdown(f"**{len(pdfs)} PDF(s) na caixa de entrada:** " + " · ".join(f"`{p.name}`" for p in pdfs[:30]))

    if st.button("🔎 Ler e conferir todos", type="primary"):
        with st.spinner("Lendo os PDFs, identificando as contas e conferindo os saldos..."):
            st.session_state["lote"] = lote.analisar_entrada()
        st.session_state.pop("lote_resultado", None)

    itens = [i for i in st.session_state.get("lote", []) if i.caminho.exists()]
    ultimo = st.session_state.get("lote_resultado")
    if ultimo:
        st.success(ultimo)
    if not itens:
        return
    if {p.name for p in pdfs} - {i.nome for i in itens}:
        st.caption("Há PDFs novos na caixa que ainda não foram lidos: clique em **Ler e conferir todos** de novo.")

    st.subheader("2. Resultado da leitura")
    cont = {k: sum(1 for i in itens if i.situacao == k) for k in SITUACAO}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prontos para importar", cont["pronto"])
    c2.metric("Já importados antes", cont["ja_importado"])
    c3.metric("Precisam que você escolha a conta", cont["sem_conta"])
    c4.metric("Com problema", cont["conferencia"] + cont["erro"])

    st.dataframe(pd.DataFrame([
        {"Arquivo": i.nome, "Tipo": i.tipo or "?", "Banco": i.banco or "?",
         "Conta": i.conta.nome if i.conta else "—",
         "Período": f"{data_br(i.periodo[0])} a {data_br(i.periodo[1])}" if i.periodo else "—",
         "Novas": str(i.qtd_novas) if i.qtd_novas is not None and i.conta else "—",
         "Situação": SITUACAO[i.situacao], "Observação": i.mensagem}
        for i in itens
    ]), hide_index=True, use_container_width=True, height=min(35 * len(itens) + 38, 460))
    st.caption("**Conta** é onde o PDF vai entrar. O programa decide pelo banco, pelo número da conta e pelo nome "
               "do titular; a coluna Observação diz como. Se não tiver certeza, ele não chuta: pergunta. "
               "Na primeira importação de cada conta ele guarda o número dela, e as próximas entram sozinhas.")

    # ---- contas que o programa não conseguiu identificar
    for k, item in enumerate(itens):
        if item.situacao != "sem_conta":
            continue
        a, b = st.columns([3, 1], vertical_alignment="bottom")
        escolha = a.selectbox(f"De qual conta é **{item.nome}**?", item.candidatas,
                              format_func=lambda c: f"{c.nome} ({c.banco}) — titular {c.titular}",
                              key=f"lote_conta_{item.nome}")
        if b.button("Usar esta conta", key=f"lote_usar_{item.nome}") and escolha is not None:
            todos = st.session_state["lote"]
            todos[todos.index(item)] = lote.analisar_arquivo(item.caminho, escolha)
            st.rerun()

    # ---- detalhes dos problemas
    for item in itens:
        if item.situacao not in ("conferencia", "erro"):
            continue
        with st.expander(f"{SITUACAO[item.situacao]} — {item.nome}"):
            a = item.analise
            erro = item.erro or (a.erro if a else None)
            if erro:
                st.write(erro.mensagem)
                if erro.detalhe:
                    st.code(erro.detalhe, language=None)
            for p in (a.problemas if a else []):
                st.write(p.mensagem + (f" — página {p.pagina}" if p.pagina else ""))
                st.code(p.detalhe, language=None)
            st.caption("Registrado em **Ocorrências**. Este PDF fica na caixa de entrada e não é importado.")

    # ---- importar
    st.subheader("3. Importar")
    b1, b2 = st.columns(2)
    if cont["pronto"]:
        if b1.button(f"📥 Importar os {cont['pronto']} PDF(s) prontos", type="primary"):
            with st.spinner("Importando..."):
                feitos, falhas = lote.importar_prontos(itens)
            por_conta: dict[str, int] = {}
            for i in feitos:
                por_conta[i.conta.nome] = por_conta.get(i.conta.nome, 0) + 1
            texto = (f"✅ {len(feitos)} PDF(s) importado(s): "
                     + " · ".join(f"{c}: {n}" for c, n in sorted(por_conta.items()))
                     + ". Backup feito antes de cada um. Os arquivos foram guardados na pasta de cada conta. "
                       "Veja **Revisão**, **Movimentações** e **Caixinhas**.")
            if falhas:
                texto += "\n\n⚠️ Não importados: " + " · ".join(f"{i.nome} ({m})" for i, m in falhas)
            st.session_state["lote_resultado"] = texto
            st.session_state["lote"] = lote.analisar_entrada(registrar_ocorrencias=False)
            st.rerun()
    else:
        b1.caption("Nenhum PDF pronto para importar.")
    if cont["ja_importado"]:
        if b2.button(f"🧹 Tirar da caixa os {cont['ja_importado']} já importados"):
            lote.limpar_ja_importados(itens)
            st.session_state["lote"] = [i for i in itens if i.caminho.exists()]
            st.rerun()


modo = st.segmented_control("Como importar", ["Vários PDFs (automático)", "Um PDF (manual)"],
                            default="Vários PDFs (automático)",
                            help="Automático: solte todos os PDFs do mês e o programa descobre a conta de cada um. "
                                 "Manual: você escolhe a conta e um PDF (use também para PDF com senha).") \
    or "Vários PDFs (automático)"
if modo.startswith("Vários"):
    tela_lote()
    st.stop()

contas = contas_repo.listar(somente_ativas=True)
conta = st.selectbox("Conta", contas, format_func=lambda c: f"{c.nome} ({c.banco})")
if conta is None:
    st.stop()

if conta.banco not in LEITORES:
    st.warning(
        f"Ainda não existe leitor para o **{conta.banco}**. "
        "Hoje o programa lê extratos em PDF do Nubank e do Sicoob."
    )
st.caption("Aceita o **extrato da conta** e o **Extrato de Rendimentos das Caixinhas** (Nubank): "
           "o programa reconhece sozinho qual é.")

pasta_conta = config.pasta_extratos() / conta.pasta

# ------------------------------------------------------------ escolher o PDF
st.subheader("1. Escolha o PDF")
aba_pasta, aba_enviar = st.tabs(["📂 PDFs na pasta da conta", "⬆️ Enviar um PDF"])

with aba_enviar:
    enviado = st.file_uploader("Arquivo PDF do extrato", type=["pdf"], key=f"up_{conta.id}")
    if enviado is not None and st.button("Guardar na pasta da conta"):
        pasta_conta.mkdir(parents=True, exist_ok=True)
        destino = pasta_conta / enviado.name
        n = 2
        while destino.exists():
            destino = pasta_conta / f"{Path(enviado.name).stem} ({n}).pdf"
            n += 1
        destino.write_bytes(enviado.getvalue())
        st.success(f"Guardado em extratos/{conta.pasta}/{destino.name}. Escolha-o na aba ao lado.")

with aba_pasta:
    st.caption(f"Pasta: `extratos/{conta.pasta}/` — aparecem só os PDFs ainda não importados.")
    pendentes = servico.pdfs_pendentes(conta)
    if not pendentes:
        st.info("Nenhum PDF novo nesta pasta. Coloque o extrato lá ou use a aba **Enviar um PDF**.")
        escolhido = None
    else:
        escolhido = st.radio(
            "PDF", pendentes, format_func=lambda p: str(p.relative_to(pasta_conta)), key=f"pdf_{conta.id}"
        )

if not escolhido:
    st.stop()

senha = st.text_input("Senha do PDF (só se ele tiver)", type="password", key="senha_pdf")

chave = f"analise::{conta.id}::{escolhido}"
if st.button("🔎 Ler e conferir", type="primary"):
    with st.spinner("Lendo o PDF e conferindo os saldos..."):
        if rendimentos.e_pdf_de_rendimentos(escolhido, senha or None):
            st.session_state[chave] = rendimentos.analisar(conta, escolhido, senha or None)
        else:
            st.session_state[chave] = servico.analisar(conta, escolhido, senha or None)

a = st.session_state.get(chave)
if a is None:
    st.stop()

if hasattr(a, "movimentos"):   # análise de um PDF de rendimentos
    mostrar_rendimentos(a, chave)
    st.stop()

# ------------------------------------------------------------ resultado
st.subheader("2. Resultado da leitura")

if a.documento_existente:
    d = a.documento_existente
    st.info(
        f"Este arquivo **já foi importado** em {data_br(d['importado_em'])} "
        f"(conta {d['conta_nome']}, período {data_br(d['periodo_inicio'])} a {data_br(d['periodo_fim'])}). "
        "Nada a fazer."
    )
    st.stop()

if a.erro:
    st.error(f"🔴 **Não consegui ler:** {a.erro.mensagem}")
    if a.erro.detalhe:
        st.code(a.erro.detalhe, language=None)
    st.caption("Registrado em **Ocorrências**. Nada foi importado.")
    st.stop()

ext = a.extrato
st.markdown(
    f"**Período:** {data_br(ext.periodo_inicio)} a {data_br(ext.periodo_fim)} · "
    f"**Páginas:** {ext.paginas}"
)
c1, c2, c3 = st.columns(3)
c1.metric("Movimentações lidas", len(ext.itens))
c2.metric("Já existentes", len(a.existentes))
c3.metric("Novas", len(a.novas))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Saldo inicial", reais(ext.saldo_inicial))
c2.metric("Entradas", reais(ext.total_entradas))
c3.metric("Saídas", reais(ext.total_saidas))
c4.metric("Saldo final", reais(ext.saldo_final))

if a.problemas:
    st.error(f"🟠 **Tive dificuldade para confirmar:** {len(a.problemas)} conferência(s) falharam. "
             "O extrato **não será importado**.")
    for p in a.problemas:
        with st.expander(f"{p.mensagem}" + (f" — página {p.pagina}" if p.pagina else "")):
            st.code(p.detalhe, language=None)
    st.caption("Registrado em **Ocorrências**.")
else:
    st.success(
        "✅ Todas as conferências passaram: "
        + ("cada bloco de entradas/saídas bate com seus itens, " if ext.grupos else "")
        + f"os {len(ext.saldos_dia)} saldos do dia batem e o saldo final bate."
    )
    if a.pode_importar:
        st.info("⬇️ **Ainda não foi gravado.** Confira a lista abaixo e clique em **📥 Importar** no fim da página.")

if a.sumidas:
    st.warning(
        f"🟡 {len(a.sumidas)} movimentação(ões) que vieram em um PDF anterior deste período "
        "**não aparecem** neste. Se importar, isso vai para **Ocorrências** para você revisar."
    )

novas_chaves = {k for _, k in a.novas}
tabela = pd.DataFrame([
    {
        "Data": data_br(i.data),
        "Tipo": i.tipo,
        "Valor": reais(i.valor if i.tipo == "Entrada" else -i.valor, sinal=True),
        "Operação": i.operacao,
        "Contraparte": i.contraparte,
        "Pág.": i.pagina,
        "Situação": "🆕 Nova" if k in novas_chaves else "Já existe",
    }
    for i, k in zip(ext.itens, a.chaves)
])
st.dataframe(tabela, hide_index=True, use_container_width=True, height=min(35 * len(tabela) + 38, 500))

# ------------------------------------------------------------ importar
if a.pode_importar:
    st.subheader("3. Importar")
    rotulo = (f"Importar {len(a.novas)} movimentação(ões) nova(s)" if a.novas
              else "Registrar o documento (nenhuma movimentação nova)")
    if st.button(f"📥 {rotulo}", type="primary"):
        doc_id = servico.importar(a)
        del st.session_state[chave]
        st.success(f"Importado (documento nº {doc_id}). Backup feito antes. Agora dê as categorias em **Revisão**.")
        st.balloons()
