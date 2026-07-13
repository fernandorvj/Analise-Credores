"""Modelos de dados do módulo Petição Inicial — independentes do contrato de
Credor/ResultadoExtracao em `src/models.py` (não compartilham nenhum campo,
não há motivo para viver no mesmo arquivo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

NAO_LOCALIZADO = "não localizado"


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

    # --- As 12 seções --------------------------------------------------------
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
    resumo_final: str = ""


# (título exibido, chave do atributo em RelatorioPeticaoInicial) — ordem fixa das
# 12 seções, usada tanto pela interface (accordion/navegação) quanto pela
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
    ("Resumo Final", "resumo_final"),
]
