"""Modelos de dados do módulo Precificação Inteligente de Créditos.

Independente do módulo Credores e do módulo Petição Inicial. A IA só
interpreta o Plano de Recuperação Judicial (condições de pagamento por
classe); todo cálculo financeiro é feito em Python puro, de forma
determinística e auditável (ver `src/calculadora/precificacao_motor.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.models_peticao_inicial import NAO_LOCALIZADO


@dataclass
class TrechoPlano:
    """Um trecho do Plano de RJ que fundamenta uma condição extraída — nunca
    inventado, sempre extraído literalmente do documento."""

    pagina: str = "-"
    trecho: str = ""
    contexto: str = ""


@dataclass
class CondicoesPagamentoClasse:
    """Condições de pagamento previstas no Plano de RJ para uma classe de
    credores — texto livre extraído pela IA, sempre revisado/editado pelo
    usuário (via formulário estruturado) antes de qualquer cálculo.
    """

    classe: str
    desagio: str = NAO_LOCALIZADO
    carencia: str = NAO_LOCALIZADO
    correcao_monetaria_indice: str = NAO_LOCALIZADO
    juros: str = NAO_LOCALIZADO
    numero_parcelas: str = NAO_LOCALIZADO
    periodicidade: str = NAO_LOCALIZADO
    data_primeira_parcela: str = NAO_LOCALIZADO
    parcela_balao: str = NAO_LOCALIZADO
    fluxos_alternativos: str = ""
    excecoes_regras_especiais: str = ""
    trechos_localizados: list[TrechoPlano] = field(default_factory=list)


@dataclass
class ExtracaoPlanoPorClasse:
    """Resultado da extração via IA do Plano de RJ — condições de pagamento
    organizadas pelas 4 classes padrão (`config.CLASSES_RJ_PADRAO`). Só
    interpretação do texto, nunca cálculo.
    """

    arquivo_nome: str
    data_analise: date
    condicoes_por_classe: dict[str, CondicoesPagamentoClasse] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)


@dataclass
class ParcelaPrecificacao:
    """Uma parcela do fluxo de pagamento de uma classe — valor nominal (já
    com correção monetária, se aplicável) e valor descontado a valor
    presente pela taxa de desconto (SELIC ou manual)."""

    numero: int
    data: date
    descricao: str
    valor_nominal: Decimal
    valor_descontado: Decimal


@dataclass
class ResultadoPrecificacaoClasse:
    """Saída completa do cálculo de VPL para uma classe — 100% em Python,
    determinístico e auditável (nunca calculado pela IA).
    """

    classe: str
    valor_nominal_credito: Decimal
    valor_atualizado_credito: Decimal | None
    condicoes: CondicoesPagamentoClasse
    taxa_desconto_anual: Decimal
    origem_taxa_desconto: str
    data_taxa_desconto: date | None
    fluxo: list[ParcelaPrecificacao] = field(default_factory=list)
    vpl: Decimal = Decimal(0)
    memoria_calculo: list[str] = field(default_factory=list)
    # False até a metodologia ser comparada e confirmada equivalente à
    # planilha oficial da AMF3 — ver ETAPA de validação do módulo.
    metodologia_validada: bool = False
