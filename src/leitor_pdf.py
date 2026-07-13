"""Leitura de PDFs de relação de credores.

Cada página é primeiro triada com PyMuPDF para decidir se contém texto digital
ou é uma imagem escaneada. Páginas digitais são extraídas com pdfplumber
(preserva tabelas); páginas escaneadas passam pelo módulo de OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

from config import configurar_logging
from src import ocr

logger = configurar_logging()

LIMIAR_CARACTERES_DIGITAL = 20  # abaixo disso, a página é considerada escaneada


@dataclass
class PaginaExtraida:
    """Conteúdo extraído de uma única página do PDF."""

    numero: int  # 1-indexado, corresponde à numeração exibida ao usuário
    texto: str
    tabelas: list[list[list[str | None]]] = field(default_factory=list)
    fonte: str = "digital"  # "digital", "ocr" ou "ocr_indisponivel"


def _pagina_e_digital(pagina: fitz.Page) -> bool:
    texto = pagina.get_text("text") or ""
    return len(texto.strip()) >= LIMIAR_CARACTERES_DIGITAL


def triar_paginas(caminho_pdf: str | Path) -> dict[int, bool]:
    """Classifica cada página do PDF como digital (True) ou escaneada (False)."""
    resultado: dict[int, bool] = {}
    with fitz.open(caminho_pdf) as doc:
        for i, pagina in enumerate(doc, start=1):
            resultado[i] = _pagina_e_digital(pagina)
    return resultado


def _extrair_pagina_digital(pdf_plumber, numero_pagina: int) -> PaginaExtraida:
    pagina = pdf_plumber.pages[numero_pagina - 1]
    texto = pagina.extract_text() or ""
    tabelas = pagina.extract_tables() or []
    return PaginaExtraida(numero=numero_pagina, texto=texto, tabelas=tabelas, fonte="digital")


def _extrair_pagina_ocr(caminho_pdf: str | Path, numero_pagina: int) -> PaginaExtraida:
    with fitz.open(caminho_pdf) as doc:
        pagina = doc[numero_pagina - 1]
        texto = ocr.ocr_pagina_pdf(pagina)
    return PaginaExtraida(numero=numero_pagina, texto=texto, tabelas=[], fonte="ocr")


def ler_pdf(caminho_pdf: str | Path) -> list[PaginaExtraida]:
    """Lê todas as páginas de um PDF, combinando extração digital e OCR conforme necessário.

    Nunca falha silenciosamente: páginas escaneadas sem Tesseract disponível são
    retornadas com texto vazio e fonte "ocr_indisponivel", para que o parser e a
    interface possam sinalizar o problema ao usuário em vez de omitir credores.
    """
    caminho_pdf = Path(caminho_pdf)
    triagem = triar_paginas(caminho_pdf)
    paginas_escaneadas = [n for n, digital in triagem.items() if not digital]

    ocr_ok = ocr.tesseract_disponivel() if paginas_escaneadas else True
    if paginas_escaneadas and not ocr_ok:
        logger.warning(
            "PDF possui %d página(s) escaneada(s) %s e o Tesseract OCR não está disponível.",
            len(paginas_escaneadas),
            paginas_escaneadas,
        )

    paginas: list[PaginaExtraida] = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for numero, digital in sorted(triagem.items()):
            if digital:
                paginas.append(_extrair_pagina_digital(pdf, numero))
            elif ocr_ok:
                logger.info("Página %d escaneada — aplicando OCR.", numero)
                paginas.append(_extrair_pagina_ocr(caminho_pdf, numero))
            else:
                paginas.append(
                    PaginaExtraida(numero=numero, texto="", tabelas=[], fonte="ocr_indisponivel")
                )

    logger.info(
        "PDF '%s' lido: %d página(s), %d via OCR.",
        caminho_pdf.name,
        len(paginas),
        len(paginas_escaneadas),
    )
    return paginas
