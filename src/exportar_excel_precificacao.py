"""Exportação para Excel do resultado da Precificação Inteligente de
Créditos — reaproveita os helpers de formatação já usados pela Calculadora
(`src/calculadora/exportar_excel.py`), sem duplicá-los.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Font

from src.calculadora.exportar_excel import _aplicar_formatos, _df_fluxo
from src.models_precificacao import ResultadoPrecificacao
from src.utils import formatar_moeda, formatar_percentual


def _linha(indicador: str, valor: str) -> dict:
    return {"Indicador": indicador, "Valor": valor}


def exportar_excel_precificacao(resultado: ResultadoPrecificacao, caminho_saida: str | Path) -> Path:
    """Exporta o resultado da Precificação Inteligente (abas Resumo, Fluxo
    Descontado e, se houver, Trechos Localizados) para um arquivo .xlsx."""
    caminho_saida = Path(caminho_saida)
    rv = resultado.resultado_vpl
    p = rv.parametros
    tg = resultado.extracao.termos_gerais

    linhas = [
        _linha("Documento Analisado", resultado.extracao.arquivo_nome),
        _linha("Deságio (identificado pela IA)", tg.desagio),
        _linha("Carência (identificado pela IA)", tg.carencia),
        _linha("Juros (identificado pela IA)", tg.juros),
        _linha("Correção Monetária (identificado pela IA)", tg.correcao_monetaria),
        _linha("Periodicidade (identificado pela IA)", tg.periodicidade_parcelas),
        _linha("Quantidade de Parcelas (identificado pela IA)", tg.quantidade_parcelas),
        _linha("Valor do Crédito", formatar_moeda(float(p.valor_credito))),
        _linha("Deságio Utilizado", formatar_percentual(float(p.desagio))),
        _linha("Valor de Compra", formatar_moeda(float(p.valor_compra))),
        _linha("Taxa de Desconto (a.a.)", formatar_percentual(float(p.taxa_desconto_anual))),
        _linha("Origem da Taxa de Desconto", p.origem_taxa_desconto),
        _linha("Valor Futuro", formatar_moeda(float(rv.valor_futuro))),
        _linha("Valor Econômico", formatar_moeda(float(rv.valor_economico))),
        _linha("VPL", formatar_moeda(float(rv.vpl))),
        _linha("Ganho Líquido", formatar_moeda(float(rv.ganho_liquido))),
        _linha("TIR (a.a.)", formatar_percentual(float(rv.tir_anual)) if rv.tir_anual is not None else "-"),
        _linha("Payback", str(rv.payback_data) if rv.payback_data else "Não atingido"),
        _linha(
            "Payback Descontado",
            str(resultado.payback_descontado_data) if resultado.payback_descontado_data else "Não atingido",
        ),
        _linha("Duration", f"{float(resultado.duration_anos):.2f} anos" if resultado.duration_anos is not None else "-"),
        _linha("ROI", formatar_percentual(float(rv.roi)) if rv.roi is not None else "-"),
        _linha("Rentabilidade", formatar_percentual(float(rv.rentabilidade)) if rv.rentabilidade is not None else "-"),
        _linha("Margem", formatar_percentual(float(rv.margem)) if rv.margem is not None else "-"),
        _linha("Spread (a.a.)", formatar_percentual(float(rv.spread)) if rv.spread is not None else "-"),
        _linha("Preço Máximo (Breakeven)", formatar_moeda(float(resultado.preco_maximo_breakeven))),
        _linha(
            f"Preço Máximo (TIR-alvo {formatar_percentual(float(resultado.taxa_alvo_anual))})",
            formatar_moeda(float(resultado.preco_maximo_taxa_alvo)),
        ),
    ]
    df_resumo = pd.DataFrame(linhas)
    df_fluxo = _df_fluxo(rv.fluxo_descontado)

    with pd.ExcelWriter(caminho_saida, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
        df_fluxo.to_excel(writer, sheet_name="Fluxo Descontado", index=False)
        _aplicar_formatos(writer.sheets["Fluxo Descontado"], df_fluxo)
        for celula in writer.sheets["Resumo"][1]:
            celula.font = Font(bold=True)

        if resultado.extracao.trechos_localizados:
            df_trechos = pd.DataFrame(
                [
                    {"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto}
                    for t in resultado.extracao.trechos_localizados
                ]
            )
            df_trechos.to_excel(writer, sheet_name="Trechos Localizados", index=False)
            for celula in writer.sheets["Trechos Localizados"][1]:
                celula.font = Font(bold=True)

    return caminho_saida
