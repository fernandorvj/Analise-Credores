"""Exportação da Proposta ao Credor para Word (.docx) — reaproveita a capa e
o rodapé compartilhados de `src/exportar_word_base.py`, sem duplicá-los.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

from config import NOME_EMPRESA, configurar_logging
from src import exportar_word_base as base

logger = configurar_logging()

_TEXTO_AVISO_CAPA = (
    "Este documento é um rascunho de proposta gerado com apoio de Inteligência Artificial a partir "
    "dos dados informados — revise integralmente antes do envio. Não constitui aconselhamento "
    "jurídico ou financeiro nem garantia de resultado."
)


def exportar_word_proposta(texto_proposta: str, nome_credor: str, caminho_saida: str | Path) -> Path:
    """Gera o .docx da proposta (capa + texto + rodapé paginado) a partir do
    texto já gerado (e possivelmente revisado pelo usuário) em
    `src/ia.py::gerar_proposta_credor`."""
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    base.adicionar_capa(
        doc,
        nome_arquivo_pdf=f"Proposta ao Credor — {nome_credor}" if nome_credor.strip() else "Proposta ao Credor",
        subtitulo_modulo="Proposta de Aquisição de Crédito",
        texto_aviso=_TEXTO_AVISO_CAPA,
        pagina_isolada=False,
    )

    for paragrafo in texto_proposta.split("\n"):
        doc.add_paragraph(paragrafo)

    base.adicionar_rodape_paginacao(doc, f"{NOME_EMPRESA} — Proposta ao Credor")

    doc.save(caminho_saida)
    logger.info("Word da Proposta ao Credor exportado em '%s'.", caminho_saida)
    return caminho_saida
