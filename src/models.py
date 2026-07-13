"""Modelos de dados compartilhados entre todos os módulos do sistema.

Define o contrato único de um credor extraído do PDF, evitando que cada
módulo (parser, análise, exportação) invente sua própria representação.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StatusLeitura(str, Enum):
    """Confiabilidade da extração de um registro de credor."""

    OK = "ok"
    REVISAR = "revisar"  # extraído, mas com algum campo ambíguo (ex.: documento inválido)
    ERRO = "erro"  # não foi possível extrair de forma confiável


class TipoDocumento(str, Enum):
    CPF = "CPF"
    CNPJ = "CNPJ"
    INDEFINIDO = "Indefinido"


class VotoIntencao(str, Enum):
    """Intenção de voto de um credor na Assembleia Geral de Credores.

    Não é extraída do PDF — é definida manualmente pelo usuário na interface,
    para simular cenários de aprovação do plano por classe.
    """

    FAVORAVEL = "Favorável"
    CONTRARIO = "Contrário"
    INDEFINIDO = "Indefinido"


@dataclass
class Credor:
    """Um registro de credor extraído da relação de credores em PDF."""

    id: int
    nome: str
    documento: str = ""
    tipo_documento: TipoDocumento = TipoDocumento.INDEFINIDO
    classe: str = "Não identificada"
    valor: float | None = None
    pagina: int = 0
    status_leitura: StatusLeitura = StatusLeitura.OK
    observacoes: str = ""
    texto_origem: str = ""  # linha/trecho bruto de onde o registro foi extraído (auditoria)
    voto: VotoIntencao = VotoIntencao.INDEFINIDO  # definido pelo usuário, não extraído do PDF

    def to_dict(self) -> dict:
        return {
            "ID": self.id,
            "Nome": self.nome,
            "Documento": self.documento,
            "Tipo Documento": self.tipo_documento.value if isinstance(self.tipo_documento, TipoDocumento) else self.tipo_documento,
            "Classe": self.classe,
            "Valor": self.valor,
            "Página": self.pagina,
            "Status Leitura": self.status_leitura.value if isinstance(self.status_leitura, StatusLeitura) else self.status_leitura,
            "Observações": self.observacoes,
            "Voto": self.voto.value if isinstance(self.voto, VotoIntencao) else self.voto,
        }


@dataclass
class ResultadoExtracao:
    """Resultado completo da leitura de um PDF: credores + metadados de qualidade."""

    arquivo_nome: str
    credores: list[Credor] = field(default_factory=list)
    total_paginas: int = 0
    paginas_ocr: list[int] = field(default_factory=list)  # páginas que precisaram de OCR
    paginas_com_erro: list[int] = field(default_factory=list)
    # Subtotais impressos no próprio PDF (classe -> valor), usados para conferir a
    # extração — ferramentas de tabela (pdfplumber) podem perder linhas silenciosamente
    # em quebras de página; comparar contra o subtotal do documento expõe isso.
    subtotais_documento: dict[str, float] = field(default_factory=dict)
    total_geral_documento: float | None = None
    avisos_reconciliacao: list[str] = field(default_factory=list)

    @property
    def total_credores(self) -> int:
        return len(self.credores)

    @property
    def credores_com_erro(self) -> list[Credor]:
        return [c for c in self.credores if c.status_leitura == StatusLeitura.ERRO]

    @property
    def credores_para_revisar(self) -> list[Credor]:
        return [c for c in self.credores if c.status_leitura == StatusLeitura.REVISAR]

    @property
    def credores_validos(self) -> list[Credor]:
        return [c for c in self.credores if c.status_leitura == StatusLeitura.OK]
