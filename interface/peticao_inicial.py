"""Módulo Petição Inicial — ainda não implementado.

Responsável, no futuro, por importar e analisar a Petição Inicial da
Recuperação Judicial. Por ora, expõe apenas a navegação e uma página de
aviso, conforme solicitado.
"""

from __future__ import annotations

from interface.layout import renderizar_pagina_em_construcao


def renderizar_peticao_inicial() -> None:
    renderizar_pagina_em_construcao(
        icone="📄",
        titulo="Petição Inicial",
        descricao=(
            "Importação e análise inteligente da Petição Inicial da Recuperação Judicial."
        ),
        futuras=[
            "Importar o PDF da Petição Inicial",
            "Extrair automaticamente todas as informações do processo",
            "Identificar dados da empresa",
            "Construir o cadastro automático do cliente",
            "Gerar um resumo executivo completo",
            "Identificar os motivos da Recuperação Judicial",
            "Construir um Dossiê Inteligente da empresa",
            "Integrar posteriormente com os demais módulos",
        ],
    )
