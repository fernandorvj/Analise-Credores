"""Funções utilitárias: validação de documentos, parsing de valores monetários
e formatação — usadas por todo o pipeline de extração e análise.
"""

from __future__ import annotations

import re

from config import CLASSES_RJ_PADRAO
from src.models import Credor, TipoDocumento

_RE_NAO_DIGITO = re.compile(r"\D")


def somente_digitos(texto: str) -> str:
    """Remove tudo que não for dígito."""
    return _RE_NAO_DIGITO.sub("", texto or "")


def validar_cpf(cpf: str) -> bool:
    """Valida um CPF pelos dígitos verificadores (algoritmo módulo 11)."""
    cpf = somente_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    for i in (9, 10):
        soma = sum(int(cpf[num]) * ((i + 1) - num) for num in range(0, i))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[i]):
            return False
    return True


def validar_cnpj(cnpj: str) -> bool:
    """Valida um CNPJ pelos dígitos verificadores (algoritmo módulo 11)."""
    cnpj = somente_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False

    pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    for pesos, pos in ((pesos_1, 12), (pesos_2, 13)):
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(len(pesos)))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(cnpj[pos]):
            return False
    return True


def identificar_tipo_documento(documento: str) -> tuple[TipoDocumento, bool]:
    """Identifica se um documento é CPF ou CNPJ e se seus dígitos verificadores são válidos.

    Retorna (tipo, valido). Se não for possível classificar pelo tamanho,
    retorna (INDEFINIDO, False) — nunca inventa um tipo.
    """
    digitos = somente_digitos(documento)
    if len(digitos) == 11:
        return TipoDocumento.CPF, validar_cpf(digitos)
    if len(digitos) == 14:
        return TipoDocumento.CNPJ, validar_cnpj(digitos)
    return TipoDocumento.INDEFINIDO, False


def formatar_documento(documento: str) -> str:
    """Formata CPF (000.000.000-00) ou CNPJ (00.000.000/0000-00) para exibição."""
    digitos = somente_digitos(documento)
    if len(digitos) == 11:
        return f"{digitos[0:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:11]}"
    if len(digitos) == 14:
        return f"{digitos[0:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:14]}"
    return documento


_RE_VALOR_BR = re.compile(
    r"-?\d{1,3}(?:\.\d{3})+,\d{2}"  # 1.234.567,89 (agrupado, com centavos)
    r"|-?\d+,\d{2}"  # 1234,89 (sem agrupamento, com centavos)
    r"|-?\d{1,3}(?:\.\d{3})+"  # 1.234.567 (agrupado, sem centavos)
    r"|-?\d+"  # 1234 (inteiro simples)
)


def parse_valor_brl(texto: str) -> float | None:
    """Converte um valor monetário no formato brasileiro (ex.: 'R$ 1.234,56') em float.

    Retorna None se não for possível interpretar o texto com confiança —
    nunca tenta "adivinhar" um número a partir de texto ambíguo.
    """
    if not texto:
        return None

    limpo = texto.strip().replace("R$", "").strip()
    match = _RE_VALOR_BR.search(limpo)
    if not match:
        return None

    valor_str = match.group(0)
    valor_str = valor_str.replace(".", "").replace(",", ".")
    try:
        return float(valor_str)
    except ValueError:
        return None


def formatar_moeda(valor: float | None) -> str:
    """Formata um float como moeda brasileira: R$ 1.234,56."""
    if valor is None:
        return "-"
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def formatar_percentual(valor: float | None, casas: int = 2) -> str:
    """Formata uma fração (0-1) como percentual: 0.1234 -> 12,34%."""
    if valor is None:
        return "-"
    texto = f"{valor * 100:.{casas}f}"
    texto = texto.replace(".", ",")
    return f"{texto}%"


def limpar_espacos(texto: str) -> str:
    """Colapsa espaços múltiplos e remove espaços nas bordas."""
    return re.sub(r"\s+", " ", (texto or "")).strip()


def credor_utilizavel_para_analise(credor: Credor) -> bool:
    """Um credor só entra nas tabelas, gráficos e simulações (quórum, aprovação
    por classe) quando tem valor identificado E uma classe reconhecida (uma das
    4 classes padrão de RJ).

    Sem uma classe válida não há como calcular quórum/percentual por classe —
    incluir esses registros geraria inconsistência entre o total geral exibido
    e a soma das classes usada na estratégia (ex.: o passivo total mostrado nos
    KPIs não bateria com a soma das 4 classes na aba de Aprovação do Plano).

    Esses credores nunca são descartados: continuam em `resultado.credores`
    (com status ERRO) e visíveis em "Pendências de Revisão", para correção
    manual — apenas ficam fora das análises agregadas até serem corrigidos.
    """
    return credor.valor is not None and credor.classe in CLASSES_RJ_PADRAO


# Nomes de coluna usados de forma consistente pelos DataFrames de análise
# (src/analise_quorum.py, src/estrategia.py) — centralizados aqui para que a
# exportação Excel e o dashboard Streamlit apliquem a mesma formatação.
COLUNAS_MOEDA_PADRAO = {"Valor", "Valor Total", "Valor Alvo", "Valor a Adquirir", "Valor Necessário"}
COLUNAS_PERCENTUAL_PADRAO = {
    "% da Classe",
    "% do Passivo Total",
    "% do Total",
    "Participação Acumulada",
    "Quórum Alvo",
    "Quórum Atingido",
}
