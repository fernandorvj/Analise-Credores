"""Aba "Calculadora de VPL" — VPL, TIR, Payback, ROI e demais indicadores de
retorno para uma operação de aquisição de crédito, com taxa de desconto
obtida da Meta Selic (API pública do BACEN) ou informada manualmente.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from config import CORES, EXPORTADOS_DIR
from interface.calculadora.componentes import aplicar_tema_escuro_grafico, container_grafico, editor_fluxo, renderizar_kpis, salvar_cenario
from interface.icones import icone
from src.calculadora.amortizacao import adicionar_periodos
from src.calculadora.exportar_excel import exportar_excel_vpl
from src.calculadora.exportar_word import exportar_word_vpl
from src.calculadora.fluxo import novo_item
from src.calculadora.models import ParametrosVPL, Periodicidade, TipoFluxoItem
from src.calculadora.selic import ORIGEM_MANUAL, obter_selic_bacen
from src.calculadora.vpl_tir import calcular_resultado_vpl
from src.utils import formatar_moeda, formatar_percentual


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_selic_cache():
    resultado = obter_selic_bacen()
    if resultado is None:
        return None
    return {"valor_anual": resultado.valor_anual, "data_referencia": resultado.data_referencia, "origem": resultado.origem}


def _bloco_taxa_desconto() -> tuple[Decimal, str]:
    st.markdown("#### Taxa de Desconto (SELIC)")
    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("Atualizar SELIC", icon=icone("atualizar")):
            _consultar_selic_cache.clear()

    selic = _consultar_selic_cache()
    with col_a:
        if selic is not None:
            st.success(
                f"Meta Selic: {formatar_percentual(float(selic['valor_anual']))} a.a. — "
                f"referência {selic['data_referencia'].strftime('%d/%m/%Y')} ({selic['origem']})"
            )
        else:
            st.warning(
                "Não foi possível consultar a API do BACEN neste momento. Informe a taxa manualmente abaixo."
            )

    usar_manual = st.checkbox("Informar taxa manualmente", value=selic is None, key="vpl_taxa_manual")
    if usar_manual:
        taxa_padrao = st.session_state.get("calc_config_taxa_manual_padrao", Decimal("0.10"))
        taxa_percentual = st.number_input(
            "Taxa de Desconto Manual (% a.a.)",
            min_value=0.0,
            value=float((selic["valor_anual"] if selic else taxa_padrao) * 100),
            step=0.1,
        )
        return Decimal(str(taxa_percentual)) / Decimal(100), ORIGEM_MANUAL
    return selic["valor_anual"], selic["origem"]


def _formulario_credito() -> tuple[Decimal, Decimal, Decimal, date] | None:
    col1, col2 = st.columns(2)
    with col1:
        valor_credito = st.number_input("Valor do Crédito (R$)", min_value=0.0, value=100000.0, step=1000.0)
        data_base = st.date_input("Data Base", value=date.today(), key="vpl_data_base")
    with col2:
        override_compra = st.checkbox("Informar Valor de Compra diretamente (em vez de Deságio)")
        if override_compra:
            valor_compra_input = st.number_input("Valor de Compra (R$)", min_value=0.01, value=60000.0, step=1000.0)
            desagio = Decimal(1) - (Decimal(str(valor_compra_input)) / Decimal(str(valor_credito))) if valor_credito else Decimal(0)
            valor_compra = Decimal(str(valor_compra_input))
        else:
            desagio_percentual = st.number_input("Deságio (%)", min_value=0.0, max_value=99.0, value=40.0, step=1.0)
            desagio = Decimal(str(desagio_percentual)) / Decimal(100)
            valor_compra = Decimal(str(valor_credito)) * (Decimal(1) - desagio)
            st.caption(f"Valor de compra calculado: {formatar_moeda(float(valor_compra))}")

    try:
        return Decimal(str(valor_credito)), valor_compra, desagio, data_base
    except InvalidOperation:
        st.error("Não foi possível interpretar os valores informados.")
        return None


def _gerar_fluxo_automatico(valor_credito: Decimal, data_base: date) -> None:
    with st.form("form_vpl_plano"):
        col1, col2, col3 = st.columns(3)
        with col1:
            parcelas = st.number_input("Quantidade de Parcelas", min_value=1, value=12, step=1)
        with col2:
            periodicidade = st.selectbox("Periodicidade", list(Periodicidade), format_func=lambda p: p.value, index=0)
        with col3:
            carencia = st.number_input("Carência (períodos até o 1º recebimento)", min_value=0, value=0, step=1)

        gerar = st.form_submit_button("Gerar Plano de Pagamento Automático", icon=icone("vpl"))

    if gerar:
        valor_parcela = valor_credito / Decimal(int(parcelas))
        fluxo = [
            novo_item(
                i, adicionar_periodos(data_base, int(carencia) + i, periodicidade), f"Parcela {i}", TipoFluxoItem.PARCELA, valor_parcela
            )
            for i in range(1, int(parcelas) + 1)
        ]
        st.session_state["calc_vpl_fluxo"] = fluxo
        st.session_state.pop("calc_vpl_editor", None)


def _grafico_fluxo(resultado) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[item.data for item in resultado.fluxo_descontado],
            y=[float(item.valor) for item in resultado.fluxo_descontado],
            name="Valor Nominal",
            marker_color=CORES["grafico_indigo"],
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[item.data for item in resultado.fluxo_descontado],
            y=[float(item.valor_presente) if item.valor_presente is not None else 0.0 for item in resultado.fluxo_descontado],
            mode="lines+markers",
            name="Valor Presente",
            line=dict(color=CORES["destaque"], width=3),
        )
    )
    fig.update_layout(title="Fluxo Nominal x Valor Presente", xaxis_title="Data", yaxis_title="Valor (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _renderizar_resultado(resultado) -> None:
    renderizar_kpis(
        [
            ("VPL", formatar_moeda(float(resultado.vpl))),
            ("TIR (a.a.)", formatar_percentual(float(resultado.tir_anual)) if resultado.tir_anual is not None else "-"),
            ("Payback", resultado.payback_data.strftime("%d/%m/%Y") if resultado.payback_data else "Não atingido"),
            ("ROI", formatar_percentual(float(resultado.roi)) if resultado.roi is not None else "-"),
        ]
    )
    renderizar_kpis(
        [
            ("Valor Futuro", formatar_moeda(float(resultado.valor_futuro))),
            ("Valor Econômico", formatar_moeda(float(resultado.valor_economico))),
            ("Rentabilidade", formatar_percentual(float(resultado.rentabilidade)) if resultado.rentabilidade is not None else "-"),
            ("Margem", formatar_percentual(float(resultado.margem)) if resultado.margem is not None else "-"),
        ]
    )
    if resultado.tir_anual is None:
        st.warning("A TIR não convergiu para este fluxo — revise os valores informados.")

    st.markdown("#### Fluxo Descontado")
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "Data": item.data.strftime("%d/%m/%Y"),
                "Descrição": item.descricao,
                "Valor Nominal": formatar_moeda(float(item.valor)),
                "Valor Presente": formatar_moeda(float(item.valor_presente)) if item.valor_presente is not None else "-",
            }
            for item in resultado.fluxo_descontado
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("#### Gráfico")
    with container_grafico("vpl_fluxo"):
        st.plotly_chart(_grafico_fluxo(resultado), width="stretch")

    st.divider()
    col_export, col_cenario = st.columns(2)
    with col_export:
        st.markdown("**Exportar**")
        sub_a, sub_b = st.columns(2)
        with sub_a:
            if st.button("Excel", key="vpl_btn_excel", icon=icone("exportar"), width="stretch"):
                caminho = EXPORTADOS_DIR / "calculadora_vpl.xlsx"
                exportar_excel_vpl(resultado, caminho)
                st.session_state["calc_vpl_export_xlsx"] = str(caminho)
        with sub_b:
            if st.button("Word", key="vpl_btn_word", icon=icone("exportar"), width="stretch"):
                caminho = EXPORTADOS_DIR / "calculadora_vpl.docx"
                exportar_word_vpl(resultado, caminho)
                st.session_state["calc_vpl_export_docx"] = str(caminho)

        for chave_sessao, rotulo in (("calc_vpl_export_xlsx", "Baixar Excel"), ("calc_vpl_export_docx", "Baixar Word")):
            caminho_str = st.session_state.get(chave_sessao)
            if caminho_str and Path(caminho_str).exists():
                caminho = Path(caminho_str)
                st.download_button(rotulo, caminho.read_bytes(), file_name=caminho.name, key=f"vpl_download_{chave_sessao}")

    with col_cenario:
        st.markdown("**Salvar para comparação**")
        with st.form("form_salvar_cenario_vpl", border=False):
            nome_cenario = st.text_input("Nome do cenário", value="VPL Aquisição de Crédito")
            if st.form_submit_button("Salvar cenário", icon=icone("comparacao")):
                salvar_cenario(nome_cenario, "vpl", resultado)
                st.success(f'Cenário "{nome_cenario}" salvo. Veja a aba Comparação de Cenários.')


def renderizar_vpl() -> None:
    dados_credito = _formulario_credito()
    if dados_credito is None:
        return
    valor_credito, valor_compra, desagio, data_base = dados_credito

    taxa_desconto, origem_taxa = _bloco_taxa_desconto()

    with st.expander("Correção Monetária (opcional)"):
        correcao_percentual = st.number_input("Correção Monetária (% a.a.)", min_value=0.0, value=0.0, step=0.5)
    correcao = Decimal(str(correcao_percentual)) / Decimal(100)

    st.markdown("#### Plano de Pagamento")
    _gerar_fluxo_automatico(valor_credito, data_base)

    if "calc_vpl_fluxo" not in st.session_state:
        st.info('Gere um plano automático acima ou defina um plano personalizado adicionando linhas na tabela abaixo.')
        st.session_state["calc_vpl_fluxo"] = []

    st.caption("Edite livremente as parcelas — adicione recebimentos extraordinários ou remova linhas conforme necessário.")
    fluxo_editado = editor_fluxo(st.session_state["calc_vpl_fluxo"], key="calc_vpl_editor")

    if st.button("Calcular VPL", type="primary", icon=icone("vpl")):
        if not fluxo_editado:
            st.error("Defina ao menos um recebimento no plano de pagamento.")
            return
        st.session_state["calc_vpl_fluxo"] = fluxo_editado
        parametros = ParametrosVPL(
            valor_credito=valor_credito,
            valor_compra=valor_compra,
            desagio=desagio,
            data_base=data_base,
            fluxo_recebimentos=fluxo_editado,
            taxa_desconto_anual=taxa_desconto,
            origem_taxa_desconto=origem_taxa,
            correcao_monetaria_anual=correcao,
        )
        try:
            resultado = calcular_resultado_vpl(parametros)
            st.session_state["calc_vpl_resultado"] = resultado
            st.session_state.pop("calc_vpl_export_xlsx", None)
            st.session_state.pop("calc_vpl_export_docx", None)
        except ValueError as exc:
            st.error(str(exc))
            return

    resultado = st.session_state.get("calc_vpl_resultado")
    if resultado is not None:
        st.divider()
        _renderizar_resultado(resultado)
