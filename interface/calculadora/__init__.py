"""Módulo Calculadora (Simulação de Financiamento) — laboratório financeiro
para simulações de aquisição de créditos em Recuperação Judicial. Ponto de
entrada único (`renderizar_calculadora`), delegando cada aba a um submódulo
próprio — nenhuma lógica de negócio vive aqui, só a montagem das abas.

A aba de VPL migrou para o módulo Precificação Inteligente de Créditos
(`interface/precificacao.py`), que reaproveita o mesmo motor de
VPL/TIR/fluxo de caixa (`src/calculadora/vpl_tir.py`) e acrescenta a
extração automática dos termos do plano via IA — "Comparação de Cenários"
continua funcionando para os dois módulos, que salvam no mesmo
`session_state["calc_cenarios"]`.
"""

from __future__ import annotations

import streamlit as st

from interface import layout
from interface.calculadora.balao import renderizar_balao
from interface.calculadora.comparacao import renderizar_comparacao
from interface.calculadora.configuracoes import renderizar_configuracoes
from interface.calculadora.financiamento import renderizar_financiamento


def renderizar_calculadora() -> None:
    layout.renderizar_titulo_pagina("calculadora", "Simulação de Financiamento")
    st.caption("Laboratório financeiro para simulações de aquisição de créditos em Recuperação Judicial")

    aba_financiamento, aba_balao, aba_comparacao, aba_config = st.tabs(
        [
            "Simulador de Financiamento",
            "Simulação Balão",
            "Comparação de Cenários",
            "Configurações Financeiras",
        ]
    )
    with aba_financiamento:
        renderizar_financiamento()
    with aba_balao:
        renderizar_balao()
    with aba_comparacao:
        renderizar_comparacao()
    with aba_config:
        renderizar_configuracoes()
