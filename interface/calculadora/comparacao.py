"""Aba "Comparação de Cenários" — reúne os cenários salvos no Simulador de
Financiamento e na Calculadora de VPL (sessão atual, sem persistência em
banco) e apresenta uma tabela e gráficos comparativos.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import CORES, EXPORTADOS_DIR
from interface.calculadora.componentes import aplicar_tema_escuro_grafico, container_grafico, listar_cenarios
from interface.icones import icone
from src.calculadora.exportar_excel import exportar_excel_comparacao
from src.calculadora.models import Cenario, ResultadoFinanciamento, ResultadoVPL
from src.utils import formatar_moeda, formatar_percentual


def _linha_tabela(cenario: Cenario) -> dict:
    if cenario.tipo == "vpl":
        r: ResultadoVPL = cenario.resultado  # type: ignore[assignment]
        return {
            "Cenário": cenario.nome,
            "Tipo": "VPL",
            "VPL": formatar_moeda(float(r.vpl)),
            "TIR (a.a.)": formatar_percentual(float(r.tir_anual)) if r.tir_anual is not None else "-",
            "ROI": formatar_percentual(float(r.roi)) if r.roi is not None else "-",
            "Payback": r.payback_data.strftime("%d/%m/%Y") if r.payback_data else "-",
            "Rentabilidade": formatar_percentual(float(r.rentabilidade)) if r.rentabilidade is not None else "-",
        }
    f: ResultadoFinanciamento = cenario.resultado  # type: ignore[assignment]
    return {
        "Cenário": cenario.nome,
        "Tipo": "Financiamento",
        "VPL": "-",
        "TIR (a.a.)": "-",
        "ROI": "-",
        "Payback": "-",
        "Rentabilidade": "-",
        "Parcela": formatar_moeda(float(f.valor_parcela_regular or 0)),
        "Juros Totais": formatar_moeda(float(f.juros_totais)),
        "Total Pago": formatar_moeda(float(f.total_pago)),
    }


def _grafico_comparacao_vpl(cenarios_vpl: list[Cenario]) -> go.Figure:
    fig = go.Figure()
    nomes = [c.nome for c in cenarios_vpl]
    fig.add_trace(go.Bar(x=nomes, y=[float(c.resultado.vpl) for c in cenarios_vpl], name="VPL", marker_color=CORES["grafico_indigo"]))
    fig.update_layout(title="VPL por Cenário", yaxis_title="VPL (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _grafico_comparacao_financiamento(cenarios_fin: list[Cenario]) -> go.Figure:
    fig = go.Figure()
    nomes = [c.nome for c in cenarios_fin]
    fig.add_trace(
        go.Bar(x=nomes, y=[float(c.resultado.juros_totais) for c in cenarios_fin], name="Juros Totais", marker_color=CORES["destaque"])
    )
    fig.update_layout(title="Juros Totais por Cenário", yaxis_title="Valor (R$)")
    return aplicar_tema_escuro_grafico(fig)


def renderizar_comparacao() -> None:
    cenarios = listar_cenarios()
    if not cenarios:
        st.info(
            "Nenhum cenário salvo ainda. Calcule uma simulação nas abas \"Simulador de Financiamento\" "
            'ou "Calculadora de VPL" e clique em "Salvar cenário" para compará-los aqui.'
        )
        return

    st.markdown(f"**{len(cenarios)} cenário(s) salvo(s) nesta sessão.**")
    df = pd.DataFrame([_linha_tabela(c) for c in cenarios])
    st.dataframe(df, width="stretch", hide_index=True)

    opcoes = [f"{i}. {c.nome}" for i, c in enumerate(cenarios)]
    remover = st.multiselect("Remover cenário(s)", opcoes)
    if remover and st.button("Remover Selecionados", icon=icone("excluir")):
        indices_remover = {int(item.split(".")[0]) for item in remover}
        st.session_state["calc_cenarios"] = [c for i, c in enumerate(cenarios) if i not in indices_remover]
        st.rerun()

    cenarios_vpl = [c for c in cenarios if c.tipo == "vpl"]
    cenarios_fin = [c for c in cenarios if c.tipo == "financiamento"]

    if len(cenarios_vpl) >= 2 or len(cenarios_fin) >= 2:
        st.markdown("#### Gráficos Comparativos")
        col_a, col_b = st.columns(2)
        if len(cenarios_vpl) >= 2:
            with col_a:
                with container_grafico("comparacao_vpl"):
                    st.plotly_chart(_grafico_comparacao_vpl(cenarios_vpl), width="stretch")
        if len(cenarios_fin) >= 2:
            with col_b:
                with container_grafico("comparacao_financiamento"):
                    st.plotly_chart(_grafico_comparacao_financiamento(cenarios_fin), width="stretch")

    st.divider()
    if st.button("Exportar Comparação (Excel)", icon=icone("exportar")):
        caminho = EXPORTADOS_DIR / "comparacao_cenarios.xlsx"
        exportar_excel_comparacao(cenarios, caminho)
        st.session_state["calc_comparacao_export_xlsx"] = str(caminho)

    caminho_str = st.session_state.get("calc_comparacao_export_xlsx")
    if caminho_str and Path(caminho_str).exists():
        caminho = Path(caminho_str)
        st.download_button("Baixar Excel", caminho.read_bytes(), file_name=caminho.name, key="comparacao_download_xlsx")
