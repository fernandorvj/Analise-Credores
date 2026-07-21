"""Componentes de interface compartilhados pelas abas da Calculadora — tema
escuro para gráficos Plotly, editor de fluxo de caixa (usado tanto pela
Simulação Balão quanto, no futuro, por qualquer outra tela com fluxo livre) e
o mecanismo de salvar/listar cenários para a aba de Comparação.

Isolado de `interface/dashboard.py`: não importa nada de lá (mesmo havendo um
helper de tema escuro equivalente naquele módulo) para manter a Calculadora
totalmente desacoplada do módulo Credores, conforme a restrição de nunca
alterar nem depender de detalhes internos daquele módulo.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import GRAFICO_SUPERFICIE_ESCURA
from interface.icones import icone
from src.calculadora.fluxo import novo_item
from src.calculadora.models import Cenario, FluxoItem, TipoFluxoItem
from src.utils import formatar_moeda, parse_valor_brl


def aplicar_tema_escuro_grafico(fig: go.Figure) -> go.Figure:
    """Aplica o cromado (fundo, grade, fontes) do tema escuro Flat Design 2.0
    da plataforma a um gráfico Plotly da Calculadora. Não altera dados nem
    traços do gráfico.
    """
    fig.update_layout(
        paper_bgcolor=GRAFICO_SUPERFICIE_ESCURA,
        plot_bgcolor=GRAFICO_SUPERFICIE_ESCURA,
        font=dict(family="Inter, 'Segoe UI', sans-serif", color="#FFFFFF", size=13),
        title_font=dict(family="Quicksand, 'Segoe UI', sans-serif", color="#FFFFFF", size=16),
        legend=dict(font=dict(color="#C3C2B7"), bgcolor="rgba(0,0,0,0)"),
        margin=dict(t=48, l=8, r=8, b=8),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.10)", zerolinecolor="rgba(255,255,255,0.16)", color="#C3C2B7")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.10)", zerolinecolor="rgba(255,255,255,0.16)", color="#C3C2B7")
    return fig


def container_grafico(chave: str):
    """`st.container` com chave no padrão ``amf3_grafico_*`` — reaproveita o
    painel escuro já estilizado globalmente em `assets/estilos.css`
    (seletor ``[class*="st-key-amf3_grafico_"]``) sem precisar de CSS novo.
    """
    return st.container(key=f"amf3_grafico_{chave}")


_TIPOS_FLUXO = [tipo.value for tipo in TipoFluxoItem]


def editor_fluxo(fluxo: list[FluxoItem], key: str) -> list[FluxoItem]:
    """Editor de fluxo de caixa livre: tabela editável (`st.data_editor`) que
    permite adicionar, excluir e alterar data/descrição/tipo/valor de
    qualquer item — usado pela Simulação Balão. Itens marcados como não
    editáveis (ex.: a Entrada) ficam desabilitados na coluna Valor.
    """
    df = pd.DataFrame(
        [
            {
                "Data": item.data,
                "Descrição": item.descricao,
                "Tipo": item.tipo.value,
                "Valor": float(item.valor),
            }
            for item in fluxo
        ]
    )
    df_editado = st.data_editor(
        df,
        key=key,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", required=True),
            "Descrição": st.column_config.TextColumn("Descrição", required=True),
            "Tipo": st.column_config.SelectboxColumn("Tipo", options=_TIPOS_FLUXO, required=True),
            "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", required=True),
        },
    )

    novo_fluxo: list[FluxoItem] = []
    for indice, linha in df_editado.reset_index(drop=True).iterrows():
        data_linha = linha["Data"]
        if isinstance(data_linha, datetime):
            data_linha = data_linha.date()
        elif isinstance(data_linha, pd.Timestamp):
            data_linha = data_linha.date()
        if not isinstance(data_linha, date) or pd.isna(linha["Valor"]) or not str(linha.get("Descrição", "")).strip():
            continue
        tipo = TipoFluxoItem(linha["Tipo"]) if linha["Tipo"] in _TIPOS_FLUXO else TipoFluxoItem.EXTRA
        novo_fluxo.append(
            novo_item(indice + 1, data_linha, str(linha["Descrição"]), tipo, Decimal(str(linha["Valor"])))
        )
    return novo_fluxo


def campo_moeda(
    label: str,
    valor_padrao: float,
    key: str | None = None,
    dentro_de_formulario: bool = False,
    **kwargs,
) -> float:
    """Campo de valor monetário como texto (não `st.number_input`) — sempre
    mostra e aceita o formato brasileiro (ex.: "14.567.087,32").

    O `st.number_input` nativo só entende "." como separador decimal (é um
    input numérico de navegador); colar um valor no formato brasileiro nele
    (com ponto de milhar) corrompe o número silenciosamente (ex.:
    "14.567.087,32" virava "14,56708732"). Este campo usa `parse_valor_brl`
    (o mesmo parser já usado na extração de PDFs) para interpretar
    corretamente o que foi digitado/colado — o valor numérico real fica em
    `session_state`, o campo em si só guarda o texto exibido.

    Fora de formulário, o texto é reformatado para o padrão BR assim que o
    usuário sai do campo (`on_change`). `st.form` proíbe `on_change` em
    qualquer widget que não seja o `form_submit_button` — quando
    `dentro_de_formulario=True`, a reformatação ao vivo é pulada (o texto
    fica exatamente como foi digitado/colado até o formulário ser reenviado),
    mas o valor numérico interpretado continua correto de qualquer forma.
    """
    if key is None:
        chamador = inspect.stack()[1]
        key = f"campo_moeda_{chamador.filename}:{chamador.lineno}"
    chave_texto = f"{key}_texto"
    chave_valor = f"{key}_valor"
    valor_minimo = kwargs.get("min_value", 0.0)
    valor_maximo = kwargs.get("max_value")

    if chave_valor not in st.session_state:
        st.session_state[chave_valor] = valor_padrao
        st.session_state[chave_texto] = formatar_moeda(valor_padrao).replace("R$ ", "")

    def _aplicar_limites(valor: float) -> float:
        if valor_minimo is not None:
            valor = max(valor, valor_minimo)
        if valor_maximo is not None:
            valor = min(valor, valor_maximo)
        return valor

    if dentro_de_formulario:
        texto = st.text_input(label, key=chave_texto, icon=icone("moeda"))
        valor = parse_valor_brl(texto)
        if valor is None:
            valor = st.session_state[chave_valor]
        valor = _aplicar_limites(valor)
        st.session_state[chave_valor] = valor
        return valor

    def _sincronizar() -> None:
        # Acesso defensivo: em produção (Streamlit Cloud) já foi observado o
        # callback disparar numa rerun em que `chave_texto`/`chave_valor`
        # ainda não estão presentes em session_state (ex.: quando o widget
        # está dentro de um bloco condicional que mudou entre a interação e
        # o processamento do callback) — sem isso o app derruba com KeyError.
        texto_atual = st.session_state.get(chave_texto)
        if texto_atual is None:
            return
        valor = parse_valor_brl(texto_atual)
        if valor is None:
            valor = st.session_state.get(chave_valor, valor_padrao)
        valor = _aplicar_limites(valor)
        st.session_state[chave_valor] = valor
        st.session_state[chave_texto] = formatar_moeda(valor).replace("R$ ", "")

    st.text_input(label, key=chave_texto, on_change=_sincronizar, icon=icone("moeda"))
    return st.session_state[chave_valor]


def renderizar_kpis(pares: list[tuple[str, str]]) -> None:
    """KPIs em `st.metric` dentro de `st.columns` — herda automaticamente o
    estilo de card já definido globalmente para `[data-testid="stMetric"]`.
    """
    colunas = st.columns(len(pares))
    for coluna, (rotulo, valor) in zip(colunas, pares):
        with coluna:
            st.metric(rotulo, valor)


def salvar_cenario(nome: str, tipo: str, resultado) -> None:
    """Salva um cenário (financiamento ou VPL) em `session_state` para a aba
    de Comparação de Cenários — nunca grava em banco de dados, dura apenas a
    sessão do navegador.
    """
    cenarios: list[Cenario] = st.session_state.setdefault("calc_cenarios", [])
    cenarios.append(Cenario(nome=nome, tipo=tipo, resultado=resultado))


def listar_cenarios() -> list[Cenario]:
    return st.session_state.get("calc_cenarios", [])
