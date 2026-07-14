"""Aba "Simulação Balão" — financiamento com pagamentos balão periódicos e
parcelas extraordinárias, com um Editor de Fluxo livre: o usuário pode
adicionar, excluir e alterar qualquer evento do fluxo, recalculando saldo,
juros e valor presente automaticamente a cada mudança.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import CORES, EXPORTADOS_DIR
from interface.calculadora.componentes import (
    aplicar_tema_escuro_grafico,
    campo_moeda,
    container_grafico,
    editor_fluxo,
    renderizar_kpis,
    salvar_cenario,
)
from interface.icones import icone
from src.calculadora.amortizacao import converter_taxa
from src.calculadora.exportar_excel import exportar_excel_fluxo
from src.calculadora.fluxo import (
    gerar_fluxo_balao,
    gerar_fluxo_percentual,
    novo_item,
    recalcular_e_quitar_no_ultimo_evento,
    recalcular_fluxo,
    saldo_final,
)
from src.calculadora.models import Periodicidade, RegimeJuros, TipoFluxoItem
from src.calculadora.vpl_tir import xirr, xnpv
from src.utils import formatar_moeda, formatar_percentual


def _formulario_geracao() -> None:
    with st.form("form_balao"):
        col1, col2 = st.columns(2)
        with col1:
            principal = campo_moeda("Valor Financiado (R$)", 100000.0)
            valor_entrada = campo_moeda("Valor de Entrada (R$)", 10000.0)
            data_inicial = st.date_input("Data Inicial", value=date.today(), key="balao_data_inicial")
            taxa_percentual = st.number_input("Taxa de Juros Mensal (%)", min_value=0.0, value=2.0, step=0.1)
        with col2:
            prazo = st.number_input("Prazo Total (nº de parcelas)", min_value=1, value=12, step=1, key="balao_prazo")
            intervalo_balao = st.number_input("Intervalo entre Balões (a cada N parcelas)", min_value=1, value=6, step=1)
            valor_balao = campo_moeda("Valor de Cada Balão (R$)", 20000.0)

        gerar = st.form_submit_button("Gerar Fluxo Automaticamente", type="primary", icon=icone("balao"))

    if not gerar:
        return

    try:
        principal_dec = Decimal(str(principal))
        entrada_dec = Decimal(str(valor_entrada))
        taxa_dec = Decimal(str(taxa_percentual)) / Decimal(100)
        fluxo = gerar_fluxo_balao(
            principal=principal_dec,
            valor_entrada=entrada_dec,
            data_inicial=data_inicial,
            prazo=int(prazo),
            periodicidade=Periodicidade.MENSAL,
            taxa_periodica=taxa_dec,
            intervalo_balao=int(intervalo_balao),
            valor_balao=Decimal(str(valor_balao)),
        )
        fluxo = recalcular_e_quitar_no_ultimo_evento(fluxo, principal_dec, taxa_dec, data_inicial)
    except (InvalidOperation, ValueError) as exc:
        st.error(f"Não foi possível gerar o fluxo: {exc}")
        return

    st.session_state["calc_balao_fluxo"] = fluxo
    st.session_state["calc_balao_principal"] = principal_dec
    st.session_state["calc_balao_taxa"] = taxa_dec
    st.session_state["calc_balao_data_base"] = data_inicial
    st.session_state.pop("calc_balao_editor", None)  # limpa estado anterior do data_editor


def _formulario_percentual() -> None:
    """Modo alternativo de geração do fluxo: em vez de balões periódicos, as
    parcelas seguem um padrão de percentuais que se repete ciclicamente (ex.:
    "60,40" gera parcelas alternadas de peso 60%/40%/60%/40%/... "60%/40%
    durante N períodos"). Usa `fluxo.gerar_fluxo_percentual` (Fase 2) como
    "semente" inicial e o mesmo `recalcular_e_quitar_no_ultimo_evento` já
    usado pelo Balão automático — nenhuma lógica nova de recálculo/quitação.
    """
    with st.form("form_balao_percentual"):
        col1, col2 = st.columns(2)
        with col1:
            principal = campo_moeda("Valor Financiado (R$)", 100000.0, key="balao_pct_principal")
            valor_entrada = campo_moeda("Valor de Entrada (R$)", 0.0, key="balao_pct_entrada")
            data_inicial = st.date_input("Data Inicial", value=date.today(), key="balao_pct_data_inicial")
        with col2:
            taxa_percentual = st.number_input(
                "Taxa de Juros por Período (%)", min_value=0.0, value=2.0, step=0.1, key="balao_pct_taxa"
            )
            prazo = st.number_input("Prazo Total (nº de parcelas)", min_value=1, value=12, step=1, key="balao_pct_prazo")
            periodicidade = st.selectbox(
                "Periodicidade", list(Periodicidade), format_func=lambda p: p.value, index=0, key="balao_pct_periodicidade"
            )

        percentuais_texto = st.text_input(
            "Padrão de percentuais (separados por vírgula, repete ciclicamente)",
            value="60,40",
            help='Ex.: "60,40" gera parcelas alternadas de peso 60%/40%/60%/40%... até completar o '
            'prazo — use ponto para casas decimais dentro de cada percentual (ex.: "33.3,33.3,33.4").',
            key="balao_pct_percentuais",
        )

        gerar = st.form_submit_button("Gerar Fluxo por Percentual", type="primary", icon=icone("fluxo"))

    if not gerar:
        return

    try:
        percentuais = [Decimal(p.strip()) / Decimal(100) for p in percentuais_texto.split(",") if p.strip()]
        if not percentuais:
            raise ValueError("Informe ao menos um percentual.")

        principal_dec = Decimal(str(principal))
        entrada_dec = Decimal(str(valor_entrada))
        taxa_dec = Decimal(str(taxa_percentual)) / Decimal(100)
        saldo_a_distribuir = principal_dec - entrada_dec

        parcelas = gerar_fluxo_percentual(saldo_a_distribuir, data_inicial, int(prazo), periodicidade, percentuais)

        fluxo: list = []
        contador = 0
        if entrada_dec > 0:
            contador += 1
            fluxo.append(novo_item(contador, data_inicial, "Entrada", TipoFluxoItem.ENTRADA, entrada_dec, editavel=False))
        for parcela in parcelas:
            contador += 1
            parcela.id = contador
            fluxo.append(parcela)

        fluxo = recalcular_e_quitar_no_ultimo_evento(fluxo, principal_dec, taxa_dec, data_inicial)
    except (InvalidOperation, ValueError) as exc:
        st.error(f"Não foi possível gerar o fluxo: {exc}")
        return

    st.session_state["calc_balao_fluxo"] = fluxo
    st.session_state["calc_balao_principal"] = principal_dec
    st.session_state["calc_balao_taxa"] = taxa_dec
    st.session_state["calc_balao_data_base"] = data_inicial
    st.session_state.pop("calc_balao_editor", None)


def _grafico_fluxo(fluxo: list) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[item.data for item in fluxo],
            y=[float(item.valor) for item in fluxo],
            marker_color=[CORES["destaque"] if item.tipo == TipoFluxoItem.BALAO else CORES["grafico_indigo"] for item in fluxo],
            name="Pagamento",
        )
    )
    fig.update_layout(title="Fluxo de Pagamentos", xaxis_title="Data", yaxis_title="Valor (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _grafico_saldo(fluxo: list) -> go.Figure:
    fig = go.Figure()
    itens_com_saldo = [item for item in fluxo if item.saldo_devedor is not None]
    fig.add_trace(
        go.Scatter(
            x=[item.data for item in itens_com_saldo],
            y=[float(item.saldo_devedor) for item in itens_com_saldo],
            mode="lines+markers",
            line=dict(color=CORES["grafico_indigo"], width=3),
            fill="tozeroy",
            name="Saldo Devedor",
        )
    )
    fig.update_layout(title="Evolução do Saldo Devedor", xaxis_title="Data", yaxis_title="Saldo (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _renderizar_editor() -> None:
    fluxo = st.session_state["calc_balao_fluxo"]
    principal = st.session_state["calc_balao_principal"]
    taxa = st.session_state["calc_balao_taxa"]
    data_base = st.session_state["calc_balao_data_base"]

    st.markdown("#### Editor de Fluxo")
    st.caption(
        "Adicione, exclua ou altere qualquer linha (data, descrição, tipo ou valor) — o saldo devedor, "
        "os juros e o valor presente são recalculados automaticamente ao clicar em \"Recalcular\"."
    )
    fluxo_editado = editor_fluxo(fluxo, key="calc_balao_editor")

    if st.button("Recalcular", icon=icone("atualizar"), type="primary"):
        fluxo_editado = recalcular_fluxo(fluxo_editado, principal, taxa, data_base)
        st.session_state["calc_balao_fluxo"] = fluxo_editado
        st.rerun()

    fluxo_atual = st.session_state["calc_balao_fluxo"]
    if not any(item.saldo_devedor is not None for item in fluxo_atual):
        fluxo_atual = recalcular_fluxo(fluxo_atual, principal, taxa, data_base)
        st.session_state["calc_balao_fluxo"] = fluxo_atual

    residual = saldo_final(fluxo_atual)

    taxa_anual = converter_taxa(taxa, Periodicidade.MENSAL, Periodicidade.ANUAL, RegimeJuros.COMPOSTO)
    valor_presente_total = xnpv(
        [(item.data, item.valor) for item in fluxo_atual if item.tipo != TipoFluxoItem.ENTRADA], taxa_anual, data_base
    )

    fluxo_custo = [(data_base, -(principal - next((i.valor for i in fluxo_atual if i.tipo == TipoFluxoItem.ENTRADA), Decimal(0))))]
    fluxo_custo += [(item.data, item.valor) for item in fluxo_atual if item.tipo != TipoFluxoItem.ENTRADA]
    custo_efetivo_anual = xirr(fluxo_custo, data_base)

    renderizar_kpis(
        [
            ("Saldo Residual", formatar_moeda(float(residual))),
            ("Valor Presente do Fluxo", formatar_moeda(float(valor_presente_total))),
            ("Custo Efetivo (a.a.)", formatar_percentual(float(custo_efetivo_anual)) if custo_efetivo_anual is not None else "-"),
        ]
    )
    if residual != 0:
        st.warning(
            f"O fluxo atual não fecha em zero (saldo residual de {formatar_moeda(float(residual))}). "
            "Ajuste os valores ou adicione uma parcela extraordinária para quitar o saldo."
        )

    st.markdown("#### Detalhamento")
    df = pd.DataFrame(
        [
            {
                "Data": item.data.strftime("%d/%m/%Y"),
                "Descrição": item.descricao,
                "Tipo": item.tipo.value,
                "Valor": formatar_moeda(float(item.valor)),
                "Juros": formatar_moeda(float(item.juros)) if item.juros is not None else "-",
                "Amortização": formatar_moeda(float(item.amortizacao)) if item.amortizacao is not None else "-",
                "Saldo Devedor": formatar_moeda(float(item.saldo_devedor)) if item.saldo_devedor is not None else "-",
            }
            for item in sorted(fluxo_atual, key=lambda i: i.data)
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("#### Gráficos")
    col_a, col_b = st.columns(2)
    with col_a:
        with container_grafico("balao_fluxo"):
            st.plotly_chart(_grafico_fluxo(fluxo_atual), width="stretch")
    with col_b:
        with container_grafico("balao_saldo"):
            st.plotly_chart(_grafico_saldo(fluxo_atual), width="stretch")

    st.divider()
    col_export, col_cenario = st.columns(2)
    with col_export:
        st.markdown("**Exportar**")
        if st.button("Excel", key="balao_btn_excel", icon=icone("exportar")):
            caminho = EXPORTADOS_DIR / "simulacao_balao.xlsx"
            exportar_excel_fluxo(fluxo_atual, caminho, titulo_aba="Fluxo Balão")
            st.session_state["calc_balao_export_xlsx"] = str(caminho)
        caminho_str = st.session_state.get("calc_balao_export_xlsx")
        if caminho_str and Path(caminho_str).exists():
            caminho = Path(caminho_str)
            st.download_button("Baixar Excel", caminho.read_bytes(), file_name=caminho.name, key="balao_download_xlsx")

    with col_cenario:
        st.markdown("**Salvar para comparação**")
        st.caption(
            "A Comparação de Cenários utiliza os cenários do Simulador de Financiamento e da "
            "Precificação Inteligente de Créditos."
        )


def renderizar_balao() -> None:
    modo = st.radio(
        "Modo de geração do fluxo inicial",
        ["Balão automático (entrada + parcelas + balões)", "Percentual customizado (ex.: 60%/40%)"],
        key="balao_modo_geracao",
        horizontal=True,
    )
    if modo.startswith("Balão"):
        _formulario_geracao()
    else:
        _formulario_percentual()

    if "calc_balao_fluxo" not in st.session_state:
        st.info(
            'Preencha os parâmetros acima e clique em "Gerar Fluxo Automaticamente" (ou "Gerar Fluxo '
            'por Percentual") para montar o fluxo inicial — em seguida edite livremente qualquer evento.'
        )
        return

    _renderizar_editor()
