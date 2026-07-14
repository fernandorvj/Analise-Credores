"""Módulo Precificação Inteligente de Créditos — extração via IA dos termos
de um Plano de Recuperação Judicial e cálculo (100% em Python, determinístico
e auditável) de VPL, TIR, ROI, Payback, Payback Descontado, Duration e Preço
Máximo Recomendado para a aquisição do crédito.

Totalmente independente dos módulos Credores e Petição Inicial. Reaproveita a
leitura/OCR de PDF (`src/leitor_pdf.py`), o gateway único de IA (`src/ia.py`)
e o motor financeiro já validado em `src/calculadora/` (amortização, fluxo de
caixa livre, VPL/TIR/Payback/Duration, SELIC) — a IA só interpreta o
documento, nunca calcula.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import CORES, EXPORTADOS_DIR, PETICOES_DIR, possui_chave_openai
from interface import layout
from interface.calculadora.componentes import (
    aplicar_tema_escuro_grafico,
    container_grafico,
    editor_fluxo,
    renderizar_kpis,
    salvar_cenario,
)
from interface.icones import icone
from src import ia, leitor_pdf
from src.calculadora.amortizacao import gerar_cronograma
from src.calculadora.fluxo import novo_item
from src.calculadora.models import (
    ParametrosFinanciamento,
    ParametrosVPL,
    Periodicidade,
    RegimeJuros,
    SistemaAmortizacao,
    TipoFluxoItem,
)
from src.calculadora.selic import ORIGEM_MANUAL, obter_selic_bacen
from src.calculadora.vpl_tir import (
    calcular_duration,
    calcular_payback_descontado,
    calcular_resultado_vpl,
    preco_maximo_para_taxa_alvo,
)
from src.exportar_excel_precificacao import exportar_excel_precificacao
from src.exportar_word_precificacao import exportar_word_precificacao
from src.models_precificacao import ExtracaoPlano, ResultadoPrecificacao
from src.utils import formatar_moeda, formatar_percentual

_FASES = [
    "Lendo PDF",
    "Aplicando OCR",
    "Extraindo texto",
    "Organizando documento",
    "Consultando IA",
    "Extraindo termos",
]


def _processar_plano(arquivo) -> ExtracaoPlano | None:
    if not possui_chave_openai():
        st.warning(
            "Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar "
            "a extração inteligente do Plano de Recuperação Judicial."
        )
        return None

    caminho_pdf = PETICOES_DIR / arquivo.name
    caminho_pdf.write_bytes(arquivo.getvalue())

    with st.status("Analisando Plano de Recuperação Judicial...", expanded=True) as status:
        barra = st.progress(0.0)

        def _concluir_fase(indice: int) -> None:
            st.write(f"✓ {_FASES[indice]}")
            barra.progress((indice + 1) / len(_FASES))

        paginas = leitor_pdf.ler_pdf(caminho_pdf)
        _concluir_fase(0)  # Lendo PDF
        _concluir_fase(1)  # Aplicando OCR (feito dentro de ler_pdf, por página)
        _concluir_fase(2)  # Extraindo texto
        _concluir_fase(3)  # Organizando documento

        def _callback(mensagem: str) -> None:
            status.update(label=mensagem)
            st.write(mensagem)

        try:
            extracao = ia.extrair_termos_plano(paginas, arquivo.name, progress_callback=_callback)
        except RuntimeError as exc:
            status.update(label="Falha ao consultar a IA", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(4)  # Consultando IA
        _concluir_fase(5)  # Extraindo termos
        status.update(label="Termos extraídos com sucesso!", state="complete", expanded=False)

    return extracao


def _renderizar_extracao(extracao: ExtracaoPlano) -> None:
    for aviso in extracao.avisos:
        st.info(aviso)

    with st.container(border=True):
        st.markdown("#### Termos Identificados pela IA")
        st.caption(
            "Revise os termos abaixo e confirme os valores numéricos no formulário de parâmetros "
            "logo adiante — a IA só interpreta o texto do documento, nenhum cálculo é feito por ela."
        )
        tg = extracao.termos_gerais
        st.table(
            pd.DataFrame(
                [
                    ("Deságio", tg.desagio),
                    ("Carência", tg.carencia),
                    ("Juros", tg.juros),
                    ("Correção Monetária", tg.correcao_monetaria),
                    ("Periodicidade das Parcelas", tg.periodicidade_parcelas),
                    ("Quantidade de Parcelas", tg.quantidade_parcelas),
                    ("Data de Início dos Pagamentos", tg.data_inicio_pagamentos),
                ],
                columns=["Termo", "Valor Identificado"],
            )
        )

        if extracao.termos_por_classe:
            st.markdown("##### Termos por Classe")
            st.table(
                pd.DataFrame(
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
            )

        if extracao.eventos_especiais:
            st.markdown("##### Eventos Especiais")
            for evento in extracao.eventos_especiais:
                st.markdown(f"- {evento}")

        if extracao.resumo_plano:
            st.markdown("##### Resumo do Plano")
            st.markdown(extracao.resumo_plano)

        if extracao.trechos_localizados:
            with st.expander("Trechos Localizados (auditoria)"):
                st.table(
                    pd.DataFrame(
                        [
                            {"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto}
                            for t in extracao.trechos_localizados
                        ]
                    )
                )


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

    usar_manual = st.checkbox("Informar taxa manualmente", value=selic is None, key="prec_taxa_manual")
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


def _formulario_credito() -> tuple[Decimal, Decimal, Decimal, Decimal, date] | None:
    col1, col2 = st.columns(2)
    with col1:
        valor_credito = st.number_input("Valor do Crédito (R$)", min_value=0.0, value=100000.0, step=1000.0)
        data_base = st.date_input("Data Base", value=date.today(), key="prec_data_base")
    with col2:
        desagio_percentual = st.number_input(
            "Deságio do Plano de RJ (%)",
            min_value=0.0,
            max_value=99.0,
            value=40.0,
            step=1.0,
            help="Haircut que o plano de recuperação judicial impõe ao crédito — confirme com base "
            "no termo identificado pela IA acima. O fluxo de recebimentos é montado sobre o valor "
            "pós-deságio, não é o desconto de compra.",
        )
        desagio = Decimal(str(desagio_percentual)) / Decimal(100)
        valor_plano = Decimal(str(valor_credito)) * (Decimal(1) - desagio)
        st.caption(f"Valor a receber pelo plano: {formatar_moeda(float(valor_plano))}")
        valor_compra_input = st.number_input(
            "Valor de Compra (R$)",
            min_value=0.01,
            value=60000.0,
            step=1000.0,
            help="Quanto você pretende pagar pelo crédito.",
        )
        valor_compra = Decimal(str(valor_compra_input))

    try:
        return Decimal(str(valor_credito)), valor_plano, valor_compra, desagio, data_base
    except InvalidOperation:
        st.error("Não foi possível interpretar os valores informados.")
        return None


def _gerar_fluxo_automatico(valor_plano: Decimal, data_base: date) -> None:
    with st.form("form_prec_plano"):
        col1, col2 = st.columns(2)
        with col1:
            parcelas = st.number_input("Quantidade de Parcelas", min_value=1, value=12, step=1)
            periodicidade = st.selectbox("Periodicidade", list(Periodicidade), format_func=lambda p: p.value, index=0)
        with col2:
            carencia = st.number_input("Carência (períodos até o 1º recebimento)", min_value=0, value=0, step=1)
            juros_am_percentual = st.number_input(
                "Juros do plano (% a.m.)",
                min_value=0.0,
                value=0.0,
                step=0.01,
                format="%.4f",
                help="Confirme com base no termo 'Juros' identificado pela IA acima (ex.: 2,5% a.a. "
                "≈ 0,21% a.m.). Capitalizam o saldo durante a carência e compõem a parcela (Tabela "
                "Price). Se informados aqui, deixe a Correção Monetária abaixo em 0.",
            )

        gerar = st.form_submit_button("Gerar Plano de Pagamento Automático", icon=icone("precificacao"))

    if gerar:
        juros_am = Decimal(str(juros_am_percentual)) / Decimal(100)
        cronograma = gerar_cronograma(
            ParametrosFinanciamento(
                valor_financiado=valor_plano,
                valor_entrada=Decimal(0),
                taxa=juros_am,
                periodicidade_taxa=Periodicidade.MENSAL,
                periodicidade_parcela=periodicidade,
                prazo=int(parcelas),
                carencia=int(carencia),
                data_inicial=data_base,
                sistema=SistemaAmortizacao.PRICE,
                regime=RegimeJuros.COMPOSTO,
                carencia_paga_juros=False,
            )
        )
        fluxo = [
            novo_item(i, parcela.data, f"Parcela {i}", TipoFluxoItem.PARCELA, parcela.valor_parcela)
            for i, parcela in enumerate((p for p in cronograma.parcelas if not p.carencia), start=1)
        ]
        st.session_state["prec_fluxo"] = fluxo
        st.session_state.pop("prec_editor", None)


def _grafico_fluxo(resultado_vpl) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[item.data for item in resultado_vpl.fluxo_descontado],
            y=[float(item.valor) for item in resultado_vpl.fluxo_descontado],
            name="Valor Nominal",
            marker_color=CORES["grafico_indigo"],
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[item.data for item in resultado_vpl.fluxo_descontado],
            y=[
                float(item.valor_presente) if item.valor_presente is not None else 0.0
                for item in resultado_vpl.fluxo_descontado
            ],
            mode="lines+markers",
            name="Valor Presente",
            line=dict(color=CORES["destaque"], width=3),
        )
    )
    fig.update_layout(title="Fluxo Nominal x Valor Presente", xaxis_title="Data", yaxis_title="Valor (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _renderizar_resultado(resultado: ResultadoPrecificacao) -> None:
    rv = resultado.resultado_vpl
    renderizar_kpis(
        [
            ("VPL", formatar_moeda(float(rv.vpl))),
            ("TIR (a.a.)", formatar_percentual(float(rv.tir_anual)) if rv.tir_anual is not None else "-"),
            ("Payback", rv.payback_data.strftime("%d/%m/%Y") if rv.payback_data else "Não atingido"),
            (
                "Payback Descontado",
                resultado.payback_descontado_data.strftime("%d/%m/%Y") if resultado.payback_descontado_data else "Não atingido",
            ),
        ]
    )
    renderizar_kpis(
        [
            ("Duration", f"{float(resultado.duration_anos):.2f} anos" if resultado.duration_anos is not None else "-"),
            ("Ganho Líquido", formatar_moeda(float(rv.ganho_liquido))),
            ("Preço Máximo (Breakeven)", formatar_moeda(float(resultado.preco_maximo_breakeven))),
            (
                f"Preço Máximo (TIR ≥ {formatar_percentual(float(resultado.taxa_alvo_anual))})",
                formatar_moeda(float(resultado.preco_maximo_taxa_alvo)),
            ),
        ]
    )
    if rv.tir_anual is None:
        st.warning("A TIR não convergiu para este fluxo — revise os valores informados.")

    st.markdown("#### Fluxo Descontado")
    df = pd.DataFrame(
        [
            {
                "Data": item.data.strftime("%d/%m/%Y"),
                "Descrição": item.descricao,
                "Valor Nominal": formatar_moeda(float(item.valor)),
                "Valor Presente": formatar_moeda(float(item.valor_presente)) if item.valor_presente is not None else "-",
            }
            for item in rv.fluxo_descontado
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("#### Gráfico")
    with container_grafico("prec_fluxo"):
        st.plotly_chart(_grafico_fluxo(rv), width="stretch")

    st.divider()
    col_export, col_cenario = st.columns(2)
    with col_export:
        st.markdown("**Exportar**")
        sub_a, sub_b = st.columns(2)
        with sub_a:
            if st.button("Excel", key="prec_btn_excel", icon=icone("exportar"), width="stretch"):
                caminho = EXPORTADOS_DIR / "precificacao_inteligente.xlsx"
                exportar_excel_precificacao(resultado, caminho)
                st.session_state["prec_export_xlsx"] = str(caminho)
        with sub_b:
            if st.button("Word", key="prec_btn_word", icon=icone("exportar"), width="stretch"):
                caminho = EXPORTADOS_DIR / "precificacao_inteligente.docx"
                exportar_word_precificacao(resultado, caminho)
                st.session_state["prec_export_docx"] = str(caminho)

        for chave_sessao, rotulo in (("prec_export_xlsx", "Baixar Excel"), ("prec_export_docx", "Baixar Word")):
            caminho_str = st.session_state.get(chave_sessao)
            if caminho_str and Path(caminho_str).exists():
                caminho = Path(caminho_str)
                st.download_button(rotulo, caminho.read_bytes(), file_name=caminho.name, key=f"prec_download_{chave_sessao}")

    with col_cenario:
        st.markdown("**Salvar para comparação**")
        st.caption("Cenário salvo compartilha a aba Comparação de Cenários com a Simulação de Financiamento.")
        with st.form("form_salvar_cenario_prec", border=False):
            nome_cenario = st.text_input("Nome do cenário", value="Precificação de Crédito")
            if st.form_submit_button("Salvar cenário", icon=icone("comparacao")):
                salvar_cenario(nome_cenario, "vpl", rv)
                st.success(f'Cenário "{nome_cenario}" salvo. Veja a Comparação de Cenários na Simulação de Financiamento.')


def renderizar_precificacao() -> None:
    layout.renderizar_titulo_pagina("precificacao", "Precificação Inteligente de Créditos")
    st.caption("Extração automática do Plano de RJ via IA + cálculo financeiro auditável em Python")

    arquivo = st.file_uploader("Selecionar PDF do Plano de Recuperação Judicial", type=["pdf"], key="prec_uploader")
    if arquivo is not None:
        chave_cache = f"{arquivo.name}_{arquivo.size}"
        if st.session_state.get("prec_chave_cache") != chave_cache:
            if st.button("Analisar Plano com IA", type="primary", icon=icone("precificacao"), key="prec_btn_analisar"):
                extracao = _processar_plano(arquivo)
                if extracao is not None:
                    st.session_state["prec_extracao"] = extracao
                    st.session_state["prec_chave_cache"] = chave_cache
                    st.rerun()

    extracao = st.session_state.get("prec_extracao")
    if extracao is not None:
        _renderizar_extracao(extracao)
    else:
        st.info(
            'Envie o PDF do Plano de Recuperação Judicial e clique em "Analisar Plano com IA" para '
            "extrair os termos automaticamente — ou preencha os parâmetros manualmente abaixo, sem "
            "upload."
        )

    st.divider()
    dados_credito = _formulario_credito()
    if dados_credito is None:
        return
    valor_credito, valor_plano, valor_compra, desagio, data_base = dados_credito

    taxa_desconto, origem_taxa = _bloco_taxa_desconto()

    with st.expander("Correção Monetária e Taxa-Alvo (opcional)"):
        correcao_percentual = st.number_input("Correção Monetária (% a.a.)", min_value=0.0, value=0.0, step=0.5)
        taxa_alvo_percentual = st.number_input(
            "Taxa de Retorno Mínima Desejada (% a.a.) — usada no Preço Máximo Recomendado",
            min_value=0.0,
            value=float(taxa_desconto * 100) + 5.0,
            step=0.5,
        )
    correcao = Decimal(str(correcao_percentual)) / Decimal(100)
    taxa_alvo = Decimal(str(taxa_alvo_percentual)) / Decimal(100)

    st.markdown("#### Plano de Pagamento")
    _gerar_fluxo_automatico(valor_plano, data_base)

    if "prec_fluxo" not in st.session_state:
        st.info('Gere um plano automático acima ou defina um plano personalizado adicionando linhas na tabela abaixo.')
        st.session_state["prec_fluxo"] = []

    st.caption("Edite livremente as parcelas — adicione recebimentos extraordinários ou remova linhas conforme necessário.")
    fluxo_editado = editor_fluxo(st.session_state["prec_fluxo"], key="prec_editor")

    if st.button("Calcular Precificação", type="primary", icon=icone("precificacao")):
        if not fluxo_editado:
            st.error("Defina ao menos um recebimento no plano de pagamento.")
            return
        st.session_state["prec_fluxo"] = fluxo_editado
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
            resultado_vpl = calcular_resultado_vpl(parametros)
        except ValueError as exc:
            st.error(str(exc))
            return

        fluxo_tuplas = [(item.data, item.valor) for item in resultado_vpl.fluxo_descontado]
        duration = calcular_duration(fluxo_tuplas, taxa_desconto, data_base)
        fluxo_completo = [(data_base, -valor_compra), *fluxo_tuplas]
        pb_desc_data, pb_desc_meses = calcular_payback_descontado(fluxo_completo, taxa_desconto, data_base)
        preco_taxa_alvo = preco_maximo_para_taxa_alvo(fluxo_tuplas, taxa_alvo, data_base)

        extracao_atual = extracao or ExtracaoPlano(arquivo_nome="(preenchido manualmente)", data_analise=date.today())
        resultado = ResultadoPrecificacao(
            extracao=extracao_atual,
            resultado_vpl=resultado_vpl,
            duration_anos=duration,
            payback_descontado_data=pb_desc_data,
            payback_descontado_meses=pb_desc_meses,
            preco_maximo_breakeven=resultado_vpl.valor_economico,
            preco_maximo_taxa_alvo=preco_taxa_alvo,
            taxa_alvo_anual=taxa_alvo,
        )
        st.session_state["prec_resultado"] = resultado
        st.session_state.pop("prec_export_xlsx", None)
        st.session_state.pop("prec_export_docx", None)

    resultado = st.session_state.get("prec_resultado")
    if resultado is not None:
        st.divider()
        _renderizar_resultado(resultado)
