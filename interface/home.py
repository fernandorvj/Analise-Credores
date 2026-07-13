"""Tela inicial (Home) — painel central de navegação da plataforma AMF3.

Não contém lógica de negócio: cada card apenas leva a um módulo já
implementado em outro lugar (`interface/dashboard.py`, `interface/
peticao_inicial.py`, `interface/calculadora.py`).
"""

from __future__ import annotations

import streamlit as st

from interface.icones import icone
from interface.layout import navegar_para

_CARDS = [
    {
        "chave_icone": "credores",
        "titulo": "Credores",
        "descricao": "Sistema completo para análise de listas de credores em Recuperação Judicial.",
        "itens": [
            "Importação de PDFs",
            "Extração automática e OCR",
            "Dashboard, ranking e percentuais",
            "Estratégias e simulação de quórum",
            "Exportação para Excel e Word",
            "Integração com IA",
        ],
        "pagina_destino": "credores",
        "key": "home_card_credores",
    },
    {
        "chave_icone": "peticao_inicial",
        "titulo": "Petição Inicial",
        "descricao": (
            "Importe uma Petição Inicial de Recuperação Judicial e obtenha uma análise "
            "inteligente completa do processo.<br><br>O módulo realiza leitura integral do "
            "documento, identifica os principais fatos, resume a situação da empresa, destaca "
            "riscos, oportunidades e gera um relatório executivo estruturado com apoio de "
            "Inteligência Artificial."
        ),
        "itens": [
            "Leitura integral do documento (com OCR quando necessário)",
            "Resumo executivo, histórico e situação financeira da empresa",
            "Riscos, pontos positivos e pontos de atenção, sempre justificados",
            "Visão estratégica para aquisição de créditos e formação de quórum",
            "Exportação do relatório completo em Word",
        ],
        "pagina_destino": "peticao_inicial",
        "key": "home_card_peticao",
    },
    {
        "chave_icone": "calculadora",
        "titulo": "Calculadora",
        "descricao": "Ferramentas financeiras para análise de aquisição de créditos.",
        "itens": [
            "VPL, TIR e Payback",
            "Fluxo de caixa e simulação de compra",
            "Simulação de financiamento e ROI",
            "Comparação de cenários",
        ],
        "pagina_destino": "calculadora",
        "key": "home_card_calculadora",
    },
]


def _renderizar_card(card: dict) -> None:
    with st.container(border=True, key=card["key"]):
        st.markdown(f"## {icone(card['chave_icone'])}")
        st.markdown(
            f"""
            <div class="amf3-card-conteudo">
                <div class="amf3-card-titulo">{card['titulo']}</div>
                <div class="amf3-card-descricao">{card['descricao']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for item in card["itens"]:
            st.markdown(f"- {item}")
        st.write("")
        if st.button(
            "Entrar",
            key=f"{card['key']}_btn",
            type="primary",
            width="stretch",
            icon=icone("entrar"),
        ):
            navegar_para(card["pagina_destino"])


def renderizar_home() -> None:
    """Renderiza a tela inicial: mensagem de boas-vindas + os 3 cards de módulos."""
    st.markdown("### Bem-vindo à Central AMF3 Capital")
    st.caption("Selecione um módulo abaixo para começar.")
    st.write("")

    colunas = st.columns(3)
    for coluna, card in zip(colunas, _CARDS):
        with coluna:
            _renderizar_card(card)
