"""Modelos de dados do módulo Calculadora — dataclasses puras (sem Streamlit
e sem dependência de nenhum outro módulo de negócio da plataforma: Credores e
Petição Inicial não são tocados nem importados aqui). Compartilhados entre o
motor de cálculo (amortizacao.py, fluxo.py, vpl_tir.py) e a interface
(interface/calculadora/*.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class SistemaAmortizacao(str, Enum):
    """Sistema de amortização do financiamento."""

    PRICE = "Tabela Price"
    SAC = "Tabela SAC"
    AMERICANO = "Sistema Americano"


class RegimeJuros(str, Enum):
    """Regime usado (1) na conversão de taxa entre periodicidades e (2) na
    capitalização de juros durante a carência. O cálculo das parcelas em si
    (Price/SAC) segue sempre a convenção padrão de mercado de cada sistema —
    Price e SAC são, por definição, sistemas de juros compostos; não existe
    "Tabela Price em juros simples" como conceito financeiro válido.
    """

    SIMPLES = "Juros Simples"
    COMPOSTO = "Juros Compostos"


class Periodicidade(str, Enum):
    """Periodicidade de uma taxa ou de um conjunto de parcelas."""

    MENSAL = "Mensal"
    BIMESTRAL = "Bimestral"
    TRIMESTRAL = "Trimestral"
    QUADRIMESTRAL = "Quadrimestral"
    SEMESTRAL = "Semestral"
    ANUAL = "Anual"

    @property
    def meses(self) -> int:
        return {
            "Mensal": 1,
            "Bimestral": 2,
            "Trimestral": 3,
            "Quadrimestral": 4,
            "Semestral": 6,
            "Anual": 12,
        }[self.value]


class TipoFluxoItem(str, Enum):
    """Natureza de um item do fluxo de caixa livre (Simulação Balão / Editor de Fluxo)."""

    ENTRADA = "Entrada"
    PARCELA = "Parcela"
    BALAO = "Balão"
    EXTRA = "Extraordinária"


# --- Simulador de Financiamento --------------------------------------------


@dataclass
class ParametrosFinanciamento:
    """Entradas do Simulador de Financiamento."""

    valor_financiado: Decimal
    valor_entrada: Decimal
    taxa: Decimal  # fração (0.02 = 2%), na periodicidade `periodicidade_taxa`
    periodicidade_taxa: Periodicidade
    periodicidade_parcela: Periodicidade
    prazo: int
    carencia: int
    data_inicial: date
    sistema: SistemaAmortizacao
    regime: RegimeJuros
    carencia_paga_juros: bool = False  # False = juros da carência capitalizam ao saldo


@dataclass
class ParcelaAmortizacao:
    """Uma linha do cronograma de amortização (carência ou amortização)."""

    numero: int
    data: date
    saldo_inicial: Decimal
    juros: Decimal
    amortizacao: Decimal
    valor_parcela: Decimal
    saldo_final: Decimal
    carencia: bool = False


@dataclass
class ResultadoFinanciamento:
    """Saída completa do Simulador de Financiamento."""

    parametros: ParametrosFinanciamento
    taxa_periodica: Decimal
    parcelas: list[ParcelaAmortizacao] = field(default_factory=list)

    @property
    def juros_totais(self) -> Decimal:
        return sum((p.juros for p in self.parcelas), Decimal(0))

    @property
    def total_pago(self) -> Decimal:
        return sum((p.valor_parcela for p in self.parcelas), Decimal(0)) + self.parametros.valor_entrada

    @property
    def valor_parcela_regular(self) -> Decimal | None:
        """Valor da primeira parcela após a carência (referência de "a parcela é de R$...")."""
        regulares = [p for p in self.parcelas if not p.carencia]
        return regulares[0].valor_parcela if regulares else None


# --- Simulação Balão / Editor de Fluxo --------------------------------------


@dataclass
class FluxoItem:
    """Um evento do fluxo de caixa livre — entrada, parcela regular, balão ou
    pagamento extraordinário. Editável livremente pelo usuário na interface;
    os campos calculados (juros/amortizacao/saldo_devedor/valor_presente) são
    preenchidos por `fluxo.recalcular_fluxo`.
    """

    id: int
    data: date
    descricao: str
    tipo: TipoFluxoItem
    valor: Decimal  # positivo = valor pago pelo devedor nessa data
    editavel: bool = True
    juros: Decimal | None = None
    amortizacao: Decimal | None = None
    saldo_devedor: Decimal | None = None
    valor_presente: Decimal | None = None


# --- Calculadora de VPL -----------------------------------------------------


@dataclass
class ParametrosVPL:
    """Entradas da Calculadora de VPL (aquisição de crédito)."""

    valor_credito: Decimal
    valor_compra: Decimal
    desagio: Decimal  # fração (0.85 = 85%) — haircut do plano de RJ sobre o crédito; define o fluxo recebido, não o preço de compra
    data_base: date
    fluxo_recebimentos: list[FluxoItem]  # apenas os recebimentos esperados (sem a saída do valor_compra)
    taxa_desconto_anual: Decimal
    origem_taxa_desconto: str
    correcao_monetaria_anual: Decimal = Decimal(0)


@dataclass
class ResultadoVPL:
    """Saída completa da Calculadora de VPL."""

    parametros: ParametrosVPL
    vpl: Decimal  # valor presente do fluxo recebido (igual ao valor_economico — convenção da planilha de referência)
    ganho_liquido: Decimal  # valor_economico − valor_compra
    valor_futuro: Decimal
    valor_economico: Decimal
    tir_anual: Decimal | None
    taxa_efetiva_anual: Decimal | None
    payback_data: date | None
    payback_meses: float | None
    roi: Decimal | None
    rentabilidade: Decimal | None
    margem: Decimal | None
    spread: Decimal | None
    fluxo_descontado: list[FluxoItem] = field(default_factory=list)


# --- Comparação de Cenários --------------------------------------------------


@dataclass
class Cenario:
    """Um cenário salvo (financiamento ou VPL) para a aba de Comparação."""

    nome: str
    tipo: str  # "financiamento" | "vpl"
    resultado: ResultadoFinanciamento | ResultadoVPL
    criado_em: datetime = field(default_factory=datetime.now)
