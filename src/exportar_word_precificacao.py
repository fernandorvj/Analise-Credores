"""Exportação para Word (.docx) do resultado da Precificação Inteligente de
Créditos — reaproveita a capa/sumário/rodapé compartilhados
(`src/exportar_word_base.py`) e o gráfico de fluxo já usado pela Calculadora
de VPL (`src/calculadora/exportar_word.py`), sem duplicá-los.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from docx import Document
from docx.shared import Inches

from config import NOME_EMPRESA
from src import exportar_word_base as base
from src.calculadora.exportar_excel import _df_fluxo
from src.calculadora.exportar_word import _grafico_fluxo_vpl
from src.models_precificacao import ResultadoPrecificacao
from src.utils import formatar_moeda, formatar_percentual


def exportar_word_precificacao(resultado: ResultadoPrecificacao, caminho_saida: str | Path) -> Path:
    """Gera o relatório Word da Precificação Inteligente: capa, sumário,
    termos identificados pela IA, parâmetros, premissas, fluxo, gráfico,
    resultados/indicadores e trechos localizados (auditoria).
    """
    caminho_saida = Path(caminho_saida)
    rv = resultado.resultado_vpl
    p = rv.parametros
    extracao = resultado.extracao
    tg = extracao.termos_gerais
    doc = Document()

    base.adicionar_capa(
        doc,
        nome_arquivo_pdf=extracao.arquivo_nome,
        subtitulo_modulo="Precificação Inteligente de Créditos",
        texto_aviso=(
            "Esta análise combina termos extraídos por Inteligência Artificial do documento enviado "
            "com cálculos financeiros determinísticos em Python — não constitui garantia de "
            "resultado, proposta de investimento ou aconselhamento financeiro/jurídico."
        ),
        pagina_isolada=True,
    )
    base.adicionar_sumario(doc)

    doc.add_heading("Termos Identificados pela IA", level=1)
    df_termos = pd.DataFrame(
        [
            ("Deságio", tg.desagio),
            ("Carência", tg.carencia),
            ("Juros", tg.juros),
            ("Correção Monetária", tg.correcao_monetaria),
            ("Periodicidade", tg.periodicidade_parcelas),
            ("Quantidade de Parcelas", tg.quantidade_parcelas),
            ("Início dos Pagamentos", tg.data_inicio_pagamentos),
        ],
        columns=["Termo", "Valor Identificado"],
    )
    base.adicionar_tabela_dataframe(doc, df_termos)
    if extracao.resumo_plano:
        doc.add_paragraph(extracao.resumo_plano)

    if extracao.termos_por_classe:
        doc.add_heading("Termos por Classe", level=1)
        df_classes = pd.DataFrame(
            [
                {
                    "Classe": t.classe,
                    "Deságio": t.desagio,
                    "Carência": t.carencia,
                    "Juros": t.juros,
                    "Periodicidade": t.periodicidade_parcelas,
                    "Parcelas": t.quantidade_parcelas,
                    "Observações": t.observacoes,
                }
                for t in extracao.termos_por_classe
            ]
        )
        base.adicionar_tabela_dataframe(doc, df_classes)

    if extracao.eventos_especiais:
        doc.add_heading("Eventos Especiais", level=1)
        for evento in extracao.eventos_especiais:
            doc.add_paragraph(evento, style="List Bullet")

    doc.add_heading("Parâmetros da Precificação", level=1)
    df_parametros = pd.DataFrame(
        [
            ("Valor do Crédito", formatar_moeda(float(p.valor_credito))),
            ("Deságio Utilizado", formatar_percentual(float(p.desagio))),
            ("Valor de Compra", formatar_moeda(float(p.valor_compra))),
            ("Data Base", p.data_base.strftime("%d/%m/%Y")),
            ("Taxa de Desconto (a.a.)", formatar_percentual(float(p.taxa_desconto_anual))),
            ("Origem da Taxa de Desconto", p.origem_taxa_desconto),
        ],
        columns=["Parâmetro", "Valor"],
    )
    base.adicionar_tabela_dataframe(doc, df_parametros)

    doc.add_heading("Premissas", level=1)
    doc.add_paragraph(
        "VPL, TIR, Payback Descontado e Duration seguem a metodologia XNPV/XIRR (fluxos de caixa "
        "com datas irregulares, base de 365 dias/ano). O Preço Máximo (Breakeven) é o valor "
        "econômico do fluxo de recebimentos — pagar mais que isso já produz ganho líquido negativo. "
        "O Preço Máximo (TIR-alvo) é o preço de aquisição que resulta exatamente na taxa de retorno "
        "mínima desejada informada. Todos os cálculos são feitos em Python, de forma determinística "
        "e auditável — a Inteligência Artificial participa apenas da extração dos termos do plano, "
        "nunca de nenhum cálculo financeiro."
    )

    doc.add_heading("Fluxo Descontado", level=1)
    base.adicionar_tabela_dataframe(doc, _df_fluxo(rv.fluxo_descontado), colunas_moeda={"Valor", "Valor Presente"})

    doc.add_heading("Gráfico", level=1)
    doc.add_picture(_grafico_fluxo_vpl(rv), width=Inches(6))

    doc.add_heading("Resultados e Indicadores", level=1)
    df_resultados = pd.DataFrame(
        [
            ("Valor Futuro", formatar_moeda(float(rv.valor_futuro))),
            ("Valor Econômico", formatar_moeda(float(rv.valor_economico))),
            ("VPL", formatar_moeda(float(rv.vpl))),
            ("Ganho Líquido", formatar_moeda(float(rv.ganho_liquido))),
            (
                "TIR (a.a.)",
                formatar_percentual(float(rv.tir_anual)) if rv.tir_anual is not None else "Não convergiu",
            ),
            ("Payback", rv.payback_data.strftime("%d/%m/%Y") if rv.payback_data else "Não atingido"),
            (
                "Payback Descontado",
                resultado.payback_descontado_data.strftime("%d/%m/%Y") if resultado.payback_descontado_data else "Não atingido",
            ),
            ("Duration", f"{float(resultado.duration_anos):.2f} anos" if resultado.duration_anos is not None else "-"),
            ("ROI", formatar_percentual(float(rv.roi)) if rv.roi is not None else "-"),
            ("Rentabilidade", formatar_percentual(float(rv.rentabilidade)) if rv.rentabilidade is not None else "-"),
            ("Margem", formatar_percentual(float(rv.margem)) if rv.margem is not None else "-"),
            ("Spread (a.a.)", formatar_percentual(float(rv.spread)) if rv.spread is not None else "-"),
            ("Preço Máximo (Breakeven)", formatar_moeda(float(resultado.preco_maximo_breakeven))),
            (
                f"Preço Máximo (TIR-alvo {formatar_percentual(float(resultado.taxa_alvo_anual))})",
                formatar_moeda(float(resultado.preco_maximo_taxa_alvo)),
            ),
        ],
        columns=["Indicador", "Valor"],
    )
    base.adicionar_tabela_dataframe(doc, df_resultados)

    if extracao.trechos_localizados:
        doc.add_heading("Trechos Localizados (Auditoria)", level=1)
        df_trechos = pd.DataFrame(
            [{"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto} for t in extracao.trechos_localizados]
        )
        base.adicionar_tabela_dataframe(doc, df_trechos)

    doc.add_heading("Observações", level=1)
    doc.add_paragraph("Análise gerada automaticamente pela Calculadora AMF3 Capital.")

    base.adicionar_rodape_paginacao(doc, f"{NOME_EMPRESA} — Precificação Inteligente de Créditos")
    doc.save(caminho_saida)
    return caminho_saida
