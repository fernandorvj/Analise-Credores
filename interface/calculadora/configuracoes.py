"""Aba "Configurações Financeiras" — padrões aplicados às demais abas da
Calculadora nesta sessão (taxa de desconto manual padrão, regime de juros
padrão) e a documentação das metodologias de cálculo usadas.
"""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from interface.icones import icone
from src.calculadora.models import RegimeJuros


def renderizar_configuracoes() -> None:
    st.markdown("#### Padrões da Sessão")
    st.caption(
        "Esses valores são aplicados como sugestão inicial nas demais abas da Calculadora — podem "
        "ser alterados a qualquer momento em cada simulação. Válidos apenas para esta sessão do navegador "
        "(nada é gravado em banco de dados)."
    )

    taxa_atual = st.session_state.get("calc_config_taxa_manual_padrao", Decimal("0.10"))
    taxa_percentual = st.number_input(
        "Taxa de Desconto Manual Padrão (% a.a.) — usada quando a API do BACEN estiver indisponível",
        min_value=0.0,
        value=float(taxa_atual * 100),
        step=0.1,
    )
    st.session_state["calc_config_taxa_manual_padrao"] = Decimal(str(taxa_percentual)) / Decimal(100)

    regime_atual = st.session_state.get("calc_config_regime_padrao", RegimeJuros.COMPOSTO)
    regime = st.selectbox(
        "Regime de Juros Padrão",
        list(RegimeJuros),
        index=list(RegimeJuros).index(regime_atual),
        format_func=lambda r: r.value,
    )
    st.session_state["calc_config_regime_padrao"] = regime

    if st.button("Restaurar Padrões", icon=icone("atualizar")):
        st.session_state.pop("calc_config_taxa_manual_padrao", None)
        st.session_state.pop("calc_config_regime_padrao", None)
        st.rerun()

    st.divider()
    st.markdown("#### Sobre os Cálculos")
    with st.expander("Metodologia de Amortização (Price / SAC)"):
        st.markdown(
            "- **Tabela Price**: parcelas fixas (sistema francês de amortização); a última parcela "
            "absorve eventual resíduo de arredondamento.\n"
            "- **Tabela SAC**: amortização constante, parcelas decrescentes.\n"
            "- O **regime de juros** (simples/compostos) se aplica à conversão da taxa informada entre "
            "periodicidades e à capitalização de juros durante a carência — o cálculo das parcelas em "
            "si sempre segue a convenção padrão de mercado do sistema escolhido.\n"
            "- Toda a matemática usa precisão decimal exata (nunca `float`), evitando erro de "
            "arredondamento em centavos."
        )
    with st.expander("Metodologia de VPL / TIR (XNPV / XIRR)"):
        st.markdown(
            "- **VPL** e **TIR** seguem a metodologia XNPV/XIRR — a mesma convenção usada por planilhas "
            "financeiras (Excel/Google Sheets) para fluxos de caixa com datas irregulares, descontados "
            "numa base de 365 dias por ano.\n"
            "- **Valor Econômico**: valor presente apenas dos recebimentos esperados.\n"
            "- **VPL**: Valor Econômico menos o Valor de Compra.\n"
            "- **Taxa Efetiva**: por definição financeira, é a própria TIR anualizada da operação.\n"
            "- **ROI**: retorno nominal (sem desconto) sobre o capital investido.\n"
            "- **Rentabilidade**: VPL sobre o capital investido, em valor presente.\n"
            "- **Margem**: VPL sobre o Valor Econômico do crédito.\n"
            "- **Spread**: Taxa Efetiva menos a Taxa de Desconto (SELIC) — o prêmio de retorno sobre a "
            "taxa livre de risco."
        )
    with st.expander("Taxa Selic (fonte)"):
        st.markdown(
            "A taxa de desconto padrão é a **Meta Selic** definida pelo Copom, consultada na API pública "
            "do Banco Central (SGS, série 432). Quando a API está indisponível, a calculadora permite — "
            "e nunca impede — a edição manual da taxa, sempre exibindo a origem do valor usado no relatório."
        )
