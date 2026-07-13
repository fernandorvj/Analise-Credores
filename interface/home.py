"""Tela inicial (Home) — painel central de navegação da plataforma AMF3.

Não contém lógica de negócio: cada card apenas leva a um módulo já
implementado em outro lugar (`interface/dashboard.py`, `interface/
peticao_inicial.py`, `interface/calculadora.py`).
"""

from __future__ import annotations

import streamlit as st

from interface.layout import navegar_para

_CARDS = [
    {
        "icone": "👥",
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
        "icone": "📄",
        "titulo": "Petição Inicial",
        "descricao": "Importação e análise inteligente da Petição Inicial da Recuperação Judicial.",
        "itens": [
            "Importação do PDF da Petição Inicial",
            "Extração automática dos dados do processo",
            "Cadastro automático do cliente",
            "Resumo executivo e dossiê inteligente",
        ],
        "pagina_destino": "peticao_inicial",
        "key": "home_card_peticao",
    },
    {
        "icone": "🧮",
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
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="amf3-card-conteudo">
                <div class="amf3-card-icone">{card['icone']}</div>
                <div class="amf3-card-titulo">{card['titulo']}</div>
                <div class="amf3-card-descricao">{card['descricao']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for item in card["itens"]:
            st.markdown(f"- {item}")
        st.write("")
        if st.button("Entrar", key=card["key"], type="primary", width="stretch"):
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
