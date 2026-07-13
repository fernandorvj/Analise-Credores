"""Extração estruturada de credores a partir do texto/tabelas lidos do PDF.

Estratégia por página:
1. Se a página tem tabelas com um cabeçalho reconhecível (Nome, CPF/CNPJ, Classe, Valor),
   usa as linhas da tabela diretamente — é a fonte mais confiável.
2. Caso contrário, tenta extrair por linha de texto usando padrões de CPF/CNPJ e valor
   monetário como âncoras.

Um registro nunca é descartado por ter um campo ambíguo: ele é marcado com
StatusLeitura.REVISAR ou ERRO e mantido na relação, para revisão humana.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import CLASSES_RJ_PADRAO, configurar_logging
from src.leitor_pdf import PaginaExtraida
from src.models import Credor, ResultadoExtracao, StatusLeitura, TipoDocumento
from src.utils import (
    formatar_documento,
    identificar_tipo_documento,
    limpar_espacos,
    parse_valor_brl,
    somente_digitos,
)

logger = configurar_logging()

_RE_DOCUMENTO = re.compile(
    r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}"  # CPF: 000.000.000-00
    r"|\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"  # CNPJ: 00.000.000/0000-00
)

_RE_VALOR_MONETARIO = re.compile(r"R?\$?\s*-?\d[\d.,]*\d")

# Ordem importa: classes mais específicas (IV, III) são checadas antes das mais
# genéricas para blindar contra o \b não bastar em algum caso de entrada malformada.
_PADROES_CLASSE = [
    ("Classe IV - ME/EPP", re.compile(r"classe\s+iv\b|classe\s+4\b|me\s*/\s*epp|microempresa", re.IGNORECASE)),
    ("Classe III - Quirografário", re.compile(r"classe\s+iii\b|classe\s+3\b|quirograf", re.IGNORECASE)),
    ("Classe II - Garantia Real", re.compile(r"classe\s+ii\b|classe\s+2\b|garantia\s+real", re.IGNORECASE)),
    ("Classe I - Trabalhista", re.compile(r"classe\s+i\b|classe\s+1\b|trabalhista", re.IGNORECASE)),
]

# Palavras-chave (não nomes exatos de coluna) usadas para reconhecer cabeçalhos de
# tabela reais, que variam muito entre tribunais/administradores judiciais
# (ex.: "Valor\nem R$", "Classificação", "Credor"). Checadas por substring — não
# por igualdade exata — na ordem abaixo (nome antes de documento, etc.).
_PALAVRAS_CABECALHO_NOME = ("nome", "credor", "razão social", "razao social")
_PALAVRAS_CABECALHO_DOCUMENTO = ("cpf/cnpj", "cpf", "cnpj", "documento")
_PALAVRAS_CABECALHO_CLASSE = ("classificação", "classificacao", "classe")
_PALAVRAS_CABECALHO_VALOR = ("valor",)

_PADRAO_SUBTOTAL = re.compile(r"^(sub[\s-]?total|total)$", re.IGNORECASE)
_PADRAO_TOTAL_GERAL = re.compile(r"^total\s+geral$", re.IGNORECASE)

# Marcador usado quando a coluna de nome vem vazia — geralmente um fragmento de
# tabela sem informação real (não um credor de verdade), por isso é removido
# por completo do resultado (ver `_remover_credores_sem_nome`), e não apenas
# marcado para revisão.
_NOME_NAO_IDENTIFICADO = "(nome não identificado)"


def _identificar_classe(texto: str) -> str:
    for classe, padrao in _PADROES_CLASSE:
        if padrao.search(texto):
            return classe
    return "Não identificada"


def _mapear_cabecalho(cabecalho: list[str | None]) -> dict[str, int] | None:
    """Tenta mapear colunas de uma tabela para nome/documento/classe/valor.

    Retorna None se o cabeçalho não for reconhecível — sinal para usar o
    parser baseado em texto em vez de confiar na estrutura da tabela.
    """
    mapa: dict[str, int] = {}
    for indice, coluna in enumerate(cabecalho):
        if not coluna:
            continue
        # limpar_espacos colapsa quebras de linha internas (ex.: "Valor\nem R$")
        # em espaço simples, permitindo casar por substring.
        coluna_norm = limpar_espacos(coluna).lower()
        if any(palavra in coluna_norm for palavra in _PALAVRAS_CABECALHO_NOME):
            mapa["nome"] = indice
        elif any(palavra in coluna_norm for palavra in _PALAVRAS_CABECALHO_DOCUMENTO):
            mapa["documento"] = indice
        elif any(palavra in coluna_norm for palavra in _PALAVRAS_CABECALHO_CLASSE):
            mapa["classe"] = indice
        elif any(palavra in coluna_norm for palavra in _PALAVRAS_CABECALHO_VALOR):
            mapa["valor"] = indice

    if "nome" in mapa and "valor" in mapa:
        return mapa
    return None


def _campo_tabela(linha: list[str | None], mapa: dict[str, int], chave: str) -> str:
    indice = mapa.get(chave)
    if indice is None or indice >= len(linha) or linha[indice] is None:
        return ""
    return limpar_espacos(linha[indice])


def _criar_credor_de_tabela(
    linha: list[str | None], mapa: dict[str, int], id_credor: int, pagina: int
) -> Credor:
    nome = _campo_tabela(linha, mapa, "nome")
    documento_bruto = _campo_tabela(linha, mapa, "documento")
    classe_bruta = _campo_tabela(linha, mapa, "classe")
    valor_bruto = _campo_tabela(linha, mapa, "valor")

    tipo_doc, doc_valido = identificar_tipo_documento(documento_bruto) if documento_bruto else (
        TipoDocumento.INDEFINIDO,
        False,
    )
    valor = parse_valor_brl(valor_bruto)
    classe = _identificar_classe(classe_bruta) if classe_bruta else "Não identificada"
    if classe == "Não identificada" and classe_bruta:
        classe = classe_bruta  # preserva o texto original em vez de descartar a informação

    status, observacoes = _avaliar_qualidade(nome, documento_bruto, doc_valido, valor, classe)

    return Credor(
        id=id_credor,
        nome=nome or _NOME_NAO_IDENTIFICADO,
        documento=formatar_documento(documento_bruto) if documento_bruto else "",
        tipo_documento=tipo_doc,
        classe=classe,
        valor=valor,
        pagina=pagina,
        status_leitura=status,
        observacoes=observacoes,
        texto_origem=" | ".join(c or "" for c in linha),
    )


def _avaliar_qualidade(
    nome: str, documento_bruto: str, doc_valido: bool, valor: float | None, classe: str
) -> tuple[StatusLeitura, str]:
    problemas = []
    if not nome:
        problemas.append("nome não identificado")
    if valor is None:
        problemas.append("valor não identificado")
    if classe not in CLASSES_RJ_PADRAO:
        problemas.append("classe não identificada")
    if documento_bruto and not doc_valido:
        problemas.append("dígito verificador do documento inválido")
    # Documento ausente não é tratado como problema: muitas relações de
    # credores (ex.: listas simplificadas do administrador judicial) não
    # trazem CPF/CNPJ, e isso não indica erro de leitura.

    # Sem nome, valor ou classe reconhecida, o credor não pode entrar nas
    # análises por classe (quórum, aprovação do plano) — é tratado como ERRO e
    # fica de fora dos totais até ser corrigido manualmente, para nunca gerar
    # inconsistência entre o passivo total e a soma das 4 classes.
    if not nome or valor is None or classe not in CLASSES_RJ_PADRAO:
        return StatusLeitura.ERRO, "; ".join(problemas)
    if problemas:
        return StatusLeitura.REVISAR, "; ".join(problemas)
    return StatusLeitura.OK, ""


_MAX_LINHAS_BUSCA_CABECALHO = 3  # cabeçalho pode vir depois de linha(s) de título mesclada(s)


def _localizar_cabecalho(tabela: list[list[str | None]]) -> tuple[dict[str, int] | None, int]:
    """Procura um cabeçalho reconhecível nas primeiras linhas da tabela (a linha 0
    às vezes é um título mesclado, ex.: "SEGUNDA RELAÇÃO DE CREDORES - ...", não
    o cabeçalho de fato). Retorna (mapa, índice da primeira linha de dados).
    """
    for indice, linha in enumerate(tabela[:_MAX_LINHAS_BUSCA_CABECALHO]):
        mapa = _mapear_cabecalho(linha)
        if mapa:
            return mapa, indice + 1
    return None, 0


@dataclass
class _EstadoTabelas:
    """Estado que precisa atravessar páginas: tabelas de relações de credores
    frequentemente continuam por várias páginas sem repetir o cabeçalho nem a
    classe corrente (a linha de SUB-TOTAL de uma classe pode cair logo no topo
    da página seguinte).
    """

    mapa_cabecalho: dict[str, int] | None = None
    ultima_classe: str = "Não identificada"


def _extrair_de_tabelas(
    pagina: PaginaExtraida,
    proximo_id: int,
    estado: _EstadoTabelas,
    resultado: ResultadoExtracao,
) -> list[Credor] | None:
    """Extrai credores das tabelas da página, mutando `estado` (cabeçalho/classe
    correntes) e `resultado` (subtotais do documento) para uso pelas páginas
    seguintes e pela reconciliação final.

    Tabelas de relações de credores frequentemente continuam por várias páginas
    sem repetir o cabeçalho. Quando a página não tem um cabeçalho reconhecível
    (nem na linha 0, nem nas seguintes), reaproveitamos o último cabeçalho válido
    (de uma página anterior) e tratamos a tabela inteira como dados — em vez de
    descartar a primeira linha como se fosse cabeçalho.

    Linhas de "SUB-TOTAL" e "TOTAL GERAL" nunca viram credores, mas seus valores
    são capturados em `resultado.subtotais_documento` / `total_geral_documento`
    — são os números que o próprio documento imprime, usados para conferir a
    extração (ferramentas de tabela podem perder linhas silenciosamente em
    quebras de página).
    """
    for tabela in pagina.tabelas:
        if not tabela:
            continue

        mapa, indice_dados = _localizar_cabecalho(tabela)
        if mapa:
            linhas_dados = tabela[indice_dados:]
        elif estado.mapa_cabecalho:
            mapa = estado.mapa_cabecalho
            linhas_dados = tabela
        else:
            continue

        credores = []
        for linha in linhas_dados:
            if not any(linha):
                continue

            nome_bruto = _campo_tabela(linha, mapa, "nome")
            valor_linha = parse_valor_brl(_campo_tabela(linha, mapa, "valor"))

            if _PADRAO_TOTAL_GERAL.match(nome_bruto):
                if valor_linha is not None:
                    resultado.total_geral_documento = valor_linha
                continue
            if _PADRAO_SUBTOTAL.match(nome_bruto):
                if valor_linha is not None:
                    resultado.subtotais_documento[estado.ultima_classe] = valor_linha
                continue

            credor = _criar_credor_de_tabela(linha, mapa, proximo_id, pagina.numero)
            estado.ultima_classe = credor.classe
            credores.append(credor)
            proximo_id += 1

        estado.mapa_cabecalho = mapa
        if credores:
            return credores
    return None


def _extrair_de_linha_texto(linha: str, id_credor: int, pagina: int) -> Credor | None:
    linha = limpar_espacos(linha)
    if not linha:
        return None

    doc_match = _RE_DOCUMENTO.search(linha)
    if not doc_match:
        return None  # linha sem documento não é considerada um registro de credor

    documento_bruto = doc_match.group(0)
    tipo_doc, doc_valido = identificar_tipo_documento(documento_bruto)

    nome = limpar_espacos(linha[: doc_match.start()])
    resto = linha[doc_match.end():]

    valores_encontrados = _RE_VALOR_MONETARIO.findall(resto)
    valor_bruto = valores_encontrados[-1] if valores_encontrados else ""
    valor = parse_valor_brl(valor_bruto) if valor_bruto else None

    classe = _identificar_classe(resto)

    status, observacoes = _avaliar_qualidade(nome, documento_bruto, doc_valido, valor, classe)

    return Credor(
        id=id_credor,
        nome=nome or _NOME_NAO_IDENTIFICADO,
        documento=formatar_documento(documento_bruto),
        tipo_documento=tipo_doc,
        classe=classe,
        valor=valor,
        pagina=pagina,
        status_leitura=status,
        observacoes=observacoes,
        texto_origem=linha,
    )


_LINHAS_IGNORADAS = re.compile(
    r"^(relação de credores|processo|página|classe\s|nome\s+cpf|sub[\s-]?total|total\s+geral|total\b)",
    re.IGNORECASE,
)


def _extrair_de_texto(pagina: PaginaExtraida, proximo_id: int) -> list[Credor]:
    credores = []
    for linha in pagina.texto.splitlines():
        if _LINHAS_IGNORADAS.match(linha.strip()):
            continue
        credor = _extrair_de_linha_texto(linha, proximo_id, pagina.numero)
        if credor:
            credores.append(credor)
            proximo_id += 1
    return credores


# --- Extração por "ficha" (um campo por bloco de texto) -----------------
#
# Alguns PDFs escaneados (gerados de formulário) trazem cada credor como uma
# ficha vertical — nome, documento, valor e classe cada um em seu próprio
# bloco de linhas, separados por linha(s) em branco, em vez de tudo em uma
# única linha de tabela. O parser de linha de texto acima não funciona nesse
# formato (não há nome+documento+valor na mesma linha). Este parser usa o
# documento (CPF/CNPJ) como âncora e lê nome/valor/classe pela posição fixa
# ao redor dele: [NOME] [DOCUMENTO] ["R$"] [VALOR] [CLASSE] ...

_RE_DOCUMENTO_COMPLETO = re.compile(
    r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"  # CPF isolado no bloco
    r"|^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"  # CNPJ isolado no bloco
)
_RE_INDICE_ISOLADO = re.compile(r"^\d{1,4}$")  # bloco só com um número (índice da ficha, ex.: "10")


def _agrupar_blocos(texto: str) -> list[str]:
    """Agrupa linhas de texto em blocos (um campo de ficha cada), separados por
    linha(s) em branco. Linhas dentro do mesmo bloco (ex.: endereço quebrado em
    duas linhas) são unidas com espaço.
    """
    blocos: list[str] = []
    linhas_bloco: list[str] = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha:
            linhas_bloco.append(linha)
        elif linhas_bloco:
            blocos.append(limpar_espacos(" ".join(linhas_bloco)))
            linhas_bloco = []
    if linhas_bloco:
        blocos.append(limpar_espacos(" ".join(linhas_bloco)))
    return blocos


def _extrair_de_blocos(pagina: PaginaExtraida, proximo_id: int) -> list[Credor]:
    """Extrai credores de PDFs em formato de ficha (ver módulo acima)."""
    blocos = _agrupar_blocos(pagina.texto)
    credores: list[Credor] = []

    for i, bloco in enumerate(blocos):
        if not _RE_DOCUMENTO_COMPLETO.match(bloco):
            continue

        documento_bruto = bloco
        tipo_doc, doc_valido = identificar_tipo_documento(documento_bruto)

        nome = ""
        if i > 0:
            candidato = blocos[i - 1]
            nome = "" if _RE_INDICE_ISOLADO.match(candidato) else candidato

        k = i + 1
        if k < len(blocos) and blocos[k].upper() == "R$":
            k += 1
        valor = parse_valor_brl(blocos[k]) if k < len(blocos) else None
        k += 1
        classe_bruta = blocos[k] if k < len(blocos) else ""

        classe = _identificar_classe(classe_bruta) if classe_bruta else "Não identificada"
        if classe == "Não identificada" and classe_bruta:
            classe = classe_bruta

        status, observacoes = _avaliar_qualidade(nome, documento_bruto, doc_valido, valor, classe)

        credores.append(
            Credor(
                id=proximo_id,
                nome=nome or _NOME_NAO_IDENTIFICADO,
                documento=formatar_documento(documento_bruto),
                tipo_documento=tipo_doc,
                classe=classe,
                valor=valor,
                pagina=pagina.numero,
                status_leitura=status,
                observacoes=observacoes,
                texto_origem=bloco,
            )
        )
        proximo_id += 1

    return credores


_TOLERANCIA_RECONCILIACAO = 0.01  # diferenças de centavos (arredondamento) não geram aviso


def _reconciliar_com_documento(resultado: ResultadoExtracao) -> None:
    """Compara os subtotais/total geral impressos no PDF contra o que foi
    efetivamente extraído, e registra avisos quando não baterem — nunca corrige
    os dados automaticamente, apenas sinaliza para revisão humana.
    """
    somas_por_classe: dict[str, float] = {}
    for credor in resultado.credores:
        if credor.valor is not None:
            somas_por_classe[credor.classe] = somas_por_classe.get(credor.classe, 0.0) + credor.valor

    for classe, valor_documento in resultado.subtotais_documento.items():
        valor_extraido = somas_por_classe.get(classe, 0.0)
        diferenca = valor_documento - valor_extraido
        if abs(diferenca) > _TOLERANCIA_RECONCILIACAO:
            resultado.avisos_reconciliacao.append(
                f"Subtotal de '{classe}' no documento é {valor_documento:,.2f}, mas a soma dos "
                f"credores extraídos é {valor_extraido:,.2f} (diferença de {diferenca:,.2f}) — "
                "possível perda de linha(s) na extração da tabela nesta classe."
            )

    if resultado.total_geral_documento is not None:
        total_extraido = sum(somas_por_classe.values())
        diferenca = resultado.total_geral_documento - total_extraido
        if abs(diferenca) > _TOLERANCIA_RECONCILIACAO:
            resultado.avisos_reconciliacao.append(
                f"Total geral no documento é {resultado.total_geral_documento:,.2f}, mas a soma "
                f"de todos os credores extraídos é {total_extraido:,.2f} (diferença de "
                f"{diferenca:,.2f})."
            )


def _remover_linhas_de_total(credores: list[Credor]) -> list[Credor]:
    """Remove defensivamente qualquer registro cujo nome seja uma linha de
    SUB-TOTAL/TOTAL GERAL — essas nunca são credores, apenas somas impressas
    pelo próprio documento (já capturadas separadamente em
    `resultado.subtotais_documento`/`total_geral_documento`). A extração via
    tabela já as filtra na origem; este é um filtro de segurança para o caminho
    de extração por texto, que não passa pelo mesmo filtro.
    """
    return [
        c
        for c in credores
        if not _PADRAO_SUBTOTAL.match(limpar_espacos(c.nome))
        and not _PADRAO_TOTAL_GERAL.match(limpar_espacos(c.nome))
    ]


def _remover_credores_sem_nome(credores: list[Credor]) -> list[Credor]:
    """Remove por completo os registros sem nome identificado — sem nome não há
    como saber quem é o credor nem revisar manualmente, então (a pedido do
    usuário) são descartados junto com qualquer valor que tragam, em vez de
    ficarem pendentes de revisão.
    """
    return [c for c in credores if c.nome != _NOME_NAO_IDENTIFICADO]


def _chave_consolidacao(credor: Credor) -> tuple[str, str, str]:
    """Chave de agrupamento para consolidar credores duplicados: mesma classe e,
    dentro dela, mesmo CPF/CNPJ (quando presente) ou mesmo nome normalizado
    (quando não há documento).
    """
    documento_normalizado = somente_digitos(credor.documento)
    if documento_normalizado:
        return (credor.classe, "documento", documento_normalizado)
    return (credor.classe, "nome", limpar_espacos(credor.nome).upper())


def _mesclar_credores(membros: list[Credor]) -> Credor:
    """Funde um grupo de credores duplicados (mesma classe, mesmo CPF/CNPJ ou
    nome) em um único registro com o valor somado. Nunca descarta informação:
    a fusão é sempre registrada nas observações, com as páginas de origem.
    """
    primeiro = min(membros, key=lambda c: c.id)
    valor_total = sum(c.valor for c in membros)
    paginas = sorted({c.pagina for c in membros})
    documento = next((c.documento for c in membros if c.documento), "")
    tipo_documento = next((c.tipo_documento for c in membros if c.documento), primeiro.tipo_documento)

    status = StatusLeitura.OK
    outras_observacoes = []
    for c in membros:
        if c.status_leitura == StatusLeitura.REVISAR:
            status = StatusLeitura.REVISAR
        if c.observacoes:
            outras_observacoes.append(c.observacoes)

    nota_fusao = (
        f"Consolidado a partir de {len(membros)} lançamentos "
        f"(página(s) {', '.join(str(p) for p in paginas)}) — valores somados."
    )
    observacoes = "; ".join(dict.fromkeys([nota_fusao, *outras_observacoes]))  # remove duplicatas, preserva ordem

    return Credor(
        id=primeiro.id,
        nome=primeiro.nome,
        documento=documento,
        tipo_documento=tipo_documento,
        classe=primeiro.classe,
        valor=valor_total,
        pagina=paginas[0],
        status_leitura=status,
        observacoes=observacoes,
        texto_origem=" || ".join(c.texto_origem for c in membros if c.texto_origem),
    )


def consolidar_credores_duplicados(credores: list[Credor]) -> list[Credor]:
    """Funde, dentro de cada classe, credores duplicados (mesmo CPF/CNPJ, ou
    mesmo nome quando não há documento) em um único registro com o valor
    somado — para refletir o peso real de cada credor na classe.

    Apenas credores com valor identificado entram na consolidação; registros
    com erro de leitura (sem valor) nunca são fundidos, pois não há valor
    confiável para somar.
    """
    fundiveis = [c for c in credores if c.valor is not None]
    nao_fundiveis = [c for c in credores if c.valor is None]

    grupos: dict[tuple[str, str, str], list[Credor]] = {}
    ordem_grupos: list[tuple[str, str, str]] = []
    for c in fundiveis:
        chave = _chave_consolidacao(c)
        if chave not in grupos:
            grupos[chave] = []
            ordem_grupos.append(chave)
        grupos[chave].append(c)

    consolidados = [
        grupos[chave][0] if len(grupos[chave]) == 1 else _mesclar_credores(grupos[chave])
        for chave in ordem_grupos
    ]
    consolidados.sort(key=lambda c: c.id)
    return consolidados + nao_fundiveis


def parsear_credores(paginas: list[PaginaExtraida], arquivo_nome: str) -> ResultadoExtracao:
    """Extrai todos os credores de uma lista de páginas já lidas do PDF."""
    resultado = ResultadoExtracao(arquivo_nome=arquivo_nome, total_paginas=len(paginas))
    proximo_id = 1
    estado = _EstadoTabelas()

    for pagina in paginas:
        if pagina.fonte == "ocr_indisponivel":
            resultado.paginas_com_erro.append(pagina.numero)
            continue
        if pagina.fonte == "ocr":
            resultado.paginas_ocr.append(pagina.numero)

        credores_tabela = _extrair_de_tabelas(pagina, proximo_id, estado, resultado)
        if credores_tabela is not None:
            resultado.credores.extend(credores_tabela)
            proximo_id += len(credores_tabela)
            continue

        credores_texto = _extrair_de_texto(pagina, proximo_id)
        # Se nenhum registro tem nome de verdade, o parser de linha não serve
        # para o layout desta página (ex.: "ficha por credor", um campo por
        # linha) — tenta o parser de blocos antes de aceitar o resultado vazio.
        if not any(c.nome != _NOME_NAO_IDENTIFICADO for c in credores_texto):
            credores_texto = _extrair_de_blocos(pagina, proximo_id)
        resultado.credores.extend(credores_texto)
        proximo_id += len(credores_texto)

    resultado.credores = _remover_linhas_de_total(resultado.credores)
    resultado.credores = _remover_credores_sem_nome(resultado.credores)
    _reconciliar_com_documento(resultado)

    total_antes_consolidacao = len(resultado.credores)
    resultado.credores = consolidar_credores_duplicados(resultado.credores)
    duplicados_consolidados = total_antes_consolidacao - len(resultado.credores)

    logger.info(
        "Parser concluído para '%s': %d credores (%d ok, %d p/ revisar, %d com erro, "
        "%d duplicado(s) consolidado(s), %d aviso(s) de reconciliação).",
        arquivo_nome,
        resultado.total_credores,
        len(resultado.credores_validos),
        len(resultado.credores_para_revisar),
        len(resultado.credores_com_erro),
        duplicados_consolidados,
        len(resultado.avisos_reconciliacao),
    )
    return resultado
