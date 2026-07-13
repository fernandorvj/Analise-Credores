"""Módulo Calculadora — ainda não implementado.

Responsável, no futuro, por ferramentas financeiras de análise de aquisição
de créditos. Por ora, expõe apenas a navegação e uma página de aviso,
conforme solicitado.
"""

from __future__ import annotations

from interface.layout import renderizar_pagina_em_construcao


def renderizar_calculadora() -> None:
    renderizar_pagina_em_construcao(
        icone="🧮",
        titulo="Calculadora",
        descricao="Ferramentas financeiras para análise de aquisição de créditos.",
        futuras=[
            "VPL (Valor Presente Líquido)",
            "TIR (Taxa Interna de Retorno)",
            "Payback",
            "Fluxo de caixa",
            "Simulação de compra",
            "Simulação de financiamento",
            "Rentabilidade",
            "Comparação de cenários",
            "ROI",
        ],
    )
