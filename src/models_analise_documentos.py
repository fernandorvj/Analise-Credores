"""Modelos de dados do módulo Análise de Documentos — independente dos
módulos Credores, Petição Inicial e Precificação Inteligente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class ItemComContexto:
    """Um item de lista com uma breve justificativa/contexto — usado nas
    seções que listam riscos, garantias, execuções, cláusulas, datas e
    valores relevantes."""

    item: str
    contexto: str = ""


@dataclass
class AnaliseDocumento:
    """Análise completa de um documento (qualquer formato suportado por
    `src/leitor_documentos.py`)."""

    arquivo_nome: str
    tipo_origem: str  # "PDF" | "DOCX" | "XLSX" | "TXT" | "Imagem" | "Link"
    data_analise: date
    resumo_executivo: str = ""
    objetivo_documento: str = ""
    pontos_importantes: list[str] = field(default_factory=list)
    riscos_juridicos: list[ItemComContexto] = field(default_factory=list)
    riscos_financeiros: list[ItemComContexto] = field(default_factory=list)
    garantias: list[ItemComContexto] = field(default_factory=list)
    execucoes: list[ItemComContexto] = field(default_factory=list)
    passivo_fiscal: str = ""
    clausulas_relevantes: list[ItemComContexto] = field(default_factory=list)
    datas_relevantes: list[ItemComContexto] = field(default_factory=list)
    valores_relevantes: list[ItemComContexto] = field(default_factory=list)
    impacto_aquisicao_creditos: str = ""
    conclusao: str = ""
    avisos: list[str] = field(default_factory=list)
    texto_fonte: str = ""  # texto integral extraído, usado pelas perguntas de acompanhamento


# (título exibido, chave do atributo em AnaliseDocumento) — ordem fixa das
# seções, usada tanto pela interface (accordion) quanto pela exportação Word.
SECOES = [
    ("Resumo Executivo", "resumo_executivo"),
    ("Objetivo do Documento", "objetivo_documento"),
    ("Pontos Importantes", "pontos_importantes"),
    ("Riscos Jurídicos", "riscos_juridicos"),
    ("Riscos Financeiros", "riscos_financeiros"),
    ("Garantias", "garantias"),
    ("Execuções", "execucoes"),
    ("Passivo Fiscal", "passivo_fiscal"),
    ("Cláusulas Relevantes", "clausulas_relevantes"),
    ("Datas Relevantes", "datas_relevantes"),
    ("Valores Relevantes", "valores_relevantes"),
    ("Impacto na Aquisição de Créditos", "impacto_aquisicao_creditos"),
    ("Conclusão", "conclusao"),
]
