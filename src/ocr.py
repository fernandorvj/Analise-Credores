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


_ANGULOS_TESTADOS = (0, 90, 180, 270)


def _pontuacao_ocr(imagem: Image.Image, idioma: str) -> int:
    """Soma das confianças (0-100) de cada palavra reconhecida — usada só
    para COMPARAR orientações candidatas entre si, nunca como confiança
    absoluta. Cresce tanto com mais palavras reconhecidas quanto com maior
    confiança em cada uma, o que penaliza tanto texto girado (poucas
    palavras, baixa confiança) quanto texto de cabeça para baixo/espelhado
    (às vezes reconhece bastante "lixo" com confiança baixa)."""
    dados = pytesseract.image_to_data(imagem, lang=idioma, output_type=pytesseract.Output.DICT)
    confiancas = [int(c) for c in dados["conf"] if str(c) != "-1" and int(c) >= 0]
    return sum(confiancas)


def _corrigir_orientacao(imagem: Image.Image, idioma: str) -> Image.Image:
    """Detecta e corrige a orientação de UMA imagem isolada testando OCR nas
    4 rotações possíveis (0°/90°/180°/270°) e ficando com a de maior
    pontuação de confiança — usada quando não há mais páginas do mesmo
    documento para reforçar a decisão (ver `detectar_rotacao_documento` para
    o caso de várias páginas escaneadas do mesmo PDF, mais robusto).

    Digitalizações de planilhas/relatórios em paisagem às vezes chegam com o
    conteúdo girado dentro da própria página (sem que o PDF marque isso nos
    metadados de rotação — `pagina.rotation` continua 0), o que faz o OCR
    devolver texto embaralhado/sem sentido se lido "reto". A detecção nativa
    do Tesseract (`image_to_osd`) foi tentada primeiro e descartada: em
    páginas com pouco texto ou layout incomum ela erra o ângulo com
    confiança baixa (observado em produção). Comparar a pontuação de OCR
    real nas 4 rotações é mais lento (4x OCR), mas decide pelo resultado que
    realmente funciona, não por uma heurística à parte — ainda assim, numa
    página isolada com pouco conteúdo, o placar entre a rotação certa e uma
    errada (mas parcialmente "legível") pode ficar bem próximo; é exatamente
    esse caso que `detectar_rotacao_documento` resolve ao somar o placar de
    todas as páginas do documento antes de decidir.
    """
    melhor_imagem = imagem
    melhor_pontuacao = -1
    for angulo in _ANGULOS_TESTADOS:
        candidata = imagem.rotate(-angulo, expand=True) if angulo else imagem
        pontuacao = _pontuacao_ocr(candidata, idioma)
        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_imagem = candidata
    return melhor_imagem


def detectar_rotacao_documento(imagens: list[Image.Image], idioma: str = IDIOMA_OCR) -> int:
    """Detecta a rotação (0/90/180/270) compartilhada por VÁRIAS páginas
    escaneadas do MESMO documento, somando a pontuação de OCR de cada
    rotação candidata em todas as páginas antes de decidir.

    Mais robusto do que decidir página a página (`_corrigir_orientacao`):
    páginas de conteúdo esparso (comum na última página de uma relação —
    poucas linhas + um "Total Geral") podem ter placar embaralhado entre a
    rotação certa e uma errada que, por acaso, ainda produz algumas palavras
    "reconhecíveis" com confiança parecida — foi exatamente esse empate
    observado em produção (placar 13132 x 13227 entre 90° certo e 180°
    errado numa página de 15 linhas) que motivou juntar o sinal de TODAS as
    páginas do documento: como a rotação real é a mesma em todas elas, ela
    vence com folga quando o placar de várias páginas é somado, mesmo que
    uma página isolada não bastasse para decidir sozinha.
    """
    melhor_angulo = 0
    melhor_pontuacao = -1
    for angulo in _ANGULOS_TESTADOS:
        pontuacao_total = sum(
            _pontuacao_ocr(imagem.rotate(-angulo, expand=True) if angulo else imagem, idioma) for imagem in imagens
        )
        if pontuacao_total > melhor_pontuacao:
            melhor_pontuacao = pontuacao_total
            melhor_angulo = angulo
    return melhor_angulo


_FATOR_TOLERANCIA_LINHA = 0.6  # fração da altura mediana de palavra: mesma linha se o "top" variar até isso
_FATOR_LIMIAR_COLUNA = 1.0  # fração da altura mediana de palavra: gap horizontal acima disso é fim de coluna

# Ambos expressos como fração da altura mediana das palavras da própria página
# (não um valor fixo de pixel) para funcionar em qualquer DPI de renderização —
# o espaço normal entre palavras de um mesmo nome fica bem abaixo de 1x altura,
# enquanto o vão entre colunas de uma tabela (visto em produção: 10x-15x altura)
# fica bem acima; a margem entre os dois é folgada o suficiente para não exigir
# calibração fina.


