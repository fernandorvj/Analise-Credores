"""Aba "Simulador de Financiamento" — Tabela Price ou SAC, juros simples ou
compostos, com carência, gera cronograma completo, gráficos e exportação.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import CORES, EXPORTADOS_DIR
from interface.calculadora.componentes import container_grafico, aplicar_tema_escuro_grafico, renderizar_kpis, salvar_cenario
from interface.icones import icone
from src.calculadora.amortizacao import gerar_cronograma
from src.calculadora.exportar_excel import exportar_excel_financiamento
from src.calculadora.exportar_word import exportar_word_financiamento
from src.calculadora.models import (
    ParametrosFinanciamento,
    Periodicidade,
    RegimeJuros,
    ResultadoFinanciamento,
    SistemaAmortizacao,
)
from src.utils import formatar_moeda, formatar_percentual


def _formulario() -> ParametrosFinanciamento | None:
    with st.form("form_financiamento"):
        col1, col2 = st.columns(2)
        with col1:
            valor_financiado = st.number_input("Valor Financiado (R$)", min_value=0.0, value=100000.0, step=1000.0)
            valor_entrada = st.number_input("Valor de Entrada (R$)", min_value=0.0, value=0.0, step=1000.0)
            taxa_percentual = st.number_input("Taxa de Juros (%)", min_value=0.0, value=2.0, step=0.1)
            periodicidade_taxa = st.selectbox(
                "Periodicidade da Taxa", list(Periodicidade), format_func=lambda p: p.value, index=0
            )
            data_inicial = st.date_input("Data Inicial", value=date.today())
        with col2:
            prazo = st.number_input("Prazo (nº de parcelas)", min_value=1, value=12, step=1)
            carencia = st.number_input("Carência (nº de parcelas)", min_value=0, value=0, step=1)
            periodicidade_parcela = st.selectbox(
                "Periodicidade das Parcelas", list(Periodicidade), format_func=lambda p: p.value, index=0
            )
            sistema = st.selectbox("Sistema de Amortização", list(SistemaAmortizacao), format_func=lambda s: s.value)
            regime_padrao = st.session_state.get("calc_config_regime_padrao", RegimeJuros.COMPOSTO)
            regime = st.selectbox(
                "Regime de Juros",
                list(RegimeJuros),
                index=list(RegimeJuros).index(regime_padrao),
                format_func=lambda r: r.value,
            )

        carencia_paga_juros = st.checkbox(
            "Pagar os juros da carência a cada período (em vez de capitalizar ao saldo)", value=False
        )

        st.caption(
            "O regime de juros se aplica à conversão da taxa entre periodicidades e à carência; "
            "o cálculo das parcelas em si segue sempre a convenção padrão do sistema escolhido."
        )

        enviado = st.form_submit_button("Calcular", type="primary", icon=icone("financiamento"))

    if not enviado:
        return None

    try:
        taxa = Decimal(str(taxa_percentual)) / Decimal(100)
        return ParametrosFinanciamento(
            valor_financiado=Decimal(str(valor_financiado)),
            valor_entrada=Decimal(str(valor_entrada)),
            taxa=taxa,
            periodicidade_taxa=periodicidade_taxa,
            periodicidade_parcela=periodicidade_parcela,
            prazo=int(prazo),
            carencia=int(carencia),
            data_inicial=data_inicial,
            sistema=sistema,
            regime=regime,
            carencia_paga_juros=carencia_paga_juros,
        )
    except InvalidOperation:
        st.error("Não foi possível interpretar os valores informados. Verifique os campos numéricos.")
        return None


def _grafico_saldo_devedor(resultado: ResultadoFinanciamento) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p.numero for p in resultado.parcelas],
            y=[float(p.saldo_final) for p in resultado.parcelas],
            mode="lines",
            line=dict(color=CORES["grafico_indigo"], width=3),
            fill="tozeroy",
            name="Saldo Devedor",
        )
    )
    fig.update_layout(title="Evolução do Saldo Devedor", xaxis_title="Parcela", yaxis_title="Saldo (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _grafico_composicao(resultado: ResultadoFinanciamento) -> go.Figure:
    fig = go.Figure()
    numeros = [p.numero for p in resultado.parcelas]
    fig.add_trace(go.Bar(x=numeros, y=[float(p.amortizacao) for p in resultado.parcelas], name="Amortização", marker_color=CORES["grafico_indigo"]))
    fig.add_trace(go.Bar(x=numeros, y=[float(p.juros) for p in resultado.parcelas], name="Juros", marker_color=CORES["destaque"]))
    fig.update_layout(title="Composição da Parcela", xaxis_title="Parcela", yaxis_title="Valor (R$)", barmode="stack")
    return aplicar_tema_escuro_grafico(fig)


def _renderizar_resultado(resultado: ResultadoFinanciamento) -> None:
    renderizar_kpis(
        [
            ("Valor da Parcela", formatar_moeda(float(resultado.valor_parcela_regular or 0))),
            ("Juros Totais", formatar_moeda(float(resultado.juros_totais))),
            ("Total Pago", formatar_moeda(float(resultado.total_pago))),
            ("Taxa Periódica Efetiva", formatar_percentual(float(resultado.taxa_periodica))),
        ]
    )

    st.markdown("#### Cronograma")
    df = pd.DataFrame(
        [
            {
                "Nº": p.numero,
                "Data": p.data.strftime("%d/%m/%Y"),
                "Carência": "Sim" if p.carencia else "Não",
                "Saldo Inicial": formatar_moeda(float(p.saldo_inicial)),
                "Juros": formatar_moeda(float(p.juros)),
                "Amortização": formatar_moeda(float(p.amortizacao)),
                "Valor Parcela": formatar_moeda(float(p.valor_parcela)),
                "Saldo Final": formatar_moeda(float(p.saldo_final)),
            }
            for p in resultado.parcelas
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("#### Gráficos")
    col_a, col_b = st.columns(2)
    with col_a:
        with container_grafico("financiamento_saldo"):
            st.plotly_chart(_grafico_saldo_devedor(resultado), width="stretch")
    with col_b:
        with container_grafico("financiamento_composicao"):
            st.plotly_chart(_grafico_composicao(resultado), width="stretch")

    st.divider()
    col_export, col_cenario = st.columns(2)
    with col_export:
        st.markdown("**Exportar**")
        sub_a, sub_b = st.columns(2)
        with sub_a:
            if st.button("Excel", key="fin_btn_excel", icon=icone("exportar"), width="stretch"):
                caminho = EXPORTADOS_DIR / "simulacao_financiamento.xlsx"
                exportar_excel_financiamento(resultado, caminho)
                st.session_state["calc_fin_export_xlsx"] = str(caminho)
        with sub_b:
            if st.button("Word", key="fin_btn_word", icon=icone("exportar"), width="stretch"):
                caminho = EXPORTADOS_DIR / "simulacao_financiamento.docx"
                exportar_word_financiamento(resultado, caminho)
                st.session_state["calc_fin_export_docx"] = str(caminho)

        for chave_sessao, rotulo in (("calc_fin_export_xlsx", "Baixar Excel"), ("calc_fin_export_docx", "Baixar Word")):
            caminho_str = st.session_state.get(chave_sessao)
            if caminho_str:
                caminho = Path(caminho_str)
                if caminho.exists():
                    st.download_button(rotulo, caminho.read_bytes(), file_name=caminho.name, key=f"fin_download_{chave_sessao}")

    with col_cenario:
        st.markdown("**Salvar para comparação**")
        with st.form("form_salvar_cenario_financiamento", border=False):
            nome_cenario = st.text_input("Nome do cenário", value=f"Financiamento {resultado.parametros.sistema.value}")
            if st.form_submit_button("Salvar cenário", icon=icone("comparacao")):
                salvar_cenario(nome_cenario, "financiamento", resultado)
                st.success(f'Cenário "{nome_cenario}" salvo. Veja a aba Comparação de Cenários.')


def renderizar_financiamento() -> None:
    parametros = _formulario()
    if parametros is not None:
        try:
            resultado = gerar_cronograma(parametros)
            st.session_state["calc_fin_resultado"] = resultado
            st.session_state.pop("calc_fin_export_xlsx", None)
            st.session_state.pop("calc_fin_export_docx", None)
        except ValueError as exc:
            st.error(str(exc))

    resultado = st.session_state.get("calc_fin_resultado")
    if resultado is None:
        st.info("Preencha os parâmetros acima e clique em \"Calcular\" para gerar o cronograma.")
        return

    _renderizar_resultado(resultado)
