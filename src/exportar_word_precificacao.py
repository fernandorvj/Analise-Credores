"""Exportação para Word (.docx) do resultado da Precificação Inteligente de
Créditos — reaproveita a capa/sumário/rodapé compartilhados
(`src/exportar_word_base.py`), sem duplicá-los. Gráficos são renderizados
com `matplotlib` (mesmo padrão já usado em `src/calculadora/exportar_word.py`).
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # backend sem interface gráfica, necessário para servidores/Streamlit
import matplotlib.pyplot as plt
import pandas as pd
from docx import Document
from docx.shared import Inches

from config import NOME_EMPRESA
from src import exportar_word_base as base
from src.models_precificacao import ResultadoPrecificacaoClasse
from src.utils import formatar_moeda, formatar_percentual

_COR_GRAFICO = "#3633CC"
_COR_GRAFICO_2 = "#B87A12"


def _grafico_fluxo(resultado: ResultadoPrecificacaoClasse) -> io.BytesIO:
    fluxo_ordenado = sorted(resultado.fluxo, key=lambda item: item.data)
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    datas = [p.data for p in fluxo_ordenado]
    nominal = [float(p.valor_nominal) for p in fluxo_ordenado]
    descontado = [float(p.valor_descontado) for p in fluxo_ordenado]
    ax.plot(datas, nominal, marker="o", color=_COR_GRAFICO, label="Valor Nominal")
    ax.plot(datas, descontado, marker="o", color=_COR_GRAFICO_2, label="Valor Presente")
    ax.set_title("Fluxo de Caixa: Nominal x Valor Presente")
    ax.set_ylabel("Valor (R$)")
    plt.xticks(rotation=25, ha="right", fontsize=8)
    ax.legend()
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    buffer.seek(0)
    return buffer


def exportar_word_precificacao(resultado: ResultadoPrecificacaoClasse, caminho_saida: str | Path) -> Path:
    """Gera o relatório Word da Precificação Inteligente: capa, sumário,
    condições consideradas, premissas, fluxo, gráfico, VPL e memória de
    cálculo (auditoria)."""
    caminho_saida = Path(caminho_saida)
    c = resultado.condicoes
    doc = Document()

    base.adicionar_capa(
        doc,
        nome_arquivo_pdf=f"Precificação — {resultado.classe}",
        subtitulo_modulo="Precificação Inteligente de Créditos",
        texto_aviso=(
            "Esta análise combina condições de pagamento extraídas por Inteligência Artificial do "
            "Plano de Recuperação Judicial com cálculos financeiros determinísticos em Python — não "
            "constitui garantia de resultado, proposta de investimento ou aconselhamento jurídico/"
            "financeiro. Metodologia de cálculo ainda pendente de validação contra a planilha "
            "oficial da AMF3 Capital."
            if not resultado.metodologia_validada
            else "Esta análise combina condições de pagamento extraídas por Inteligência Artificial do "
            "Plano de Recuperação Judicial com cálculos financeiros determinísticos em Python — não "
            "constitui garantia de resultado, proposta de investimento ou aconselhamento jurídico/"
            "financeiro."
        ),
        pagina_isolada=True,
    )
    base.adicionar_sumario(doc)

    if not resultado.metodologia_validada:
        aviso = doc.add_paragraph()
        run = aviso.add_run(
            "⚠ Metodologia de cálculo ainda não validada contra a planilha oficial de VPL da AMF3 "
            "Capital — os números deste relatório usam a convenção XNPV (dias corridos/365, padrão "
            "Excel/Google Sheets). Trate como uma estimativa até a validação ser concluída."
        )
        run.bold = True

    doc.add_heading("Condições de Pagamento Consideradas", level=1)
    df_condicoes = pd.DataFrame(
        [
            ("Classe", resultado.classe),
            ("Deságio", c.desagio),
            ("Carência", c.carencia),
            ("Índice de Correção Monetária", c.correcao_monetaria_indice),
            ("Juros", c.juros),
            ("Número de Parcelas", c.numero_parcelas),
            ("Periodicidade", c.periodicidade),
            ("Data da 1ª Parcela", c.data_primeira_parcela),
            ("Parcela Balão", c.parcela_balao),
        ],
        columns=["Condição", "Valor Considerado"],
    )
    base.adicionar_tabela_dataframe(doc, df_condicoes)

    if c.trechos_localizados:
        doc.add_heading("Trechos do Plano (Auditoria)", level=1)
        df_trechos = pd.DataFrame([{"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto} for t in c.trechos_localizados])
        base.adicionar_tabela_dataframe(doc, df_trechos)

    doc.add_heading("Dados da Operação", level=1)
    df_operacao = pd.DataFrame(
        [
            ("Valor Nominal do Crédito", formatar_moeda(float(resultado.valor_nominal_credito))),
            (
                "Valor Atualizado do Crédito",
                formatar_moeda(float(resultado.valor_atualizado_credito)) if resultado.valor_atualizado_credito is not None else "Não aplicável",
            ),
            ("Taxa de Desconto (a.a.)", formatar_percentual(float(resultado.taxa_desconto_anual))),
            ("Origem da Taxa de Desconto", resultado.origem_taxa_desconto),
            (
                "Data da Taxa de Desconto",
                resultado.data_taxa_desconto.strftime("%d/%m/%Y") if resultado.data_taxa_desconto else "Manual",
            ),
        ],
        columns=["Parâmetro", "Valor"],
    )
    base.adicionar_tabela_dataframe(doc, df_operacao)

    doc.add_heading("Fluxo de Caixa", level=1)
    df_fluxo = pd.DataFrame(
        [
            {
                "Nº": p.numero,
                "Data": p.data.strftime("%d/%m/%Y"),
                "Descrição": p.descricao,
                "Valor": float(p.valor_nominal),
                "Valor Presente": float(p.valor_descontado),
            }
            for p in sorted(resultado.fluxo, key=lambda item: item.data)
        ]
    )
    base.adicionar_tabela_dataframe(doc, df_fluxo, colunas_moeda={"Valor", "Valor Presente"})

    doc.add_heading("Gráfico", level=1)
    doc.add_picture(_grafico_fluxo(resultado), width=Inches(6))

    doc.add_heading("Valor Presente Líquido (VPL)", level=1)
    paragrafo_vpl = doc.add_paragraph()
    paragrafo_vpl.add_run(f"VPL: {formatar_moeda(float(resultado.vpl))}").bold = True

    doc.add_heading("Memória de Cálculo", level=1)
    for linha in resultado.memoria_calculo:
        doc.add_paragraph(linha, style="List Bullet")

    base.adicionar_rodape_paginacao(doc, f"{NOME_EMPRESA} — Precificação Inteligente de Créditos")
    doc.save(caminho_saida)
    return caminho_saida
