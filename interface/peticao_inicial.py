"""Módulo Petição Inicial — análise documental inteligente via IA.

Totalmente independente do módulo Credores: não cria clientes, não grava
cadastros, não compartilha estado com `interface/dashboard.py`. Reaproveita
a leitura/OCR de PDF (`src/leitor_pdf.py`) e o gateway único de IA
(`src/ia.py`) já usados pelo restante do sistema.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from config import EXPORTADOS_DIR, PETICOES_DIR, possui_chave_openai
from interface import layout
from interface.icones import icone
from src import ia, leitor_pdf
from src.exportar_word_peticao_inicial import exportar_word_peticao_inicial
from src.models_peticao_inicial import (
    SECOES,
    DadosEmpresa,
    EventoCronologia,
    ItemComJustificativa,
    PassivoFiscal,
    RelatorioPeticaoInicial,
)

_ICONE_GRAU_ATENCAO = {"Baixo": icone("aprovado"), "Médio": icone("alerta"), "Alto": icone("erro")}

_FASES = [
    "Lendo PDF",
    "Aplicando OCR",
    "Extraindo texto",
    "Organizando documento",
    "Consultando IA",
    "Gerando relatório",
]


def _processar_peticao(arquivo) -> RelatorioPeticaoInicial | None:
    if not possui_chave_openai():
        st.warning(
            "Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar "
            "a análise inteligente da Petição Inicial."
        )
        return None

    caminho_pdf = PETICOES_DIR / arquivo.name
    caminho_pdf.write_bytes(arquivo.getvalue())

    with st.status("Processando Petição Inicial...", expanded=True) as status:
        barra = st.progress(0.0)

        def _concluir_fase(indice: int) -> None:
            st.write(f"{icone('concluido')} {_FASES[indice]}")
            barra.progress((indice + 1) / len(_FASES))

        paginas = leitor_pdf.ler_pdf(caminho_pdf)
        _concluir_fase(0)  # Lendo PDF
        _concluir_fase(1)  # Aplicando OCR (feito dentro de ler_pdf, por página)

        _concluir_fase(2)  # Extraindo texto
        _concluir_fase(3)  # Organizando documento

        def _callback(mensagem: str) -> None:
            status.update(label=mensagem)
            st.write(mensagem)

        try:
            relatorio = ia.gerar_relatorio_peticao_inicial(paginas, arquivo.name, progress_callback=_callback)
        except RuntimeError as exc:
            status.update(label="Falha ao consultar a IA", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(4)  # Consultando IA

        _concluir_fase(5)  # Gerando relatório
        status.update(label="Relatório gerado com sucesso!", state="complete", expanded=False)

    return relatorio


def _renderizar_avisos(relatorio: RelatorioPeticaoInicial) -> None:
    if relatorio.paginas_ocr_baixa_confianca:
        paginas = ", ".join(str(p) for p in relatorio.paginas_ocr_baixa_confianca)
        st.warning(
            f"Páginas {paginas} foram lidas via OCR com possível baixa qualidade de "
            "reconhecimento — revise manualmente essas páginas no PDF original."
        )
    for aviso in relatorio.avisos:
        st.info(aviso)


def _renderizar_card_passivo_fiscal(relatorio: RelatorioPeticaoInicial) -> None:
    """Card de destaque fixo no topo da página — nunca omitido, mesmo quando
    nada foi localizado — para o usuário identificar rapidamente a existência
    (ou não) de passivo fiscal/execuções fiscais sem precisar abrir a seção.
    """
    pf = relatorio.passivo_fiscal
    with st.container(border=True):
        st.markdown(f"#### {icone('fiscal')} Passivo Fiscal e Execuções Fiscais")
        if pf.localizado:
            st.warning("Localizado")
        else:
            st.success("Não localizado")

        col_valor, col_execucao, col_qtd, col_orgaos = st.columns(4)
        with col_valor:
            st.metric(f"{icone('moeda')} Valor do Passivo Fiscal", pf.valor_passivo_fiscal)
        with col_execucao:
            st.metric(f"{icone('moeda')} Valor das Execuções", pf.valor_execucoes_fiscais)
        with col_qtd:
            st.metric(f"{icone('peticao_inicial')} Nº de Execuções/Processos", pf.quantidade_processos)
        with col_orgaos:
            orgaos_texto = ", ".join(pf.orgaos_envolvidos) if pf.orgaos_envolvidos else "Não localizado"
            st.metric(f"{icone('orgao')} Órgãos Envolvidos", orgaos_texto)

        icone_grau = _ICONE_GRAU_ATENCAO.get(pf.grau_atencao, icone("aprovado"))
        st.caption(f"Grau de Atenção: {icone_grau} {pf.grau_atencao}")


def _renderizar_passivo_fiscal(pf: PassivoFiscal) -> None:
    st.markdown("##### Situação Encontrada")
    situacao = [
        ("Existe Passivo Fiscal?", pf.existe_passivo_fiscal),
        ("Existe Execução Fiscal?", pf.existe_execucao_fiscal),
        ("Existe Parcelamento?", pf.existe_parcelamento),
        ("Existe Transação Tributária?", pf.existe_transacao_tributaria),
        ("Existe discussão administrativa ou judicial?", pf.existe_discussao_administrativa_judicial),
    ]
    st.table(pd.DataFrame(situacao, columns=["Pergunta", "Resposta"]))

    st.markdown("##### Resumo")
    st.markdown(pf.resumo)

    st.markdown("##### Valores")
    valores = [
        ("Valor do Passivo Fiscal", pf.valor_passivo_fiscal),
        ("Valor das Execuções Fiscais", pf.valor_execucoes_fiscais),
        ("Quantidade de Processos", pf.quantidade_processos),
        ("Tributos Envolvidos", ", ".join(pf.tributos_envolvidos) if pf.tributos_envolvidos else "Não localizado"),
    ]
    st.table(pd.DataFrame(valores, columns=["Item", "Valor"]))

    st.markdown("##### Trechos Localizados")
    if pf.trechos_localizados:
        st.table(
            pd.DataFrame(
                [{"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto} for t in pf.trechos_localizados]
            )
        )
    else:
        st.info("Nenhum trecho localizado no documento.")

    st.markdown("##### Avaliação Estratégica")
    st.markdown(pf.avaliacao_estrategica or "_Sem conteúdo gerado para esta seção._")

    st.markdown("##### Grau de Atenção")
    icone_grau = _ICONE_GRAU_ATENCAO.get(pf.grau_atencao, icone("aprovado"))
    st.markdown(f"{icone_grau} **{pf.grau_atencao}**")
    if pf.justificativa_grau_atencao:
        st.caption(pf.justificativa_grau_atencao)


def _renderizar_valor_secao(valor: object) -> None:
    if isinstance(valor, PassivoFiscal):
        _renderizar_passivo_fiscal(valor)
        return

    if isinstance(valor, DadosEmpresa):
        campos = [
            ("Razão Social", valor.razao_social),
            ("Nome Fantasia", valor.nome_fantasia),
            ("CNPJ", valor.cnpj),
            ("Segmento", valor.segmento),
            ("Atividade", valor.atividade),
            ("Grupo Econômico", valor.grupo_economico),
            ("Nº de Funcionários", valor.numero_funcionarios),
            ("Filiais", valor.filiais),
            ("Mercado de Atuação", valor.mercado_atuacao),
            *valor.outros_dados,
        ]
        st.table(pd.DataFrame(campos, columns=["Campo", "Valor"]))
        return

    if isinstance(valor, list):
        if not valor:
            st.info("Não foi possível identificar itens para esta seção no documento.")
        elif isinstance(valor[0], EventoCronologia):
            st.table(pd.DataFrame([{"Data": e.data, "Evento": e.evento} for e in valor]))
        elif isinstance(valor[0], ItemComJustificativa):
            for item in valor:
                st.markdown(f"**{item.ponto}**")
                st.caption(item.justificativa)
        return

    st.markdown(str(valor) or "_Sem conteúdo gerado para esta seção._")


def _renderizar_navegacao_por_secao(relatorio: RelatorioPeticaoInicial) -> None:
    titulos = [titulo for titulo, _ in SECOES]
    indice_ativo = st.session_state.get("peticao_secao_ativa", 0)

    col_nav, col_conteudo = st.columns([1, 3])
    with col_nav:
        escolha = st.radio(
            "Seções", titulos, index=indice_ativo, key="peticao_radio_secao", label_visibility="collapsed"
        )
        indice_ativo = titulos.index(escolha)
        st.session_state["peticao_secao_ativa"] = indice_ativo

    with col_conteudo:
        titulo, chave = SECOES[indice_ativo]
        with st.container(border=True):
            st.markdown(f"### {titulo}")
            _renderizar_valor_secao(getattr(relatorio, chave))

        col_ant, col_meio, col_prox = st.columns([1, 2, 1])
        with col_ant:
            if st.button("◀ Anterior", disabled=indice_ativo == 0, width="stretch", key="peticao_btn_anterior"):
                st.session_state["peticao_secao_ativa"] = max(0, indice_ativo - 1)
                st.rerun()
        with col_meio:
            st.markdown(
                f"<p style='text-align:center;color:var(--amf3-texto-mudo);'>Seção {indice_ativo + 1} de {len(SECOES)}</p>",
                unsafe_allow_html=True,
            )
        with col_prox:
            if st.button(
                "Próxima ▶", disabled=indice_ativo == len(SECOES) - 1, width="stretch", key="peticao_btn_proxima"
            ):
                st.session_state["peticao_secao_ativa"] = min(len(SECOES) - 1, indice_ativo + 1)
                st.rerun()


def _renderizar_relatorio_completo(relatorio: RelatorioPeticaoInicial) -> None:
    for titulo, chave in SECOES:
        with st.expander(titulo, expanded=False):
            _renderizar_valor_secao(getattr(relatorio, chave))


def _renderizar_exportacao(relatorio: RelatorioPeticaoInicial) -> None:
    st.divider()
    if st.button("Exportar Relatório", type="primary", icon=icone("peticao_inicial"), key="peticao_btn_exportar"):
        nome_base = Path(relatorio.arquivo_nome).stem
        caminho = exportar_word_peticao_inicial(relatorio, EXPORTADOS_DIR / f"{nome_base}_peticao_inicial.docx")
        st.session_state["peticao_caminho_docx"] = str(caminho)

    if st.session_state.get("peticao_caminho_docx"):
        caminho = Path(st.session_state["peticao_caminho_docx"])
        st.download_button(
            "Baixar Word (.docx)",
            caminho.read_bytes(),
            file_name=caminho.name,
            key="peticao_btn_baixar",
        )


def renderizar_peticao_inicial() -> None:
    layout.renderizar_titulo_pagina("peticao_inicial", "Petição Inicial")
    st.caption("Análise Inteligente da Recuperação Judicial")

    arquivo = st.file_uploader("Selecionar PDF", type=["pdf"], key="peticao_uploader")

    if arquivo is not None:
        chave_cache = f"{arquivo.name}_{arquivo.size}"
        if st.session_state.get("peticao_chave_cache") != chave_cache:
            if st.button("Analisar Petição", type="primary", icon=icone("peticao_inicial"), key="peticao_btn_analisar"):
                relatorio = _processar_peticao(arquivo)
                if relatorio is not None:
                    st.session_state["peticao_relatorio"] = relatorio
                    st.session_state["peticao_chave_cache"] = chave_cache
                    st.session_state["peticao_secao_ativa"] = 0
                    st.session_state.pop("peticao_caminho_docx", None)
                    st.rerun()

    relatorio = st.session_state.get("peticao_relatorio")
    if relatorio is None:
        st.info('Envie o PDF da Petição Inicial acima e clique em "Analisar Petição" para iniciar.')
        return

    _renderizar_avisos(relatorio)

    _renderizar_card_passivo_fiscal(relatorio)

    st.divider()
    modo = st.radio(
        "Modo de visualização",
        ["Navegação por seção", "Ver relatório completo"],
        horizontal=True,
        key="peticao_modo_visualizacao",
        label_visibility="collapsed",
    )
    if modo == "Navegação por seção":
        _renderizar_navegacao_por_secao(relatorio)
    else:
        _renderizar_relatorio_completo(relatorio)

    _renderizar_exportacao(relatorio)
