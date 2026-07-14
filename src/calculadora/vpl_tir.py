"""Indicadores de retorno para a Calculadora de VPL — VPL (XNPV), TIR (XIRR),
Payback, Payback Descontado, Duration (Macaulay), ROI, rentabilidade, valor
econômico, margem e spread.

Usa a metodologia XNPV/XIRR (fluxos de caixa com datas irregulares, base de
365 dias/ano) — a mesma convenção usada por planilhas financeiras como
Excel/Google Sheets (`XNPV`/`XIRR`), mais adequada que um NPV de período fixo
quando os recebimentos não são uniformemente espaçados (parcelas, balão,
pagamentos extraordinários). Funções puras — sem Streamlit, sem estado
global; toda a matemática usa `Decimal`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.calculadora.amortizacao import arredondar
from src.calculadora.models import FluxoItem, ParametrosVPL, ResultadoVPL, TipoFluxoItem

_DIAS_ANO = Decimal(365)
_TOLERANCIA_TIR = Decimal("0.0000001")
_MAX_ITERACOES_NEWTON = 60


def xnpv(fluxo: list[tuple[date, Decimal]], taxa_anual: Decimal, data_base: date) -> Decimal:
    """Valor presente líquido de um fluxo de datas irregulares, descontado a
    `taxa_anual` a partir de `data_base` (metodologia XNPV: dias corridos/365).
    """
    if taxa_anual <= -1:
        raise ValueError("A taxa de desconto não pode ser menor ou igual a -100%.")
    total = Decimal(0)
    base = Decimal(1) + taxa_anual
    ln_base = base.ln()
    for data_item, valor in fluxo:
        dias = Decimal((data_item - data_base).days)
        expoente = dias / _DIAS_ANO
        fator = (ln_base * expoente).exp()
        total += valor / fator
    return total


def xirr(fluxo: list[tuple[date, Decimal]], data_base: date, chute_inicial: Decimal = Decimal("0.15")) -> Decimal | None:
    """Taxa anual que zera o XNPV do fluxo (XIRR), por Newton-Raphson com
    fallback por bisseção. Retorna `None` se o fluxo não tiver mudança de
    sinal (nenhuma saída ou nenhuma entrada) ou se não convergir — nunca
    inventa uma taxa.
    """
    valores = [v for _, v in fluxo]
    if not valores or all(v <= 0 for v in valores) or all(v >= 0 for v in valores):
        return None

    taxa = chute_inicial
    delta = Decimal("0.0001")
    for _ in range(_MAX_ITERACOES_NEWTON):
        try:
            valor = xnpv(fluxo, taxa, data_base)
            valor_delta = xnpv(fluxo, taxa + delta, data_base)
        except (ValueError, OverflowError):
            break
        derivada = (valor_delta - valor) / delta
        if derivada == 0:
            break
        nova_taxa = taxa - valor / derivada
        if nova_taxa <= Decimal("-0.999"):
            nova_taxa = (taxa + Decimal("-0.9")) / 2
        if abs(nova_taxa - taxa) < _TOLERANCIA_TIR:
            return nova_taxa
        taxa = nova_taxa

    return _xirr_bisseccao(fluxo, data_base)


def _xirr_bisseccao(
    fluxo: list[tuple[date, Decimal]], data_base: date, baixo: Decimal = Decimal("-0.99"), alto: Decimal = Decimal("50")
) -> Decimal | None:
    """Fallback robusto quando Newton-Raphson não converge: bisseção num
    intervalo amplo de taxas plausíveis (-99% a +5000% a.a.).
    """
    try:
        f_baixo = xnpv(fluxo, baixo, data_base)
        f_alto = xnpv(fluxo, alto, data_base)
    except (ValueError, OverflowError):
        return None
    if f_baixo * f_alto > 0:
        return None
    for _ in range(200):
        meio = (baixo + alto) / 2
        f_meio = xnpv(fluxo, meio, data_base)
        if abs(f_meio) < Decimal("0.01"):
            return meio
        if (f_baixo * f_meio) < 0:
            alto, f_alto = meio, f_meio
        else:
            baixo, f_baixo = meio, f_meio
    return (baixo + alto) / 2


def preco_maximo_para_taxa_alvo(fluxo: list[tuple[date, Decimal]], taxa_alvo_anual: Decimal, data_base: date) -> Decimal:
    """Preço máximo de aquisição para atingir exatamente `taxa_alvo_anual` de
    TIR na operação (usado como "Preço Máximo Recomendado" na Precificação
    Inteligente de Créditos).

    Por definição de TIR (a taxa que zera o VPL do fluxo completo
    ``-preço + XNPV(fluxo, taxa)``), o preço de equilíbrio para uma taxa-alvo
    é o próprio XNPV do fluxo de recebimentos descontado a essa taxa — pagar
    mais do que isso reduz o retorno da operação abaixo do alvo.
    """
    return xnpv(fluxo, taxa_alvo_anual, data_base)


def calcular_payback(fluxo: list[tuple[date, Decimal]], data_base: date) -> tuple[date | None, float | None]:
    """Payback simples (sem desconto): primeira data em que o saldo acumulado
    do fluxo (a partir de `data_base`) deixa de ser negativo, e o número
    aproximado de meses corridos até lá. Retorna (None, None) se o fluxo
    nunca zera o investimento inicial.
    """
    acumulado = Decimal(0)
    for data_item, valor in sorted(fluxo, key=lambda item: item[0]):
        acumulado += valor
        if acumulado >= 0:
            dias = (data_item - data_base).days
            return data_item, float(dias) / 30.0
    return None, None


def calcular_payback_descontado(
    fluxo: list[tuple[date, Decimal]], taxa_anual: Decimal, data_base: date
) -> tuple[date | None, float | None]:
    """Payback descontado: primeira data em que a soma dos valores do fluxo já
    trazidos a valor presente (a partir de `data_base`, à `taxa_anual`) deixa
    de ser negativa. Mais conservador que `calcular_payback` (nominal) por
    incorporar o custo de oportunidade do capital. Retorna (None, None) se o
    fluxo nunca zera o investimento inicial em valor presente.
    """
    acumulado = Decimal(0)
    base = Decimal(1) + taxa_anual
    ln_base = base.ln() if base > 0 else None
    for data_item, valor in sorted(fluxo, key=lambda item: item[0]):
        if ln_base is not None:
            dias = Decimal((data_item - data_base).days)
            fator = (ln_base * (dias / _DIAS_ANO)).exp()
            valor_descontado = valor / fator
        else:
            valor_descontado = valor
        acumulado += valor_descontado
        if acumulado >= 0:
            dias_total = (data_item - data_base).days
            return data_item, float(dias_total) / 30.0
    return None, None


def calcular_duration(fluxo: list[tuple[date, Decimal]], taxa_anual: Decimal, data_base: date) -> Decimal | None:
    """Duration de Macaulay: prazo médio (em anos) dos recebimentos de um
    fluxo, ponderado pelo valor presente de cada parcela — mede o "prazo
    médio financeiro" do fluxo e a sensibilidade do seu valor presente a
    variações na taxa de desconto. Considera apenas os valores POSITIVOS do
    fluxo (recebimentos); retorna `None` se não houver nenhum recebimento.

    Fórmula: ``Duration = Σ(tᵢ · VPᵢ) / Σ(VPᵢ)``, com ``tᵢ`` em anos
    (dias corridos / 365) e ``VPᵢ`` o valor presente de cada recebimento.
    """
    if taxa_anual <= -1:
        raise ValueError("A taxa de desconto não pode ser menor ou igual a -100%.")
    base = Decimal(1) + taxa_anual
    ln_base = base.ln()
    soma_vp = Decimal(0)
    soma_vp_tempo = Decimal(0)
    for data_item, valor in fluxo:
        if valor <= 0:
            continue
        dias = Decimal((data_item - data_base).days)
        tempo_anos = dias / _DIAS_ANO
        fator = (ln_base * tempo_anos).exp()
        valor_presente = valor / fator
        soma_vp += valor_presente
        soma_vp_tempo += valor_presente * tempo_anos
    if soma_vp == 0:
        return None
    return soma_vp_tempo / soma_vp


def calcular_resultado_vpl(parametros: ParametrosVPL) -> ResultadoVPL:
    """Orquestra o cálculo completo da Calculadora de VPL a partir do fluxo de
    recebimentos esperados e do valor de compra do crédito.

    Definições usadas (documentadas para auditoria):
    - **Valor Futuro**: soma nominal (sem desconto) de todos os recebimentos.
    - **Valor Econômico / VPL**: valor presente (XNPV) dos recebimentos que o
      plano de RJ efetivamente paga pelo crédito (fluxo já pós-deságio do
      plano) — quanto o direito creditório vale hoje. O deságio aqui é o
      haircut imposto pelo plano ao crédito, não o desconto de compra; por
      isso o VPL exibido é o próprio valor presente do fluxo, sem subtrair o
      Valor de Compra (mesma convenção da planilha de referência).
    - **Ganho Líquido**: Valor Econômico menos o Valor de Compra — o ganho em
      valor presente caso o crédito seja adquirido pelo Valor de Compra
      informado.
    - **TIR / Taxa Efetiva**: a mesma taxa (XIRR) do fluxo completo
      (-valor_compra na data_base seguido dos recebimentos) — a "taxa
      efetiva" da operação é, por definição financeira, a sua TIR anualizada;
      exibida sob os dois rótulos pedidos porque ambos aparecem no relatório.
    - **ROI**: (Valor Futuro − Valor de Compra) / Valor de Compra — retorno
      nominal sobre o capital investido, sem considerar o tempo.
    - **Rentabilidade**: Ganho Líquido / Valor de Compra — retorno líquido em
      valor presente sobre o capital investido.
    - **Margem**: Ganho Líquido / Valor Econômico — parcela do valor econômico
      do crédito que corresponde a ganho líquido da operação.
    - **Spread**: Taxa Efetiva anual − Taxa de Desconto anual (SELIC) — o
      prêmio de retorno da operação sobre a taxa livre de risco.
    """
    if parametros.valor_compra <= 0:
        raise ValueError("O valor de compra deve ser maior que zero.")

    correcao = Decimal(1) + parametros.correcao_monetaria_anual
    ln_correcao = correcao.ln() if correcao > 0 else None

    fluxo_corrigido: list[tuple[date, Decimal]] = []
    for item in parametros.fluxo_recebimentos:
        valor = item.valor
        if ln_correcao is not None and parametros.correcao_monetaria_anual != 0:
            dias = Decimal((item.data - parametros.data_base).days)
            valor = valor * (ln_correcao * (dias / _DIAS_ANO)).exp()
        fluxo_corrigido.append((item.data, valor))

    valor_futuro = sum((v for _, v in fluxo_corrigido), Decimal(0))
    valor_economico = arredondar(xnpv(fluxo_corrigido, parametros.taxa_desconto_anual, parametros.data_base))
    vpl = valor_economico
    ganho_liquido = arredondar(valor_economico - parametros.valor_compra)

    fluxo_completo = [(parametros.data_base, -parametros.valor_compra), *fluxo_corrigido]
    tir_anual = xirr(fluxo_completo, parametros.data_base)
    taxa_efetiva_anual = tir_anual

    payback_data, payback_meses = calcular_payback(fluxo_completo, parametros.data_base)

    roi = (valor_futuro - parametros.valor_compra) / parametros.valor_compra
    rentabilidade = ganho_liquido / parametros.valor_compra
    margem = (ganho_liquido / valor_economico) if valor_economico != 0 else None
    spread = (taxa_efetiva_anual - parametros.taxa_desconto_anual) if taxa_efetiva_anual is not None else None

    fluxo_descontado: list[FluxoItem] = []
    for item, (_, valor_corrigido) in zip(parametros.fluxo_recebimentos, fluxo_corrigido):
        dias = Decimal((item.data - parametros.data_base).days)
        vp = arredondar(xnpv([(item.data, valor_corrigido)], parametros.taxa_desconto_anual, parametros.data_base))
        fluxo_descontado.append(
            FluxoItem(
                id=item.id,
                data=item.data,
                descricao=item.descricao,
                tipo=item.tipo,
                valor=arredondar(valor_corrigido),
                editavel=item.editavel,
                valor_presente=vp,
            )
        )

    return ResultadoVPL(
        parametros=parametros,
        vpl=vpl,
        ganho_liquido=ganho_liquido,
        valor_futuro=arredondar(valor_futuro),
        valor_economico=valor_economico,
        tir_anual=tir_anual,
        taxa_efetiva_anual=taxa_efetiva_anual,
        payback_data=payback_data,
        payback_meses=payback_meses,
        roi=roi,
        rentabilidade=rentabilidade,
        margem=margem,
        spread=spread,
        fluxo_descontado=fluxo_descontado,
    )
