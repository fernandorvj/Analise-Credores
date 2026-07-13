"""Cálculos de totais, percentuais e ranking sobre a relação de credores extraída.

Todas as funções recebem uma lista de `Credor` e retornam `pandas.DataFrame`
prontos para exibição na interface ou exportação. Apenas credores com valor
numérico E classe reconhecida entram nos cálculos (ver
`src.utils.credor_utilizavel_para_analise`) — registros com erro de leitura são
naturalmente excluídos, nunca com um dado inventado.
"""

from __future__ import annotations

import pandas as pd

from src.models import Credor
from src.utils import credor_utilizavel_para_analise


def _credores_com_valor(credores: list[Credor]) -> list[Credor]:
    return [c for c in credores if credor_utilizavel_para_analise(c)]


def valor_total_passivo(credores: list[Credor]) -> float:
    """Soma o valor de todos os credores com valor identificado."""
    return sum(c.valor for c in _credores_com_valor(credores))


def resumo_por_classe(credores: list[Credor]) -> pd.DataFrame:
    """Totais e percentual sobre o passivo total, agregados por classe."""
    validos = _credores_com_valor(credores)
    total_passivo = sum(c.valor for c in validos)

    agregados: dict[str, dict] = {}
    for c in validos:
        linha = agregados.setdefault(c.classe, {"Classe": c.classe, "Quantidade": 0, "Valor Total": 0.0})
        linha["Quantidade"] += 1
        linha["Valor Total"] += c.valor

    df = pd.DataFrame(agregados.values())
    if df.empty:
        return df

    df["% do Passivo Total"] = df["Valor Total"] / total_passivo if total_passivo else 0.0
    return df.sort_values("Valor Total", ascending=False).reset_index(drop=True)


def tabela_analitica(credores: list[Credor]) -> pd.DataFrame:
    """Tabela completa: um registro por credor, com percentuais e participação acumulada.

    Ordenada por valor decrescente — a participação acumulada reflete essa ordem
    (equivalente ao ranking dos maiores credores).
    """
    validos = _credores_com_valor(credores)
    total_passivo = sum(c.valor for c in validos)

    totais_por_classe: dict[str, float] = {}
    for c in validos:
        totais_por_classe[c.classe] = totais_por_classe.get(c.classe, 0.0) + c.valor

    ordenados = sorted(validos, key=lambda c: c.valor, reverse=True)
    registros = []
    for c in ordenados:
        total_classe = totais_por_classe[c.classe]
        registros.append(
            {
                "ID": c.id,
                "Nome": c.nome,
                "Documento": c.documento,
                "Classe": c.classe,
                "Valor": c.valor,
                "% da Classe": c.valor / total_classe if total_classe else 0.0,
                "% do Passivo Total": c.valor / total_passivo if total_passivo else 0.0,
                "Página": c.pagina,
                "Status Leitura": c.status_leitura.value
                if hasattr(c.status_leitura, "value")
                else c.status_leitura,
            }
        )

    df = pd.DataFrame(registros)
    if df.empty:
        return df

    df["Participação Acumulada"] = df["% do Passivo Total"].cumsum()
    df.insert(0, "Ranking", range(1, len(df) + 1))
    return df


def ranking_maiores_credores(credores: list[Credor], top_n: int = 20) -> pd.DataFrame:
    """Os `top_n` maiores credores por valor, com percentuais já calculados."""
    df = tabela_analitica(credores)
    return df.head(top_n).reset_index(drop=True) if not df.empty else df
