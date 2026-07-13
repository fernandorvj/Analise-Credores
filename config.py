"""Configuração central do projeto: caminhos, constantes e carregamento de segredos.

Nenhum outro módulo deve ler variáveis de ambiente diretamente — tudo passa por aqui,
para que a chave da API nunca seja espalhada nem impressa em logs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv
import os
import streamlit as st

# --- Caminhos base -----------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

ASSETS_DIR = BASE_DIR / "assets"
IDENTIDADE_VISUAL_DIR = ASSETS_DIR / "identidade_visual"
LOGO_PATH = ASSETS_DIR / "logo.png"
CSS_PATH = ASSETS_DIR / "estilos.css"

DOCUMENTOS_DIR = BASE_DIR / "documentos"
PDFS_DIR = DOCUMENTOS_DIR / "pdfs"
PETICOES_DIR = DOCUMENTOS_DIR / "peticoes_iniciais"
MODELOS_WORD_DIR = DOCUMENTOS_DIR / "modelos_word"
EXPORTADOS_DIR = DOCUMENTOS_DIR / "exportados"

LOGS_DIR = BASE_DIR / "logs"

for _dir in (PDFS_DIR, PETICOES_DIR, MODELOS_WORD_DIR, EXPORTADOS_DIR, LOGS_DIR, IDENTIDADE_VISUAL_DIR):
    try:
        _dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Alguns ambientes hospedados restringem escrita fora de diretórios
        # específicos — uma pasta auxiliar não criável não pode derrubar o
        # app inteiro na importação (isso acontecia antes desta blindagem).
        pass

# --- Segredos ------------------------------------------------------------

load_dotenv(BASE_DIR / ".env")


def _obter_segredo(nome: str, padrao: str = "") -> str:
    """Lê um segredo do .env local (variável de ambiente) ou, se ausente, dos
    "Secrets" do Streamlit Community Cloud (`st.secrets`) — permite o mesmo
    código rodar localmente e publicado sem alterações. `st.secrets` levanta
    exceção quando não há nenhum secrets.toml (caso local sem deploy), por
    isso o try/except.
    """
    valor = os.getenv(nome)
    if valor:
        return valor
    try:
        return str(st.secrets.get(nome, padrao))
    except Exception:
        return padrao


OPENAI_API_KEY = _obter_segredo("OPENAI_API_KEY")
OPENAI_MODEL = _obter_segredo("OPENAI_MODEL", "gpt-4o-mini")
APP_USERNAME = _obter_segredo("APP_USERNAME")  # se vazio, o app fica sem proteção por login
APP_PASSWORD = _obter_segredo("APP_PASSWORD")


def possui_chave_openai() -> bool:
    """Retorna True se uma chave da OpenAI foi carregada, sem nunca expor o valor."""
    return bool(OPENAI_API_KEY)


def possui_protecao_por_senha() -> bool:
    """Retorna True se login/senha de acesso foram configurados."""
    return bool(APP_PASSWORD)


# --- Identidade visual AMF3 Capital --------------------------------------
# Extraída de Modelos/Logo Programa.png e Modelos/*.pdf (material institucional).
# "primaria" é o indigo exato da marca (logo, títulos); as cores de gráfico
# ("classe_*") são variantes ajustadas para acessibilidade e validadas com o
# validador de paleta categórica (dataviz skill) — ΔE mínimo adjacente 21.6.

CORES = {
    "primaria": "#242288",       # indigo da marca (logo "3", títulos, UI primária)
    "secundaria": "#373435",     # carvão da marca (texto "AMF", texto principal)
    "destaque": "#B87A12",       # âmbar (acento, categórico slot 2)
    "fundo": "#FAFAFA",          # canvas claro do redesign (evoluído do cinza institucional)
    "texto": "#373435",
    "sucesso": "#0CA30C",        # status: ok
    "alerta": "#FAB219",         # status: revisar
    "erro": "#D03B3B",           # status: erro
    "informacao": "#3633CC",     # status: informativo (mesmo tom do indigo claro, já validado)
    "grafico_indigo": "#3633CC", # indigo p/ gráficos de série única (mesmo valor de classe_1)
}

# Paleta categórica para gráficos por classe (ordem fixa — nunca reordenar por
# valor/ranking). Indigo mais claro que "primaria" para respeitar a faixa de
# luminosidade exigida em marcas de gráfico (OKLCH L 0.43–0.77).
CLASSE_CORES = {
    "Classe I - Trabalhista": "#3633CC",
    "Classe II - Garantia Real": "#B87A12",
    "Classe III - Quirografário": "#1B8F7A",
    "Classe IV - ME/EPP": "#9C3D8C",
}
CLASSE_COR_PADRAO = "#8A8780"  # cinza neutro p/ classes fora da lista padrão (ex.: "Não identificada")

# Variante da paleta categórica para os gráficos em modo escuro (Flat Design
# 2.0 / dashboards escuros) — mesmas 4 classes/mesma ordem, hues reclareados
# para a superfície escura dos gráficos (GRAFICO_SUPERFICIE_ESCURA), validados
# com o validador de paleta categórica (dataviz skill): banda de luminosidade
# OKLCH 0.48–0.67, contraste ≥ 3:1, ΔE mínimo adjacente 20.1.
CLASSE_CORES_ESCURO = {
    "Classe I - Trabalhista": "#6D6BE0",
    "Classe II - Garantia Real": "#B4830E",
    "Classe III - Quirografário": "#219A85",
    "Classe IV - ME/EPP": "#C25FB0",
}
CLASSE_COR_PADRAO_ESCURO = "#8A8780"
GRAFICO_SUPERFICIE_ESCURA = "#1B1930"

NOME_EMPRESA = "AMF3 Capital"
NOME_SISTEMA = "RJ Análise de Credores"

# --- Plataforma (Home e navegação) -----------------------------------------

NOME_PLATAFORMA = "AMF3 Capital"
SUBTITULO_PLATAFORMA = "Plataforma de Inteligência em Recuperação Judicial"
TEXTO_INSTITUCIONAL = (
    "Central de gestão, análise e inteligência para operações de compra de "
    "créditos em Recuperação Judicial."
)
VERSAO_SISTEMA = "1.0.0"
DATA_ATUALIZACAO = "13/07/2026"

# --- Parâmetros de análise -------------------------------------------------

FAIXAS_QUORUM = [0.25, 0.33, 0.50, 0.66, 0.75, 0.90]

CLASSES_RJ_PADRAO = [
    "Classe I - Trabalhista",
    "Classe II - Garantia Real",
    "Classe III - Quirografário",
    "Classe IV - ME/EPP",
]

# Critérios de aprovação do Plano de Recuperação Judicial por classe, na AGC
# (Lei 11.101/2005, art. 45, com alterações da Lei 14.112/2020):
# - Classes I (Trabalhista) e IV (ME/EPP): maioria simples por QUANTIDADE de
#   credores presentes (cabeça); valor do crédito não é critério nessas classes.
# - Classes II (Garantia Real) e III (Quirografário): maioria por VALOR dos
#   créditos E por QUANTIDADE de credores presentes — os dois critérios juntos.
CRITERIOS_APROVACAO_CLASSE = {
    "Classe I - Trabalhista": {"valor": False, "quantidade": True},
    "Classe II - Garantia Real": {"valor": True, "quantidade": True},
    "Classe III - Quirografário": {"valor": True, "quantidade": True},
    "Classe IV - ME/EPP": {"valor": False, "quantidade": True},
}
CRITERIOS_APROVACAO_PADRAO = {"valor": True, "quantidade": True}  # fallback p/ classes fora da lista


# --- Logging ---------------------------------------------------------------


def configurar_logging() -> logging.Logger:
    """Configura logging para arquivo (logs/app.log) e console.

    Nunca registra segredos: o handler de arquivo usa um filtro que remove
    qualquer substring igual à chave da OpenAI antes de gravar.
    """
    logger = logging.getLogger("rj_analise_credores")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    class _FiltroSegredos(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            mensagem = record.getMessage()
            for segredo in (OPENAI_API_KEY, APP_PASSWORD):
                if segredo and segredo in mensagem:
                    mensagem = mensagem.replace(segredo, "***REDACTED***")
                    record.msg = mensagem
                    record.args = ()
            return True

    file_handler = logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_FiltroSegredos())

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_FiltroSegredos())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger
