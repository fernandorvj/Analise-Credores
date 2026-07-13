"""Componentes de interface do dashboard Streamlit.

Cada função renderiza uma seção da página e recebe o estado já calculado
(`ResultadoExtracao`). Nenhuma lógica de negócio vive aqui — apenas
orquestração de UI sobre o que já foi calculado em `src/`.
"""

from __future__ import annotations

import base64
import hmac
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import (
    APP_PASSWORD,
    APP_USERNAME,
    CLASSE_CORES,
    CLASSE_COR_PADRAO,
    CLASSES_RJ_PADRAO,
    CORES,
    CSS_PATH,
    EXPORTADOS_DIR,
    LOGO_PATH,
    NOME_EMPRESA,
    NOME_SISTEMA,
    PDFS_DIR,
    possui_chave_openai,
    possui_protecao_por_senha,
)
from src import analise_quorum, estrategia, ia, leitor_pdf
from src.estrategia import SimulacaoAprovacaoClasse
from src.exportar_excel import exportar_excel
from src.exportar_word import exportar_word
from src.models import Credor, ResultadoExtracao, StatusLeitura, VotoIntencao
from src.parser_credores import parsear_credores
from src.utils import (
    COLUNAS_MOEDA_PADRAO,
    COLUNAS_PERCENTUAL_PADRAO,
    credor_utilizavel_para_analise,
    formatar_moeda,
    formatar_percentual,
    parse_valor_brl,
)


def _cor_por_classe(classes: list[str]) -> dict[str, str]:
    """Mapa classe -> cor fixo (nunca reordenado por valor/ranking): usa a paleta
    categórica validada para as classes padrão de RJ e um cinza neutro para
    qualquer classe fora da lista padrão (ex.: "Não identificada").
    """
    return {classe: CLASSE_CORES.get(classe, CLASSE_COR_PADRAO) for classe in classes}


