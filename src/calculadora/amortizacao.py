"""Motor de cálculo de amortização — Tabela Price, Tabela SAC e Sistema
Americano —, com conversão de taxa entre periodicidades e carência
(capitalizada ou com pagamento de juros). Funções puras — sem Streamlit, sem
estado global — toda a matemática
usa `Decimal` (nunca `float`) para evitar erro de arredondamento em valores
monetários, incluindo a exponenciação fracionária da conversão de taxa (via
`Decimal.ln()`/`Decimal.exp()`, não uma ponte por `float`).
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from src.calculadora.models import (
    ParametrosFinanciamento,
    ParcelaAmortizacao,
    Periodicidade,
    RegimeJuros,
    ResultadoFinanciamento,
    SistemaAmortizacao,
)

_CENTAVO = Decimal("0.01")


def arredondar(valor: Decimal) -> Decimal:
    """Arredonda um valor monetário para 2 casas decimais (ROUND_HALF_UP)."""
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def _ultimo_dia_mes(ano: int, mes: int) -> int:
    return calendar.monthrange(ano, mes)[1]


def adicionar_periodos(data_inicial: date, quantidade: int, periodicidade: Periodicidade) -> date:
    """Soma `quantidade` períodos (na periodicidade dada) a uma data,
    preservando o dia do mês quando possível — dia 31 num mês sem dia 31 recua
    para o último dia do mês, mesma convenção usada em planilhas financeiras.
    """
    total_meses = quantidade * periodicidade.meses
    mes_total = data_inicial.month - 1 + total_meses
    ano = data_inicial.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(data_inicial.day, _ultimo_dia_mes(ano, mes))
    return date(ano, mes, dia)


def converter_taxa(taxa: Decimal, de: Periodicidade, para: Periodicidade, regime: RegimeJuros) -> Decimal:
    """Converte uma taxa periódica (ex.: ao ano) para outra periodicidade
    (ex.: ao mês).

    - Juros compostos: equivalência de capitalização — ``(1+taxa)^(m2/m1) - 1``,
      calculado via ``ln``/``exp`` nativos de `Decimal` (sem passar por
      `float`, evitando o vazamento de precisão comum em ``Decimal(x**y)``).
    - Juros simples: proporção linear — ``taxa * (m2/m1)``.
    """
    if taxa == 0:
        return Decimal(0)
    fator_periodos = Decimal(para.meses) / Decimal(de.meses)
    if regime == RegimeJuros.COMPOSTO:
        base = Decimal(1) + taxa
        return (base.ln() * fator_periodos).exp() - 1
    return taxa * fator_periodos


def gerar_cronograma(parametros: ParametrosFinanciamento) -> ResultadoFinanciamento:
    """Gera o cronograma completo de amortização: carência (se houver) seguida
    da tabela Price, SAC ou Sistema Americano sobre o saldo remanescente.

    A última parcela sempre absorve o resíduo de arredondamento acumulado
    (padrão de mercado), garantindo que o saldo final feche exatamente em
    zero.
    """
    if parametros.prazo <= 0:
        raise ValueError("O prazo deve ser maior que zero.")
    if parametros.valor_entrada > parametros.valor_financiado:
        raise ValueError("O valor de entrada não pode ser maior que o valor financiado.")
    if parametros.valor_entrada < 0 or parametros.valor_financiado < 0:
        raise ValueError("Valores não podem ser negativos.")
    if parametros.taxa < 0:
        raise ValueError("A taxa de juros não pode ser negativa.")

    taxa_periodica = converter_taxa(
        parametros.taxa, parametros.periodicidade_taxa, parametros.periodicidade_parcela, parametros.regime
    )

    saldo = parametros.valor_financiado - parametros.valor_entrada
    parcelas: list[ParcelaAmortizacao] = []
    indice_periodo = 0

    # --- Carência: sem amortização; juros pagos ou capitalizados ao saldo ---
    principal_original = saldo
    for i in range(1, parametros.carencia + 1):
        indice_periodo += 1
        data = adicionar_periodos(parametros.data_inicial, indice_periodo, parametros.periodicidade_parcela)
        if parametros.regime == RegimeJuros.SIMPLES:
            juros = arredondar(principal_original * taxa_periodica)
        else:
            juros = arredondar(saldo * taxa_periodica)
        saldo_final = saldo if parametros.carencia_paga_juros else saldo + juros
        parcelas.append(
            ParcelaAmortizacao(
                numero=indice_periodo,
                data=data,
                saldo_inicial=saldo,
                juros=juros,
                amortizacao=Decimal(0),
                valor_parcela=juros,
                saldo_final=saldo_final,
                carencia=True,
            )
        )
        saldo = saldo_final

    # --- Amortização (Price ou SAC) -----------------------------------------
    prazo = parametros.prazo
    if parametros.sistema == SistemaAmortizacao.PRICE:
        if taxa_periodica == 0:
            pmt = arredondar(saldo / prazo)
        else:
            fator = (Decimal(1) + taxa_periodica) ** prazo
            pmt = arredondar(saldo * taxa_periodica * fator / (fator - 1))

        for i in range(1, prazo + 1):
            indice_periodo += 1
            data = adicionar_periodos(parametros.data_inicial, indice_periodo, parametros.periodicidade_parcela)
            juros = arredondar(saldo * taxa_periodica)
            if i == prazo:
                amortizacao = saldo
                valor_parcela = amortizacao + juros
            else:
                amortizacao = pmt - juros
                valor_parcela = pmt
            saldo_final = saldo - amortizacao
            parcelas.append(
                ParcelaAmortizacao(
                    numero=indice_periodo,
                    data=data,
                    saldo_inicial=saldo,
                    juros=juros,
                    amortizacao=amortizacao,
                    valor_parcela=valor_parcela,
                    saldo_final=saldo_final,
                )
            )
            saldo = saldo_final
    elif parametros.sistema == SistemaAmortizacao.SAC:
        amortizacao_fixa = arredondar(saldo / prazo)
        for i in range(1, prazo + 1):
            indice_periodo += 1
            data = adicionar_periodos(parametros.data_inicial, indice_periodo, parametros.periodicidade_parcela)
            juros = arredondar(saldo * taxa_periodica)
            amortizacao = amortizacao_fixa if i < prazo else saldo
            valor_parcela = amortizacao + juros
            saldo_final = saldo - amortizacao
            parcelas.append(
                ParcelaAmortizacao(
                    numero=indice_periodo,
                    data=data,
                    saldo_inicial=saldo,
                    juros=juros,
                    amortizacao=amortizacao,
                    valor_parcela=valor_parcela,
                    saldo_final=saldo_final,
                )
            )
            saldo = saldo_final
    else:  # Sistema Americano: só juros a cada período, principal integral na última parcela
        for i in range(1, prazo + 1):
            indice_periodo += 1
            data = adicionar_periodos(parametros.data_inicial, indice_periodo, parametros.periodicidade_parcela)
            juros = arredondar(saldo * taxa_periodica)
            if i == prazo:
                amortizacao = saldo
                valor_parcela = amortizacao + juros
            else:
                amortizacao = Decimal(0)
                valor_parcela = juros
            saldo_final = saldo - amortizacao
            parcelas.append(
                ParcelaAmortizacao(
                    numero=indice_periodo,
                    data=data,
                    saldo_inicial=saldo,
                    juros=juros,
                    amortizacao=amortizacao,
                    valor_parcela=valor_parcela,
                    saldo_final=saldo_final,
                )
            )
            saldo = saldo_final

    return ResultadoFinanciamento(parametros=parametros, taxa_periodica=taxa_periodica, parcelas=parcelas)
