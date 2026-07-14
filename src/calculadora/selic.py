"""Integração com a API pública do Banco Central (SGS — Sistema Gerenciador de
Séries Temporais) para obter a Meta Selic (série 432, definida pelo Copom,
% ao ano) usada como taxa de desconto padrão na Calculadora de VPL.

Nunca derruba a calculadora se a API estiver fora do ar: qualquer falha
(timeout, erro HTTP, resposta inesperada) é capturada aqui e o chamador
recebe `None`, devendo então oferecer edição manual da taxa ao usuário — a
mesma política de "nunca inventar dado" já usada no restante da plataforma.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

_URL_SELIC_META = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
_TIMEOUT_SEGUNDOS = 6
_ORIGEM_API = "BACEN — API SGS, série 432 (Meta Selic definida pelo Copom)"
ORIGEM_MANUAL = "Definida manualmente pelo usuário"


@dataclass
class TaxaSelic:
    """Taxa Selic (fração anual, ex.: 0.105 = 10,5% a.a.) com metadados de origem."""

    valor_anual: Decimal
    data_referencia: date
    origem: str


def obter_selic_bacen() -> TaxaSelic | None:
    """Consulta a Meta Selic vigente na API pública do BACEN.

    Retorna `None` em qualquer falha de rede, HTTP ou parsing — nunca levanta
    exceção para o chamador, que deve tratar `None` oferecendo entrada manual.
    """
    try:
        resposta = requests.get(_URL_SELIC_META, timeout=_TIMEOUT_SEGUNDOS)
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados:
            return None
        item = dados[-1]
        valor_percentual = Decimal(str(item["valor"]))
        data_referencia = datetime.strptime(item["data"], "%d/%m/%Y").date()
        return TaxaSelic(
            valor_anual=valor_percentual / Decimal(100),
            data_referencia=data_referencia,
            origem=_ORIGEM_API,
        )
    except (requests.RequestException, ValueError, KeyError, InvalidOperation, TypeError):
        return None
