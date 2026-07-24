"""Tela inicial (Home) — painel central de navegação da plataforma AMF3.

Não contém lógica de negócio: cada barra de navegação apenas leva a um
módulo já implementado em outro lugar (`interface/dashboard.py`, `interface/
peticao_inicial.py`, `interface/calculadora/`, ou uma página "em construção"
para os módulos ainda não implementados — ver `app.py`).
"""

from __future__ import annotations

import streamlit as st

from config import LOGO_PATH
from interface.icones import icone
from interface.layout import navegar_para

_CARDS = [
    {
        "chave_icone": "credores",
        "titulo": "Credores",
        "descricao": "Análise completa de listas de credores em Recuperação Judicial.",
        "pagina_destino": "credores",
        "key": "home_card_credores",
    },
    {
        "chave_icone": "peticao_inicial",
        "titulo": "Petição Inicial",
        "descricao": "Leitura e análise inteligente da Petição Inicial com IA.",
        "pagina_destino": "peticao_inicial",
        "key": "home_card_peticao",
    },
    {
        "chave_icone": "precificacao",
        "titulo": "Precificação Inteligente de Créditos",
        "descricao": "VPL, TIR e preço máximo recomendado a partir do Plano de RJ.",
        "pagina_destino": "precificacao",
        "key": "home_card_precificacao",
    },
    {
        "chave_icone": "calculadora",
        "titulo": "Simulação de Financiamento",
        "descricao": "Cronogramas de amortização, fluxo de caixa e comparação de cenários.",
        "pagina_destino": "calculadora",
        "key": "home_card_calculadora",
    },
    {
        "chave_icone": "analise_documentos",
        "titulo": "Análise de Documentos",
        "descricao": "Resumo executivo e perguntas e respostas sobre qualquer documento do processo.",
        "pagina_destino": "analise_documentos",
        "key": "home_card_analise_documentos",
    },
    {
        "chave_icone": "proposta_credor",
        "titulo": "Proposta ao Credor",
        "descricao": "Geração automática de proposta institucional de aquisição de crédito.",
        "pagina_destino": "proposta_credor",
        "key": "home_card_proposta_credor",
    },
]


def _renderizar_barra_nav(card: dict) -> None:
    """Renderiza uma barra de navegação horizontal e compacta para um
    módulo — ícone à esquerda, título+descrição no meio, seta à direita."""
    with st.container(border=True, key=card["key"]):
        col_icone, col_texto, col_seta = st.columns([0.9, 8, 0.9], vertical_alignment="center")
        with col_icone:
            # O shortcode :material/xxx: só é expandido pelo processamento de
            # markdown de verdade do Streamlit — dentro de um <div> cru via
            # unsafe_allow_html ele aparece como texto literal. Por isso vai
            # num st.markdown simples (sem HTML próprio); o estilo do "selo"
            # ao redor do ícone é aplicado em CSS direto no elemento gerado
            # pelo Streamlit ([data-testid="stIconMaterial"]), não num wrapper.
            st.markdown(icone(card["chave_icone"]))
        with col_texto:
            st.markdown(
                f"""
                <div class="amf3-navbar-texto">
                    <span class="amf3-navbar-titulo">{card['titulo']}</span>
                    <span class="amf3-navbar-descricao">{card['descricao']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col_seta:
            if st.button(
                "", key=f"{card['key']}_btn", icon=icone("entrar"), help=f"Abrir {card['titulo']}"
            ):
                navegar_para(card["pagina_destino"])


def renderizar_home() -> None:
    """Renderiza a tela inicial: hero de boas-vindas (logo + mensagem própria
    da Home — o nome da plataforma/subtítulo/texto institucional já aparecem
    no cabeçalho fixo, `layout.renderizar_cabecalho_app()`, então o hero não
    repete o mesmo texto) seguido de uma lista vertical de barras de
    navegação, uma por módulo — no lugar da antiga grade de 2 linhas x 3
    cards."""
    with st.container(key="amf3_home_hero"):
        col_logo, col_texto = st.columns([1, 5], vertical_alignment="center")
        with col_logo:
            if LOGO_PATH.exists():
                # Logo tem cores escuras (feito pra ficar sobre fundo claro,
                # ver .st-key-amf3_logo_chip no cabeçalho) — sem o chip
                # branco, fica quase invisível sobre o novo canvas escuro.
                with st.container(key="amf3_home_hero_logo"):
                    st.image(str(LOGO_PATH), width=110)
        with col_texto:
            st.markdown(
                """
                <p class="amf3-home-hero-eyebrow">Central de Inteligência</p>
                <h1 class="amf3-home-hero-titulo">Bem-vindo(a) de volta</h1>
                <p class="amf3-home-hero-subtitulo">Selecione um módulo abaixo para começar.</p>
                """,
                unsafe_allow_html=True,
            )

    for card in _CARDS:
        _renderizar_barra_nav(card)
