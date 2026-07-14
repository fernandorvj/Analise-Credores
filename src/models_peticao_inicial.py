"""Modelos de dados do módulo Petição Inicial — independentes do contrato de
Credor/ResultadoExtracao em `src/models.py` (não compartilham nenhum campo,
não há motivo para viver no mesmo arquivo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

NAO_LOCALIZADO = "não localizado"

# Mensagem obrigatória quando nenhuma referência a passivo fiscal/execução
# fiscal é encontrada no documento — nunca se assume a inexistência do
# passivo, apenas que o texto analisado não traz essa informação.
MENSAGEM_PASSIVO_FISCAL_AUSENTE = (
    "Após análise integral da Petição Inicial, não foram localizadas referências expressas a "
    "passivos fiscais ou execuções fiscais. Isso não significa necessariamente sua inexistência, "
    "apenas que tais informações não constam no documento analisado."
)
VALOR_FISCAL_NAO_LOCALIZADO = "Valor não localizado na Petição Inicial."


@dataclass
class DadosEmpresa:
    """Seção 2 — Sobre a Empresa."""

    razao_social: str = NAO_LOCALIZADO
    nome_fantasia: str = NAO_LOCALIZADO
    cnpj: str = NAO_LOCALIZADO
    segmento: str = NAO_LOCALIZADO
    atividade: str = NAO_LOCALIZADO
    grupo_economico: str = NAO_LOCALIZADO
    numero_funcionarios: str = NAO_LOCALIZADO
    filiais: str = NAO_LOCALIZADO
    mercado_atuacao: str = NAO_LOCALIZADO
    outros_dados: list[tuple[str, str]] = field(default_factory=list)  # (campo, valor) extensível


@dataclass
class EventoCronologia:
    """Um evento da seção 6 — Cronologia dos Fatos."""

    data: str
    evento: str


@dataclass
class ItemComJustificativa:
    """Um item das seções 8/9 — Pontos Positivos / Pontos de Atenção."""

    ponto: str
    justificativa: str


@dataclass
class TrechoFiscal:
    """Um trecho da Petição Inicial que fundamenta a seção de Passivo Fiscal
    e Execuções Fiscais — nunca inventado, sempre extraído literalmente do
    documento (ver `PassivoFiscal.trechos_localizados`)."""

    pagina: str = "-"
    trecho: str = ""
    contexto: str = ""


@dataclass
class PassivoFiscal:
    """Seção obrigatória — 🧾 Passivo Fiscal e Execuções Fiscais. Sempre
    presente no relatório, mesmo quando nada é encontrado no documento: nesse
    caso os campos de situação recebem "Não localizado", os valores recebem
    `VALOR_FISCAL_NAO_LOCALIZADO` e o resumo traz `MENSAGEM_PASSIVO_FISCAL_AUSENTE`
    — a ausência de menção nunca é interpretada como inexistência do passivo.
    """

    existe_passivo_fiscal: str = NAO_LOCALIZADO
    existe_execucao_fiscal: str = NAO_LOCALIZADO
    existe_parcelamento: str = NAO_LOCALIZADO
    existe_transacao_tributaria: str = NAO_LOCALIZADO
    existe_discussao_administrativa_judicial: str = NAO_LOCALIZADO
    resumo: str = MENSAGEM_PASSIVO_FISCAL_AUSENTE
    valor_passivo_fiscal: str = VALOR_FISCAL_NAO_LOCALIZADO
    valor_execucoes_fiscais: str = VALOR_FISCAL_NAO_LOCALIZADO
    quantidade_processos: str = NAO_LOCALIZADO
    tributos_envolvidos: list[str] = field(default_factory=list)
    orgaos_envolvidos: list[str] = field(default_factory=list)
    trechos_localizados: list[TrechoFiscal] = field(default_factory=list)
    avaliacao_estrategica: str = ""
    grau_atencao: str = "Baixo"  # "Baixo" | "Médio" | "Alto"
    justificativa_grau_atencao: str = ""

    @property
    def localizado(self) -> bool:
        """True se há indício de passivo fiscal ou execução fiscal no documento
        (usado pelo card de destaque e pela exportação — nunca decide sozinho
        que "não há", só reflete o que a IA já concluiu a partir do texto)."""
        return self.existe_passivo_fiscal.strip().lower() == "sim" or self.existe_execucao_fiscal.strip().lower() == "sim"


@dataclass
class RelatorioPeticaoInicial:
    """Relatório executivo completo gerado a partir de uma Petição Inicial de RJ."""

    # --- Metadados ---------------------------------------------------------
    arquivo_nome: str
    data_analise: date
    total_paginas: int
    paginas_ocr: list[int] = field(default_factory=list)
    # Heurística (não é confiança real do Tesseract): páginas via OCR cujo
    # texto extraído ficou anormalmente curto/vazio — provável leitura ruim.
    paginas_ocr_baixa_confianca: list[int] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    # --- As 13 seções --------------------------------------------------------
    resumo_executivo: str = ""
    sobre_empresa: DadosEmpresa = field(default_factory=DadosEmpresa)
    historico_empresa: str = ""
    motivos_recuperacao_judicial: str = ""
    situacao_financeira: str = ""
    cronologia_fatos: list[EventoCronologia] = field(default_factory=list)
    principais_riscos: str = ""
    pontos_positivos: list[ItemComJustificativa] = field(default_factory=list)
    pontos_atencao: list[ItemComJustificativa] = field(default_factory=list)
    visao_estrategica_aquisicao: str = ""
    fatores_impacto_quorum: str = ""
    passivo_fiscal: PassivoFiscal = field(default_factory=PassivoFiscal)
    resumo_final: str = ""


# (título exibido, chave do atributo em RelatorioPeticaoInicial) — ordem fixa das
# 13 seções, usada tanto pela interface (accordion/navegação) quanto pela
# exportação Word, para as duas nunca divergirem na ordem/títulos.
SECOES = [
    ("Resumo Executivo", "resumo_executivo"),
    ("Sobre a Empresa", "sobre_empresa"),
    ("Histórico da Empresa", "historico_empresa"),
    ("Motivos da Recuperação Judicial", "motivos_recuperacao_judicial"),
    ("Situação Financeira", "situacao_financeira"),
    ("Cronologia dos Fatos", "cronologia_fatos"),
    ("Principais Riscos", "principais_riscos"),
    ("Pontos Positivos", "pontos_positivos"),
    ("Pontos de Atenção", "pontos_atencao"),
    ("Visão Estratégica para Aquisição de Créditos", "visao_estrategica_aquisicao"),
    ("Fatores que Podem Impactar a Formação de Quórum", "fatores_impacto_quorum"),
    ("🧾 Passivo Fiscal e Execuções Fiscais", "passivo_fiscal"),
    ("Resumo Final", "resumo_final"),
]
