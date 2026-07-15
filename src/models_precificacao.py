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
class CondicoesGerais:
    """Condições do Plano de RJ que se aplicam a TODOS os credores/todas as
    classes, geralmente declaradas uma única vez (ex.: metodologia de
    correção monetária ou juros do Quadro Geral de Credores) antes do
    detalhamento específico de cada classe — mesmo que o texto não use a
    palavra "geral". Usada para preencher os campos de uma classe quando a
    cláusula específica dela não menciona aquele campo (a classe sempre tem
    prioridade; a condição geral só entra quando a classe está em branco —
    ver `_mesclar_com_geral` em `src/ia.py`).
    """

    descricao: str = ""
    desagio: str = NAO_LOCALIZADO
    carencia: str = NAO_LOCALIZADO
    correcao_monetaria_indice: str = NAO_LOCALIZADO
    juros: str = NAO_LOCALIZADO
    periodicidade: str = NAO_LOCALIZADO
    trechos_localizados: list[TrechoPlano] = field(default_factory=list)


@dataclass
class LinhaProjecaoFluxoAnual:
    """Uma linha (um período) de uma tabela de projeção de fluxo de
    pagamentos já pronta no Plano de RJ — texto extraído literalmente
    (nunca calculado pela IA); a conversão para número é feita em Python,
    depois de o usuário revisar/editar."""

    periodo: str  # ex.: "Ano 01", "Ano 02"
    valor: str  # valor bruto extraído, ex.: "180.421,63"


@dataclass
class ProjecaoFluxoAnualClasse:
    """Projeção de fluxo de pagamentos já pronta no Plano de RJ para uma
    classe específica — só existe quando o documento traz uma tabela desse
    tipo (ex.: "Projeção de Fluxo Anual de Pagamentos"), como alternativa às
    condições de deságio/carência/parcelas de `CondicoesPagamentoClasse`
    (ver `src/calculadora/precificacao_motor.py:calcular_precificacao_classe_com_projecao`,
    que usa essas linhas diretamente como fluxo, sem gerar cronograma Price).
    """

    classe: str
    linhas: list[LinhaProjecaoFluxoAnual] = field(default_factory=list)
    trechos_localizados: list[TrechoPlano] = field(default_factory=list)


@dataclass
class ExtracaoPlanoPorClasse:
    """Resultado da extração via IA do Plano de RJ — condições gerais (se
    houver) mais as condições de pagamento organizadas pelas 4 classes
    padrão (`config.CLASSES_RJ_PADRAO`), já mescladas (específico da classe
    sobrepõe o geral), e a projeção de fluxo anual por classe, quando o
    documento já trouxer uma tabela pronta desse tipo. Só interpretação do
    texto, nunca cálculo.
    """

    arquivo_nome: str
    data_analise: date
    condicoes_gerais: CondicoesGerais = field(default_factory=CondicoesGerais)
    condicoes_por_classe: dict[str, CondicoesPagamentoClasse] = field(default_factory=dict)
    projecoes_fluxo_anual: dict[str, ProjecaoFluxoAnualClasse] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)


@dataclass
class ParcelaPrecificacao:
    """Uma linha do cronograma unificado (carência ou parcela de pagamento).

    Todas as linhas do cronograma são mantidas aqui — inclusive as de
    carência — para auditoria "linha por linha": numa linha de carência,
    `amortizacao` e `valor_nominal` são zero (nada é pago ao credor; os
    juros do período capitalizam ao saldo, refletido em `saldo_final`).
    """

    numero: int  # posição cronológica (1..N) — usada como `t` na descapitalização
    data: date
    descricao: str
    carencia: bool
    saldo_inicial: Decimal
    juros_periodo: Decimal
    amortizacao: Decimal
    valor_nominal: Decimal  # fluxo total efetivamente recebido pelo credor nesta linha (0 se carência)
    saldo_final: Decimal
    valor_descontado: Decimal  # VP_t = valor_nominal / (1 + taxa_desconto_periodo) ** numero


@dataclass
class ResultadoPrecificacaoClasse:
    """Saída completa do cálculo de VPL para uma classe — 100% em Python,
    determinístico e auditável (nunca calculado pela IA). Segue a
    metodologia de cronograma unificado + casamento de período +
    descapitalização linha por linha fornecida pela AMF3 Capital.
    """

    classe: str
    valor_nominal_credito: Decimal  # Crédito Original (C0)
    valor_atualizado_credito: Decimal | None
    condicoes: CondicoesPagamentoClasse
    taxa_desconto_anual: Decimal
    taxa_desconto_periodo: Decimal  # já convertida para a periodicidade das parcelas ("molde")
    origem_taxa_desconto: str
    data_taxa_desconto: date | None
    fluxo: list[ParcelaPrecificacao] = field(default_factory=list)
    fluxo_nominal_total: Decimal = Decimal(0)  # soma de amortização + juros pagos em todas as parcelas
    vp_total: Decimal = Decimal(0)  # Valor Presente do Fluxo = soma de todos os VP_t
    vpl_comercial: Decimal = Decimal(0)  # VPL Real Comercial = VP Total − Crédito Original
    percentual_recuperacao_efetiva: Decimal = Decimal(0)  # VP Total / Crédito Original × 100
    memoria_calculo: list[str] = field(default_factory=list)
    # False até a metodologia ser comparada e confirmada equivalente à
    # planilha oficial da AMF3 — ver ETAPA de validação do módulo.
    metodologia_validada: bool = False
