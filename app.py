"""Ponto de entrada Streamlit da plataforma AMF3 Capital.

Atua apenas como roteador: autentica, monta o cabeçalho/menu compartilhados
(`interface/layout.py`) e despacha para a página selecionada. Toda a lógica de
cada módulo vive em seu próprio arquivo (`interface/dashboard.py` para
Credores, `interface/home.py`, etc.) — nada de específico de módulo é
implementado aqui.
"""

from __future__ import annotations

import streamlit as st

from config import NOME_SISTEMA
from interface import (
    analise_documentos,
    calculadora,
    dashboard,
    home,
    layout,
    peticao_inicial,
    precificacao,
    proposta_credor,
)

st.set_page_config(page_title=NOME_SISTEMA, page_icon="⚖️", layout="wide")

dashboard.injetar_css()

if not dashboard.verificar_autenticacao():
    st.stop()

layout.renderizar_menu_lateral()
layout.renderizar_cabecalho_app()

pagina = layout.pagina_atual()

if pagina == "credores":
    dashboard.renderizar_pagina_credores()
elif pagina == "peticao_inicial":
    peticao_inicial.renderizar_peticao_inicial()
elif pagina == "calculadora":
    calculadora.renderizar_calculadora()
elif pagina == "precificacao":
    precificacao.renderizar_precificacao()
elif pagina == "analise_documentos":
    analise_documentos.renderizar_analise_documentos()
elif pagina == "proposta_credor":
    proposta_credor.renderizar_proposta_credor()
elif pagina == "configuracoes":
    layout.renderizar_pagina_em_construcao(
        chave_icone="configuracoes",
        titulo="Configurações",
        descricao="Preferências e configurações gerais da plataforma.",
        futuras=[],
    )
else:
    home.renderizar_home()

layout.renderizar_rodape()
