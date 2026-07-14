"""Motor de fluxo de caixa livre — usado tanto pela Simulação Balão quanto
pelo Editor de Fluxo (o mesmo componente, conforme a especificação: adicionar
parcelas, excluir, alterar datas/valores/juros e recalcular automaticamente).

Funções puras — sem Streamlit, sem estado global.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.calculadora.amortizacao import adicionar_periodos, arredondar
from src.calculadora.models import FluxoItem, Periodicidade, TipoFluxoItem

_DIAS_MES_COMERCIAL = Decimal(30)


def novo_item(
    id_: int, data: date, descricao: str, tipo: TipoFluxoItem, valor: Decimal, editavel: bool = True
) -> FluxoItem:
    """Fábrica simples de `FluxoItem`, usada tanto pela geração automática
    quanto pelo botão "Adicionar parcela" da interface.
    """
    return FluxoItem(id=id_, data=data, descricao=descricao, tipo=tipo, valor=valor, editavel=editavel)


def gerar_fluxo_balao(
    principal: Decimal,
    valor_entrada: Decimal,
    data_inicial: date,
    prazo: int,
    periodicidade: Periodicidade,
    taxa_periodica: Decimal,
    intervalo_balao: int,
    valor_balao: Decimal,
) -> list[FluxoItem]:
    """Monta um fluxo inicial (entrada + parcelas regulares + balões
    periódicos a cada `intervalo_balao` parcelas) já com um valor de parcela
    regular estimado — a partir daí o usuário edita livremente qualquer item
    (adicionar, excluir, mover data, alterar valor).

    A estimativa da parcela regular usa a tabela Price sobre o saldo
    remanescente após deduzir o valor presente dos balões (descontados à
    própria taxa periódica informada), preservando o número total de parcelas.
    """
    if prazo <= 0:
        raise ValueError("O prazo deve ser maior que zero.")

    saldo_principal = principal - valor_entrada
    indices_balao = set(range(intervalo_balao, prazo + 1, intervalo_balao)) if intervalo_balao > 0 else set()
    indices_regulares = [i for i in range(1, prazo + 1) if i not in indices_balao]

    valor_presente_balao = Decimal(0)
    if valor_balao > 0:
        for i in indices_balao:
            if taxa_periodica == 0:
                valor_presente_balao += valor_balao
            else:
                valor_presente_balao += valor_balao / ((Decimal(1) + taxa_periodica) ** i)

    saldo_para_parcelas_regulares = saldo_principal - valor_presente_balao
    n_regulares = len(indices_regulares) or 1
    if saldo_para_parcelas_regulares <= 0:
        parcela_regular = Decimal(0)
    elif taxa_periodica == 0:
        parcela_regular = arredondar(saldo_para_parcelas_regulares / n_regulares)
    else:
        fator = (Decimal(1) + taxa_periodica) ** prazo
        parcela_regular = arredondar(saldo_para_parcelas_regulares * taxa_periodica * fator / (fator - 1))

    itens: list[FluxoItem] = []
    contador = 0
    if valor_entrada > 0:
        contador += 1
        itens.append(novo_item(contador, data_inicial, "Entrada", TipoFluxoItem.ENTRADA, valor_entrada, editavel=False))

    for i in range(1, prazo + 1):
        contador += 1
        data_parcela = adicionar_periodos(data_inicial, i, periodicidade)
        if i in indices_balao:
            itens.append(novo_item(contador, data_parcela, f"Balão {i}", TipoFluxoItem.BALAO, valor_balao))
        else:
            itens.append(novo_item(contador, data_parcela, f"Parcela {i}", TipoFluxoItem.PARCELA, parcela_regular))

    return itens


def recalcular_fluxo(fluxo: list[FluxoItem], principal: Decimal, taxa_periodica: Decimal, data_base: date) -> list[FluxoItem]:
    """Recalcula juros, amortização e saldo devedor de cada item do fluxo, na
    ordem cronológica: juros primeiro (sobre o saldo e o tempo decorrido desde
    o evento anterior), depois amortização do principal com o restante do
    pagamento — convenção padrão de amortização de dívida.

    Usa contagem de dias corridos sobre uma base de 30 dias/mês (mês
    comercial) para converter a taxa periódica informada em juros
    proporcionais ao intervalo real entre pagamentos, o que permite datas
    irregulares (essencial para "alteração manual do fluxo").
    """
    entradas = [item for item in fluxo if item.tipo == TipoFluxoItem.ENTRADA]
    demais = sorted((item for item in fluxo if item.tipo != TipoFluxoItem.ENTRADA), key=lambda i: i.data)

    saldo = principal
    for item in entradas:
        item.amortizacao = item.valor
        item.juros = Decimal(0)
        saldo -= item.valor
        item.saldo_devedor = saldo

    data_anterior = data_base
    for item in demais:
        dias = Decimal((item.data - data_anterior).days)
        periodos_decorridos = dias / _DIAS_MES_COMERCIAL if _DIAS_MES_COMERCIAL else Decimal(0)
        juros = arredondar(max(saldo, Decimal(0)) * taxa_periodica * periodos_decorridos)
        amortizacao = item.valor - juros
        saldo_final = saldo - amortizacao
        item.juros = juros
        item.amortizacao = amortizacao
        item.saldo_devedor = saldo_final
        saldo = saldo_final
        data_anterior = item.data

    return entradas + demais


def saldo_final(fluxo: list[FluxoItem]) -> Decimal:
    """Saldo devedor após o último evento do fluxo (idealmente próximo de zero)."""
    itens_com_saldo = [item for item in fluxo if item.saldo_devedor is not None]
    if not itens_com_saldo:
        return Decimal(0)
    return sorted(itens_com_saldo, key=lambda i: i.data)[-1].saldo_devedor  # type: ignore[return-value]


def recalcular_e_quitar_no_ultimo_evento(
    fluxo: list[FluxoItem], principal: Decimal, taxa_periodica: Decimal, data_base: date
) -> list[FluxoItem]:
    """Recalcula o fluxo e, se sobrar (ou faltar) saldo devedor ao final, ajusta
    o valor do último evento editável para zerá-lo exatamente — mesma
    convenção de "última parcela absorve o resíduo" usada no cronograma
    Price/SAC. Só é chamado na geração automática inicial; edições manuais
    subsequentes do usuário chamam apenas `recalcular_fluxo`, preservando o
    saldo residual como informação (o usuário decide como zerá-lo).
    """
    recalculado = recalcular_fluxo(fluxo, principal, taxa_periodica, data_base)
    residual = saldo_final(recalculado)
    if residual == 0:
        return recalculado

    candidatos = [item for item in reversed(recalculado) if item.editavel]
    if not candidatos:
        return recalculado
    candidatos[0].valor += residual
    return recalcular_fluxo(recalculado, principal, taxa_periodica, data_base)
