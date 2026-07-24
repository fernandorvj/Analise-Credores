"""Módulo Precificação Inteligente de Créditos.

A IA tem uma única responsabilidade: ler o Plano de Recuperação Judicial e
localizar as condições de pagamento previstas para cada classe de credores
(deságio, carência, correção, juros, parcelas, datas, balão, exceções) —
nunca calcula nada. Todo o cálculo de VPL é feito em Python puro, 100%
determinístico e auditável (`src/calculadora/precificacao_motor.py`).

*** METODOLOGIA PROVISÓRIA: a convenção de desconto (XNPV) ainda não foi
comparada com a planilha oficial de cálculo de VPL da AMF3 Capital — a
interface exibe esse aviso enquanto isso não for confirmado. ***
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import CLASSES_RJ_PADRAO, CORES, EXPORTADOS_DIR, PETICOES_DIR, possui_chave_openai
from interface import layout
from interface.calculadora.componentes import aplicar_tema_escuro_grafico, campo_moeda, container_grafico, renderizar_kpis
from interface.componentes_ui import renderizar_preview_arquivo, tabela_premium
from interface.icones import icone
from src import ia, leitor_pdf
from src.calculadora.amortizacao import adicionar_periodos, converter_taxa
from src.calculadora.indices import obter_cdi_bacen, obter_igpm_12m_bacen, obter_ipca_12m_bacen, obter_tr_bacen
from src.calculadora.models import Periodicidade, RegimeJuros
from src.calculadora.precificacao_motor import (
    LinhaCronogramaPercentual,
    LinhaFluxoInformado,
    ParametrosCalculoClasse,
    ParametrosCalculoClasseComCronogramaPercentual,
    ParametrosCalculoClasseComProjecao,
    calcular_precificacao_classe,
    calcular_precificacao_classe_com_cronograma_percentual,
    calcular_precificacao_classe_com_projecao,
)
from src.calculadora.selic import ORIGEM_MANUAL, obter_selic_bacen
from src.exportar_excel_precificacao import exportar_excel_precificacao
from src.exportar_word_precificacao import exportar_word_precificacao
from src.models_peticao_inicial import NAO_LOCALIZADO
from src.models_precificacao import (
    CondicoesPagamentoClasse,
    CronogramaAmortizacaoClasse,
    ExtracaoPlanoPorClasse,
    ProjecaoFluxoAnualClasse,
    ResultadoPrecificacaoClasse,
)
from src.utils import formatar_moeda, formatar_percentual, parse_valor_brl

_FASES_PDF = ["Lendo PDF", "Extraindo texto", "Organizando documento", "Consultando IA", "Extraindo condições"]
_FASES_TEXTO = ["Organizando texto", "Consultando IA", "Extraindo condições"]

_OPCOES_INDICE = ["Nenhum", "IPCA", "CDI", "IGP-M", "TR", "SELIC"]
_INDICE_FUNCOES = {"IPCA": obter_ipca_12m_bacen, "CDI": obter_cdi_bacen, "IGP-M": obter_igpm_12m_bacen, "TR": obter_tr_bacen}

_MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}


# --- Etapa 1/2: importação e extração ---------------------------------------


def _processar_pdf(arquivo) -> ExtracaoPlanoPorClasse | None:
    if not possui_chave_openai():
        st.warning("Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar a extração.")
        return None

    caminho_pdf = PETICOES_DIR / arquivo.name
    caminho_pdf.write_bytes(arquivo.getvalue())

    with st.status("Analisando Plano de Recuperação Judicial...", expanded=True) as status:
        barra = st.progress(0.0)

        def _concluir_fase(indice: int) -> None:
            st.write(f"{icone('concluido')} {_FASES_PDF[indice]}")
            barra.progress((indice + 1) / len(_FASES_PDF))

        paginas = leitor_pdf.ler_pdf_robusto(caminho_pdf)
        texto = "\n\n".join(f"--- Página {p.numero} ---\n{p.texto}" for p in paginas)
        _concluir_fase(0)
        _concluir_fase(1)
        _concluir_fase(2)

        def _callback(mensagem: str) -> None:
            status.update(label=mensagem)
            st.write(mensagem)

        try:
            extracao = ia.extrair_condicoes_plano(texto, arquivo.name, progress_callback=_callback)
        except RuntimeError as exc:
            status.update(label="Falha ao consultar a IA", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(3)
        _concluir_fase(4)
        status.update(label="Condições extraídas com sucesso!", state="complete", expanded=False)

    return extracao


def _processar_texto_colado(texto: str) -> ExtracaoPlanoPorClasse | None:
    if not possui_chave_openai():
        st.warning("Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY para habilitar a extração.")
        return None

    with st.status("Analisando trecho colado...", expanded=True) as status:
        barra = st.progress(0.0)

        def _concluir_fase(indice: int) -> None:
            st.write(f"{icone('concluido')} {_FASES_TEXTO[indice]}")
            barra.progress((indice + 1) / len(_FASES_TEXTO))

        _concluir_fase(0)

        def _callback(mensagem: str) -> None:
            status.update(label=mensagem)
            st.write(mensagem)

        try:
            extracao = ia.extrair_condicoes_plano(texto, "Trecho colado pelo usuário", progress_callback=_callback)
        except RuntimeError as exc:
            status.update(label="Falha ao consultar a IA", state="error")
            st.error(str(exc))
            return None
        _concluir_fase(1)
        _concluir_fase(2)
        status.update(label="Condições extraídas com sucesso!", state="complete", expanded=False)

    return extracao


def _renderizar_quadro_geral(extracao: ExtracaoPlanoPorClasse) -> None:
    for aviso in extracao.avisos:
        st.info(aviso)

    geral = extracao.condicoes_gerais
    tem_condicao_geral = any(
        getattr(geral, campo) != NAO_LOCALIZADO
        for campo in ("desagio", "carencia", "correcao_monetaria_indice", "juros", "periodicidade")
    )
    if tem_condicao_geral or geral.descricao:
        st.markdown("#### Condições Gerais do Plano (válidas para todas as classes)")
        st.caption(
            "Regras declaradas uma única vez no Plano, aplicáveis a todo o Quadro Geral de Credores — "
            "já refletidas abaixo em cada classe que não tem uma condição específica própria."
        )
        if geral.descricao:
            st.info(geral.descricao)
        linhas_gerais = [
            {"Condição": "Deságio", "Valor": geral.desagio},
            {"Condição": "Carência", "Valor": geral.carencia},
            {"Condição": "Correção Monetária", "Valor": geral.correcao_monetaria_indice},
            {"Condição": "Juros", "Valor": geral.juros},
            {"Condição": "Periodicidade", "Valor": geral.periodicidade},
        ]
        tabela_premium(pd.DataFrame(linhas_gerais), key="prec_condicoes_gerais")
        if geral.trechos_localizados:
            with st.expander("Trechos das condições gerais no Plano (auditoria)"):
                tabela_premium(
                    pd.DataFrame(
                        [{"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto} for t in geral.trechos_localizados]
                    ),
                    key="prec_trechos_gerais",
                    permitir_busca=True,
                    rotulo_busca="Buscar trecho",
                )

    st.markdown("#### Condições por Classe (já mescladas com as condições gerais)")
    st.caption("Confira o resumo por classe abaixo — os campos da classe selecionada ficam editáveis mais adiante.")
    linhas = []
    for classe in CLASSES_RJ_PADRAO:
        c = extracao.condicoes_por_classe.get(classe) or CondicoesPagamentoClasse(classe=classe)
        projecao = extracao.projecoes_fluxo_anual.get(classe)
        linhas.append(
            {
                "Classe": classe,
                "Deságio": c.desagio,
                "Carência": c.carencia,
                "Correção": c.correcao_monetaria_indice,
                "Juros": c.juros,
                "Parcelas": c.numero_parcelas,
                "Periodicidade": c.periodicidade,
                "1ª Parcela": c.data_primeira_parcela,
                "Balão": c.parcela_balao,
                "Projeção Pronta": f"Sim ({len(projecao.linhas)} linhas)" if projecao and projecao.linhas else "Não",
            }
        )
    tabela_premium(pd.DataFrame(linhas), key="prec_condicoes_por_classe")


# --- Etapa 3: confirmação (parsing best-effort + edição) --------------------


def _parse_percentual(texto: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", texto or "")
    return float(match.group(1).replace(",", ".")) / 100 if match else None


def _parse_inteiro(texto: str) -> int | None:
    match = re.search(r"\d+", texto or "")
    return int(match.group(0)) if match else None


def _parse_periodicidade(texto: str) -> Periodicidade | None:
    texto_lower = (texto or "").strip().lower()
    if not texto_lower:
        return None
    for periodicidade in Periodicidade:
        if periodicidade.value.lower() in texto_lower:
            return periodicidade
    return None


def _parse_periodicidade_taxa(texto: str) -> Periodicidade:
    texto_lower = (texto or "").lower()
    if "a.a" in texto_lower or "ano" in texto_lower or "anual" in texto_lower:
        return Periodicidade.ANUAL
    if "trimestr" in texto_lower:
        return Periodicidade.TRIMESTRAL
    if "semestr" in texto_lower:
        return Periodicidade.SEMESTRAL
    return Periodicidade.MENSAL


def _parse_data(texto: str) -> date | None:
    texto_limpo = (texto or "").strip()
    if not texto_limpo:
        return None
    match = re.match(r"([A-Za-zçÇãÃ]+)\s*[/\- ]\s*(\d{4})", texto_limpo)
    if match and match.group(1).lower() in _MESES_PT:
        return date(int(match.group(2)), _MESES_PT[match.group(1).lower()], 1)
    match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto_limpo)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", texto_limpo)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.match(r"(\d{1,2})/(\d{4})", texto_limpo)
    if match:
        try:
            return date(int(match.group(2)), int(match.group(1)), 1)
        except ValueError:
            return None
    return None


def _parse_indice(texto: str) -> str:
    texto_lower = (texto or "").strip().lower()
    if "ipca" in texto_lower:
        return "IPCA"
    if "cdi" in texto_lower:
        return "CDI"
    if "igp" in texto_lower:
        return "IGP-M"
    if re.search(r"\btr\b", texto_lower) or "referencial" in texto_lower:
        return "TR"
    if "selic" in texto_lower:
        return "SELIC"
    return "Nenhum"


# Planos de RJ costumam declarar a correção como "<índice> + <spread>% a.a.
# limitado a <teto>% a.a." (ex.: "TR + 1,00% a.a. limitado a 3,00% a.a.") —
# um índice variável somado a um spread fixo, com teto. `_bloco_taxa_indice`
# só sabe usar a taxa de UM índice isolado; esta regex detecta essa fórmula
# composta no texto bruto extraído para poder calculá-la automaticamente
# em vez de exigir que o usuário monte a conta na mão.
_RE_FORMULA_CORRECAO = re.compile(
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-]{1,15})\s*\+\s*(\d+(?:[.,]\d+)?)\s*%.{0,120}?limitad[oa].{0,30}?(\d+(?:[.,]\d+)?)\s*%",
    re.IGNORECASE | re.DOTALL,
)


def _parse_formula_correcao(texto: str) -> tuple[str, Decimal, Decimal] | None:
    """Detecta uma fórmula "índice + spread% a.a. limitado a teto% a.a." no
    texto bruto extraído — retorna (nome_do_índice, spread, teto), todos já
    como fração (ex.: 0.01 = 1%), ou None se o texto não seguir esse
    padrão (nesse caso, cai no fluxo simples de um único índice)."""
    match = _RE_FORMULA_CORRECAO.search(texto or "")
    if not match:
        return None
    indice_nome = _parse_indice(match.group(1))
    if indice_nome == "Nenhum":
        return None
    spread = Decimal(match.group(2).replace(",", ".")) / Decimal(100)
    teto = Decimal(match.group(3).replace(",", ".")) / Decimal(100)
    return indice_nome, spread, teto


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_taxa_cache(nome_indice: str):
    if nome_indice == "SELIC":
        resultado = obter_selic_bacen()
        if resultado is None:
            return None
        return {"valor": resultado.valor_anual, "data_referencia": resultado.data_referencia, "origem": resultado.origem}
    funcao = _INDICE_FUNCOES.get(nome_indice)
    if funcao is None:
        return None
    resultado = funcao()
    if resultado is None:
        return None
    return {"valor": resultado.valor, "data_referencia": resultado.data_referencia, "origem": resultado.origem}


def _bloco_taxa_indice(rotulo: str, indice_sugerido: str, key_prefix: str, permitir_nenhum: bool = True) -> tuple[str, Decimal, str, date | None]:
    """Bloco reutilizável de seleção de índice + resolução da taxa (API do
    BACEN com fallback manual) — usado tanto para o Índice de Correção
    Monetária quanto para a Taxa de Desconto (SELIC)."""
    opcoes = _OPCOES_INDICE if permitir_nenhum else _OPCOES_INDICE[1:]
    indice_escolhido = st.selectbox(
        rotulo, opcoes, index=opcoes.index(indice_sugerido) if indice_sugerido in opcoes else 0, key=f"{key_prefix}_indice"
    )
    if indice_escolhido == "Nenhum":
        return indice_escolhido, Decimal(0), "Sem correção monetária", None

    dados_indice = _consultar_taxa_cache(indice_escolhido)
    if dados_indice is not None:
        st.caption(
            f"{indice_escolhido}: {formatar_percentual(float(dados_indice['valor']))} a.a. — referência "
            f"{dados_indice['data_referencia'].strftime('%d/%m/%Y')} ({dados_indice['origem']})"
        )
    else:
        st.caption(f"Não foi possível consultar {indice_escolhido} na API do BACEN agora — informe manualmente.")

    usar_manual = st.checkbox("Informar taxa manualmente", value=dados_indice is None, key=f"{key_prefix}_manual")
    if usar_manual:
        taxa_percentual = st.number_input(
            f"Taxa de {indice_escolhido} Manual (% a.a.)",
            min_value=0.0,
            value=float((dados_indice["valor"] if dados_indice else Decimal(0)) * 100),
            step=0.1,
            key=f"{key_prefix}_taxa_manual",
        )
        return indice_escolhido, Decimal(str(taxa_percentual)) / Decimal(100), ORIGEM_MANUAL, None

    return indice_escolhido, dados_indice["valor"], dados_indice["origem"], dados_indice["data_referencia"]


def _bloco_correcao_monetaria(condicoes_texto: str, indice_sugerido: str, key_prefix: str) -> tuple[str, Decimal, str, date | None]:
    """Índice de correção monetária — detecta automaticamente fórmulas
    compostas do tipo "<índice> + <spread>% a.a. limitado a <teto>% a.a."
    (comuns em Planos de RJ) no texto bruto extraído e calcula a taxa
    aplicável sozinha (índice atual da API do BACEN + spread, limitada ao
    teto) — sem essa detecção, cai no fluxo simples de `_bloco_taxa_indice`
    (um único índice, sem spread nem teto)."""
    formula = _parse_formula_correcao(condicoes_texto)
    if formula is None:
        return _bloco_taxa_indice("Índice de Correção Monetária", indice_sugerido, key_prefix)

    indice_nome, spread, teto = formula
    st.caption(
        f"Fórmula detectada no Plano: {indice_nome} + {formatar_percentual(float(spread))} a.a., "
        f"limitado a {formatar_percentual(float(teto))} a.a."
    )
    usar_formula = st.checkbox(
        "Calcular automaticamente a partir do índice atual (recomendado)",
        value=True,
        key=f"{key_prefix}_usar_formula",
    )
    if not usar_formula:
        return _bloco_taxa_indice("Índice de Correção Monetária", indice_sugerido, key_prefix)

    dados_indice = _consultar_taxa_cache(indice_nome)
    if dados_indice is None:
        st.caption(
            f"Não foi possível consultar {indice_nome} na API do BACEN agora — usando o teto "
            f"({formatar_percentual(float(teto))} a.a.) como taxa conservadora até a consulta funcionar."
        )
        return f"{indice_nome}+spread (teto, sem consulta)", teto, "Teto do Plano (API indisponível)", None

    taxa_indice = dados_indice["valor"]
    taxa_calculada = min(taxa_indice + spread, teto)
    st.caption(
        f"{indice_nome} atual: {formatar_percentual(float(taxa_indice))} a.a. (referência "
        f"{dados_indice['data_referencia'].strftime('%d/%m/%Y')}, {dados_indice['origem']}) + "
        f"{formatar_percentual(float(spread))} a.a. = {formatar_percentual(float(taxa_indice + spread))} a.a. → "
        f"aplicado {formatar_percentual(float(taxa_calculada))} a.a. "
        f"({'limitado pelo teto' if taxa_indice + spread > teto else 'dentro do teto'})."
    )
    return (
        f"{indice_nome}+{formatar_percentual(float(spread))} limitado a {formatar_percentual(float(teto))}",
        taxa_calculada,
        f"{indice_nome} ({dados_indice['origem']}) + spread, limitado ao teto do Plano",
        dados_indice["data_referencia"],
    )


def _formulario_condicoes_classe(condicoes: CondicoesPagamentoClasse, sufixo_chave: str) -> dict:
    """Formulário editável com as condições da classe selecionada,
    pré-preenchido (melhor esforço) a partir do texto extraído pela IA — o
    usuário sempre revisa/corrige antes do cálculo.

    `sufixo_chave` (classe + identidade da extração) entra nas chaves dos
    widgets de propósito — sem isso, o valor já digitado por um usuário
    para uma classe "vazaria" ao trocar de classe ou ao chegar uma nova
    extração, porque o Streamlit só usa `value=`/`index=` na primeira vez
    que a identidade (chave) de um widget aparece na sessão.
    """
    st.markdown(f"#### Condições de Pagamento — {condicoes.classe}")
    if condicoes.trechos_localizados:
        with st.expander("Trechos localizados no Plano (auditoria)"):
            tabela_premium(
                pd.DataFrame(
                    [{"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto} for t in condicoes.trechos_localizados]
                ),
                key=f"prec_trechos_classe_{sufixo_chave}",
                permitir_busca=True,
                rotulo_busca="Buscar trecho",
            )
    if condicoes.fluxos_alternativos:
        st.info(f"Fluxos alternativos identificados: {condicoes.fluxos_alternativos}")
    if condicoes.excecoes_regras_especiais:
        st.info(f"Exceções/regras especiais identificadas: {condicoes.excecoes_regras_especiais}")

    col1, col2 = st.columns(2)
    with col1:
        desagio_percentual = st.number_input(
            "Deságio (%)", min_value=0.0, max_value=99.0,
            value=(_parse_percentual(condicoes.desagio) or 0.0) * 100, step=1.0, key=f"prec_desagio_{sufixo_chave}",
        )
        carencia_periodos = st.number_input(
            "Carência (nº de períodos)", min_value=0, value=_parse_inteiro(condicoes.carencia) or 0, key=f"prec_carencia_{sufixo_chave}"
        )
        numero_parcelas = st.number_input(
            "Número de Parcelas", min_value=1, value=_parse_inteiro(condicoes.numero_parcelas) or 12, key=f"prec_num_parcelas_{sufixo_chave}"
        )
        periodicidades = list(Periodicidade)
        periodicidade_sugerida = _parse_periodicidade(condicoes.periodicidade) or Periodicidade.MENSAL
        periodicidade = st.selectbox(
            "Periodicidade das Parcelas", periodicidades, index=periodicidades.index(periodicidade_sugerida),
            format_func=lambda p: p.value, key=f"prec_periodicidade_{sufixo_chave}",
        )
        data_sugerida = _parse_data(condicoes.data_primeira_parcela) or date.today()
        data_primeira_parcela = st.date_input("Data da 1ª Parcela", value=data_sugerida, key=f"prec_data_primeira_{sufixo_chave}")
    with col2:
        juros_percentual = st.number_input(
            "Juros (%)", min_value=0.0, value=(_parse_percentual(condicoes.juros) or 0.0) * 100, step=0.1, key=f"prec_juros_{sufixo_chave}"
        )
        periodicidade_taxa_juros = st.selectbox(
            "Periodicidade do Juros Informado", periodicidades,
            index=periodicidades.index(_parse_periodicidade_taxa(condicoes.juros)), format_func=lambda p: p.value,
            key=f"prec_juros_periodicidade_{sufixo_chave}",
        )
        tem_balao = st.checkbox(
            "Possui parcela balão", value=condicoes.parcela_balao not in ("", "não localizado"), key=f"prec_tem_balao_{sufixo_chave}"
        )
        valor_balao = Decimal(0)
        periodo_balao = 0
        if tem_balao:
            valor_balao_input = campo_moeda("Valor da Parcela Balão (R$)", 0.0, key=f"prec_valor_balao_{sufixo_chave}")
            periodo_balao = st.number_input(
                "Nº da Parcela em que ocorre o Balão", min_value=1, value=min(numero_parcelas, int(numero_parcelas)),
                key=f"prec_periodo_balao_{sufixo_chave}",
            )
            valor_balao = Decimal(str(valor_balao_input))

        indice_sugerido = _parse_indice(condicoes.correcao_monetaria_indice)
        correcao_indice, correcao_taxa_anual, correcao_origem, _ = _bloco_correcao_monetaria(
            condicoes.correcao_monetaria_indice, indice_sugerido, f"prec_correcao_{sufixo_chave}"
        )

    return {
        "desagio": Decimal(str(desagio_percentual)) / Decimal(100),
        "carencia_periodos": int(carencia_periodos),
        "numero_parcelas": int(numero_parcelas),
        "periodicidade": periodicidade,
        "data_primeira_parcela": data_primeira_parcela,
        "juros": Decimal(str(juros_percentual)) / Decimal(100),
        "periodicidade_taxa_juros": periodicidade_taxa_juros,
        "valor_balao": valor_balao,
        "periodo_balao": int(periodo_balao),
        "correcao_indice": correcao_indice,
        "correcao_taxa_anual": correcao_taxa_anual,
        "correcao_origem": correcao_origem,
    }


def _formulario_projecao_fluxo(
    projecao: ProjecaoFluxoAnualClasse, sufixo_chave: str
) -> tuple[list[LinhaFluxoInformado], Periodicidade]:
    """Formulário editável com a projeção de fluxo já pronta extraída do
    Plano — cada linha já é o valor final a receber naquele período (não
    gerado por cronograma Price/SAC). O usuário confere/corrige os valores
    antes do cálculo: a extração automática de tabelas pode perder precisão
    em documentos com diagramação incomum (proteções anticópia, watermarks).
    """
    st.markdown(f"#### Projeção de Fluxo Extraída do Plano — {projecao.classe}")
    st.caption(
        "Confira e corrija os valores abaixo se necessário antes de calcular — a extração automática de "
        "tabelas pode perder precisão em documentos com diagramação incomum."
    )
    if projecao.trechos_localizados:
        with st.expander("Trechos localizados no Plano (auditoria)"):
            tabela_premium(
                pd.DataFrame(
                    [{"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto} for t in projecao.trechos_localizados]
                ),
                key=f"prec_trechos_projecao_{sufixo_chave}",
                permitir_busca=True,
                rotulo_busca="Buscar trecho",
            )

    col1, col2 = st.columns(2)
    with col1:
        data_primeira_linha = st.date_input(
            "Data da 1ª linha da projeção", value=date.today(), key=f"prec_projecao_data_{sufixo_chave}"
        )
    with col2:
        periodicidades = list(Periodicidade)
        periodicidade = st.selectbox(
            "Periodicidade das linhas",
            periodicidades,
            index=periodicidades.index(Periodicidade.ANUAL),
            format_func=lambda p: p.value,
            key=f"prec_projecao_periodicidade_{sufixo_chave}",
        )

    df_linhas = pd.DataFrame(
        [{"Período": linha.periodo, "Valor (R$)": parse_valor_brl(linha.valor) or 0.0} for linha in projecao.linhas]
    )
    df_editado = st.data_editor(
        df_linhas,
        column_config={
            "Período": st.column_config.TextColumn(disabled=True),
            "Valor (R$)": st.column_config.NumberColumn(format="R$ %.2f", min_value=0.0, step=0.01),
        },
        hide_index=True,
        width="stretch",
        key=f"prec_projecao_editor_{sufixo_chave}",
    )

    linhas_calculo = [
        LinhaFluxoInformado(
            data=adicionar_periodos(data_primeira_linha, numero, periodicidade),
            descricao=str(linha["Período"]),
            valor=Decimal(str(linha["Valor (R$)"])),
        )
        for numero, linha in enumerate(df_editado.to_dict(orient="records"))
    ]
    return linhas_calculo, periodicidade


def _formulario_cronograma_percentual(
    cronograma: CronogramaAmortizacaoClasse, condicoes: CondicoesPagamentoClasse, sufixo_chave: str
) -> tuple[list[LinhaCronogramaPercentual], Periodicidade, Decimal, str, Decimal]:
    """Formulário editável com o cronograma de amortização em PERCENTUAL do
    saldo pós-deságio, extraído do Plano — padrão comum quando o documento
    define a forma de pagamento como "Ano 1: 0%, Ano 2 a 6: 3%..." em vez
    de uma Tabela Price ou de uma projeção de fluxo já pronta em R$. Cada
    percentual incide sobre o saldo pós-deságio DESTE crédito específico
    (nunca sobre o total da classe inteira) — ver
    `calcular_precificacao_classe_com_cronograma_percentual`.
    """
    st.markdown(f"#### Cronograma de Amortização (%) Extraído do Plano — {cronograma.classe}")
    st.caption(
        "Confira e corrija os percentuais abaixo se necessário antes de calcular — cada percentual incide "
        "sobre o saldo já deságiado deste crédito específico, não sobre o total da classe."
    )
    if cronograma.trechos_localizados:
        with st.expander("Trechos localizados no Plano (auditoria)"):
            tabela_premium(
                pd.DataFrame(
                    [{"Página": t.pagina, "Trecho": t.trecho, "Contexto": t.contexto} for t in cronograma.trechos_localizados]
                ),
                key=f"prec_trechos_cronograma_{sufixo_chave}",
                permitir_busca=True,
                rotulo_busca="Buscar trecho",
            )

    col1, col2, col3 = st.columns(3)
    with col1:
        desagio_percentual = st.number_input(
            "Deságio (%)", min_value=0.0, max_value=99.0,
            value=(_parse_percentual(condicoes.desagio) or 0.0) * 100, step=1.0, key=f"prec_cronograma_desagio_{sufixo_chave}",
        )
    with col2:
        data_primeira_linha = st.date_input(
            "Data da 1ª linha do cronograma", value=date.today(), key=f"prec_cronograma_data_{sufixo_chave}"
        )
    with col3:
        periodicidades = list(Periodicidade)
        periodicidade = st.selectbox(
            "Periodicidade das linhas",
            periodicidades,
            index=periodicidades.index(Periodicidade.ANUAL),
            format_func=lambda p: p.value,
            key=f"prec_cronograma_periodicidade_{sufixo_chave}",
        )

    indice_sugerido = _parse_indice(condicoes.correcao_monetaria_indice)
    correcao_indice, correcao_taxa_anual, _, _ = _bloco_correcao_monetaria(
        condicoes.correcao_monetaria_indice, indice_sugerido, f"prec_cronograma_correcao_{sufixo_chave}"
    )

    df_linhas = pd.DataFrame(
        [{"Período": linha.periodo, "% Amort.": (_parse_percentual(linha.percentual) or 0.0) * 100} for linha in cronograma.linhas]
    )
    df_editado = st.data_editor(
        df_linhas,
        column_config={
            "Período": st.column_config.TextColumn(disabled=True),
            "% Amort.": st.column_config.NumberColumn(format="%.2f%%", min_value=0.0, max_value=100.0, step=0.5),
        },
        hide_index=True,
        width="stretch",
        key=f"prec_cronograma_editor_{sufixo_chave}",
    )

    linhas_calculo = [
        LinhaCronogramaPercentual(
            data=adicionar_periodos(data_primeira_linha, numero, periodicidade),
            descricao=str(linha["Período"]),
            percentual=Decimal(str(linha["% Amort."])) / Decimal(100),
        )
        for numero, linha in enumerate(df_editado.to_dict(orient="records"))
    ]
    return (
        linhas_calculo,
        periodicidade,
        Decimal(str(desagio_percentual)) / Decimal(100),
        correcao_indice,
        correcao_taxa_anual,
    )


# --- Etapa 5: gráficos e resultado -------------------------------------------


def _grafico_fluxo_nominal(resultado: ResultadoPrecificacaoClasse) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[p.data for p in resultado.fluxo], y=[float(p.valor_nominal) for p in resultado.fluxo],
            name="Fluxo Nominal", marker_color=CORES["grafico_indigo"],
        )
    )
    fig.update_layout(title="Fluxo de Caixa Projetado (Nominal)", xaxis_title="Data", yaxis_title="Valor (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _grafico_fluxo_descontado(resultado: ResultadoPrecificacaoClasse) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[p.data for p in resultado.fluxo], y=[float(p.valor_descontado) for p in resultado.fluxo],
            name="Fluxo Descontado", marker_color=CORES["destaque"],
        )
    )
    fig.update_layout(title="Fluxo de Caixa Descontado (Valor Presente)", xaxis_title="Data", yaxis_title="Valor Presente (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _grafico_linha_tempo(resultado: ResultadoPrecificacaoClasse) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p.data for p in resultado.fluxo], y=[float(p.valor_nominal) for p in resultado.fluxo],
            mode="markers+lines", name="Pagamentos", line=dict(color=CORES["grafico_indigo"], width=2),
        )
    )
    fig.update_layout(title="Linha do Tempo dos Pagamentos", xaxis_title="Data", yaxis_title="Valor (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _grafico_evolucao_saldo(resultado: ResultadoPrecificacaoClasse) -> go.Figure:
    fluxo_ordenado = sorted(resultado.fluxo, key=lambda item: item.numero)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p.data for p in fluxo_ordenado], y=[float(p.saldo_final) for p in fluxo_ordenado],
            mode="lines+markers", fill="tozeroy", name="Saldo Devedor", line=dict(color=CORES["grafico_indigo"], width=2),
        )
    )
    fig.update_layout(title="Evolução do Saldo Devedor", xaxis_title="Data", yaxis_title="Saldo (R$)")
    return aplicar_tema_escuro_grafico(fig)


def _renderizar_resultado(resultado: ResultadoPrecificacaoClasse) -> None:
    if not resultado.metodologia_validada:
        st.warning(
            "Metodologia de cálculo (cronograma unificado, casamento de período e descapitalização "
            "linha por linha) ainda pendente de validação final contra a planilha oficial de VPL da "
            "AMF3 Capital. Trate os números abaixo como uma estimativa até a confirmação."
        )

    st.markdown("#### Ficha Resumo")
    st.caption("Mesma estrutura da planilha VPL.xlsx de referência da AMF3 Capital.")
    meses_por_periodo = resultado.periodicidade.meses if resultado.periodicidade else None

    def _periodos_em_meses(periodos: int | None) -> str:
        if periodos is None:
            return "N/A"
        if meses_por_periodo is None:
            return str(periodos)
        return str(periodos * meses_por_periodo)

    def _carencia_em_meses() -> str:
        # "Carência" aqui é o prazo até o VENCIMENTO da 1ª parcela (o jeito
        # como o Plano de RJ normalmente declara isso, ex.: "vencendo-se a
        # primeira ao final do 24.º mês") — não apenas a contagem de
        # períodos com pagamento zero: com períodos ANUAIS, 1 período de
        # carência (Ano 1: 0%) ainda exige que o Ano 2 (o 1º período pago)
        # se complete, então a 1ª parcela só vence no mês 24, não no mês 12.
        if resultado.carencia_periodos is None or meses_por_periodo is None:
            return "N/A"
        if not resultado.numero_parcelas:
            return str(resultado.carencia_periodos * meses_por_periodo)
        return str((resultado.carencia_periodos + 1) * meses_por_periodo)

    def _pct(valor: Decimal | None) -> str:
        return formatar_percentual(float(valor)) if valor is not None else "N/A"

    def _rs(valor: Decimal | None) -> str:
        return formatar_moeda(float(valor)) if valor is not None else "N/A"

    taxa_desconto_am = converter_taxa(
        resultado.taxa_desconto_anual, Periodicidade.ANUAL, Periodicidade.MENSAL, RegimeJuros.COMPOSTO
    )
    if resultado.taxa_juros_periodo is not None and resultado.periodicidade is not None:
        juros_am = converter_taxa(
            resultado.taxa_juros_periodo, resultado.periodicidade, Periodicidade.MENSAL, RegimeJuros.COMPOSTO
        )
    else:
        juros_am = None

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Crédito", formatar_moeda(float(resultado.valor_nominal_credito)))
        st.metric("Deságio", _pct(resultado.desagio_percentual))
        st.metric("Prazo (mês)", _periodos_em_meses(
            (resultado.carencia_periodos or 0) + (resultado.numero_parcelas or 0)
            if resultado.numero_parcelas is not None else None
        ))
    with col_b:
        st.metric("Carência (mês)", _carencia_em_meses())
        st.metric("Juros (a.m.)", _pct(juros_am))
        st.metric("Taxa de Descap. (a.m.)", _pct(taxa_desconto_am))
    with col_c:
        st.metric("Saldo Pós Deságio", _rs(resultado.saldo_pos_desagio))
        st.metric("Saldo Pós Carência", _rs(resultado.saldo_pos_carencia))
        st.metric("Saldo Final", _rs(resultado.saldo_final))

    col_vpl, col_pct = st.columns(2)
    with col_vpl:
        st.metric("VPL (Valor Presente do Fluxo)", formatar_moeda(float(resultado.vp_total)))
    with col_pct:
        st.metric("VPL / Crédito", formatar_percentual(float(resultado.percentual_recuperacao_efetiva) / 100))
    st.caption(
        "\"Juros (a.m.)\" reflete a taxa de juros do plano (Tabela Price) ou, quando o plano usa correção "
        "monetária em vez de juros (ex.: cronograma por percentual), a taxa de correção — convertida para "
        "equivalente mensal. Campos \"N/A\" não se aplicam ao método de cálculo usado nesta classe."
    )

    st.markdown("#### Resumo Financeiro")
    renderizar_kpis(
        [
            ("Valor Nominal do Crédito (C0)", formatar_moeda(float(resultado.valor_nominal_credito))),
            ("Classe", resultado.classe),
            (
                "Taxa de Desconto",
                f"{formatar_percentual(float(resultado.taxa_desconto_anual))} a.a. "
                f"({formatar_percentual(float(resultado.taxa_desconto_periodo))}/período)",
            ),
            (
                "Data da Taxa",
                resultado.data_taxa_desconto.strftime("%d/%m/%Y") if resultado.data_taxa_desconto else "Manual",
            ),
        ]
    )
    st.caption(f"Origem da taxa de desconto: {resultado.origem_taxa_desconto}")

    st.markdown("#### Resultado")
    variante_vpl = "kpi_positivo" if resultado.vpl_comercial > 0 else "kpi_negativo"
    renderizar_kpis(
        [
            ("Fluxo Nominal Total", formatar_moeda(float(resultado.fluxo_nominal_total))),
            ("Valor Presente do Fluxo (VP Total)", formatar_moeda(float(resultado.vp_total))),
            ("VPL Real Comercial", formatar_moeda(float(resultado.vpl_comercial))),
            ("% Recuperação Efetiva", formatar_percentual(float(resultado.percentual_recuperacao_efetiva) / 100)),
        ],
        variantes=[None, None, variante_vpl, variante_vpl],
    )
    st.caption(
        "VPL Real Comercial = Valor Presente do Fluxo − Crédito Original. Como se trata de uma Recuperação "
        "Judicial com deságio e prazo longo, um VPL comercial significativamente negativo é esperado — ele "
        "reflete a perda real de poder de compra do credor, não um erro de cálculo."
    )

    st.markdown("#### Cronograma Unificado (Carência + Parcelas)")
    df = pd.DataFrame(
        [
            {
                "Nº": p.numero,
                "Data": p.data.strftime("%d/%m/%Y"),
                "Descrição": p.descricao,
                "Carência?": "Sim" if p.carencia else "Não",
                "Saldo Inicial": formatar_moeda(float(p.saldo_inicial)),
                "Juros do Período": formatar_moeda(float(p.juros_periodo)),
                "Amortização": formatar_moeda(float(p.amortizacao)),
                "Valor Pago ao Credor": formatar_moeda(float(p.valor_nominal)),
                "Saldo Final": formatar_moeda(float(p.saldo_final)),
                "Valor Presente (VP_t)": formatar_moeda(float(p.valor_descontado)),
            }
            for p in sorted(resultado.fluxo, key=lambda item: item.numero)
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True)

    with st.expander("Memória de Cálculo (auditoria)"):
        for linha in resultado.memoria_calculo:
            st.markdown(f"- {linha}")

    st.markdown("#### Dashboard")
    col_a, col_b = st.columns(2)
    with col_a:
        with container_grafico("prec_fluxo_nominal"):
            st.plotly_chart(_grafico_fluxo_nominal(resultado), width="stretch")
        with container_grafico("prec_linha_tempo"):
            st.plotly_chart(_grafico_linha_tempo(resultado), width="stretch")
    with col_b:
        with container_grafico("prec_fluxo_descontado"):
            st.plotly_chart(_grafico_fluxo_descontado(resultado), width="stretch")
        with container_grafico("prec_evolucao_saldo"):
            st.plotly_chart(_grafico_evolucao_saldo(resultado), width="stretch")

    st.divider()
    st.markdown("**Exportar**")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Excel", key="prec_btn_excel", icon=icone("exportar"), width="stretch"):
            caminho = EXPORTADOS_DIR / "precificacao_inteligente.xlsx"
            exportar_excel_precificacao(resultado, caminho)
            st.session_state["prec_export_xlsx"] = str(caminho)
    with col_b:
        if st.button("Word", key="prec_btn_word", icon=icone("exportar"), width="stretch"):
            caminho = EXPORTADOS_DIR / "precificacao_inteligente.docx"
            exportar_word_precificacao(resultado, caminho)
            st.session_state["prec_export_docx"] = str(caminho)

    for chave_sessao, rotulo in (("prec_export_xlsx", "Baixar Excel"), ("prec_export_docx", "Baixar Word")):
        caminho_str = st.session_state.get(chave_sessao)
        if caminho_str and Path(caminho_str).exists():
            caminho = Path(caminho_str)
            st.download_button(rotulo, caminho.read_bytes(), file_name=caminho.name, key=f"prec_download_{chave_sessao}")


# --- Página principal ---------------------------------------------------------


def renderizar_precificacao() -> None:
    layout.renderizar_titulo_pagina("precificacao", "Precificação Inteligente de Créditos")
    st.caption("A IA localiza as condições do Plano de RJ; todo o cálculo de VPL é feito em Python.")

    st.markdown("#### Importação do Plano de Recuperação Judicial")
    modo = st.radio("Como importar o Plano", ["Upload de PDF", "Colar trecho de texto"], horizontal=True, key="prec_modo_importacao")

    if modo == "Upload de PDF":
        arquivo = st.file_uploader("Selecionar PDF do Plano de RJ", type=["pdf"], key="prec_uploader")
        renderizar_preview_arquivo(arquivo)
        if arquivo is not None:
            chave_cache = f"{arquivo.name}_{arquivo.size}"
            if st.session_state.get("prec_chave_cache") != chave_cache:
                if st.button("Analisar Plano com IA", type="primary", icon=icone("precificacao"), key="prec_btn_analisar_pdf"):
                    extracao = _processar_pdf(arquivo)
                    if extracao is not None:
                        st.session_state["prec_extracao"] = extracao
                        st.session_state["prec_chave_cache"] = chave_cache
                        st.session_state.pop("prec_resultado", None)
                        st.rerun()
    else:
        texto_colado = st.text_area(
            "Cole aqui o trecho do Plano referente ao pagamento dos credores", height=180, key="prec_texto_colado"
        )
        if texto_colado.strip():
            chave_cache = f"texto_{hash(texto_colado.strip())}"
            if st.session_state.get("prec_chave_cache") != chave_cache:
                if st.button("Analisar Texto com IA", type="primary", icon=icone("precificacao"), key="prec_btn_analisar_texto"):
                    extracao = _processar_texto_colado(texto_colado.strip())
                    if extracao is not None:
                        st.session_state["prec_extracao"] = extracao
                        st.session_state["prec_chave_cache"] = chave_cache
                        st.session_state.pop("prec_resultado", None)
                        st.rerun()

    extracao = st.session_state.get("prec_extracao")
    if extracao is not None:
        _renderizar_quadro_geral(extracao)
    else:
        st.info(
            "Envie o PDF (ou cole um trecho) do Plano acima e clique em \"Analisar\" para identificar "
            "automaticamente as condições de pagamento — ou preencha manualmente abaixo, sem IA."
        )

    st.divider()
    st.markdown("#### Precificar um Crédito")
    st.caption(
        "Informe o crédito e a classe — o cálculo usa automaticamente as condições de pagamento do Plano "
        "identificadas acima (deságio, carência, cronograma, correção) e a SELIC atual como taxa de desconto, "
        "exatamente como na planilha de referência."
    )
    col1, col2 = st.columns(2)
    with col1:
        valor_nominal_credito = campo_moeda("Valor Nominal do Crédito (R$)", 100000.0, min_value=0.01, key="prec_valor_nominal")
    with col2:
        classe_escolhida = st.selectbox("Classe do Crédito", CLASSES_RJ_PADRAO, key="prec_classe_escolhida")

    condicoes_classe = (
        (extracao.condicoes_por_classe.get(classe_escolhida) if extracao else None)
        or CondicoesPagamentoClasse(classe=classe_escolhida)
    )
    projecao_classe = extracao.projecoes_fluxo_anual.get(classe_escolhida) if extracao else None
    tem_projecao = bool(projecao_classe and projecao_classe.linhas)
    cronograma_classe = extracao.cronogramas_amortizacao.get(classe_escolhida) if extracao else None
    tem_cronograma = bool(cronograma_classe and cronograma_classe.linhas)
    sufixo_chave = f"{classe_escolhida}_{id(extracao) if extracao else 0}"

    opcoes_metodo = []
    if tem_cronograma:
        opcoes_metodo.append("cronograma_percentual")
    if tem_projecao:
        opcoes_metodo.append("projecao_pronta")
    opcoes_metodo.append("manual")
    rotulos_metodo = {
        "cronograma_percentual": "Cronograma de amortização em % extraído do Plano (recomendado quando disponível)",
        "projecao_pronta": "Projeção de fluxo já pronta em R$ — atenção: geralmente é o total da classe inteira, "
        "não deste crédito específico",
        "manual": "Informar deságio, carência, juros e parcelas manualmente (Tabela Price)",
    }
    st.caption(
        f"Método usado para {classe_escolhida}: **{rotulos_metodo[opcoes_metodo[0]]}**"
        + ("" if extracao else " — nenhum Plano importado ainda, condições zeradas por padrão.")
    )

    with st.expander("Ajustar condições manualmente (opcional)", expanded=False):
        metodo = (
            st.radio(
                "Como calcular o fluxo de pagamentos desta classe?",
                opcoes_metodo,
                format_func=lambda k: rotulos_metodo[k],
                key=f"prec_metodo_{sufixo_chave}",
            )
            if len(opcoes_metodo) > 1
            else opcoes_metodo[0]
        )

        st.divider()
        if metodo == "cronograma_percentual":
            linhas_cronograma, periodicidade_cronograma, desagio_cronograma, correcao_indice_cronograma, correcao_taxa_cronograma = (
                _formulario_cronograma_percentual(cronograma_classe, condicoes_classe, sufixo_chave)
            )
            dados_formulario = None
        elif metodo == "projecao_pronta":
            linhas_projecao, periodicidade_projecao = _formulario_projecao_fluxo(projecao_classe, sufixo_chave)
            dados_formulario = None
        else:
            dados_formulario = _formulario_condicoes_classe(condicoes_classe, sufixo_chave)

        st.divider()
        st.markdown("#### Taxa de Desconto")
        _, taxa_desconto_anual, origem_taxa_desconto, data_taxa_desconto = _bloco_taxa_indice(
            "Fonte da Taxa de Desconto", "SELIC", "prec_desconto", permitir_nenhum=False
        )

    if st.button("Calcular Precificação", type="primary", icon=icone("precificacao"), key="prec_btn_calcular"):
        try:
            if metodo == "cronograma_percentual":
                parametros_cronograma = ParametrosCalculoClasseComCronogramaPercentual(
                    classe=classe_escolhida,
                    valor_nominal_credito=Decimal(str(valor_nominal_credito)),
                    desagio=desagio_cronograma,
                    linhas=linhas_cronograma,
                    correcao_indice=correcao_indice_cronograma,
                    correcao_taxa_anual=correcao_taxa_cronograma,
                    periodicidade=periodicidade_cronograma,
                    taxa_desconto_anual=taxa_desconto_anual,
                    origem_taxa_desconto=origem_taxa_desconto,
                    data_taxa_desconto=data_taxa_desconto,
                    condicoes=condicoes_classe,
                )
                resultado = calcular_precificacao_classe_com_cronograma_percentual(parametros_cronograma)
            elif metodo == "projecao_pronta":
                parametros_projecao = ParametrosCalculoClasseComProjecao(
                    classe=classe_escolhida,
                    valor_nominal_credito=Decimal(str(valor_nominal_credito)),
                    linhas=linhas_projecao,
                    periodicidade=periodicidade_projecao,
                    taxa_desconto_anual=taxa_desconto_anual,
                    origem_taxa_desconto=origem_taxa_desconto,
                    data_taxa_desconto=data_taxa_desconto,
                    condicoes=condicoes_classe,
                )
                resultado = calcular_precificacao_classe_com_projecao(parametros_projecao)
            else:
                juros_periodo = dados_formulario["juros"]
                if dados_formulario["periodicidade_taxa_juros"] != dados_formulario["periodicidade"]:
                    from src.calculadora.amortizacao import converter_taxa
                    from src.calculadora.models import RegimeJuros

                    juros_periodo = converter_taxa(
                        dados_formulario["juros"], dados_formulario["periodicidade_taxa_juros"], dados_formulario["periodicidade"], RegimeJuros.COMPOSTO
                    )

                parametros = ParametrosCalculoClasse(
                    classe=classe_escolhida,
                    valor_nominal_credito=Decimal(str(valor_nominal_credito)),
                    desagio=dados_formulario["desagio"],
                    carencia_periodos=dados_formulario["carencia_periodos"],
                    correcao_indice=dados_formulario["correcao_indice"],
                    correcao_taxa_anual=dados_formulario["correcao_taxa_anual"],
                    juros=juros_periodo,
                    numero_parcelas=dados_formulario["numero_parcelas"],
                    periodicidade=dados_formulario["periodicidade"],
                    data_primeira_parcela=dados_formulario["data_primeira_parcela"],
                    data_base=date.today(),
                    valor_balao=dados_formulario["valor_balao"],
                    periodo_balao=dados_formulario["periodo_balao"],
                    taxa_desconto_anual=taxa_desconto_anual,
                    origem_taxa_desconto=origem_taxa_desconto,
                    data_taxa_desconto=data_taxa_desconto,
                    condicoes=condicoes_classe,
                )
                resultado = calcular_precificacao_classe(parametros)
            st.session_state["prec_resultado"] = resultado
            st.session_state.pop("prec_export_xlsx", None)
            st.session_state.pop("prec_export_docx", None)
        except (ValueError, InvalidOperation) as exc:
            st.error(f"Não foi possível calcular o VPL: {exc}")

    resultado = st.session_state.get("prec_resultado")
    if resultado is not None:
        st.divider()
        _renderizar_resultado(resultado)
