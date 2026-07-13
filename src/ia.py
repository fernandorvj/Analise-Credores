"""Integração com a API da OpenAI: geração de resumo executivo e respostas a
perguntas sobre a análise já calculada dos credores.

Este é o único módulo do sistema que acessa a API da OpenAI — nenhum outro
módulo deve importar o cliente diretamente. CPF/CNPJ nunca são enviados ao
modelo; apenas nomes, classes, valores e métricas agregadas.
"""

from __future__ import annotations

import json

from openai import OpenAI, OpenAIError

from config import OPENAI_API_KEY, OPENAI_MODEL, configurar_logging, possui_chave_openai
from src import analise_quorum, estrategia
from src.models import ResultadoExtracao

logger = configurar_logging()

_INSTRUCOES_BASE = (
    "Você é um analista técnico que apoia uma equipe de aquisição de créditos em processos de "
    "Recuperação Judicial. Responda em português do Brasil, de forma objetiva. Baseie-se "
    "exclusivamente nos dados numéricos fornecidos — nunca invente credores, valores ou fatos "
    "que não estejam nos dados. Não forneça aconselhamento jurídico ou financeiro; apresente "
    "apenas leituras técnicas dos números (concentração, quórum, oportunidades de negociação)."
)


def _client() -> OpenAI:
    if not possui_chave_openai():
        raise RuntimeError(
            "Nenhuma chave de API da OpenAI configurada. Defina OPENAI_API_KEY no arquivo .env."
        )
    return OpenAI(api_key=OPENAI_API_KEY)


def _montar_contexto(resultado: ResultadoExtracao) -> dict:
    """Resumo agregado e sem PII (sem CPF/CNPJ) da análise, para enviar ao modelo."""
    df_resumo_classe = analise_quorum.resumo_por_classe(resultado.credores)
    df_ranking = analise_quorum.ranking_maiores_credores(resultado.credores, top_n=10)
    concentracao = estrategia.concentracao_votos(resultado.credores)
    simulacoes = estrategia.simular_formacao_quorum(resultado.credores)

    return {
        "arquivo": resultado.arquivo_nome,
        "total_credores": resultado.total_credores,
        "valor_total_passivo": analise_quorum.valor_total_passivo(resultado.credores),
        "pendentes_revisao": len(resultado.credores_para_revisar) + len(resultado.credores_com_erro),
        "resumo_por_classe": (
            df_resumo_classe.to_dict(orient="records") if not df_resumo_classe.empty else []
        ),
        "top_10_credores": (
            df_ranking[["Ranking", "Nome", "Classe", "Valor", "% do Passivo Total"]].to_dict(
                orient="records"
            )
            if not df_ranking.empty
            else []
        ),
        "concentracao_votos": concentracao,
        "simulacoes_quorum": [
            {
                "percentual_alvo": s.percentual_alvo,
                "credores_necessarios": s.credores_necessarios,
                "valor_necessario": s.valor_necessario,
                "atingivel": s.atingivel,
            }
            for s in simulacoes
        ],
    }


def _chamar_modelo(prompt: str, temperatura: float = 0.3) -> str:
    try:
        resposta = _client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _INSTRUCOES_BASE},
                {"role": "user", "content": prompt},
            ],
            temperature=temperatura,
        )
    except OpenAIError as exc:
        logger.error("Falha ao chamar a API da OpenAI: %s", type(exc).__name__)
        raise RuntimeError(
            "Não foi possível concluir a chamada à IA no momento. Tente novamente mais tarde."
        ) from exc

    return (resposta.choices[0].message.content or "").strip()


def gerar_resumo_executivo(resultado: ResultadoExtracao) -> str:
    """Gera, via OpenAI, um resumo executivo (3-5 parágrafos) da análise de credores."""
    contexto = _montar_contexto(resultado)
    prompt = (
        f"Dados agregados da análise (JSON):\n{json.dumps(contexto, ensure_ascii=False, indent=2)}\n\n"
        "Escreva um resumo executivo de 3 a 5 parágrafos cobrindo: (1) visão geral do passivo e "
        "composição por classe, (2) concentração de credores e o que isso implica para formação "
        "de quórum, (3) leitura das simulações de aquisição de quórum apresentadas."
    )
    return _chamar_modelo(prompt)


def responder_pergunta(resultado: ResultadoExtracao, pergunta: str) -> str:
    """Responde a uma pergunta livre do usuário sobre a análise, com o mesmo contexto agregado."""
    contexto = _montar_contexto(resultado)
    prompt = (
        f"Dados agregados da análise (JSON):\n{json.dumps(contexto, ensure_ascii=False, indent=2)}\n\n"
        f"Pergunta do usuário: {pergunta}"
    )
    return _chamar_modelo(prompt)
