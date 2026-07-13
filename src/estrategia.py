"""Simulações estratégicas: formação de quórum e cenários de aquisição de créditos.

Todas as simulações partem exclusivamente dos valores extraídos do PDF e usam uma
estratégia gulosa (maiores créditos primeiro) para estimar o menor número de
negociações necessário para atingir cada percentual de quórum. São apresentadas
como cenários técnicos — não constituem aconselhamento jurídico ou financeiro.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config import CLASSES_RJ_PADRAO, CRITERIOS_APROVACAO_CLASSE, CRITERIOS_APROVACAO_PADRAO, FAIXAS_QUORUM
from src.models import Credor, VotoIntencao
from src.utils import credor_utilizavel_para_analise


def _filtrar_base(credores: list[Credor], classe: str | None = None) -> list[Credor]:
    validos = [c for c in credores if credor_utilizavel_para_analise(c)]
    if classe and classe != "Total":
        validos = [c for c in validos if c.classe == classe]
    return validos


@dataclass
class PassoAquisicao:
    ordem: int
    nome: str
    documento: str
    valor: float
    valor_acumulado: float
    percentual_acumulado: float


@dataclass
class SimulacaoQuorum:
    percentual_alvo: float
    valor_alvo: float
    valor_total_base: float
    credores_necessarios: int
    valor_necessario: float
    percentual_atingido: float
    atingivel: bool
    passos: list[PassoAquisicao] = field(default_factory=list)


def simular_formacao_quorum(
    credores: list[Credor],
    classe: str | None = None,
    ja_adquiridos_ids: set[int] | None = None,
) -> list[SimulacaoQuorum]:
    """Para cada percentual em FAIXAS_QUORUM, simula a aquisição dos maiores créditos
    disponíveis (estratégia de menor número de negociações) até atingir o alvo.

    `classe=None` ou `"Total"` calcula sobre o passivo total; caso contrário, restringe
    a simulação aos credores da classe informada.
    """
    base = _filtrar_base(credores, classe)
    valor_total_base = sum(c.valor for c in base)
    ja_adquiridos_ids = ja_adquiridos_ids or set()

    valor_ja_adquirido = sum(c.valor for c in base if c.id in ja_adquiridos_ids)
    disponiveis = sorted(
        (c for c in base if c.id not in ja_adquiridos_ids),
        key=lambda c: c.valor,
        reverse=True,
    )

    simulacoes = []
    for percentual_alvo in FAIXAS_QUORUM:
        valor_alvo = percentual_alvo * valor_total_base
        acumulado = valor_ja_adquirido
        passos: list[PassoAquisicao] = []

        for i, c in enumerate(disponiveis, start=1):
            if acumulado >= valor_alvo:
                break
            acumulado += c.valor
            passos.append(
                PassoAquisicao(
                    ordem=i,
                    nome=c.nome,
                    documento=c.documento,
                    valor=c.valor,
                    valor_acumulado=acumulado,
                    percentual_acumulado=acumulado / valor_total_base if valor_total_base else 0.0,
                )
            )

        simulacoes.append(
            SimulacaoQuorum(
                percentual_alvo=percentual_alvo,
                valor_alvo=valor_alvo,
                valor_total_base=valor_total_base,
                credores_necessarios=len(passos),
                valor_necessario=sum(p.valor for p in passos),
                percentual_atingido=acumulado / valor_total_base if valor_total_base else 0.0,
                atingivel=acumulado >= valor_alvo,
                passos=passos,
            )
        )
    return simulacoes


def tabela_simulacoes(simulacoes: list[SimulacaoQuorum]) -> pd.DataFrame:
    """Resumo tabular (uma linha por faixa de quórum) das simulações."""
    return pd.DataFrame(
        [
            {
                "Quórum Alvo": s.percentual_alvo,
                "Valor Alvo": s.valor_alvo,
                "Credores Necessários": s.credores_necessarios,
                "Valor a Adquirir": s.valor_necessario,
                "Quórum Atingido": s.percentual_atingido,
                "Atingível": s.atingivel,
            }
            for s in simulacoes
        ]
    )


def credores_estrategicos(credores: list[Credor], classe: str | None = None, top_n: int = 15) -> pd.DataFrame:
    """Maiores créditos individuais disponíveis — os que oferecem o maior ganho de
    quórum por negociação (menor número de contrapartes para um dado percentual).
    """
    base = _filtrar_base(credores, classe)
    if not base:
        return pd.DataFrame()

    valor_total_base = sum(c.valor for c in base)
    ordenado = sorted(base, key=lambda c: c.valor, reverse=True)[:top_n]
    return pd.DataFrame(
        [
            {
                "Ranking": i,
                "Nome": c.nome,
                "Documento": c.documento,
                "Classe": c.classe,
                "Valor": c.valor,
                "% do Total": c.valor / valor_total_base if valor_total_base else 0.0,
            }
            for i, c in enumerate(ordenado, start=1)
        ]
    )


def concentracao_votos(credores: list[Credor], classe: str | None = None) -> dict[str, float]:
    """Percentual do passivo (ou da classe) detido pelos N maiores credores, para N em (1, 5, 10, 20)."""
    base = _filtrar_base(credores, classe)
    valor_total = sum(c.valor for c in base)
    ordenado = sorted(base, key=lambda c: c.valor, reverse=True)

    resultado = {}
    for n in (1, 5, 10, 20):
        valor_top_n = sum(c.valor for c in ordenado[:n])
        resultado[f"top_{n}"] = valor_top_n / valor_total if valor_total else 0.0
    return resultado


# --- Aprovação do Plano de RJ por classe (Lei 11.101/2005, art. 45) -----------
#
# Diferente das simulações de quórum acima (que olham o passivo como um bloco
# único), a aprovação do plano na AGC é decidida CLASSE A CLASSE, com critérios
# próprios: Classes I e IV exigem maioria por QUANTIDADE de credores; Classes II
# e III exigem maioria por VALOR e por QUANTIDADE simultaneamente. A intenção de
# voto de cada credor (Credor.voto) é definida manualmente pelo usuário na
# interface — nunca extraída do PDF.


@dataclass
class PassoAprovacao:
    ordem: int
    nome: str
    documento: str
    valor: float
    valor_acumulado: float
    percentual_valor_acumulado: float
    quantidade_acumulada: int
    percentual_quantidade_acumulado: float


@dataclass
class SimulacaoAprovacaoClasse:
    classe: str
    exige_valor: bool
    exige_quantidade: bool
    valor_total: float
    quantidade_total: int
    valor_favoravel_atual: float
    quantidade_favoravel_atual: int
    percentual_valor_atual: float
    percentual_quantidade_atual: float
    aprovada_atualmente: bool
    valor_a_adquirir: float
    quantidade_a_adquirir: int
    percentual_valor_projetado: float
    percentual_quantidade_projetado: float
    atingivel: bool
    passos: list[PassoAprovacao] = field(default_factory=list)


def _criterios_da_classe(classe: str) -> dict[str, bool]:
    return CRITERIOS_APROVACAO_CLASSE.get(classe, CRITERIOS_APROVACAO_PADRAO)


def simular_aprovacao_classe(credores: list[Credor], classe: str) -> SimulacaoAprovacaoClasse:
    """Simula a aquisição de créditos NÃO favoráveis (contrário ou indefinido) de
    uma classe até que ela ultrapasse 50% nos critérios que a lei exige para essa
    classe (valor, quantidade de credores, ou ambos).

    Estratégia gulosa em duas fases, já que os dois critérios (valor e
    quantidade) puxam para direções opostas — não há garantia matemática de
    ótimo global, é um cenário técnico razoável, não uma otimização exata:
    1. Se a classe exige valor: adquire primeiro os MAIORES créditos (mais
       valor por negociação), até bater 50%+ de valor.
    2. Se ainda faltar quantidade de credores: completa com os MENORES créditos
       disponíveis (mais barato para "comprar" um voto adicional por cabeça).
    """
    base = [c for c in credores if credor_utilizavel_para_analise(c) and c.classe == classe]
    valor_total = sum(c.valor for c in base)
    quantidade_total = len(base)

    favoraveis = [c for c in base if c.voto == VotoIntencao.FAVORAVEL]
    valor_favoravel = sum(c.valor for c in favoraveis)
    quantidade_favoravel = len(favoraveis)

    pct_valor_atual = valor_favoravel / valor_total if valor_total else 0.0
    pct_qtd_atual = quantidade_favoravel / quantidade_total if quantidade_total else 0.0

    criterios = _criterios_da_classe(classe)
    exige_valor = criterios["valor"]
    exige_quantidade = criterios["quantidade"]

    def _atende(valor_acum: float, qtd_acum: int) -> bool:
        ok_valor = (not exige_valor) or (valor_total > 0 and valor_acum > valor_total * 0.5)
        ok_qtd = (not exige_quantidade) or (quantidade_total > 0 and qtd_acum > quantidade_total * 0.5)
        return ok_valor and ok_qtd

    aprovada_atual = _atende(valor_favoravel, quantidade_favoravel)

    disponiveis = [c for c in base if c.voto != VotoIntencao.FAVORAVEL]
    adquiridos_ids: set[int] = set()
    valor_acumulado = valor_favoravel
    qtd_acumulada = quantidade_favoravel
    passos: list[PassoAprovacao] = []

    def _registrar_passo(c: Credor) -> None:
        nonlocal valor_acumulado, qtd_acumulada
        valor_acumulado += c.valor
        qtd_acumulada += 1
        adquiridos_ids.add(c.id)
        passos.append(
            PassoAprovacao(
                ordem=len(passos) + 1,
                nome=c.nome,
                documento=c.documento,
                valor=c.valor,
                valor_acumulado=valor_acumulado,
                percentual_valor_acumulado=valor_acumulado / valor_total if valor_total else 0.0,
                quantidade_acumulada=qtd_acumulada,
                percentual_quantidade_acumulado=qtd_acumulada / quantidade_total if quantidade_total else 0.0,
            )
        )

    def _valor_ok() -> bool:
        return (not exige_valor) or (valor_total > 0 and valor_acumulado > valor_total * 0.5)

    def _quantidade_ok() -> bool:
        return (not exige_quantidade) or (quantidade_total > 0 and qtd_acumulada > quantidade_total * 0.5)

    if not aprovada_atual:
        # Fase 1: ataca SÓ o critério de valor com os maiores créditos primeiro —
        # pára assim que o valor sozinho já basta, mesmo que a quantidade ainda
        # não tenha sido atingida (isso fica para a fase 2, mais barata).
        if exige_valor:
            for c in sorted(disponiveis, key=lambda c: c.valor, reverse=True):
                if _valor_ok():
                    break
                _registrar_passo(c)

        # Fase 2: completa a quantidade que ainda faltar com os MENORES créditos
        # disponíveis — mais barato por voto adicional do que continuar com os
        # maiores.
        if exige_quantidade and not _quantidade_ok():
            for c in sorted(disponiveis, key=lambda c: c.valor):
                if c.id in adquiridos_ids:
                    continue
                if _quantidade_ok():
                    break
                _registrar_passo(c)

    return SimulacaoAprovacaoClasse(
        classe=classe,
        exige_valor=exige_valor,
        exige_quantidade=exige_quantidade,
        valor_total=valor_total,
        quantidade_total=quantidade_total,
        valor_favoravel_atual=valor_favoravel,
        quantidade_favoravel_atual=quantidade_favoravel,
        percentual_valor_atual=pct_valor_atual,
        percentual_quantidade_atual=pct_qtd_atual,
        aprovada_atualmente=aprovada_atual,
        valor_a_adquirir=sum(p.valor for p in passos),
        quantidade_a_adquirir=len(passos),
        percentual_valor_projetado=valor_acumulado / valor_total if valor_total else 0.0,
        percentual_quantidade_projetado=qtd_acumulada / quantidade_total if quantidade_total else 0.0,
        atingivel=_atende(valor_acumulado, qtd_acumulada),
        passos=passos,
    )


def simular_aprovacao_todas_classes(credores: list[Credor]) -> list[SimulacaoAprovacaoClasse]:
    """Roda `simular_aprovacao_classe` para cada uma das 4 classes padrão de RJ
    presentes nos dados extraídos, na ordem I, II, III, IV.
    """
    classes_presentes = {c.classe for c in credores if credor_utilizavel_para_analise(c)}
    classes = [classe for classe in CLASSES_RJ_PADRAO if classe in classes_presentes]
    return [simular_aprovacao_classe(credores, classe) for classe in classes]