def injetar_css() -> None:
    """Injeta o CSS de identidade visual da AMF3 Capital na página."""
    if CSS_PATH.exists():
        st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def verificar_autenticacao() -> bool:
    """Bloqueia o acesso ao app até usuário e senha corretos serem informados.

    Sem `APP_PASSWORD` configurada (nem no .env local, nem nos Secrets do
    Streamlit Cloud), libera o acesso diretamente — conveniente para
    desenvolvimento local, mas o app publicado deve sempre ter login/senha
    definidos (ver README/instruções de deploy).
    """
    if not possui_protecao_por_senha():
        return True
    if st.session_state.get("autenticado"):
        return True

    st.markdown(f"### 🔒 {NOME_SISTEMA}")
    st.caption(f"{NOME_EMPRESA} — acesso restrito")
    with st.form("form_login"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar")

    if entrar:
        usuario_ok = hmac.compare_digest(usuario, APP_USERNAME) if APP_USERNAME else True
        senha_ok = hmac.compare_digest(senha, APP_PASSWORD)
        if usuario_ok and senha_ok:
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    return False


def renderizar_cabecalho() -> None:
    """Cabeçalho institucional: faixa em gradiente indigo (identidade AMF3) com
    a logo embutida em base64 (necessário para exibir dentro de HTML customizado
    do Streamlit, que não serve arquivos locais por caminho relativo).
    """
    logo_html = ""
    if LOGO_PATH.exists():
        logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")
        logo_html = f'<img src="data:image/png;base64,{logo_b64}" class="amf3-hero-logo" alt="{NOME_EMPRESA}" />'

    st.markdown(
        f"""
        <div class="amf3-hero">
            <div class="amf3-hero-dots"></div>
            {logo_html}
            <div class="amf3-hero-texto">
                <h1>{NOME_SISTEMA}</h1>
                <p>{NOME_EMPRESA} — Plataforma de Análise de Credores em Recuperação Judicial</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def renderizar_upload() -> ResultadoExtracao | None:
    """Renderiza o uploader de PDF e processa o arquivo, com cache em session_state
    para não reprocessar o mesmo arquivo a cada interação do usuário.
    """
    arquivo = st.file_uploader("Envie o PDF da relação de credores", type=["pdf"])
    if arquivo is None:
        return st.session_state.get("resultado")

    chave_cache = f"{arquivo.name}_{arquivo.size}"
    if st.session_state.get("_chave_cache") == chave_cache:
        return st.session_state.get("resultado")

    caminho_pdf = PDFS_DIR / arquivo.name
    caminho_pdf.write_bytes(arquivo.getvalue())

    with st.spinner("Lendo o PDF (páginas escaneadas podem levar mais tempo devido ao OCR)..."):
        paginas = leitor_pdf.ler_pdf(caminho_pdf)
        resultado = parsear_credores(paginas, arquivo.name)

    st.session_state["resultado"] = resultado
    st.session_state["_chave_cache"] = chave_cache
    st.session_state.pop("resumo_ia", None)
    st.session_state.pop("_caminho_xlsx", None)
    st.session_state.pop("_caminho_docx", None)

    if resultado.paginas_com_erro:
        st.warning(
            f"{len(resultado.paginas_com_erro)} página(s) escaneada(s) não puderam ser lidas "
            "(Tesseract OCR não disponível): " + ", ".join(str(p) for p in resultado.paginas_com_erro)
        )

    return resultado


def renderizar_kpis(resultado: ResultadoExtracao) -> None:
    valor_total = analise_quorum.valor_total_passivo(resultado.credores)
    classes = {c.classe for c in resultado.credores if credor_utilizavel_para_analise(c)}
    pendencias = len(resultado.credores_para_revisar) + len(resultado.credores_com_erro)

    colunas = st.columns(4)
    dados = [
        ("Total de Credores", str(resultado.total_credores)),
        ("Valor Total do Passivo", formatar_moeda(valor_total)),
        ("Classes Identificadas", str(len(classes))),
        ("Pendentes de Revisão", str(pendencias)),
    ]
    for coluna, (rotulo, valor) in zip(colunas, dados):
        with coluna:
            st.metric(rotulo, valor)


_OPCOES_CLASSE_EDITOR = CLASSES_RJ_PADRAO + ["Não identificada"]


def _editor_credores(
    credores_para_editar: list[Credor],
    resultado: ResultadoExtracao,
    key: str,
    mostrar_voto: bool = False,
) -> None:
    """Tabela editável de credores: permite corrigir nome, documento, classe e
    valor diretamente na interface (valores ausentes aparecem como R$ 0,00), e
    marcar "Aprovar" para mover o registro de Revisar/Erro para OK.

    As edições são gravadas diretamente nos objetos `Credor` de
    `resultado.credores` (mesma lista usada por toda a análise), então valem
    para a sessão inteira — tabelas, gráficos e exportações refletem a
    correção no próximo recálculo.
    """
    if not credores_para_editar:
        st.info("Nenhum registro para exibir.")
        return

    mapa_credores = {c.id: c for c in resultado.credores}

    linhas = [
        {
            "ID": c.id,
            "Nome": c.nome,
            "Documento": c.documento,
            "Classe": c.classe if c.classe in _OPCOES_CLASSE_EDITOR else "Não identificada",
            # Texto já formatado (R$ 1.234,56) — o NumberColumn do Streamlit não
            # suporta separador de milhar no padrão brasileiro (ponto/vírgula),
            # só o americano. Editar como texto e reaproveitar parse_valor_brl
            # ao gravar preserva o formato brasileiro em todo lugar.
            "Valor": formatar_moeda(c.valor if c.valor is not None else 0.0),
            "Status": c.status_leitura.value,
            **({"Voto": c.voto.value} if mostrar_voto else {}),
            "Aprovar": c.status_leitura == StatusLeitura.OK,
        }
        for c in credores_para_editar
    ]
    df_editor = pd.DataFrame(linhas)

    colunas_config = {
        "Valor": st.column_config.TextColumn(
            "Valor (R$)",
            help="Formato: R$ 1.234,56. Valores não identificados aparecem como R$ 0,00 — edite para o valor correto.",
        ),
        "Classe": st.column_config.SelectboxColumn("Classe", options=_OPCOES_CLASSE_EDITOR, required=True),
        "Status": st.column_config.TextColumn("Status", disabled=True),
        "Aprovar": st.column_config.CheckboxColumn(
            "Aprovar", help='Marque para mudar o status de "Revisar"/"Erro" para "OK".'
        ),
    }
    colunas_ordem = ["Nome", "Documento", "Classe", "Valor", "Status"]
    if mostrar_voto:
        colunas_config["Voto"] = st.column_config.SelectboxColumn(
            "Intenção de Voto", options=[v.value for v in VotoIntencao], required=True
        )
        colunas_ordem.append("Voto")
    colunas_ordem.append("Aprovar")

    df_editado = st.data_editor(
        df_editor,
        column_config=colunas_config,
        column_order=colunas_ordem,
        disabled=["ID"],
        hide_index=True,
        width="stretch",
        key=key,
    )

    for _, linha in df_editado.iterrows():
        credor = mapa_credores.get(linha["ID"])
        if credor is None:
            continue
        credor.nome = linha["Nome"]
        credor.documento = linha["Documento"]
        credor.classe = linha["Classe"]
        valor_editado = parse_valor_brl(linha["Valor"])
        if valor_editado is not None:
            credor.valor = valor_editado
        if mostrar_voto:
            credor.voto = VotoIntencao(linha["Voto"])
        if linha["Aprovar"]:
            credor.status_leitura = StatusLeitura.OK
            credor.observacoes = ""


def renderizar_pendencias(resultado: ResultadoExtracao) -> None:
    pendencias = resultado.credores_para_revisar + resultado.credores_com_erro
    if not pendencias:
        return
    with st.expander(f"⚠️ {len(pendencias)} registro(s) pendente(s) de revisão manual", expanded=False):
        st.caption(
            "Corrija nome, documento, classe ou valor diretamente na tabela e marque "
            '"Aprovar" para mover o registro para OK.'
        )
        _editor_credores(pendencias, resultado, key="editor_pendencias")


def renderizar_avisos_reconciliacao(resultado: ResultadoExtracao) -> None:
    """Alerta quando os subtotais/total geral impressos no PDF não batem com o
    que foi extraído — sinal de que a extração de tabela pode ter perdido linhas
    em alguma quebra de página (limitação conhecida de ferramentas de leitura de
    tabela em PDF). Os dados extraídos nunca são alterados automaticamente.
    """
    if not resultado.avisos_reconciliacao:
        return
    st.error(
        "**Divergência entre a extração e os totais impressos no documento.** "
        "A ferramenta de leitura de tabelas pode ter perdido linha(s) em alguma "
        "quebra de página. Confira manualmente as classes abaixo antes de usar os "
        "números para decisão:"
    )
    for aviso in resultado.avisos_reconciliacao:
        st.markdown(f"- {aviso}")


def _formatar_para_exibicao(df: pd.DataFrame) -> pd.DataFrame:
    df_exibicao = df.copy()
    for coluna in df_exibicao.columns:
        if coluna in COLUNAS_MOEDA_PADRAO:
            df_exibicao[coluna] = df_exibicao[coluna].apply(formatar_moeda)
        elif coluna in COLUNAS_PERCENTUAL_PADRAO:
            df_exibicao[coluna] = df_exibicao[coluna].apply(formatar_percentual)
    return df_exibicao


def renderizar_tabela(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Nenhum registro para exibir.")
        return
    st.dataframe(_formatar_para_exibicao(df), width="stretch", hide_index=True)


def renderizar_filtros(credores: list) -> pd.DataFrame:
    """Renderiza filtros de classe, status e faixa de valor, além de campo de busca."""
    df = analise_quorum.tabela_analitica(credores)
    if df.empty:
        st.info("Nenhum credor com valor identificado para exibir.")
        return df

    with st.expander("Filtros e pesquisa", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            classes = sorted(df["Classe"].unique())
            classes_selecionadas = st.multiselect("Classe", classes, default=classes)
        with col2:
            status = sorted(df["Status Leitura"].unique())
            status_selecionados = st.multiselect("Status de leitura", status, default=status)
        with col3:
            termo_busca = st.text_input("Buscar por nome ou documento")

        valor_min, valor_max = float(df["Valor"].min()), float(df["Valor"].max())
        if valor_min < valor_max:
            faixa_valor = st.slider(
                "Faixa de valor (R$)", min_value=valor_min, max_value=valor_max, value=(valor_min, valor_max)
            )
        else:
            faixa_valor = (valor_min, valor_max)

    filtrado = df[df["Classe"].isin(classes_selecionadas) & df["Status Leitura"].isin(status_selecionados)]
    filtrado = filtrado[(filtrado["Valor"] >= faixa_valor[0]) & (filtrado["Valor"] <= faixa_valor[1])]
    if termo_busca:
        termo = termo_busca.lower()
        filtrado = filtrado[
            filtrado["Nome"].str.lower().str.contains(termo) | filtrado["Documento"].str.lower().str.contains(termo)
        ]
    return filtrado


def renderizar_ranking(resultado: ResultadoExtracao) -> None:
    top_n = st.slider("Quantidade de credores no ranking", min_value=5, max_value=50, value=15, step=5)
    renderizar_tabela(analise_quorum.ranking_maiores_credores(resultado.credores, top_n=top_n))


def renderizar_graficos(resultado: ResultadoExtracao) -> None:
    df_classe = analise_quorum.resumo_por_classe(resultado.credores)
    if df_classe.empty:
        st.info("Sem dados suficientes para gerar gráficos.")
        return

    mapa_cores = _cor_por_classe(list(df_classe["Classe"]))

    col1, col2 = st.columns(2)
    with col1:
        fig_barras = px.bar(
            df_classe, x="Classe", y="Valor Total", color="Classe",
            color_discrete_map=mapa_cores, title="Valor Total por Classe",
        )
        fig_barras.update_layout(showlegend=False)
        st.plotly_chart(fig_barras, width="stretch")
    with col2:
        fig_pizza = px.pie(
            df_classe, names="Classe", values="Valor Total",
            color="Classe", color_discrete_map=mapa_cores, title="Participação por Classe",
        )
        st.plotly_chart(fig_pizza, width="stretch")

    df_analitica = analise_quorum.tabela_analitica(resultado.credores)
    if not df_analitica.empty:
        fig_pareto = go.Figure()
        fig_pareto.add_bar(
            x=df_analitica["Ranking"], y=df_analitica["Valor"], name="Valor",
            marker_color=CORES["grafico_indigo"],
        )
        fig_pareto.add_scatter(
            x=df_analitica["Ranking"], y=df_analitica["Participação Acumulada"] * 100,
            name="% Acumulado", yaxis="y2", marker_color=CORES["destaque"],
        )
        fig_pareto.update_layout(
            title="Concentração de Credores (Curva de Pareto)",
            yaxis=dict(title="Valor (R$)"),
            yaxis2=dict(title="% Acumulado", overlaying="y", side="right", range=[0, 100]),
            xaxis=dict(title="Ranking"),
        )
        st.plotly_chart(fig_pareto, width="stretch")


def _opcoes_classe(resultado: ResultadoExtracao) -> list[str]:
    classes = sorted({c.classe for c in resultado.credores if credor_utilizavel_para_analise(c)})
    return ["Total"] + classes


def renderizar_estrategia(resultado: ResultadoExtracao) -> None:
    classe_selecionada = st.selectbox("Base da análise", _opcoes_classe(resultado), key="estrategia_classe")
    classe_filtro = None if classe_selecionada == "Total" else classe_selecionada

    st.subheader("Credores Estratégicos")
    st.caption("Maiores créditos individuais disponíveis — oferecem o maior ganho de quórum por negociação.")
    renderizar_tabela(estrategia.credores_estrategicos(resultado.credores, classe=classe_filtro))

    st.subheader("Concentração de Votos")
    concentracao = estrategia.concentracao_votos(resultado.credores, classe=classe_filtro)
    colunas = st.columns(4)
    for coluna, (n, chave) in zip(colunas, [(1, "top_1"), (5, "top_5"), (10, "top_10"), (20, "top_20")]):
        with coluna:
            st.metric(f"Top {n} credor(es)", formatar_percentual(concentracao.get(chave, 0.0)))


def renderizar_simulacoes(resultado: ResultadoExtracao) -> None:
    classe_selecionada = st.selectbox("Base da simulação", _opcoes_classe(resultado), key="simulacao_classe")
    classe_filtro = None if classe_selecionada == "Total" else classe_selecionada

    credores_base = [
        c for c in resultado.credores
        if credor_utilizavel_para_analise(c) and (classe_filtro is None or c.classe == classe_filtro)
    ]
    opcoes_nomes = {
        f"{c.nome} ({formatar_moeda(c.valor)})": c.id
        for c in sorted(credores_base, key=lambda c: c.valor, reverse=True)
    }
    selecionados = st.multiselect(
        "Créditos já adquiridos (opcional — simula a partir de uma posição existente)",
        list(opcoes_nomes.keys()),
    )
    ids_adquiridos = {opcoes_nomes[s] for s in selecionados}

    simulacoes = estrategia.simular_formacao_quorum(
        resultado.credores, classe=classe_filtro, ja_adquiridos_ids=ids_adquiridos
    )
    renderizar_tabela(estrategia.tabela_simulacoes(simulacoes))

    for sim in simulacoes:
        if not sim.passos:
            continue
        with st.expander(f"Passo a passo para atingir {formatar_percentual(sim.percentual_alvo)}"):
            df_passos = pd.DataFrame(
                [
                    {
                        "Ordem": p.ordem,
                        "Nome": p.nome,
                        "Valor": formatar_moeda(p.valor),
                        "% Acumulado": formatar_percentual(p.percentual_acumulado),
                    }
                    for p in sim.passos
                ]
            )
            st.dataframe(df_passos, width="stretch", hide_index=True)


def renderizar_votacao_aprovacao(resultado: ResultadoExtracao) -> None:
    """Editor de credores (nome/documento/classe/valor + aprovação de pendências)
    e intenção de voto, seguido do status de aprovação do Plano de RJ por classe
    (Lei 11.101/2005, art. 45): Classes I e IV exigem maioria por quantidade de
    credores; Classes II e III exigem maioria por valor E por quantidade. A
    intenção de voto é definida manualmente aqui — não vem do PDF.
    """
    if not resultado.credores:
        st.info("Nenhum credor para exibir.")
        return

    st.caption(
        "Corrija nome, documento, classe ou valor e marque a intenção de voto de "
        "cada credor para simular a aprovação do plano por classe. Registros "
        "pendentes de revisão têm valor R$ 0,00 até serem corrigidos — marque "
        '"Aprovar" depois de corrigir para que entrem na análise. Isso não altera '
        "os dados extraídos do PDF — é um cenário técnico definido por você."
    )

    classes_presentes = sorted({c.classe for c in resultado.credores})
    classe_filtro = st.selectbox(
        "Filtrar credores para edição", ["Todas as classes"] + classes_presentes, key="voto_classe_filtro"
    )
    credores_editaveis = sorted(
        (c for c in resultado.credores if classe_filtro == "Todas as classes" or c.classe == classe_filtro),
        key=lambda c: c.valor or 0.0,
        reverse=True,
    )

    _editor_credores(credores_editaveis, resultado, key=f"editor_votos_{classe_filtro}", mostrar_voto=True)

    st.divider()
    st.subheader("Status de Aprovação por Classe")

    for sim in estrategia.simular_aprovacao_todas_classes(resultado.credores):
        _renderizar_card_aprovacao_classe(sim)


def _renderizar_card_aprovacao_classe(sim: SimulacaoAprovacaoClasse) -> None:
    icone = "✅" if sim.aprovada_atualmente else "🔴"
    with st.container(border=True):
        st.markdown(f"#### {icone} {sim.classe}")

        criterios_texto = []
        if sim.exige_valor:
            criterios_texto.append("valor")
        if sim.exige_quantidade:
            criterios_texto.append("quantidade de credores")
        st.caption("Critério de aprovação exigido: " + " e ".join(criterios_texto) + " (> 50%).")

        colunas = st.columns(2)
        if sim.exige_valor:
            with colunas[0]:
                st.metric("% Valor Favorável", formatar_percentual(sim.percentual_valor_atual))
        if sim.exige_quantidade:
            with colunas[1]:
                st.metric("% Credores Favoráveis (quantidade)", formatar_percentual(sim.percentual_quantidade_atual))

        if sim.aprovada_atualmente:
            st.success("Classe aprovada com a intenção de voto atual.")
            return

        if not sim.atingivel:
            st.warning("Mesmo adquirindo todos os credores não favoráveis desta classe, o critério não é atingido.")

        st.warning(
            f"Faltam **{formatar_moeda(sim.valor_a_adquirir)}** em **{sim.quantidade_a_adquirir} credor(es)** "
            "(entre os não favoráveis, adquiridos na ordem mais barata possível) para aprovar esta classe."
        )
        if sim.passos:
            with st.expander("Ver credores sugeridos para aquisição"):
                df_passos = pd.DataFrame(
                    [
                        {
                            "Ordem": p.ordem,
                            "Nome": p.nome,
                            "Valor": formatar_moeda(p.valor),
                            "% Valor Acumulado": formatar_percentual(p.percentual_valor_acumulado),
                            "% Quantidade Acumulada": formatar_percentual(p.percentual_quantidade_acumulado),
                        }
                        for p in sim.passos
                    ]
                )
                st.dataframe(df_passos, width="stretch", hide_index=True)


def renderizar_ia(resultado: ResultadoExtracao) -> None:
    if not possui_chave_openai():
        st.warning(
            "Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY no arquivo .env "
            "para habilitar esta seção."
        )
        return

    if st.button("Gerar resumo executivo com IA", type="primary"):
        with st.spinner("Consultando a IA..."):
            try:
                st.session_state["resumo_ia"] = ia.gerar_resumo_executivo(resultado)
            except RuntimeError as exc:
                st.error(str(exc))

    if st.session_state.get("resumo_ia"):
        st.markdown(st.session_state["resumo_ia"])

    st.divider()
    st.subheader("Pergunte sobre esta análise")
    pergunta = st.text_input("Sua pergunta", key="pergunta_ia")
    if st.button("Perguntar") and pergunta:
        with st.spinner("Consultando a IA..."):
            try:
                st.markdown(ia.responder_pergunta(resultado, pergunta))
            except RuntimeError as exc:
                st.error(str(exc))


def renderizar_exportacao(resultado: ResultadoExtracao) -> None:
    nome_base = Path(resultado.arquivo_nome).stem

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Gerar Excel (.xlsx)"):
            caminho = exportar_excel(resultado, EXPORTADOS_DIR / f"{nome_base}_analise.xlsx")
            st.session_state["_caminho_xlsx"] = str(caminho)
        if st.session_state.get("_caminho_xlsx"):
            caminho = Path(st.session_state["_caminho_xlsx"])
            st.download_button("Baixar Excel", caminho.read_bytes(), file_name=caminho.name)

    with col2:
        if st.button("Gerar Word (.docx)"):
            caminho = exportar_word(
                resultado,
                EXPORTADOS_DIR / f"{nome_base}_relatorio.docx",
                resumo_executivo=st.session_state.get("resumo_ia"),
            )
            st.session_state["_caminho_docx"] = str(caminho)
        if st.session_state.get("_caminho_docx"):
            caminho = Path(st.session_state["_caminho_docx"])
            st.download_button("Baixar Word", caminho.read_bytes(), file_name=caminho.name)


def renderizar_pagina_credores() -> None:
    """Página completa do módulo Credores — upload, KPIs e todas as abas de
    análise. Empacota, sem alterar, a mesma sequência de chamadas que antes
    vivia diretamente em `app.py`, para que o roteador da plataforma (agora
    com Home/menu lateral) possa tratar "Credores" como mais uma página.
    Nenhuma lógica de negócio ou algoritmo deste módulo foi alterado.
    """
    renderizar_cabecalho()

    resultado = renderizar_upload()
    if resultado is None:
        st.info("Envie um PDF da relação de credores acima para iniciar a análise.")
        return

    renderizar_kpis(resultado)
    renderizar_avisos_reconciliacao(resultado)
    renderizar_pendencias(resultado)

    (
        aba_tabela,
        aba_ranking,
        aba_graficos,
        aba_estrategia,
        aba_simulacoes,
        aba_aprovacao,
        aba_ia,
        aba_exportacao,
    ) = st.tabs(
        [
            "Tabela de Credores",
            "Ranking",
            "Gráficos",
            "Análise Estratégica",
            "Simulações de Quórum",
            "Aprovação do Plano",
            "IA",
            "Exportação",
        ]
    )

    with aba_tabela:
        renderizar_tabela(renderizar_filtros(resultado.credores))
    with aba_ranking:
        renderizar_ranking(resultado)
    with aba_graficos:
        renderizar_graficos(resultado)
    with aba_estrategia:
        renderizar_estrategia(resultado)
    with aba_simulacoes:
        renderizar_simulacoes(resultado)
    with aba_aprovacao:
        renderizar_votacao_aprovacao(resultado)
    with aba_ia:
        renderizar_ia(resultado)
    with aba_exportacao:
        renderizar_exportacao(resultado)
