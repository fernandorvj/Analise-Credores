"""Componentes de interface reutilizáveis, compartilhados por múltiplos
módulos fora do namespace de `interface/calculadora/` (que já tem os seus
próprios em `componentes.py`). Nenhuma lógica de negócio vive aqui — só
apresentação, no padrão visual único da plataforma (ver `assets/estilos.css`).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from interface.icones import icone

_ICONE_POR_EXTENSAO = {
    "pdf": "arquivo_pdf",
    "doc": "peticao_inicial",
    "docx": "peticao_inicial",
    "xls": "arquivo_planilha",
    "xlsx": "arquivo_planilha",
    "csv": "arquivo_planilha",
    "png": "arquivo_imagem",
    "jpg": "arquivo_imagem",
    "jpeg": "arquivo_imagem",
    "bmp": "arquivo_imagem",
    "tiff": "arquivo_imagem",
}


def _formatar_tamanho(tamanho_bytes: int) -> str:
    """Tamanho de arquivo legível (KB/MB) — só apresentação."""
    tamanho = float(tamanho_bytes)
    for unidade in ("B", "KB", "MB"):
        if tamanho < 1024:
            return f"{tamanho:.0f} {unidade}" if unidade == "B" else f"{tamanho:.1f} {unidade}"
        tamanho /= 1024
    return f"{tamanho:.1f} GB"


def renderizar_preview_arquivo(arquivo) -> None:
    """Chip com ícone do tipo de arquivo + nome + tamanho, exibido logo após
    um `st.file_uploader` — reforça visualmente o que já foi selecionado, no
    padrão do design system (card de vidro, ícone consistente)."""
    if arquivo is None:
        return
    extensao = arquivo.name.rsplit(".", 1)[-1].lower() if "." in arquivo.name else ""
    chave_icone = _ICONE_POR_EXTENSAO.get(extensao, "arquivo_generico")
    with st.container(key="amf3_upload_preview_chip", border=True):
        st.markdown(f"##### {icone(chave_icone)} {arquivo.name}")
        st.caption(_formatar_tamanho(arquivo.size))


def tabela_premium(
    df: pd.DataFrame,
    key: str,
    permitir_busca: bool = False,
    rotulo_busca: str = "Buscar",
) -> None:
    """`st.dataframe` com o visual padrão da plataforma, no lugar de
    `st.table` (que renderiza tudo de uma vez, sem ordenação nem scroll
    virtualizado). Busca opcional por substring em qualquer coluna — só faz
    sentido para tabelas que podem crescer bastante (itens/trechos extraídos
    pela IA); tabelas curtas de chave-valor não precisam e ficam mais limpas
    sem esse controle a mais.
    """
    exibir = df
    if permitir_busca and not df.empty:
        termo = st.text_input(rotulo_busca, key=f"{key}_busca", icon=icone("buscar"))
        if termo:
            termo_lower = termo.lower()
            mascara = df.apply(
                lambda linha: linha.astype(str).str.lower().str.contains(termo_lower, na=False).any(),
                axis=1,
            )
            exibir = df[mascara]
    st.dataframe(exibir, width="stretch", hide_index=True)
    if permitir_busca and not df.empty:
        st.caption(f"{len(exibir)} de {len(df)} registro(s)")
