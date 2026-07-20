"""Módulo Proposta ao Credor — geração automática de um e-mail institucional
formal de proposta de aquisição de crédito, a partir dos dados informados
pelo usuário (e, opcionalmente, do contexto de documentos anexados).

Totalmente independente dos demais módulos: não cria clientes, não grava
cadastros, não envia e-mail (apenas gera o texto para revisão/exportação).
Reaproveita o leitor unificado (`src/leitor_documentos.py`) para o contexto
opcional e o gateway único de IA (`src/ia.py`).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from config import EXPORTADOS_DIR, PETICOES_DIR, possui_chave_openai
from interface import layout
from interface.componentes_ui import renderizar_preview_arquivo
from interface.icones import icone
from src import ia, leitor_documentos
from src.exportar_word_proposta import exportar_word_proposta

_TAMANHO_MAX_CONTEXTO_POR_ARQUIVO = 8000


def _ler_contexto_arquivos(arquivos) -> tuple[str, list[str]]:
    """Lê os documentos de contexto opcionais (petição, plano, lista de
    credores etc.) e monta um resumo textual truncado por arquivo — nunca
    interrompe o fluxo principal se um arquivo não puder ser lido, apenas
    avisa e segue com os demais.
    """
    partes: list[str] = []
    avisos: list[str] = []
    for arquivo in arquivos:
        caminho = PETICOES_DIR / arquivo.name
        caminho.write_bytes(arquivo.getvalue())
        try:
            texto, avisos_leitura = leitor_documentos.ler_documento(caminho)
            avisos.extend(avisos_leitura)
            partes.append(f"--- {arquivo.name} ---\n{texto[:_TAMANHO_MAX_CONTEXTO_POR_ARQUIVO]}")
        except (ValueError, RuntimeError) as exc:
            avisos.append(f"Não foi possível ler '{arquivo.name}': {exc}")
    return "\n\n".join(partes), avisos


def _formulario() -> tuple[dict, str] | None:
    with st.form("form_proposta_credor"):
        col1, col2 = st.columns(2)
        with col1:
            nome_credor = st.text_input("Nome do Credor / Destinatário")
            classe = st.text_input("Classe do Crédito", placeholder="Ex.: Classe III - Quirografário")
            valor_credito = st.number_input("Valor do Crédito (R$)", min_value=0.0, value=100000.0, step=1000.0)
        with col2:
            valor_atualizado = st.number_input("Valor Atualizado (R$)", min_value=0.0, value=0.0, step=1000.0)
            valor_proposta = st.number_input("Valor da Proposta (R$)", min_value=0.0, value=60000.0, step=1000.0)
            vpl = st.number_input("VPL (opcional, R$)", min_value=0.0, value=0.0, step=1000.0)

        observacoes = st.text_area("Observações (opcional)", height=80)

        arquivos_contexto = st.file_uploader(
            "Documentos de contexto (opcional) — petição, plano, lista de credores etc.",
            type=["pdf", "docx", "xlsx", "xls", "txt"],
            accept_multiple_files=True,
            key="prop_arquivos_contexto",
        )
        for arquivo_contexto in arquivos_contexto or []:
            renderizar_preview_arquivo(arquivo_contexto)

        enviado = st.form_submit_button("Gerar Proposta", type="primary", icon=icone("proposta_credor"))

    if not enviado:
        return None

    if not possui_chave_openai():
        st.warning(
            "Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar a "
            "geração da proposta."
        )
        return None

    contexto_documentos = None
    if arquivos_contexto:
        with st.spinner("Lendo documentos de contexto..."):
            contexto_documentos, avisos_contexto = _ler_contexto_arquivos(arquivos_contexto)
        for aviso in avisos_contexto:
            st.info(aviso)

    dados = {
        "Nome do Credor": nome_credor or "não informado",
        "Classe do Crédito": classe or "não informado",
        "Valor do Crédito": f"R$ {valor_credito:,.2f}",
        "Valor Atualizado": f"R$ {valor_atualizado:,.2f}" if valor_atualizado else None,
        "Valor da Proposta": f"R$ {valor_proposta:,.2f}",
        "VPL": f"R$ {vpl:,.2f}" if vpl else None,
        "Observações": observacoes or None,
        "Contexto de Documentos Anexados": contexto_documentos,
    }
    return dados, nome_credor


def renderizar_proposta_credor() -> None:
    layout.renderizar_titulo_pagina("proposta_credor", "Proposta ao Credor")
    st.caption("Geração de Proposta Formal de Aquisição de Crédito")

    resultado_formulario = _formulario()
    if resultado_formulario is not None:
        dados, nome_credor = resultado_formulario
        try:
            texto = ia.gerar_proposta_credor(dados)
            st.session_state["prop_texto_gerado"] = texto
            st.session_state["prop_nome_credor"] = nome_credor
            st.session_state.pop("prop_caminho_docx", None)
        except RuntimeError as exc:
            st.error(str(exc))

    texto_gerado = st.session_state.get("prop_texto_gerado")
    if texto_gerado is None:
        st.info('Preencha os dados acima e clique em "Gerar Proposta" para criar o texto formal.')
        return

    st.divider()
    st.markdown("#### Proposta Gerada")
    st.caption("Revise e edite livremente o texto abaixo antes de exportar — nada é enviado automaticamente.")
    texto_editado = st.text_area("Texto da proposta", value=texto_gerado, height=400, key="prop_texto_editado")

    st.divider()
    if st.button("Exportar Word", type="primary", icon=icone("exportar"), key="prop_btn_exportar"):
        nome_credor = st.session_state.get("prop_nome_credor", "") or "credor"
        nome_arquivo = "".join(c if c.isalnum() else "_" for c in nome_credor).strip("_") or "credor"
        caminho = exportar_word_proposta(texto_editado, st.session_state.get("prop_nome_credor", ""), EXPORTADOS_DIR / f"proposta_{nome_arquivo}.docx")
        st.session_state["prop_caminho_docx"] = str(caminho)

    caminho_str = st.session_state.get("prop_caminho_docx")
    if caminho_str and Path(caminho_str).exists():
        caminho = Path(caminho_str)
        st.download_button("Baixar Word (.docx)", caminho.read_bytes(), file_name=caminho.name, key="prop_btn_baixar")
