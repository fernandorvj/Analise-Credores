"""Camada de navegação compartilhada por todas as páginas da plataforma AMF3.

Cabeçalho superior, menu lateral, rodapé e troca de página — nada aqui
contém lógica de negócio de nenhum módulo específico (Credores, Petição
Inicial, Calculadora); cada módulo continua responsável pelo seu próprio
conteúdo. A navegação principal é a sidebar (`renderizar_menu_lateral`,
recolhível nativamente pelo Streamlit); a Home continua existindo como
landing institucional com os cards de módulo.
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
from interface.icones import icone

# (chave interna da página, rótulo exibido no menu, chave do ícone) — a chave
# interna de "calculadora" é mantida por compatibilidade de rotas/session_state
# mesmo com o rótulo agora refletindo o nome do módulo na Home ("Simulação de
# Financiamento"); a antiga aba de VPL dessa página migra para "precificacao"
# numa fase futura, sem remover nada enquanto isso não acontecer.
PAGINAS = [
    ("home", "Home", "home"),
    ("credores", "Credores", "credores"),
    ("peticao_inicial", "Petição Inicial", "peticao_inicial"),
    ("precificacao", "Precificação Inteligente", "precificacao"),
    ("calculadora", "Simulação de Financiamento", "calculadora"),
    ("analise_documentos", "Análise de Documentos", "analise_documentos"),
    ("proposta_credor", "Proposta ao Credor", "proposta_credor"),
    ("configuracoes", "Configurações", "configuracoes"),
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


def renderizar_menu_lateral() -> None:
    """Menu lateral, recolhível nativamente pelo Streamlit (seta no topo) —
    navegação principal da plataforma. A Home continua acessível como landing
    institucional (cards de módulo), mas trocar de módulo rapidamente a
    partir de qualquer página passa a ser feito por aqui.
    """
    pagina = pagina_atual()
    with st.sidebar:
        st.markdown(
            f'<div class="amf3-sidebar-marca">{NOME_PLATAFORMA}</div>',
            unsafe_allow_html=True,
        )
        for chave, rotulo, chave_icone in PAGINAS:
            ativo = chave == pagina
            if st.button(
                rotulo,
                key=f"menu_{chave}",
                icon=icone(chave_icone),
                type="primary" if ativo else "secondary",
                width="stretch",
            ):
                if not ativo:
                    navegar_para(chave)


def renderizar_cabecalho_app() -> None:
    """Cabeçalho fixo (sticky) no topo de toda página pós-login: logo,
    identidade da plataforma e, à direita, usuário logado + botões
    Home/Configurações/Sair. O `st.container(key=...)` ao redor das colunas
    existe só para dar à CSS um "invólucro" único do cabeçalho inteiro (ver
    `.st-key-amf3_cabecalho_shell` em assets/estilos.css) — sem isso, CSS só
    alcançaria cada coluna isoladamente, não a barra como uma unidade fixa.
    """
    with st.container(key="amf3_cabecalho_shell"):
        col_logo, col_titulo, col_usuario = st.columns([1, 3, 1.6], vertical_alignment="center")

        with col_logo:
            if LOGO_PATH.exists():
                with st.container(key="amf3_logo_chip"):
                    st.image(str(LOGO_PATH), width=110)

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
            col_home, col_config, col_sair = st.columns(3)
            with col_home:
                if st.button("Home", key="topo_btn_home", icon=icone("home"), width="stretch"):
                    navegar_para("home")
            with col_config:
                if st.button("Config.", key="topo_btn_config", icon=icone("configuracoes"), width="stretch"):
                    navegar_para("configuracoes")
            with col_sair:
                if st.button("Sair", key="topo_btn_sair", icon=icone("sair"), width="stretch"):
                    fazer_logout()

    st.divider()


def renderizar_titulo_pagina(chave_icone: str, titulo: str) -> None:
    """Título compacto e consistente para o topo do conteúdo de uma página
    (substitui, em cada módulo, um cabeçalho grande próprio — evita duplicar
    banners empilhados sob o cabeçalho global da plataforma). Usa o shortcode
    de ícone nativo do Streamlit dentro do markdown — mesmo mecanismo já usado
    nos botões, sem depender de nenhum detalhe interno de implementação.

    A navegação entre módulos é feita pela sidebar (`renderizar_menu_lateral`);
    esta função não injeta mais um botão de retorno redundante.
    """
    with st.container(key="amf3_titulo_pagina"):
        st.markdown(f"## {icone(chave_icone)} {titulo}")


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


def renderizar_pagina_em_construcao(chave_icone: str, titulo: str, descricao: str, futuras: list[str]) -> None:
    """Corpo padrão para módulos ainda não implementados (Petição Inicial,
    Calculadora, Configurações) — evita duplicar essa estrutura em cada página.
    """
    renderizar_titulo_pagina(chave_icone, titulo)
    st.info("Este módulo será implementado em uma etapa futura.")
    st.write(descricao)
    if futuras:
        st.markdown("**Funcionalidades futuras planejadas:**")
        for item in futuras:
            st.markdown(f"- {item}")
