"""Ícones padronizados da plataforma — Google Material Symbols, nativos do
Streamlit via shortcode ``:material/nome:`` (aceito tanto em ``st.markdown``
quanto no parâmetro ``icon=`` de ``st.button``). Sem CDN externo, sem SVG
embutido à mão: um único lugar para trocar o ícone de um conceito no futuro.
"""

from __future__ import annotations

NOMES = {
    "home": "home",
    "credores": "group",
    "peticao_inicial": "description",
    "calculadora": "calculate",
    "configuracoes": "settings",
    "sair": "logout",
    "usuario": "person",
    "cadeado": "lock",
    "aprovado": "check_circle",
    "alerta": "warning",
    "erro": "error",
    "entrar": "arrow_forward",
    "financiamento": "account_balance",
    "balao": "trending_up",
    "fluxo": "swap_horiz",
    "vpl": "insights",
    "comparacao": "compare_arrows",
    "config_financeira": "tune",
    "exportar": "download",
    "adicionar": "add",
    "excluir": "delete",
    "atualizar": "refresh",
}


def icone(chave: str) -> str:
    """Shortcode Material Symbols para a chave dada — use direto em
    ``st.button(icon=icone("home"))`` ou dentro de uma f-string para
    ``st.markdown`` (ex.: ``f"### {icone('credores')} Credores"``).
    """
    return f":material/{NOMES[chave]}:"
