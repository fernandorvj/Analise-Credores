"""Módulo Calculadora — laboratório financeiro para simulações de aquisição
de créditos em Recuperação Judicial. Ponto de entrada único
(`renderizar_calculadora`), delegando cada aba a um submódulo próprio —
nenhuma lógica de negócio vive aqui, só a montagem das abas.
"""

from __future__ import annotations

import streamlit as st

from interface import layout
from interface.calculadora.balao import renderizar_balao
from interface.calculadora.comparacao import renderizar_comparacao
from interface.calculadora.configuracoes import renderizar_configuracoes
from interface.calculadora.financiamento import renderizar_financiamento
from interface.calculadora.vpl import renderizar_vpl


def renderizar_calculadora() -> None:
    layout.renderizar_titulo_pagina("calculadora", "Calculadora")
    st.caption("Laboratório financeiro para simulações de aquisição de créditos em Recuperação Judicial")

    aba_financiamento, aba_balao, aba_vpl, aba_comparacao, aba_config = st.tabs(
        [
            "Simulador de Financiamento",
            "Simulação Balão",
            "Calculadora de VPL",
            "Comparação de Cenários",
            "Configurações Financeiras",
        ]
    )
    with aba_financiamento:
        renderizar_financiamento()
    with aba_balao:
        renderizar_balao()
    with aba_vpl:
        renderizar_vpl()
    with aba_comparacao:
        renderizar_comparacao()
    with aba_config:
        renderizar_configuracoes()
