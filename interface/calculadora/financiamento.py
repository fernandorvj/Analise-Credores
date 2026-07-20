"""Aba "Simulador de Financiamento" — Tabela Price, SAC ou Sistema Americano,
juros simples ou compostos, com carência, gera cronograma completo, gráficos
e exportação. Inclui um assistente de IA que converte uma descrição em texto
livre em parâmetros sugeridos — a IA nunca calcula, só interpreta o texto.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import CORES, EXPORTADOS_DIR, possui_chave_openai
from interface.calculadora.componentes import (
    aplicar_tema_escuro_grafico,
    campo_moeda,
    container_grafico,
    renderizar_kpis,
    salvar_cenario,
)
from interface.icones import icone
from src import ia
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


def _numero_ou_padrao(valor: object, padrao: float) -> float:
    """Converte um valor vindo da sugestão da IA para float, preservando 0 —
    `valor or padrao` erraria aqui, pois 0 é um valor legítimo e "falsy"."""
    if valor is None:
        return padrao
    try:
        return float(valor)
    except (TypeError, ValueError):
        return padrao


def _periodicidade_por_valor(valor: object) -> Periodicidade | None:
    if not isinstance(valor, str):
        return None
    for periodicidade in Periodicidade:
        if periodicidade.value.lower() == valor.strip().lower():
            return periodicidade
    return None


def _sistema_por_valor(valor: object) -> SistemaAmortizacao | None:
    if not isinstance(valor, str):
        return None
    for sistema_item in SistemaAmortizacao:
        if sistema_item.value.lower() == valor.strip().lower():
            return sistema_item
    return None


def _assistente_ia_texto_livre() -> None:
    """Assistente de IA: converte uma descrição em texto livre do
    financiamento em parâmetros que pré-preenchem o formulário abaixo — a IA
    apenas interpreta o texto, nunca realiza nenhum cálculo financeiro.
    """
    with st.expander("Assistente IA — descreva o financiamento em texto livre", icon=icone("ia")):
        st.caption(
            'Ex.: "Financiamento de R$ 200.000, entrada de R$ 20.000, taxa de 1,8% ao mês, 36 '
            'parcelas mensais pela Tabela Price, com 3 meses de carência." Os valores identificados '
            "pré-preenchem o formulário abaixo — revise-os antes de calcular."
        )
        texto = st.text_area("Descrição livre", key="fin_ia_texto", height=100, label_visibility="collapsed")
        if st.button("Interpretar com IA", icon=icone("financiamento"), key="fin_ia_btn"):
            if not possui_chave_openai():
                st.warning("Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar o assistente.")
            elif not texto.strip():
                st.warning("Descreva o financiamento no campo acima antes de interpretar.")
            else:
                try:
                    sugestao = ia.extrair_estrutura_financiamento(texto)
                    st.session_state["fin_ia_sugestao"] = sugestao
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
                except json.JSONDecodeError:
                    st.error("Não foi possível interpretar a resposta da IA. Tente reformular o texto.")

        if st.session_state.get("fin_ia_sugestao"):
            st.success("Sugestão aplicada ao formulário abaixo — revise os valores antes de calcular.")
            observacoes = st.session_state["fin_ia_sugestao"].get("observacoes")
            if observacoes:
                st.caption(observacoes)


def _formulario() -> ParametrosFinanciamento | None:
    sugestao = st.session_state.get("fin_ia_sugestao") or {}
    periodicidades = list(Periodicidade)
    sistemas = list(SistemaAmortizacao)
    periodicidade_taxa_sugerida = _periodicidade_por_valor(sugestao.get("periodicidade_taxa"))
    periodicidade_parcela_sugerida = _periodicidade_por_valor(sugestao.get("periodicidade_parcela"))
    sistema_sugerido = _sistema_por_valor(sugestao.get("sistema"))

    with st.form("form_financiamento"):
        col1, col2 = st.columns(2)
        with col1:
            valor_financiado = campo_moeda(
                "Valor Financiado (R$)",
                _numero_ou_padrao(sugestao.get("valor_financiado"), 100000.0),
                dentro_de_formulario=True,
            )
            valor_entrada = campo_moeda(
                "Valor de Entrada (R$)",
                _numero_ou_padrao(sugestao.get("valor_entrada"), 0.0),
                dentro_de_formulario=True,
            )
            taxa_percentual = st.number_input(
                "Taxa de Juros (%)", min_value=0.0, value=_numero_ou_padrao(sugestao.get("taxa_percentual"), 2.0), step=0.1
            )
            periodicidade_taxa = st.selectbox(
                "Periodicidade da Taxa",
                periodicidades,
                index=periodicidades.index(periodicidade_taxa_sugerida) if periodicidade_taxa_sugerida else 0,
                format_func=lambda p: p.value,
            )
            data_inicial = st.date_input("Data Inicial", value=date.today())
        with col2:
            prazo = st.number_input(
                "Prazo (nº de parcelas)", min_value=1, value=int(_numero_ou_padrao(sugestao.get("prazo"), 12.0)), step=1
            )
            carencia = st.number_input(
                "Carência (nº de parcelas)", min_value=0, value=int(_numero_ou_padrao(sugestao.get("carencia"), 0.0)), step=1
            )
            periodicidade_parcela = st.selectbox(
                "Periodicidade das Parcelas",
                periodicidades,
                index=periodicidades.index(periodicidade_parcela_sugerida) if periodicidade_parcela_sugerida else 0,
                format_func=lambda p: p.value,
            )
            sistema = st.selectbox(
                "Sistema de Amortização",
                sistemas,
                index=sistemas.index(sistema_sugerido) if sistema_sugerido else 0,
                format_func=lambda s: s.value,
            )
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
    _assistente_ia_texto_livre()
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
