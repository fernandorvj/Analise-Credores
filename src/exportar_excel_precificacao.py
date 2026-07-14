"""Exportação para Excel do resultado da Precificação Inteligente de
Créditos — reaproveita os helpers de formatação já usados pela Calculadora
(`src/calculadora/exportar_excel.py`), sem duplicá-los.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Font

from src.calculadora.exportar_excel import _aplicar_formatos
from src.models_precificacao import ResultadoPrecificacaoClasse
from src.utils import formatar_moeda, formatar_percentual


def _linha(indicador: str, valor: str) -> dict:
    return {"Indicador": indicador, "Valor": valor}


def _df_fluxo(resultado: ResultadoPrecificacaoClasse) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Nº": p.numero,
                "Data": p.data,
                "Descrição": p.descricao,
                "Valor": float(p.valor_nominal),
                "Valor Presente": float(p.valor_descontado),
            }
            for p in sorted(resultado.fluxo, key=lambda item: item.data)
        ]
    )


def exportar_excel_precificacao(resultado: ResultadoPrecificacaoClasse, caminho_saida: str | Path) -> Path:
    """Exporta o resultado da Precificação Inteligente (abas Resumo, Fluxo
    de Caixa e Memória de Cálculo) para um arquivo .xlsx."""
    caminho_saida = Path(caminho_saida)
    c = resultado.condicoes

    linhas = [
        _linha("Classe", resultado.classe),
        _linha("Valor Nominal do Crédito", formatar_moeda(float(resultado.valor_nominal_credito))),
        _linha(
            "Valor Atualizado do Crédito",
            formatar_moeda(float(resultado.valor_atualizado_credito)) if resultado.valor_atualizado_credito is not None else "Não aplicável",
        ),
        _linha("Deságio Considerado", c.desagio),
        _linha("Carência Considerada", c.carencia),
        _linha("Índice de Correção", c.correcao_monetaria_indice),
        _linha("Juros Considerado", c.juros),
        _linha("Número de Parcelas", c.numero_parcelas),
        _linha("Periodicidade", c.periodicidade),
        _linha("Data da 1ª Parcela", c.data_primeira_parcela),
        _linha("Taxa de Desconto (a.a.)", formatar_percentual(float(resultado.taxa_desconto_anual))),
        _linha("Origem da Taxa de Desconto", resultado.origem_taxa_desconto),
        _linha(
            "Data da Taxa de Desconto",
            resultado.data_taxa_desconto.strftime("%d/%m/%Y") if resultado.data_taxa_desconto else "Manual",
        ),
        _linha("VPL", formatar_moeda(float(resultado.vpl))),
        _linha("Metodologia Validada contra Planilha Oficial", "Sim" if resultado.metodologia_validada else "Não (provisória)"),
    ]
    df_resumo = pd.DataFrame(linhas)
    df_fluxo = _df_fluxo(resultado)
    df_memoria = pd.DataFrame({"Memória de Cálculo": resultado.memoria_calculo})

    with pd.ExcelWriter(caminho_saida, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
        df_fluxo.to_excel(writer, sheet_name="Fluxo de Caixa", index=False)
        _aplicar_formatos(writer.sheets["Fluxo de Caixa"], df_fluxo)
        df_memoria.to_excel(writer, sheet_name="Memória de Cálculo", index=False)
        for nome_aba in ("Resumo", "Memória de Cálculo"):
            for celula in writer.sheets[nome_aba][1]:
                celula.font = Font(bold=True)
            writer.sheets[nome_aba].column_dimensions["A"].width = 45

    return caminho_saida
