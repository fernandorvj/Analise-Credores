"""Motor de cálculo da Precificação Inteligente de Créditos — 100% Python,
determinístico e auditável. A IA nunca participa deste módulo; todos os
parâmetros de entrada aqui já são números confirmados pelo usuário (ver
`interface/precificacao.py`), nunca texto livre da extração.

Metodologia (especificação de cálculo de VPL de créditos em Planos de
Recuperação Judicial fornecida pela AMF3 Capital):

1. **Cronograma unificado**: o número total de linhas é sempre
   ``carência + número de parcelas`` — a carência entra na tabela como
   linhas próprias (sem pagamento ao credor), não é descontada à parte.
2. **Juros sobre o saldo**: em toda linha, os juros incidem sobre o saldo
   devedor do período ANTERIOR — nunca sobre o valor da parcela isolada.
   Durante a carência, os juros do período capitalizam ao saldo (não são
   pagos ao credor).
3. **Amortização integral**: a soma de todas as parcelas amortiza 100% do
   saldo pós-deságio (a última parcela absorve o resíduo de arredondamento
   — mesma convenção já usada no restante da Calculadora).
4. **Casamento de período**: a taxa de juros do plano e a taxa de desconto
   do VPL (SELIC ou manual) são sempre convertidas para a MESMA
   periodicidade das parcelas ("molde") antes de qualquer cálculo — nunca
   se mistura taxa anual com período mensal, ou vice-versa.
5. **Descapitalização linha por linha**: ``VP_t = FluxoTotal_t / (1 +
   i_desconto)^t``, onde ``t`` é o número sequencial da linha cronológica
   (1..N, contando também as linhas de carência, cujo FluxoTotal é zero) e
   ``i_desconto`` é a taxa de desconto já convertida para a periodicidade
   das parcelas — a mesma fórmula de VPL discreto (Excel `NPV`), e não uma
   descapitalização por dias corridos (XNPV).
6. **Resultados**: Fluxo Nominal Total (soma de tudo o que é pago),
   Valor Presente do Fluxo — VP Total (soma de todos os VP_t), VPL Real
   Comercial (VP Total − Crédito Original) e Percentual de Recuperação
   Efetiva (VP Total / Crédito Original).

Esta metodologia substitui a versão anterior (XNPV por dias corridos) e
segue à risca a especificação fornecida pela AMF3 Capital — ainda sujeita
à validação final contra a planilha oficial de referência, quando
disponibilizada (`ResultadoPrecificacaoClasse.metodologia_validada`
permanece `False` até essa confirmação).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.calculadora.amortizacao import adicionar_periodos, arredondar, converter_taxa, gerar_cronograma
from src.calculadora.models import ParametrosFinanciamento, Periodicidade, RegimeJuros, SistemaAmortizacao
from src.models_precificacao import CondicoesPagamentoClasse, ParcelaPrecificacao, ResultadoPrecificacaoClasse
from src.utils import formatar_moeda, formatar_percentual

_INDICES_SEM_CORRECAO = {"", "nenhum", "não localizado"}


@dataclass
class ParametrosCalculoClasse:
    """Parâmetros numéricos já confirmados pelo usuário (a partir da
    extração da IA, revisados na tela de confirmação) para o cálculo de
    VPL de uma classe — nunca texto livre.
    """

    classe: str
    valor_nominal_credito: Decimal  # Crédito Original (C0)
    desagio: Decimal  # fração, ex.: 0.60 = 60%
    carencia_periodos: int
    correcao_indice: str  # "Nenhum" | "IPCA" | "CDI" | "IGP-M" | "TR" | outro texto livre
    correcao_taxa_anual: Decimal  # fração, já resolvida (API ou manual) — 0 se sem correção
    juros: Decimal  # fração, já na periodicidade de `periodicidade` (conversão feita na interface)
    numero_parcelas: int
    periodicidade: Periodicidade  # "molde": periodicidade das parcelas, dos juros e do desconto
    data_primeira_parcela: date
    data_base: date  # data de referência da análise ("hoje")
    valor_balao: Decimal  # 0 se não houver parcela balão
    periodo_balao: int  # nº da parcela em que o balão ocorre; 0 se não houver
    taxa_desconto_anual: Decimal  # taxa de desconto na origem (SELIC ou manual, sempre a.a.)
    origem_taxa_desconto: str
    data_taxa_desconto: date | None
    condicoes: CondicoesPagamentoClasse


def calcular_precificacao_classe(parametros: ParametrosCalculoClasse) -> ResultadoPrecificacaoClasse:
    """Constrói o cronograma unificado da classe (carência + parcelas) e
    calcula o VPL pela descapitalização linha por linha — toda a matemática
    auditável via `ResultadoPrecificacaoClasse.memoria_calculo`.
    """
    if parametros.numero_parcelas <= 0:
        raise ValueError("O número de parcelas deve ser maior que zero.")
    if parametros.valor_nominal_credito <= 0:
        raise ValueError("O valor nominal do crédito deve ser maior que zero.")
    if parametros.desagio < 0 or parametros.desagio >= 1:
        raise ValueError("O deságio deve estar entre 0% e 100% (exclusive).")

    memoria: list[str] = []

    # --- 1) Saldo pós-deságio -------------------------------------------------
    valor_pos_desagio = arredondar(parametros.valor_nominal_credito * (Decimal(1) - parametros.desagio))
    memoria.append(
        f"Crédito Original (C0) = {formatar_moeda(float(parametros.valor_nominal_credito))}. Saldo pós-deságio "
        f"= C0 × (1 − {formatar_percentual(float(parametros.desagio))}) = {formatar_moeda(float(valor_pos_desagio))}."
    )

    # --- 2) Casamento de período: taxa de desconto convertida para o molde ---
    taxa_desconto_periodo = converter_taxa(
        parametros.taxa_desconto_anual, Periodicidade.ANUAL, parametros.periodicidade, RegimeJuros.COMPOSTO
    )
    memoria.append(
        f"Casamento de período: taxa de desconto ({formatar_percentual(float(parametros.taxa_desconto_anual))} "
        f"a.a., {parametros.origem_taxa_desconto}) convertida para "
        f"{formatar_percentual(float(taxa_desconto_periodo))} por {parametros.periodicidade.value.lower()} — a "
        "mesma periodicidade dos juros do plano e das parcelas, nunca se mistura taxa anual com período mensal "
        "(ou vice-versa)."
    )

    # --- 3) Cronograma unificado: carência (juros capitalizam) + parcelas ----
    # A 1ª parcela regular deve cair exatamente em `data_primeira_parcela`; o
    # cronograma soma períodos a partir de `data_inicial`, então recebe uma
    # data-base deslocada para trás pelos períodos de carência + 1.
    data_inicial_cronograma = adicionar_periodos(
        parametros.data_primeira_parcela, -(parametros.carencia_periodos + 1), parametros.periodicidade
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
            carencia_paga_juros=False,  # juros rodam e capitalizam ao saldo durante a carência
        )
    )
    total_linhas = parametros.carencia_periodos + parametros.numero_parcelas
    memoria.append(
        f"Cronograma unificado: {parametros.carencia_periodos} período(s) de carência (juros capitalizam ao "
        f"saldo devedor, sem pagamento ao credor) + {parametros.numero_parcelas} parcela(s) pela Tabela Price a "
        f"{formatar_percentual(float(parametros.juros))} por {parametros.periodicidade.value.lower()} = "
        f"{total_linhas} linha(s) cronológicas. Em toda linha, os juros incidem sobre o saldo devedor do "
        "período anterior — nunca sobre o valor da parcela isolada. A amortização das parcelas soma 100% do "
        "saldo pós-deságio (a última parcela absorve o resíduo de arredondamento)."
    )

    aplica_correcao = (
        parametros.correcao_indice.strip().lower() not in _INDICES_SEM_CORRECAO and parametros.correcao_taxa_anual != 0
    )
    correcao_periodo = (
        converter_taxa(parametros.correcao_taxa_anual, Periodicidade.ANUAL, parametros.periodicidade, RegimeJuros.COMPOSTO)
        if aplica_correcao
        else Decimal(0)
    )

    # --- 4) Monta todas as linhas (inclusive carência, para auditoria) -------
    fluxo: list[ParcelaPrecificacao] = []
    for parcela in resultado_amortizacao.parcelas:
        valor_nominal = Decimal(0) if parcela.carencia else parcela.valor_parcela
        if aplica_correcao and not parcela.carencia:
            valor_nominal = arredondar(valor_nominal * (Decimal(1) + correcao_periodo) ** parcela.numero)
        fluxo.append(
            ParcelaPrecificacao(
                numero=parcela.numero,
                data=parcela.data,
                descricao="Carência" if parcela.carencia else f"Parcela {parcela.numero}",
                carencia=parcela.carencia,
                saldo_inicial=parcela.saldo_inicial,
                juros_periodo=parcela.juros,
                amortizacao=parcela.amortizacao,
                valor_nominal=valor_nominal,
                saldo_final=parcela.saldo_final,
                valor_descontado=Decimal(0),  # preenchido no passo 5, após o fluxo completo estar montado
            )
        )

    if aplica_correcao:
        memoria.append(
            f"Correção monetária por {parametros.correcao_indice} a "
            f"{formatar_percentual(float(parametros.correcao_taxa_anual))} a.a. "
            f"({formatar_percentual(float(correcao_periodo))} por {parametros.periodicidade.value.lower()}) "
            "aplicada como fator composto sobre o valor nominal de cada parcela paga, proporcional ao número "
            "de períodos decorridos."
        )

    if parametros.valor_balao > 0 and parametros.periodo_balao > 0:
        parcela_referencia = next((p for p in fluxo if p.numero == parametros.periodo_balao), None)
        if parcela_referencia is not None:
            parcela_referencia.valor_nominal += parametros.valor_balao
            memoria.append(
                f"Parcela balão de {formatar_moeda(float(parametros.valor_balao))} somada à parcela nº "
                f"{parametros.periodo_balao} ({parcela_referencia.data.strftime('%d/%m/%Y')}) — revisar "
                "manualmente se o Plano prevê redução das parcelas subsequentes em função do balão."
            )

    # --- 5) Descapitalização linha por linha: VP_t = FluxoTotal_t / (1+i)^t --
    for item in fluxo:
        item.valor_descontado = arredondar(item.valor_nominal / ((Decimal(1) + taxa_desconto_periodo) ** item.numero))

    fluxo_nominal_total = arredondar(sum((item.valor_nominal for item in fluxo), Decimal(0)))
    vp_total = arredondar(sum((item.valor_descontado for item in fluxo), Decimal(0)))
    vpl_comercial = arredondar(vp_total - parametros.valor_nominal_credito)
    percentual_recuperacao = (
        (vp_total / parametros.valor_nominal_credito) * 100 if parametros.valor_nominal_credito != 0 else Decimal(0)
    )

    memoria.append(
        f"Fluxo Nominal Total (soma de amortização + juros pagos em todas as parcelas) = "
        f"{formatar_moeda(float(fluxo_nominal_total))}."
    )
    memoria.append(
        "Valor Presente do Fluxo (VP Total) = soma do VP de cada linha, "
        f"VP_t = Fluxo Total da linha / (1 + {formatar_percentual(float(taxa_desconto_periodo))})^t "
        f"= {formatar_moeda(float(vp_total))}."
    )
    memoria.append(
        f"VPL Real Comercial = VP Total − Crédito Original = {formatar_moeda(float(vp_total))} − "
        f"{formatar_moeda(float(parametros.valor_nominal_credito))} = {formatar_moeda(float(vpl_comercial))}."
    )
    memoria.append(
        "Percentual de Recuperação Efetiva = VP Total / Crédito Original = "
        f"{formatar_percentual(float(percentual_recuperacao) / 100)}."
    )
    memoria.append(
        "*** Metodologia de cronograma unificado, casamento de período e descapitalização linha por linha "
        "fornecida pela AMF3 Capital — ainda sujeita à validação final contra a planilha oficial de "
        "referência, quando disponibilizada. ***"
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
        taxa_desconto_periodo=taxa_desconto_periodo,
        origem_taxa_desconto=parametros.origem_taxa_desconto,
        data_taxa_desconto=parametros.data_taxa_desconto,
        fluxo=fluxo,
        fluxo_nominal_total=fluxo_nominal_total,
        vp_total=vp_total,
        vpl_comercial=vpl_comercial,
        percentual_recuperacao_efetiva=percentual_recuperacao,
        memoria_calculo=memoria,
        metodologia_validada=False,
    )


@dataclass
class LinhaFluxoInformado:
    """Uma linha de uma projeção de fluxo de pagamentos já pronta no Plano de
    RJ (ver `src.models_precificacao.ProjecaoFluxoAnualClasse`) — o valor já
    é o fluxo final a receber naquele período, não algo a recalcular."""

    data: date
    descricao: str
    valor: Decimal


@dataclass
class ParametrosCalculoClasseComProjecao:
    """Parâmetros para calcular o VPL de uma classe a partir de uma projeção
    de fluxo já pronta no Plano de RJ, em vez de gerar um cronograma
    Price/SAC — usado quando o próprio documento já traz uma tabela de
    "Valor a Pagar" por período. Só a descapitalização linha a linha
    (mesma fórmula VP_t de `calcular_precificacao_classe`) é aplicada.
    """

    classe: str
    valor_nominal_credito: Decimal  # Crédito Original (C0)
    linhas: list[LinhaFluxoInformado]  # em ordem cronológica
    periodicidade: Periodicidade  # só para o casamento de período da taxa de desconto
    taxa_desconto_anual: Decimal
    origem_taxa_desconto: str
    data_taxa_desconto: date | None
    condicoes: CondicoesPagamentoClasse


def calcular_precificacao_classe_com_projecao(
    parametros: ParametrosCalculoClasseComProjecao,
) -> ResultadoPrecificacaoClasse:
    """Calcula o VPL de uma classe a partir de uma projeção de fluxo já
    pronta no Plano de RJ — cada linha já é o valor final a receber naquele
    período (pós-deságio, já calculado pelo próprio Plano); não há
    cronograma a gerar, só a descapitalização VP_t = Valor / (1+i)^t de cada
    linha informada, na mesma convenção de `calcular_precificacao_classe`.
    """
    if not parametros.linhas:
        raise ValueError("A projeção de fluxo não tem nenhuma linha.")
    if parametros.valor_nominal_credito <= 0:
        raise ValueError("O valor nominal do crédito deve ser maior que zero.")

    memoria: list[str] = [
        f"Crédito Original (C0) = {formatar_moeda(float(parametros.valor_nominal_credito))}. Fluxo utilizado: "
        "projeção de pagamentos já pronta, extraída diretamente do Plano de Recuperação Judicial (não gerada "
        "por cronograma Price/SAC) — os valores de cada período já são o fluxo final a receber."
    ]

    taxa_desconto_periodo = converter_taxa(
        parametros.taxa_desconto_anual, Periodicidade.ANUAL, parametros.periodicidade, RegimeJuros.COMPOSTO
    )
    memoria.append(
        f"Casamento de período: taxa de desconto ({formatar_percentual(float(parametros.taxa_desconto_anual))} "
        f"a.a., {parametros.origem_taxa_desconto}) convertida para "
        f"{formatar_percentual(float(taxa_desconto_periodo))} por {parametros.periodicidade.value.lower()}."
    )

    fluxo: list[ParcelaPrecificacao] = []
    for numero, linha in enumerate(parametros.linhas, start=1):
        valor_descontado = arredondar(linha.valor / ((Decimal(1) + taxa_desconto_periodo) ** numero))
        fluxo.append(
            ParcelaPrecificacao(
                numero=numero,
                data=linha.data,
                descricao=linha.descricao,
                carencia=False,
                saldo_inicial=Decimal(0),
                juros_periodo=Decimal(0),
                amortizacao=linha.valor,
                valor_nominal=linha.valor,
                saldo_final=Decimal(0),
                valor_descontado=valor_descontado,
            )
        )

    fluxo_nominal_total = arredondar(sum((item.valor_nominal for item in fluxo), Decimal(0)))
    vp_total = arredondar(sum((item.valor_descontado for item in fluxo), Decimal(0)))
    vpl_comercial = arredondar(vp_total - parametros.valor_nominal_credito)
    percentual_recuperacao = (
        (vp_total / parametros.valor_nominal_credito) * 100 if parametros.valor_nominal_credito != 0 else Decimal(0)
    )

    memoria.append(
        "Fluxo Nominal Total (soma de todos os pagamentos da projeção) = "
        f"{formatar_moeda(float(fluxo_nominal_total))}."
    )
    memoria.append(
        "Valor Presente do Fluxo (VP Total) = soma do VP de cada linha, "
        f"VP_t = Valor da linha / (1 + {formatar_percentual(float(taxa_desconto_periodo))})^t "
        f"= {formatar_moeda(float(vp_total))}."
    )
    memoria.append(
        f"VPL Real Comercial = VP Total − Crédito Original = {formatar_moeda(float(vp_total))} − "
        f"{formatar_moeda(float(parametros.valor_nominal_credito))} = {formatar_moeda(float(vpl_comercial))}."
    )
    memoria.append(
        "Percentual de Recuperação Efetiva = VP Total / Crédito Original = "
        f"{formatar_percentual(float(percentual_recuperacao) / 100)}."
    )
    memoria.append(
        "*** Fluxo utilizado exatamente como extraído do Plano de Recuperação Judicial (projeção pronta) — "
        "revise os valores de cada linha antes de confiar no resultado; a extração automática pode ter "
        "imprecisões em documentos com diagramação incomum. ***"
    )

    return ResultadoPrecificacaoClasse(
        classe=parametros.classe,
        valor_nominal_credito=parametros.valor_nominal_credito,
        valor_atualizado_credito=None,
        condicoes=parametros.condicoes,
        taxa_desconto_anual=parametros.taxa_desconto_anual,
        taxa_desconto_periodo=taxa_desconto_periodo,
        origem_taxa_desconto=parametros.origem_taxa_desconto,
        data_taxa_desconto=parametros.data_taxa_desconto,
        fluxo=fluxo,
        fluxo_nominal_total=fluxo_nominal_total,
        vp_total=vp_total,
        vpl_comercial=vpl_comercial,
        percentual_recuperacao_efetiva=percentual_recuperacao,
        memoria_calculo=memoria,
        metodologia_validada=False,
    )
