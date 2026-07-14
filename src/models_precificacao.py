"""Modelos de dados do módulo Precificação Inteligente de Créditos.

Independente do módulo Credores e do módulo Petição Inicial. Reaproveita
`ResultadoVPL`/`ParametrosVPL` de `src/calculadora/models.py` (o mesmo motor
de VPL/TIR/fluxo de caixa já usado pela Simulação de Financiamento) em vez de
duplicar essas estruturas — este arquivo só acrescenta o que é específico
deste módulo: a extração (via IA) dos termos do Plano de Recuperação Judicial
e os indicadores adicionais (Duration, Payback Descontado, Preço Máximo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.calculadora.models import ResultadoVPL
from src.models_peticao_inicial import NAO_LOCALIZADO


@dataclass
class TermosGerais:
    """Termos gerais do Plano de RJ identificados pela IA — texto livre,
    nunca um valor numérico pronto para cálculo (o usuário confirma/ajusta os
    números antes de qualquer cálculo em `interface/precificacao.py`).
    """

    desagio: str = NAO_LOCALIZADO
    carencia: str = NAO_LOCALIZADO
    juros: str = NAO_LOCALIZADO
    correcao_monetaria: str = NAO_LOCALIZADO
    periodicidade_parcelas: str = NAO_LOCALIZADO
    quantidade_parcelas: str = NAO_LOCALIZADO
    data_inicio_pagamentos: str = NAO_LOCALIZADO


@dataclass
class TermosClasse:
    """Termos específicos de uma classe de credores, quando o plano os
    diferencia por classe (comum em Planos de RJ reais)."""

    classe: str = NAO_LOCALIZADO
    desagio: str = NAO_LOCALIZADO
    carencia: str = NAO_LOCALIZADO
    juros: str = NAO_LOCALIZADO
    periodicidade_parcelas: str = NAO_LOCALIZADO
    quantidade_parcelas: str = NAO_LOCALIZADO
    observacoes: str = ""


@dataclass
class TrechoPlano:
    """Um trecho do Plano de RJ que fundamenta um termo extraído — nunca
    inventado, sempre extraído literalmente do documento."""

    pagina: str = "-"
    trecho: str = ""
    contexto: str = ""


@dataclass
class ExtracaoPlano:
    """Resultado da extração via IA do Plano de RJ — só interpretação do
    texto, nunca cálculo (todo cálculo financeiro é feito em Python a partir
    dos números que o usuário confirma com base nesta extração).
    """

    arquivo_nome: str
    data_analise: date
    termos_gerais: TermosGerais = field(default_factory=TermosGerais)
    termos_por_classe: list[TermosClasse] = field(default_factory=list)
    eventos_especiais: list[str] = field(default_factory=list)
    resumo_plano: str = ""
    trechos_localizados: list[TrechoPlano] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


@dataclass
class ResultadoPrecificacao:
    """Saída completa da Precificação Inteligente — compõe o `ResultadoVPL`
    já existente (motor validado em `src/calculadora/vpl_tir.py`) com os
    indicadores adicionais deste módulo e o contexto da extração via IA.
    """

    extracao: ExtracaoPlano
    resultado_vpl: ResultadoVPL
    duration_anos: Decimal | None
    payback_descontado_data: date | None
    payback_descontado_meses: float | None
    preco_maximo_breakeven: Decimal  # = valor_economico: pagar mais que isso já dá ganho líquido negativo
    preco_maximo_taxa_alvo: Decimal  # preço para atingir exatamente `taxa_alvo_anual` de TIR
    taxa_alvo_anual: Decimal