def _reconstruir_texto_por_posicao(imagem: Image.Image, idioma: str) -> str:
    """Reconstrói o texto de uma imagem agrupando as palavras do OCR por
    posição (linha = mesma faixa de `top`, colunas ordenadas por `left`) em
    vez de usar a ordem de leitura padrão do Tesseract.

    Necessário porque, em página escaneadas com tabelas largas (colunas bem
    separadas), `image_to_string`/PSM automático às vezes agrupa por BLOCO
    (lê a coluna inteira de cima a baixo, depois a próxima) em vez de por
    LINHA — observado em produção numa lista de credores em formato de
    tabela dinâmica (Classe/Tipo/Credor/Valor): o texto saía com todos os
    "CLASSE X" seguidos de todos os "TIPO", depois todos os nomes, depois
    todos os valores, em vez de uma linha por credor. Mesma técnica já usada
    para texto digital em `leitor_pdf.reconstruir_texto_por_posicao`, aqui
    aplicada às caixas delimitadoras (`image_to_data`) do OCR.
    """
    dados = pytesseract.image_to_data(imagem, lang=idioma, output_type=pytesseract.Output.DICT)
    palavras = [
        {"top": dados["top"][i], "left": dados["left"][i], "right": dados["left"][i] + dados["width"][i], "text": texto}
        for i in range(len(dados["text"]))
        if (texto := dados["text"][i].strip())
    ]
    if not palavras:
        return ""

    alturas = sorted(dados["height"][i] for i in range(len(dados["text"])) if dados["text"][i].strip())
    altura_mediana = alturas[len(alturas) // 2] if alturas else 20
    tolerancia_linha = altura_mediana * _FATOR_TOLERANCIA_LINHA
    limiar_coluna = altura_mediana * _FATOR_LIMIAR_COLUNA

    palavras.sort(key=lambda p: (p["top"], p["left"]))
    linhas: list[list[dict]] = []
    for palavra in palavras:
        if linhas and abs(palavra["top"] - linhas[-1][-1]["top"]) <= tolerancia_linha:
            linhas[-1].append(palavra)
        else:
            linhas.append([palavra])

    linhas_texto: list[str] = []
    for linha in linhas:
        linha_ordenada = sorted(linha, key=lambda p: p["left"])
        partes: list[str] = []
        anterior: dict | None = None
        for palavra in linha_ordenada:
            if anterior is not None:
                partes.append("  " if (palavra["left"] - anterior["right"]) >= limiar_coluna else " ")
            partes.append(palavra["text"])
            anterior = palavra
        linhas_texto.append("".join(partes))

    return "\n".join(linhas_texto)


def ocr_imagem(imagem: Image.Image, idioma: str = IDIOMA_OCR) -> str:
    """Executa OCR em uma imagem PIL isolada e retorna o texto reconhecido —
    corrige automaticamente a orientação dessa imagem sozinha (ver
    `_corrigir_orientacao`) e reconstrói o texto por posição em vez de usar
    a ordem de leitura padrão do Tesseract (ver
    `_reconstruir_texto_por_posicao`). Para várias páginas do mesmo PDF, use
    `detectar_rotacao_documento` + `ocr_imagem_com_rotacao` (mais robusto —
    ver docstring de `detectar_rotacao_documento`)."""
    if not tesseract_disponivel():
        raise RuntimeError(
            "Tesseract OCR não está instalado ou configurado. "
            "Instale-o e/ou defina TESSERACT_CMD no arquivo .env."
        )
    imagem = _corrigir_orientacao(imagem, idioma)
    return _reconstruir_texto_por_posicao(imagem, idioma)


def ocr_imagem_com_rotacao(imagem: Image.Image, rotacao: int, idioma: str = IDIOMA_OCR) -> str:
    """Como `ocr_imagem`, mas aplicando uma rotação já conhecida (ver
    `detectar_rotacao_documento`) em vez de detectá-la de novo para esta
    imagem sozinha."""
    if not tesseract_disponivel():
        raise RuntimeError(
            "Tesseract OCR não está instalado ou configurado. "
            "Instale-o e/ou defina TESSERACT_CMD no arquivo .env."
        )
    if rotacao:
        imagem = imagem.rotate(-rotacao, expand=True)
    return _reconstruir_texto_por_posicao(imagem, idioma)


def renderizar_pagina_como_imagem(pagina: fitz.Page, dpi: int = DPI_RENDERIZACAO) -> Image.Image:
    """Renderiza uma página de PDF (PyMuPDF) como imagem PIL em alta resolução."""
    zoom = dpi / 72
    matriz = fitz.Matrix(zoom, zoom)
    pixmap = pagina.get_pixmap(matrix=matriz)
    return Image.open(io.BytesIO(pixmap.tobytes("png")))


def ocr_pagina_pdf(pagina: fitz.Page, dpi: int = DPI_RENDERIZACAO) -> str:
    """Renderiza uma página de PDF isolada e aplica OCR (detecta a
    orientação só a partir dela mesma). Para várias páginas escaneadas do
    mesmo PDF, prefira `renderizar_pagina_como_imagem` +
    `detectar_rotacao_documento` + `ocr_imagem_com_rotacao` no chamador
    (ver `src.leitor_pdf`) — mais robusto (ver `detectar_rotacao_documento`)."""
    return ocr_imagem(renderizar_pagina_como_imagem(pagina, dpi))
