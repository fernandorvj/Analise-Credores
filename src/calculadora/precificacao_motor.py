"""Motor de cálculo da Precificação Inteligente de Créditos — 100% Python,
determinístico e auditável. A IA nunca participa deste módulo; todos os
parâmetros de entrada aqui já são números confirmados pelo usuário (ver
`interface/precificacao.py`), nunca texto livre da extração.

*** METODOLOGIA PROVISÓRIA — PENDENTE DE VALIDAÇÃO ***
O desconto a valor presente usa XNPV (dias corridos/365) — a mesma
convenção já validada nesta plataforma para VPL/TIR de fluxos irregulares
(Excel/Google Sheets), reaproveitando `src/calculadora/vpl_tir.py`. Esta
metodologia ainda NÃO foi comparada com a planilha oficial de cálculo de
VPL da AMF3 Capital. `ResultadoPrecificacaoClasse.metodologia_validada`
permanece `False` em todo resultado até essa comparação ser feita e a
convergência confirmada dentro de uma tolerância definida — a interface
deve sempre exibir esse aviso enquanto o campo estiver `False`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.calculadora.amortizacao import adicionar_periodos, arredondar, gerar_cronograma
from src.calculadora.models import ParametrosFinanciamento, Periodicidade, RegimeJuros, SistemaAmortizacao
from src.calculadora.vpl_tir import xnpv
from src.models_precificacao import CondicoesPagamentoClasse, ParcelaPrecificacao, ResultadoPrecificacaoClasse
from src.utils import formatar_moeda, formatar_percentual

_DIAS_ANO = Decimal(365)

_INDICES_SEM_CORRECAO = {"", "nenhum", "não localizado"}


@dataclass
class ParametrosCalculoClasse:
    """Parâmetros numéricos já confirmados pelo usuário (a partir da
    extração da IA, revisados na tela de confirmação) para o cálculo de
    VPL de uma classe — nunca texto livre.
    """

    classe: str
    valor_nominal_credito: Decimal
    desagio: Decimal  # fração, ex.: 0.60 = 60%
    carencia_periodos: int
    correcao_indice: str  # "Nenhum" | "IPCA" | "CDI" | "IGP-M" | "TR" | outro texto livre
    correcao_taxa_anual: Decimal  # fração, já resolvida (API ou manual) — 0 se sem correção
    juros: Decimal  # fração, por período (mesma periodicidade das parcelas)
    numero_parcelas: int
    periodicidade: Periodicidade
    data_primeira_parcela: date
    data_base: date  # data de referência da análise ("hoje")
    valor_balao: Decimal  # 0 se não houver parcela balão
    periodo_balao: int  # nº da parcela em que o balão ocorre; 0 se não houver
    taxa_desconto_anual: Decimal
    origem_taxa_desconto: str
    data_taxa_desconto: date | None
    condicoes: CondicoesPagamentoClasse


def calcular_precificacao_classe(parametros: ParametrosCalculoClasse) -> ResultadoPrecificacaoClasse:
    """Constrói o fluxo de pagamento da classe a partir das condições do
    Plano e calcula o VPL — toda a matemática auditável via
    `ResultadoPrecificacaoClasse.memoria_calculo`.
    """
    if parametros.numero_parcelas <= 0:
        raise ValueError("O número de parcelas deve ser maior que zero.")
    if parametros.valor_nominal_credito <= 0:
        raise ValueError("O valor nominal do crédito deve ser maior que zero.")
    if parametros.desagio < 0 or parametros.desagio >= 1:
        raise ValueError("O deságio deve estar entre 0% e 100% (exclusive).")

    memoria: list[str] = []

    valor_pos_desagio = arredondar(parametros.valor_nominal_credito * (Decimal(1) - parametros.desagio))
    memoria.append(
        f"Valor pós-deságio = {formatar_moeda(float(parametros.valor_nominal_credito))} × "
        f"(1 − {formatar_percentual(float(parametros.desagio))}) = {formatar_moeda(float(valor_pos_desagio))}"
    )

    # A 1ª parcela regular deve cair exatamente em `data_primeira_parcela`; o
    # cronograma (que sempre soma períodos a partir de `data_inicial`) recebe
    # uma data-base deslocada para trás pelos períodos de carência + 1.
    data_inicial_cronograma = adicionar_periodos(
        parametros.data_primeira_parcela, -(parametros.carencia_periodos + 1), parametros.periodicidade
    )
    memoria.append(
        f"Data-base do cronograma: {data_inicial_cronograma} (para a 1ª parcela cair em "
        f"{parametros.data_primeira_parcela}, após {parametros.carencia_periodos} período(s) de carência)."
    )

    resultado_amortizacao = gerar_cronograma(
        ParametrosFinanciamento(
            valor_financiado=valor_pos_desagio,
            valor_entrada=Decimal(0),
            taxa=parametros.juros,
            periodicidade_taxa=parametros.periodicidade,
            periodicidade_parcela=parametros.periodicidade,
            prazo=parametros.numero_parcelas,
            carencia=parametros.carencia_periodos,
            data_inicial=data_inicial_cronograma,
            sistema=SistemaAmortizacao.PRICE,
            regime=RegimeJuros.COMPOSTO,
            carencia_paga_juros=False,
        )
    )
    memoria.append(
        f"Cronograma Tabela Price: {parametros.numero_parcelas} parcela(s) a "
        f"{formatar_percentual(float(parametros.juros))} por {parametros.periodicidade.value.lower()}, juros "
        "compostos (convenção padrão de mercado para amortização com parcelas fixas)."
    )

    aplica_correcao = parametros.correcao_indice.strip().lower() not in _INDICES_SEM_CORRECAO and parametros.correcao_taxa_anual != 0
    ln_correcao = (Decimal(1) + parametros.correcao_taxa_anual).ln() if aplica_correcao else None

    fluxo: list[ParcelaPrecificacao] = []
    for parcela in resultado_amortizacao.parcelas:
        if parcela.carencia:
            continue  # carência não gera pagamento ao credor, só capitaliza juros ao saldo
        valor_nominal = parcela.valor_parcela
        if ln_correcao is not None:
            dias = Decimal((parcela.data - parametros.data_base).days)
            fator_correcao = (ln_correcao * (dias / _DIAS_ANO)).exp()
            valor_nominal = arredondar(valor_nominal * fator_correcao)
        fluxo.append(
            ParcelaPrecificacao(
                numero=parcela.numero,
                data=parcela.data,
                descricao=f"Parcela {parcela.numero}",
                valor_nominal=valor_nominal,
                valor_descontado=Decimal(0),  # preenchido abaixo, após o fluxo completo estar montado
            )
        )

    if aplica_correcao:
        memoria.append(
            f"Correção monetária por {parametros.correcao_indice} a "
            f"{formatar_percentual(float(parametros.correcao_taxa_anual))} a.a. aplicada como fator composto "
            "sobre o valor nominal de cada parcela, proporcional ao tempo decorrido desde a data-base da análise."
        )

    if parametros.valor_balao > 0 and parametros.periodo_balao > 0:
        parcela_referencia = next((p for p in fluxo if p.numero == parametros.periodo_balao), None)
        data_balao = (
            parcela_referencia.data
            if parcela_referencia is not None
            else adicionar_periodos(data_inicial_cronograma, parametros.periodo_balao, parametros.periodicidade)
        )
        fluxo.append(
            ParcelaPrecificacao(
                numero=parametros.periodo_balao,
                data=data_balao,
                descricao="Parcela Balão",
                valor_nominal=parametros.valor_balao,
                valor_descontado=Decimal(0),
            )
        )
        memoria.append(
            f"Parcela balão de {formatar_moeda(float(parametros.valor_balao))} adicionada como pagamento "
            f"extraordinário em {data_balao.strftime('%d/%m/%Y')} (nº {parametros.periodo_balao}) — somada ao "
            "fluxo sem recalcular a amortização das demais parcelas; revisar manualmente se o Plano prevê "
            "redução das parcelas subsequentes em função do balão."
        )

    fluxo.sort(key=lambda item: (item.data, item.numero))

    for item in fluxo:
        item.valor_descontado = arredondar(
            xnpv([(item.data, item.valor_nominal)], parametros.taxa_desconto_anual, parametros.data_base)
        )

    vpl = arredondar(sum((item.valor_descontado for item in fluxo), Decimal(0)))
    memoria.append(
        f"VPL = soma do valor presente de todas as parcelas, descontadas a "
        f"{formatar_percentual(float(parametros.taxa_desconto_anual))} a.a. ({parametros.origem_taxa_desconto}) "
        f"pela metodologia XNPV (dias corridos/365) = {formatar_moeda(float(vpl))}"
    )
    memoria.append(
        "*** Metodologia provisória, ainda não comparada com a planilha oficial de cálculo de VPL "
        "da AMF3 Capital — ver aviso na interface. ***"
    )

    return ResultadoPrecificacaoClasse(
        classe=parametros.classe,
        valor_nominal_credito=parametros.valor_nominal_credito,
        # Sem uma data de referência original do crédito informada nesta tela
        # simplificada (só valor nominal + classe), não há base para calcular
        # um "valor atualizado" distinto do valor nominal — permanece None.
        valor_atualizado_credito=None,
        condicoes=parametros.condicoes,
        taxa_desconto_anual=parametros.taxa_desconto_anual,
        origem_taxa_desconto=parametros.origem_taxa_desconto,
        data_taxa_desconto=parametros.data_taxa_desconto,
        fluxo=fluxo,
        vpl=vpl,
        memoria_calculo=memoria,
        metodologia_validada=False,
    )
