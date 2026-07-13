"""Camada de navegação compartilhada por todas as páginas da plataforma AMF3.

Cabeçalho superior, menu lateral, rodapé e troca de página — nada aqui contém
lógica de negócio de nenhum módulo específico (Credores, Petição Inicial,
Calculadora); cada módulo continua responsável pelo seu próprio conteúdo.
"""

from __future__ import annotations

import streamlit as st

from config import (
    APP_USERNAME,
    DATA_ATUALIZACAO,
    LOGO_PATH,
    NOME_EMPRESA,
    NOME_PLATAFORMA,
    SUBTITULO_PLATAFORMA,
    TEXTO_INSTITUCIONAL,
    VERSAO_SISTEMA,
)

# (chave interna da página, rótulo com ícone exibido no menu)
PAGINAS = [
    ("home", "🏠 Home"),
    ("credores", "👥 Credores"),
    ("peticao_inicial", "📄 Petição Inicial"),
    ("calculadora", "🧮 Calculadora"),
    ("configuracoes", "⚙️ Configurações"),
]


def pagina_atual() -> str:
    """Página selecionada na sessão — "home" é o destino padrão após o login."""
    return st.session_state.get("pagina_atual", "home")


def navegar_para(pagina: str) -> None:
    """Troca a página atual sem exigir novo login (mesma sessão, mesmo estado)."""
    st.session_state["pagina_atual"] = pagina
    st.rerun()


def fazer_logout() -> None:
    """Desloga o usuário reutilizando o mesmo mecanismo de sessão que
    `dashboard.verificar_autenticacao()` já verifica — não duplica nem altera
    a lógica de autenticação, só limpa a flag que ela consulta.
    """
    st.session_state["autenticado"] = False
    st.session_state["pagina_atual"] = "home"
    st.rerun()


def renderizar_cabecalho_app() -> None:
    """Cabeçalho fixo no topo de toda página pós-login: logo, identidade da
    plataforma e, à direita, usuário logado + botões Home/Sair.
    """
    col_logo, col_titulo, col_usuario = st.columns([1, 3, 1.3], vertical_alignment="center")

    with col_logo:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=120)

    with col_titulo:
        st.markdown(
            f"""
            <div class="amf3-appbar-titulo">
                <h2>{NOME_PLATAFORMA}</h2>
                <p class="amf3-appbar-subtitulo">{SUBTITULO_PLATAFORMA}</p>
                <p class="amf3-appbar-institucional">{TEXTO_INSTITUCIONAL}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_usuario:
        nome_usuario = APP_USERNAME or "Usuário"
        st.markdown(
            f"""
            <div class="amf3-appbar-usuario">
                <span class="amf3-appbar-usuario-nome">{nome_usuario}</span>
                <span class="amf3-appbar-usuario-perfil">Administrador</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        col_home, col_sair = st.columns(2)
        with col_home:
            if st.button("🏠 Home", key="topo_btn_home", width="stretch"):
                navegar_para("home")
        with col_sair:
            if st.button("🚪 Sair", key="topo_btn_sair", width="stretch"):
                fazer_logout()

    st.divider()


def renderizar_menu_lateral() -> None:
    """Menu lateral fixo, disponível em todas as páginas da plataforma."""
    with st.sidebar:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=150)
        st.markdown("#### Menu")

        atual = pagina_atual()
        for chave, rotulo in PAGINAS:
            tipo = "primary" if chave == atual else "secondary"
            if st.button(rotulo, key=f"menu_{chave}", width="stretch", type=tipo):
                navegar_para(chave)

        st.divider()
        if st.button("🚪 Sair", key="menu_btn_sair", width="stretch"):
            fazer_logout()


def renderizar_rodape() -> None:
    """Rodapé discreto, exibido ao final de toda página."""
    st.divider()
    st.markdown(
        f"""
        <div class="amf3-rodape">
            <strong>{NOME_EMPRESA}</strong><br>
            {SUBTITULO_PLATAFORMA}<br>
            Versão {VERSAO_SISTEMA} — Atualizado em {DATA_ATUALIZACAO}
        </div>
        """,
        unsafe_allow_html=True,
    )


def renderizar_pagina_em_construcao(icone: str, titulo: str, descricao: str, futuras: list[str]) -> None:
    """Corpo padrão para módulos ainda não implementados (Petição Inicial,
    Calculadora, Configurações) — evita duplicar essa estrutura em cada página.
    """
    st.markdown(f"## {icone} {titulo}")
    st.info("Este módulo será implementado em uma etapa futura.")
    st.write(descricao)
    if futuras:
        st.markdown("**Funcionalidades futuras planejadas:**")
        for item in futuras:
            st.markdown(f"- {item}")
