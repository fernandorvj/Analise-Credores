"""Leitura unificada de documentos em múltiplos formatos para o módulo
Análise de Documentos — normaliza tudo para texto simples, reaproveitando os
pipelines já existentes (`src/leitor_pdf.py` para PDF, `src/ocr.py` para
imagem) em vez de duplicá-los. Nenhuma função deste módulo é usada pelo
Credores nem pela Petição Inicial, e nenhuma delas é alterada aqui.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from docx import Document as DocumentoWord
from PIL import Image

from src import leitor_pdf, ocr

EXTENSOES_SUPORTADAS = {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
_EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
_TIMEOUT_LINK_SEGUNDOS = 15


def ler_documento(caminho: Path) -> tuple[str, list[str]]:
    """Lê um documento em qualquer formato suportado (PDF, DOCX, XLSX/XLS,
    TXT, imagem) e retorna ``(texto_extraido, avisos)``.

    Levanta `ValueError` para formatos não suportados; falhas de leitura de
    um formato reconhecido (ex.: arquivo corrompido) propagam a exceção
    original — o chamador decide como reportar ao usuário.
    """
    extensao = caminho.suffix.lower()

    if extensao == ".pdf":
        return _ler_pdf(caminho)
    if extensao == ".docx":
        return _ler_docx(caminho)
    if extensao in (".xlsx", ".xls"):
        return _ler_planilha(caminho)
    if extensao == ".txt":
        return caminho.read_text(encoding="utf-8", errors="replace"), []
    if extensao in _EXTENSOES_IMAGEM:
        return _ler_imagem(caminho)

    raise ValueError(f"Formato de arquivo não suportado: {extensao}")


def _ler_pdf(caminho: Path) -> tuple[str, list[str]]:
    paginas = leitor_pdf.ler_pdf(caminho)
    texto = "\n\n".join(f"--- Página {p.numero} ---\n{p.texto}" for p in paginas)
    avisos = []
    paginas_ocr = [p.numero for p in paginas if p.fonte == "ocr"]
    if paginas_ocr:
        avisos.append(f"Página(s) {', '.join(str(p) for p in paginas_ocr)} lida(s) via OCR.")
    paginas_indisponiveis = [p.numero for p in paginas if p.fonte == "ocr_indisponivel"]
    if paginas_indisponiveis:
        avisos.append(
            f"OCR indisponível para a(s) página(s) {', '.join(str(p) for p in paginas_indisponiveis)} "
            "— o conteúdo dessas páginas não pôde ser lido."
        )
    return texto, avisos


def _ler_docx(caminho: Path) -> tuple[str, list[str]]:
    documento = DocumentoWord(str(caminho))
    partes = [paragrafo.text for paragrafo in documento.paragraphs if paragrafo.text.strip()]
    for tabela in documento.tables:
        for linha in tabela.rows:
            texto_linha = " | ".join(celula.text for celula in linha.cells)
            if texto_linha.strip():
                partes.append(texto_linha)
    return "\n".join(partes), []


def _ler_planilha(caminho: Path) -> tuple[str, list[str]]:
    planilhas = pd.read_excel(caminho, sheet_name=None)
    partes = []
    for nome_aba, df in planilhas.items():
        partes.append(f"--- Aba: {nome_aba} ---")
        partes.append(df.to_string(index=False))
    return "\n\n".join(partes), []


def _ler_imagem(caminho: Path) -> tuple[str, list[str]]:
    if not ocr.tesseract_disponivel():
        raise RuntimeError(
            "Tesseract OCR não está instalado ou configurado — não é possível ler texto de imagens "
            "neste ambiente. Instale-o e/ou defina TESSERACT_CMD no arquivo .env."
        )
    imagem = Image.open(caminho)
    texto = ocr.ocr_imagem(imagem)
    avisos = []
    if len(texto.strip()) < 40:
        avisos.append("Texto reconhecido na imagem é muito curto — possível baixa qualidade de OCR.")
    return texto, avisos


def ler_link(url: str) -> tuple[str, list[str]]:
    """Busca uma página web e extrai seu texto visível (sem scripts/estilos).

    Levanta `ValueError` se o link não puder ser acessado — nunca inventa
    conteúdo para um link que falhou.
    """
    try:
        resposta = requests.get(url, timeout=_TIMEOUT_LINK_SEGUNDOS, headers={"User-Agent": "Mozilla/5.0"})
        resposta.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"Não foi possível acessar o link informado: {exc}") from exc

    sopa = BeautifulSoup(resposta.text, "html.parser")
    for elemento in sopa(["script", "style", "noscript"]):
        elemento.decompose()

    texto_bruto = sopa.get_text(separator="\n")
    linhas = [linha.strip() for linha in texto_bruto.splitlines() if linha.strip()]
    texto = "\n".join(linhas)

    avisos = []
    if len(texto) < 40:
        avisos.append("Pouco texto foi extraído do link — a página pode depender de JavaScript para exibir o conteúdo.")
    return texto, avisos
