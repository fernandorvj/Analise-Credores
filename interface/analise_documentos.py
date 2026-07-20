"""Módulo Análise de Documentos — análise inteligente de qualquer documento
do processo (PDF, Word, Excel, TXT, imagem ou link) via IA, com perguntas de
acompanhamento livres sobre o conteúdo.

Totalmente independente dos demais módulos: não cria clientes, não grava
cadastros. Reaproveita o leitor unificado (`src/leitor_documentos.py`,
que por sua vez reaproveita `src/leitor_pdf.py` e `src/ocr.py`) e o gateway
único de IA (`src/ia.py`).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from config import EXPORTADOS_DIR, PETICOES_DIR, possui_chave_openai
from interface import layout
from interface.icones import icone
from src import ia, leitor_documentos
from src.exportar_word_analise_documentos import exportar_word_analise_documentos
from src.models_analise_documentos import SECOES, AnaliseDocumento, ItemComContexto

_FASES = ["Lendo documento", "Extraindo texto", "Organizando conteúdo", "Consultando IA", "Gerando análise"]

_EXTENSOES_ACEITAS = ["pdf", "docx", "xlsx", "xls", "txt", "png", "jpg", "jpeg", "bmp", "tiff"]

_TIPO_POR_EXTENSAO = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".xlsx": "XLSX",
    ".xls": "XLSX",
    ".txt": "TXT",
    ".png": "Imagem",
    ".jpg": "Imagem",
    ".jpeg": "Imagem",
    ".bmp": "Imagem",
    ".tiff": "Imagem",
}


def _processar_arquivo(arquivo) -> tuple[AnaliseDocumento, str] | None:
    if not possui_chave_openai():
        st.warning(
            "Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar "
            "a análise inteligente de documentos."
        )
        return None

    caminho = PETICOES_DIR / arquivo.name
    caminho.write_bytes(arquivo.getvalue())
    tipo_origem = _TIPO_POR_EXTENSAO.get(caminho.suffix.lower(), "Documento")

    with st.status("Analisando documento...", expanded=True) as status:
        barra = st.progress(0.0)

        def _concluir_fase(indice: int) -> None:
            st.write(f"{icone('concluido')} {_FASES[indice]}")
            barra.progress((indice + 1) / len(_FASES))

        try:
            texto, avisos_leitura = leitor_documentos.ler_documento(caminho)
        except (ValueError, RuntimeError) as exc:
            status.update(label="Falha ao ler o documento", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(0)
        _concluir_fase(1)
        _concluir_fase(2)

        def _callback(mensagem: str) -> None:
            status.update(label=mensagem)
            st.write(mensagem)

        try:
            analise = ia.analisar_documento(texto, arquivo.name, tipo_origem, progress_callback=_callback)
        except RuntimeError as exc:
            status.update(label="Falha ao consultar a IA", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(3)
        _concluir_fase(4)

        analise.avisos = [*avisos_leitura, *analise.avisos]
        status.update(label="Análise gerada com sucesso!", state="complete", expanded=False)

    return analise, texto


def _processar_link(url: str) -> tuple[AnaliseDocumento, str] | None:
    if not possui_chave_openai():
        st.warning(
            "Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar "
            "a análise inteligente de documentos."
        )
        return None

    with st.status("Analisando link...", expanded=True) as status:
        barra = st.progress(0.0)

        def _concluir_fase(indice: int) -> None:
            st.write(f"{icone('concluido')} {_FASES[indice]}")
            barra.progress((indice + 1) / len(_FASES))

        try:
            texto, avisos_leitura = leitor_documentos.ler_link(url)
        except ValueError as exc:
            status.update(label="Falha ao acessar o link", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(0)
        _concluir_fase(1)
        _concluir_fase(2)

        def _callback(mensagem: str) -> None:
            status.update(label=mensagem)
            st.write(mensagem)

        try:
            analise = ia.analisar_documento(texto, url, "Link", progress_callback=_callback)
        except RuntimeError as exc:
            status.update(label="Falha ao consultar a IA", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(3)
        _concluir_fase(4)

        analise.avisos = [*avisos_leitura, *analise.avisos]
        status.update(label="Análise gerada com sucesso!", state="complete", expanded=False)

    return analise, texto


def _renderizar_avisos(analise: AnaliseDocumento) -> None:
    for aviso in analise.avisos:
        st.info(aviso)


def _renderizar_valor_secao(valor: object) -> None:
    if isinstance(valor, list):
        if not valor:
            st.info("Não foi possível identificar itens para esta seção no documento.")
        elif isinstance(valor[0], ItemComContexto):
            st.table(pd.DataFrame([{"Item": i.item, "Contexto": i.contexto} for i in valor]))
        else:
            for item in valor:
                st.markdown(f"- {item}")
        return

    st.markdown(str(valor) or "_Sem conteúdo gerado para esta seção._")


def _renderizar_relatorio(analise: AnaliseDocumento) -> None:
    for titulo, chave in SECOES:
        with st.expander(titulo, expanded=(chave == "resumo_executivo")):
            _renderizar_valor_secao(getattr(analise, chave))


def _renderizar_perguntas(texto_fonte: str) -> None:
    st.markdown("#### Perguntas sobre o Documento")
    st.caption("Faça perguntas livres sobre o conteúdo — a IA responde com base exclusivamente no texto extraído.")

    historico = st.session_state.setdefault("doc_perguntas_respostas", [])
    for pergunta, resposta in historico:
        st.markdown(f"**Você:** {pergunta}")
        st.markdown(f"**IA:** {resposta}")
        st.divider()

    with st.form("form_pergunta_documento", border=False):
        pergunta = st.text_input("Sua pergunta", key="doc_pergunta_texto")
        if st.form_submit_button("Perguntar", icon=icone("analise_documentos")):
            if not possui_chave_openai():
                st.warning("Nenhuma chave de API da OpenAI configurada.")
            elif not pergunta.strip():
                st.warning("Digite uma pergunta antes de enviar.")
            else:
                try:
                    resposta = ia.responder_pergunta_documento(texto_fonte, pergunta)
                    historico.append((pergunta, resposta))
                    st.session_state["doc_perguntas_respostas"] = historico
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))


def _renderizar_exportacao(analise: AnaliseDocumento) -> None:
    st.divider()
    if st.button("Exportar Relatório", type="primary", icon=icone("analise_documentos"), key="doc_btn_exportar"):
        nome_base = Path(analise.arquivo_nome).stem or "analise_documento"
        caminho = exportar_word_analise_documentos(analise, EXPORTADOS_DIR / f"{nome_base}_analise.docx")
        st.session_state["doc_caminho_docx"] = str(caminho)

    caminho_str = st.session_state.get("doc_caminho_docx")
    if caminho_str and Path(caminho_str).exists():
        caminho = Path(caminho_str)
        st.download_button(
            "Baixar Word (.docx)", caminho.read_bytes(), file_name=caminho.name, key="doc_btn_baixar"
        )


def renderizar_analise_documentos() -> None:
    layout.renderizar_titulo_pagina("analise_documentos", "Análise de Documentos")
    st.caption("Análise Inteligente de Documentos do Processo")

    modo = st.radio(
        "Origem do documento", ["Enviar arquivo", "Informar link"], horizontal=True, key="doc_modo_origem"
    )

    if modo == "Enviar arquivo":
        arquivo = st.file_uploader("Selecionar documento", type=_EXTENSOES_ACEITAS, key="doc_uploader")
        if arquivo is not None:
            chave_cache = f"{arquivo.name}_{arquivo.size}"
            if st.session_state.get("doc_chave_cache") != chave_cache:
                if st.button("Analisar Documento", type="primary", icon=icone("analise_documentos"), key="doc_btn_analisar"):
                    resultado = _processar_arquivo(arquivo)
                    if resultado is not None:
                        analise, texto_fonte = resultado
                        st.session_state["doc_analise"] = analise
                        st.session_state["doc_texto_fonte"] = texto_fonte
                        st.session_state["doc_chave_cache"] = chave_cache
                        st.session_state["doc_perguntas_respostas"] = []
                        st.session_state.pop("doc_caminho_docx", None)
                        st.rerun()
    else:
        url = st.text_input("URL do link", key="doc_link_input", placeholder="https://...")
        if url.strip():
            chave_cache = f"link_{url.strip()}"
            if st.session_state.get("doc_chave_cache") != chave_cache:
                if st.button("Analisar Link", type="primary", icon=icone("analise_documentos"), key="doc_btn_analisar_link"):
                    resultado = _processar_link(url.strip())
                    if resultado is not None:
                        analise, texto_fonte = resultado
                        st.session_state["doc_analise"] = analise
                        st.session_state["doc_texto_fonte"] = texto_fonte
                        st.session_state["doc_chave_cache"] = chave_cache
                        st.session_state["doc_perguntas_respostas"] = []
                        st.session_state.pop("doc_caminho_docx", None)
                        st.rerun()

    analise = st.session_state.get("doc_analise")
    if analise is None:
        st.info('Envie um documento (ou informe um link) acima e clique em "Analisar" para iniciar.')
        return

    _renderizar_avisos(analise)

    st.divider()
    _renderizar_relatorio(analise)

    st.divider()
    _renderizar_perguntas(st.session_state.get("doc_texto_fonte", ""))

    _renderizar_exportacao(analise)
