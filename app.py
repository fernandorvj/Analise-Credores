"""Ponto de entrada Streamlit do RJ Análise de Credores (AMF3 Capital)."""

from __future__ import annotations

import streamlit as st

from config import NOME_SISTEMA
from interface import dashboard

st.set_page_config(page_title=NOME_SISTEMA, page_icon="⚖️", layout="wide")

dashboard.injetar_css()

if not dashboard.verificar_autenticacao():
    st.stop()

dashboard.renderizar_cabecalho()

resultado = dashboard.renderizar_upload()

if resultado is None:
    st.info("Envie um PDF da relação de credores acima para iniciar a análise.")
    st.stop()

dashboard.renderizar_kpis(resultado)
dashboard.renderizar_avisos_reconciliacao(resultado)
dashboard.renderizar_pendencias(resultado)

(
    aba_tabela,
    aba_ranking,
    aba_graficos,
    aba_estrategia,
    aba_simulacoes,
    aba_aprovacao,
    aba_ia,
    aba_exportacao,
) = st.tabs(
    [
        "Tabela de Credores",
        "Ranking",
        "Gráficos",
        "Análise Estratégica",
        "Simulações de Quórum",
        "Aprovação do Plano",
        "IA",
        "Exportação",
    ]
)

with aba_tabela:
    dashboard.renderizar_tabela(dashboard.renderizar_filtros(resultado.credores))

with aba_ranking:
    dashboard.renderizar_ranking(resultado)

with aba_graficos:
    dashboard.renderizar_graficos(resultado)

with aba_estrategia:
    dashboard.renderizar_estrategia(resultado)

with aba_simulacoes:
    dashboard.renderizar_simulacoes(resultado)

with aba_aprovacao:
    dashboard.renderizar_votacao_aprovacao(resultado)

with aba_ia:
    dashboard.renderizar_ia(resultado)

with aba_exportacao:
    dashboard.renderizar_exportacao(resultado)
