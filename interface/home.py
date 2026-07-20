"""Tela inicial (Home) — painel central de navegação da plataforma AMF3.

Não contém lógica de negócio: cada card apenas leva a um módulo já
implementado em outro lugar (`interface/dashboard.py`, `interface/
peticao_inicial.py`, `interface/calculadora/`, ou uma página "em construção"
para os módulos ainda não implementados — ver `app.py`).
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
        "chave_icone": "precificacao",
        "titulo": "Precificação Inteligente de Créditos",
        "descricao": (
            "Interprete automaticamente um Plano de Recuperação Judicial e obtenha o VPL, a TIR "
            "e o preço máximo recomendado para aquisição do crédito.<br><br>A IA extrai deságio, "
            "carência, juros, correção e cronograma do plano — todo o cálculo financeiro é feito "
            "em Python, de forma auditável."
        ),
        "itens": [
            "Leitura automática do Plano de RJ (PDF)",
            "Construção automática do fluxo de caixa",
            "VPL, TIR, ROI, Payback e Duration",
            "Taxa SELIC integrada com a API do Banco Central",
            "Preço máximo recomendado para aquisição",
        ],
        "pagina_destino": "precificacao",
        "key": "home_card_precificacao",
    },
    {
        "chave_icone": "calculadora",
        "titulo": "Simulação de Financiamento",
        "descricao": (
            "Estruture propostas de aquisição de créditos com cronogramas de amortização, fluxo "
            "de caixa livre e comparação de cenários."
        ),
        "itens": [
            "Tabela Price e SAC, juros simples e compostos",
            "Simulação Balão com editor de fluxo livre",
            "Comparação de cenários",
            "Exportação em Word e Excel",
        ],
        "pagina_destino": "calculadora",
        "key": "home_card_calculadora",
    },
    {
        "chave_icone": "analise_documentos",
        "titulo": "Análise de Documentos",
        "descricao": (
            "Envie qualquer documento do processo — PDF, Word, Excel, imagem ou link — e obtenha "
            "um resumo executivo com riscos, garantias, cláusulas relevantes e impacto na "
            "aquisição de créditos.<br><br>Converse com a IA para tirar dúvidas específicas sobre "
            "o conteúdo do documento."
        ),
        "itens": [
            "Aceita PDF, Word, Excel, TXT, imagem e links",
            "Resumo executivo e principais riscos",
            "Cláusulas, garantias e execuções identificadas",
            "Perguntas e respostas sobre o documento",
        ],
        "pagina_destino": "analise_documentos",
        "key": "home_card_analise_documentos",
    },
    {
        "chave_icone": "proposta_credor",
        "titulo": "Proposta ao Credor",
        "descricao": (
            "Gere automaticamente um e-mail institucional formal de proposta de aquisição de "
            "crédito, pronto para revisão e envio.<br><br>A IA constrói a argumentação técnica e "
            "financeira a partir dos dados informados — você revisa e exporta."
        ),
        "itens": [
            "Texto formal e institucional, pronto para revisão",
            "Contextualização, justificativa e condições da proposta",
            "Baseado no valor do crédito, VPL e classe",
            "Exportação em Word",
        ],
        "pagina_destino": "proposta_credor",
        "key": "home_card_proposta_credor",
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
        if st.button("Entrar", key=f"{card['key']}_btn", icon=icone("entrar")):
            navegar_para(card["pagina_destino"])


def renderizar_home() -> None:
    """Renderiza a tela inicial: hero de boas-vindas + os cards de módulos,
    em linhas de 3 colunas (funciona para qualquer quantidade de cards)."""
    st.markdown(
        """
        <div class="amf3-home-hero">
            <p class="amf3-home-hero-eyebrow">Central AMF3 Capital</p>
            <h1 class="amf3-home-hero-titulo">Bem-vindo à sua plataforma de análise de créditos</h1>
            <p class="amf3-home-hero-subtitulo">
                Selecione um módulo abaixo para começar — da leitura da Petição Inicial
                à precificação inteligente, simulação de financiamento e proposta ao credor.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cards_por_linha = 3
    for inicio in range(0, len(_CARDS), cards_por_linha):
        colunas = st.columns(cards_por_linha)
        linha = _CARDS[inicio : inicio + cards_por_linha]
        for coluna, card in zip(colunas, linha):
            with coluna:
                _renderizar_card(card)
        st.write("")
