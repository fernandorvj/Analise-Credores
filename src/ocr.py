"""Integração com Tesseract OCR para páginas de PDF escaneadas (sem texto digital)."""

from __future__ import annotations

import io
import os
import shutil

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from config import configurar_logging

logger = configurar_logging()

IDIOMA_OCR = "por"
DPI_RENDERIZACAO = 300

_CAMINHOS_COMUNS_WINDOWS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

# Pasta de idiomas gravável pelo usuário (sem exigir admin), usada quando o pacote de
# idioma (ex.: português) não está disponível na instalação padrão em Program Files.
_TESSDATA_DIR_PADRAO = os.path.expandvars(r"%LOCALAPPDATA%\RJ_Analise_Credores\tessdata")


def _configurar_caminho_tesseract() -> None:
    """Localiza o executável do Tesseract: variável TESSERACT_CMD, PATH, ou caminhos padrão do Windows."""
    caminho_env = os.getenv("TESSERACT_CMD")
    if caminho_env:
        pytesseract.pytesseract.tesseract_cmd = caminho_env
        return

    if shutil.which("tesseract"):
        return

    for caminho in _CAMINHOS_COMUNS_WINDOWS:
        if os.path.exists(caminho):
            pytesseract.pytesseract.tesseract_cmd = caminho
            return


def _configurar_tessdata_dir() -> None:
    """Aponta o Tesseract para uma pasta de idiomas gravável pelo usuário, via a
    variável de ambiente TESSDATA_PREFIX (herdada pelo processo filho tesseract.exe).

    Evitamos passar `--tessdata-dir` como config string do pytesseract: no Windows,
    o caminho fica entre aspas literais no argumento (não é interpretado por um shell),
    e o Tesseract falha ao tentar abrir o arquivo com as aspas coladas no caminho.
    """
    caminho = os.getenv("TESSDATA_DIR") or (
        _TESSDATA_DIR_PADRAO if os.path.isdir(_TESSDATA_DIR_PADRAO) else None
    )
    if caminho:
        os.environ["TESSDATA_PREFIX"] = caminho


_configurar_caminho_tesseract()
_configurar_tessdata_dir()

_disponibilidade_cache: bool | None = None


def tesseract_disponivel() -> bool:
    """Verifica (com cache em processo) se o Tesseract está instalado e acessível."""
    global _disponibilidade_cache
    if _disponibilidade_cache is None:
        try:
            pytesseract.get_tesseract_version()
            _disponibilidade_cache = True
        except Exception:
            _disponibilidade_cache = False
            logger.warning(
                "Tesseract OCR não encontrado. Instale em "
                "https://github.com/UB-Mannheim/tesseract/wiki ou defina TESSERACT_CMD no .env."
            )
    return _disponibilidade_cache


def ocr_imagem(imagem: Image.Image, idioma: str = IDIOMA_OCR) -> str:
    """Executa OCR em uma imagem PIL e retorna o texto reconhecido."""
    if not tesseract_disponivel():
        raise RuntimeError(
            "Tesseract OCR não está instalado ou configurado. "
            "Instale-o e/ou defina TESSERACT_CMD no arquivo .env."
        )
    return pytesseract.image_to_string(imagem, lang=idioma)


def ocr_pagina_pdf(pagina: fitz.Page, dpi: int = DPI_RENDERIZACAO) -> str:
    """Renderiza uma página de PDF (PyMuPDF) como imagem em alta resolução e aplica OCR."""
    zoom = dpi / 72
    matriz = fitz.Matrix(zoom, zoom)
    pixmap = pagina.get_pixmap(matrix=matriz)
    imagem = Image.open(io.BytesIO(pixmap.tobytes("png")))
    return ocr_imagem(imagem)
