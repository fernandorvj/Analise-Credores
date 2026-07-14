"""Integração com a API pública do Banco Central (SGS — Sistema Gerenciador
de Séries Temporais) para índices e taxas de referência usados em correção
monetária e desconto financeiro — generaliza o mesmo padrão já validado em
`selic.py` (mesma resiliência: qualquer falha de rede/parsing retorna
`None`, nunca derruba o chamador, que deve oferecer edição manual).

Séries SGS usadas — cada uma verificada empiricamente (valores retornados
plausíveis) antes de uso, não apenas assumidas por número:
- **CDI acumulado no mês, anualizado (base 252)**: série 4389, % a.a.
  (ex.: 14,15% a.a., coerente com a Meta Selic de 14,25% a.a. no mesmo dia).
- **IPCA acumulado em 12 meses**: série 13522, % a.a.
- **IGP-M**: a série 189 só traz a variação MENSAL — não existe uma série SGS
  de "IGP-M acumulado em 12 meses" oficialmente confirmada, então o
  acumulado é composto aqui a partir das 12 últimas variações mensais
  (`Π(1 + variação_mensal/100) − 1`), de forma auditável.
- **TR (Taxa Referencial)**: série 226 — valor do período vigente (~30 dias),
  usada como taxa de período/mês em contratos, não anualizada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

_TIMEOUT_SEGUNDOS = 6

_SERIE_CDI_ANUALIZADO = 4389
_SERIE_IPCA_12M = 13522
_SERIE_IGPM_MENSAL = 189
_SERIE_TR_PERIODO = 226


@dataclass
class TaxaIndice:
    """Um índice/taxa de referência com metadados de origem — `valor` é uma
    fração (0.105 = 10,5%); `periodicidade_valor` diz como interpretá-lo.
    """

    nome: str
    valor: Decimal
    data_referencia: date
    origem: str
    periodicidade_valor: str  # "a.a." | "por período (~30 dias)"


def _obter_pontos_serie(codigo: int, quantidade: int) -> list[tuple[date, Decimal]] | None:
    """Busca os `quantidade` pontos mais recentes de uma série do SGS/BACEN,
    em ordem cronológica. Retorna `None` em qualquer falha de rede, HTTP ou
    parsing — nunca levanta exceção para o chamador.
    """
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{quantidade}?formato=json"
    try:
        resposta = requests.get(url, timeout=_TIMEOUT_SEGUNDOS)
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados:
            return None
        return [
            (datetime.strptime(item["data"], "%d/%m/%Y").date(), Decimal(str(item["valor"])))
            for item in dados
        ]
    except (requests.RequestException, ValueError, KeyError, InvalidOperation, TypeError):
        return None


def _obter_ultimo_ponto_serie(codigo: int) -> tuple[date, Decimal] | None:
    pontos = _obter_pontos_serie(codigo, 1)
    return pontos[-1] if pontos else None


def obter_cdi_bacen() -> TaxaIndice | None:
    """CDI acumulado no mês, anualizado (base 252) — série SGS 4389, % a.a."""
    resultado = _obter_ultimo_ponto_serie(_SERIE_CDI_ANUALIZADO)
    if resultado is None:
        return None
    data_referencia, valor = resultado
    return TaxaIndice(
        nome="CDI",
        valor=valor / Decimal(100),
        data_referencia=data_referencia,
        origem=f"BACEN — API SGS, série {_SERIE_CDI_ANUALIZADO} (CDI acumulado no mês, anualizado)",
        periodicidade_valor="a.a.",
    )


def obter_ipca_12m_bacen() -> TaxaIndice | None:
    """IPCA acumulado em 12 meses — série SGS 13522, % a.a. (inflação oficial)."""
    resultado = _obter_ultimo_ponto_serie(_SERIE_IPCA_12M)
    if resultado is None:
        return None
    data_referencia, valor = resultado
    return TaxaIndice(
        nome="IPCA",
        valor=valor / Decimal(100),
        data_referencia=data_referencia,
        origem=f"BACEN — API SGS, série {_SERIE_IPCA_12M} (IPCA acumulado em 12 meses)",
        periodicidade_valor="a.a.",
    )


def obter_igpm_12m_bacen() -> TaxaIndice | None:
    """IGP-M acumulado em 12 meses, composto a partir das 12 últimas
    variações mensais (série SGS 189) — ver nota no docstring do módulo.
    """
    pontos = _obter_pontos_serie(_SERIE_IGPM_MENSAL, 12)
    if not pontos or len(pontos) < 12:
        return None
    fator = Decimal(1)
    for _, variacao_percentual in pontos:
        fator *= Decimal(1) + variacao_percentual / Decimal(100)
    acumulado = fator - Decimal(1)
    data_referencia = pontos[-1][0]
    return TaxaIndice(
        nome="IGP-M",
        valor=acumulado,
        data_referencia=data_referencia,
        origem=f"BACEN — API SGS, série {_SERIE_IGPM_MENSAL} (IGP-M, acumulado dos últimos 12 meses)",
        periodicidade_valor="a.a.",
    )


def obter_tr_bacen() -> TaxaIndice | None:
    """TR (Taxa Referencial) vigente no período mensal atual — série SGS 226,
    valor do período (~30 dias), usada como taxa de período em contratos.
    """
    resultado = _obter_ultimo_ponto_serie(_SERIE_TR_PERIODO)
    if resultado is None:
        return None
    data_referencia, valor = resultado
    return TaxaIndice(
        nome="TR",
        valor=valor / Decimal(100),
        data_referencia=data_referencia,
        origem=f"BACEN — API SGS, série {_SERIE_TR_PERIODO} (TR do período vigente)",
        periodicidade_valor="por período (~30 dias)",
    )
