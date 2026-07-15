"""Leitura de PDFs de relação de credores.

Cada página é primeiro triada com PyMuPDF para decidir se contém texto digital
ou é uma imagem escaneada. Páginas digitais são extraídas com pdfplumber
(preserva tabelas); páginas escaneadas passam pelo módulo de OCR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF
import pdfplumber

from config import configurar_logging
from src import ocr

logger = configurar_logging()

LIMIAR_CARACTERES_DIGITAL = 20  # abaixo disso, a página é considerada escaneada

# Páginas escaneadas do e-SAJ/TJSP costumam trazer, além da imagem integral da
# página, um pequeno rodapé de verificação digital ("Para conferir o original,
# acesse o site...") como texto real — só esse rodapé já ultrapassa
# `LIMIAR_CARACTERES_DIGITAL`, o que classificava a página como "digital" e
# pulava o OCR por completo, mesmo com todo o conteúdo real preso na imagem.
# Por isso, quando uma imagem cobre quase a página inteira, só confiamos no
# texto digital se ele for bem maior que um rodapé desse tipo.
_LIMIAR_COBERTURA_IMAGEM_DOMINANTE = 0.85  # fração da área da página
_LIMIAR_CARACTERES_APESAR_DE_IMAGEM_DOMINANTE = 500


@dataclass
class PaginaExtraida:
    """Conteúdo extraído de uma única página do PDF."""

    numero: int  # 1-indexado, corresponde à numeração exibida ao usuário
    texto: str
    tabelas: list[list[list[str | None]]] = field(default_factory=list)
    fonte: str = "digital"  # "digital", "ocr" ou "ocr_indisponivel"


def _tem_imagem_dominante(pagina: fitz.Page) -> bool:
    area_pagina = pagina.rect.width * pagina.rect.height
    if area_pagina <= 0:
        return False
    for imagem in pagina.get_images(full=True):
        xref = imagem[0]
        for bbox in pagina.get_image_rects(xref):
            if (bbox.width * bbox.height) / area_pagina >= _LIMIAR_COBERTURA_IMAGEM_DOMINANTE:
                return True
    return False


def _pagina_e_digital(pagina: fitz.Page) -> bool:
    texto = pagina.get_text("text") or ""
    tamanho_texto = len(texto.strip())
    if tamanho_texto < LIMIAR_CARACTERES_DIGITAL:
        return False
    if tamanho_texto < _LIMIAR_CARACTERES_APESAR_DE_IMAGEM_DOMINANTE and _tem_imagem_dominante(pagina):
        return False
    return True


def triar_paginas(caminho_pdf: str | Path) -> dict[int, bool]:
    """Classifica cada página do PDF como digital (True) ou escaneada (False)."""
    resultado: dict[int, bool] = {}
    with fitz.open(caminho_pdf) as doc:
        for i, pagina in enumerate(doc, start=1):
            resultado[i] = _pagina_e_digital(pagina)
    return resultado


def _extrair_pagina_digital(pagina: pdfplumber.page.Page, numero_pagina: int) -> PaginaExtraida:
    texto = pagina.extract_text() or ""
    tabelas = pagina.extract_tables() or []
    return PaginaExtraida(numero=numero_pagina, texto=texto, tabelas=tabelas, fonte="digital")


# Algumas páginas com tabelas financeiras (cronogramas, projeções de fluxo)
# têm o fluxo de conteúdo do PDF fora da ordem de leitura visual — o
# `extract_text()` padrão do pdfplumber embaralha o resultado nesses casos,
# mesmo a página sendo 100% digital. Além disso, algumas fontes subconjunto
# usadas nesse tipo de documento (proteção anticópia) mapeiam um único glifo
# para uma sequência de caracteres repetidos (ex.: "R" vira uma string de 20
# "R"s) — uma corrida de 5+ caracteres iguais em sequência nunca é conteúdo
# real, então é sempre seguro cortar o token ali.
_RE_TOKEN_RUIDO = re.compile(r"^(.)\1{4,}$")
_RE_CORTE_RUIDO = re.compile(r"(.)\1{4,}")
_TOLERANCIA_LINHA = 3.0  # pontos: palavras nessa faixa de "top" são consideradas da mesma linha
_TOLERANCIA_COLUNA = 2.0  # pontos: gap horizontal acima disso vira separador de coluna (espaço)

# Em tabelas de cronograma ("Ano 01", "Ano 02"...), o "A" de "Ano" às vezes
# fica sobreposto por um glifo de ruído na mesma posição (ver `_RE_CORTE_RUIDO`
# acima) e é descartado junto com ele, sobrando só "no 01" no início da
# linha — corrige de volta para "Ano 01" só quando esse padrão exato abre a
# linha, para não mexer em nenhum outro texto da página.
_RE_ANO_TRUNCADO = re.compile(r"^no (\d{2})\b")


def _limpar_token_ruido(texto: str) -> str:
    corte = _RE_CORTE_RUIDO.search(texto)
    return texto[: corte.start()] if corte else texto


def reconstruir_texto_por_posicao(pagina: pdfplumber.page.Page, numero_pagina: int) -> PaginaExtraida:
    """Reconstrói o texto de uma página agrupando palavras por posição (linha
    = mesma faixa de `top`, colunas ordenadas por `x0`) em vez de confiar na
    ordem do fluxo de conteúdo do PDF — usada como alternativa a
    `_extrair_pagina_digital()` para módulos que dependem de tabelas
    financeiras bem formadas (ver `ler_pdf_robusto`).
    """
    palavras = [
        p for p in pagina.extract_words(use_text_flow=False, keep_blank_chars=False)
        if not _RE_TOKEN_RUIDO.match(p["text"])
    ]
    tabelas = pagina.extract_tables() or []
    if not palavras:
        return PaginaExtraida(numero=numero_pagina, texto="", tabelas=tabelas, fonte="digital")

    palavras.sort(key=lambda p: (p["top"], p["x0"]))
    linhas: list[list[dict]] = []
    for palavra in palavras:
        if linhas and abs(palavra["top"] - linhas[-1][-1]["top"]) <= _TOLERANCIA_LINHA:
            linhas[-1].append(palavra)
        else:
            linhas.append([palavra])

    linhas_texto: list[str] = []
    for linha in linhas:
        linha_ordenada = sorted(linha, key=lambda p: p["x0"])
        partes: list[str] = []
        anterior: dict | None = None
        for palavra in linha_ordenada:
            token = _limpar_token_ruido(palavra["text"])
            if anterior is not None and (palavra["x0"] - anterior["x1"]) >= _TOLERANCIA_COLUNA:
                partes.append(" ")
            partes.append(token)
            anterior = palavra
        linha_texto = _RE_ANO_TRUNCADO.sub(r"Ano \1", "".join(partes).strip())
        if linha_texto:
            linhas_texto.append(linha_texto)

    return PaginaExtraida(numero=numero_pagina, texto="\n".join(linhas_texto), tabelas=tabelas, fonte="digital")


def _extrair_pagina_ocr(caminho_pdf: str | Path, numero_pagina: int) -> PaginaExtraida:
    with fitz.open(caminho_pdf) as doc:
        pagina = doc[numero_pagina - 1]
        texto = ocr.ocr_pagina_pdf(pagina)
    return PaginaExtraida(numero=numero_pagina, texto=texto, tabelas=[], fonte="ocr")


def _ler_pdf(
    caminho_pdf: str | Path,
    extrair_digital: Callable[[pdfplumber.page.Page, int], PaginaExtraida],
) -> list[PaginaExtraida]:
    """Lê todas as páginas de um PDF, combinando extração digital (via
    `extrair_digital`, que varia entre `ler_pdf` e `ler_pdf_robusto`) e OCR
    conforme necessário.

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
                paginas.append(extrair_digital(pdf.pages[numero - 1], numero))
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


def ler_pdf(caminho_pdf: str | Path) -> list[PaginaExtraida]:
    """Lê todas as páginas de um PDF, combinando extração digital e OCR
    conforme necessário. Usado por Credores e Petição Inicial — comportamento
    inalterado (mesma extração `pdfplumber.extract_text()` de sempre).
    """
    return _ler_pdf(caminho_pdf, _extrair_pagina_digital)


def ler_pdf_robusto(caminho_pdf: str | Path) -> list[PaginaExtraida]:
    """Como `ler_pdf`, mas reconstrói o texto de páginas digitais por posição
    (`reconstruir_texto_por_posicao`) em vez de usar `extract_text()` puro.
    Mais lento e só necessário para módulos que dependem de tabelas
    financeiras bem formadas (ex.: Precificação Inteligente de Créditos) —
    Credores e Petição Inicial continuam usando `ler_pdf`.
    """
    return _ler_pdf(caminho_pdf, reconstruir_texto_por_posicao)
