"""Integração com a API da OpenAI: geração de resumo executivo e respostas a
perguntas sobre a análise já calculada dos credores.

Este é o único módulo do sistema que acessa a API da OpenAI — nenhum outro
módulo deve importar o cliente diretamente. CPF/CNPJ nunca são enviados ao
modelo; apenas nomes, classes, valores e métricas agregadas.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Callable

from openai import OpenAI, OpenAIError

from config import OPENAI_API_KEY, OPENAI_MODEL, configurar_logging, possui_chave_openai
from src import analise_quorum, estrategia
from src.leitor_pdf import PaginaExtraida
from src.models import ResultadoExtracao
from src.models_peticao_inicial import (
    MENSAGEM_PASSIVO_FISCAL_AUSENTE,
    NAO_LOCALIZADO,
    VALOR_FISCAL_NAO_LOCALIZADO,
    DadosEmpresa,
    EventoCronologia,
    ItemComJustificativa,
    PassivoFiscal,
    RelatorioPeticaoInicial,
    TrechoFiscal,
)

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


def _chamar_modelo_bruto(mensagens: list[dict], temperatura: float, response_format: dict | None = None) -> str:
    """Plumbing única de chamada ao modelo (cliente + tratamento de erro) —
    usada tanto por `_chamar_modelo` (Credores) quanto pela orquestração da
    Petição Inicial mais abaixo, para não duplicar o try/except de erro.
    """
    try:
        kwargs: dict = {"model": OPENAI_MODEL, "messages": mensagens, "temperature": temperatura}
        if response_format is not None:
            kwargs["response_format"] = response_format
        resposta = _client().chat.completions.create(**kwargs)
    except OpenAIError as exc:
        logger.error("Falha ao chamar a API da OpenAI: %s", type(exc).__name__)
        raise RuntimeError(
            "Não foi possível concluir a chamada à IA no momento. Tente novamente mais tarde."
        ) from exc

    return (resposta.choices[0].message.content or "").strip()


def _chamar_modelo(prompt: str, temperatura: float = 0.3) -> str:
    return _chamar_modelo_bruto(
        [
            {"role": "system", "content": _INSTRUCOES_BASE},
            {"role": "user", "content": prompt},
        ],
        temperatura=temperatura,
    )


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


# =============================================================================
# Petição Inicial — módulo independente do Credores acima, mas reutilizando o
# mesmo `_client()`/`_chamar_modelo_bruto()` (gateway único da API OpenAI).
# Nenhuma função do bloco Credores acima foi alterada em comportamento.
# =============================================================================

_INSTRUCOES_PETICAO = (
    "Você é um analista técnico que apoia a equipe de aquisição de créditos da AMF3 Capital na "
    "leitura de Petições Iniciais de Recuperação Judicial. Responda sempre em português do "
    "Brasil, de forma técnica, objetiva e organizada. Baseie-se exclusivamente no texto "
    "fornecido — nunca invente fatos, números, nomes ou datas que não estejam no documento. "
    "Quando uma informação não estiver presente, diga isso explicitamente em vez de adivinhar. "
    "Não forneça aconselhamento jurídico ou financeiro nem garanta resultados."
)

# Termos (e variações/sinônimos que a IA deve considerar) que caracterizam a
# seção obrigatória "Passivo Fiscal e Execuções Fiscais" — usados tanto no
# prompt de mapeamento (busca por bloco) quanto no de redução (montagem final).
_PALAVRAS_CHAVE_FISCAL = (
    "Passivo Fiscal", "Débitos Tributários", "Execuções Fiscais", "Dívida Ativa",
    "Procuradoria-Geral da Fazenda Nacional (PGFN)", "Receita Federal", "Fazenda Nacional",
    "Fazenda Estadual", "Fazenda Municipal", "Débitos Previdenciários", "INSS", "FGTS", "ICMS",
    "ISS", "PIS", "COFINS", "IRPJ", "CSLL", "IPI", "Simples Nacional", "Parcelamentos Tributários",
    "Transação Tributária", "REFIS", "Acordos Tributários", "Garantias Fiscais", "Penhoras Fiscais",
    "Bloqueios Judiciais", "Certidões Negativas", "Certidões Positivas", "Execuções Administrativas",
    "Autos de Infração", "Contencioso Tributário",
)

# Limiar (em caracteres) a partir do qual o texto completo deixa de caber com
# folga numa única chamada e passa a ser dividido em blocos (map) antes da
# consolidação final (reduce). ~90k caracteres ≈ 22-24k tokens — bem dentro
# da janela de contexto do gpt-4o-mini, com margem para prompt e resposta.
_LIMIAR_CARACTERES_TEXTO_UNICO = 90_000
_TAMANHO_ALVO_BLOCO = 40_000

_ESQUEMA_JSON_RELATORIO = """{
  "resumo_executivo": "string",
  "sobre_empresa": {
    "razao_social": "string", "nome_fantasia": "string", "cnpj": "string",
    "segmento": "string", "atividade": "string", "grupo_economico": "string",
    "numero_funcionarios": "string", "filiais": "string", "mercado_atuacao": "string"
  },
  "historico_empresa": "string",
  "motivos_recuperacao_judicial": "string",
  "situacao_financeira": "string",
  "cronologia_fatos": [{"data": "string", "evento": "string"}],
  "principais_riscos": "string",
  "pontos_positivos": [{"ponto": "string", "justificativa": "string"}],
  "pontos_atencao": [{"ponto": "string", "justificativa": "string"}],
  "visao_estrategica_aquisicao": "string",
  "fatores_impacto_quorum": "string",
  "passivo_fiscal": {
    "existe_passivo_fiscal": "Sim | Não | não localizado",
    "existe_execucao_fiscal": "Sim | Não | não localizado",
    "existe_parcelamento": "Sim | Não | não localizado",
    "existe_transacao_tributaria": "Sim | Não | não localizado",
    "existe_discussao_administrativa_judicial": "Sim | Não | não localizado",
    "resumo": "string",
    "valor_passivo_fiscal": "string",
    "valor_execucoes_fiscais": "string",
    "quantidade_processos": "string",
    "tributos_envolvidos": ["string"],
    "orgaos_envolvidos": ["string"],
    "trechos_localizados": [{"pagina": "string", "trecho": "string", "contexto": "string"}],
    "avaliacao_estrategica": "string",
    "grau_atencao": "Baixo | Médio | Alto",
    "justificativa_grau_atencao": "string"
  },
  "resumo_final": "string"
}"""


def _texto_paginas(paginas: list[PaginaExtraida]) -> str:
    return "\n\n".join(f"--- Página {p.numero} ---\n{p.texto}" for p in paginas)


def _dividir_em_blocos(paginas: list[PaginaExtraida]) -> list[list[PaginaExtraida]]:
    """Agrupa páginas em blocos de até `_TAMANHO_ALVO_BLOCO` caracteres, sem
    nunca dividir o texto de uma mesma página entre dois blocos.
    """
    blocos: list[list[PaginaExtraida]] = []
    bloco_atual: list[PaginaExtraida] = []
    tamanho_atual = 0
    for pagina in paginas:
        tamanho_pagina = len(pagina.texto)
        if bloco_atual and tamanho_atual + tamanho_pagina > _TAMANHO_ALVO_BLOCO:
            blocos.append(bloco_atual)
            bloco_atual = []
            tamanho_atual = 0
        bloco_atual.append(pagina)
        tamanho_atual += tamanho_pagina
    if bloco_atual:
        blocos.append(bloco_atual)
    return blocos


def _prompt_mapa(bloco_texto: str, indice: int, total: int, pagina_inicial: int, pagina_final: int) -> str:
    lista_palavras_chave = ", ".join(_PALAVRAS_CHAVE_FISCAL)
    return (
        f"Você está lendo o BLOCO {indice}/{total} (páginas {pagina_inicial} a {pagina_final}) de "
        "uma Petição Inicial de Recuperação Judicial. Sob cada um dos 13 rótulos abaixo, liste "
        "apenas fatos brutos, números, nomes e datas ENCONTRADOS NESTE BLOCO — não resuma, não "
        "interprete, e não conclua 'não localizado' aqui (essa decisão só é tomada depois de ver "
        "todos os blocos). Se nada aparecer sob um rótulo neste bloco, escreva 'Nada neste "
        "bloco.'\n\n"
        "Rótulos: Resumo Executivo; Sobre a Empresa (razão social, nome fantasia, CNPJ, "
        "segmento, atividade, grupo econômico, nº de funcionários, filiais, mercado de atuação); "
        "Histórico da Empresa; Motivos da Recuperação Judicial; Situação Financeira; Cronologia "
        "dos Fatos (data + evento); Principais Riscos; Pontos Positivos; Pontos de Atenção; Visão "
        "Estratégica para Aquisição de Créditos; Fatores que Podem Impactar a Formação de "
        "Quórum; Passivo Fiscal e Execuções Fiscais; Resumo Final.\n\n"
        "Para o rótulo 'Passivo Fiscal e Execuções Fiscais', procure de forma minuciosa neste "
        "bloco qualquer menção — considerando sinônimos e diferentes formas de redação — a: "
        f"{lista_palavras_chave}. Para cada menção encontrada, transcreva o número da página, o "
        "trecho literal (verbatim) e uma breve descrição do contexto — nunca resuma nem "
        "interprete aqui, apenas colete.\n\n"
        f"Texto do bloco:\n{bloco_texto}"
    )


def _prompt_reducao(arquivo_nome: str, texto_fonte: str) -> str:
    lista_palavras_chave = ", ".join(_PALAVRAS_CHAVE_FISCAL)
    return (
        f"Documento analisado: {arquivo_nome}\n\n"
        "A seguir está o conteúdo (ou as notas já extraídas por blocos) de uma Petição Inicial "
        "de Recuperação Judicial. Produza o relatório executivo final, respondendo SOMENTE com "
        f"um objeto JSON no formato exato abaixo (sem markdown, sem texto fora do JSON):\n\n"
        f"{_ESQUEMA_JSON_RELATORIO}\n\n"
        "Regras: nunca invente informação que não esteja no texto — quando algo não for "
        f"encontrado, escreva exatamente \"{NAO_LOCALIZADO}\" no campo correspondente (nos "
        "campos de 'sobre_empresa') ou explique a ausência no texto corrido dos demais campos. "
        "'visao_estrategica_aquisicao' deve trazer uma leitura estratégica para a AMF3 Capital "
        "(classes de credores mais relevantes, concentração de passivo, fatores que facilitam ou "
        "dificultam a negociação) SEM prometer resultados nem substituir aconselhamento "
        "jurídico ou financeiro. 'fatores_impacto_quorum' deve indicar grupos econômicos, "
        "credores institucionais, dependência de fornecedores e estrutura do passivo relevantes "
        f"para uma futura formação de quórum — e dizer explicitamente \"{NAO_LOCALIZADO}\" quando "
        "ausente.\n\n"
        "'passivo_fiscal' é uma seção OBRIGATÓRIA — deve sempre ser preenchida, mesmo quando nada "
        "for encontrado. Baseie-se em todas as menções (diretas ou por sinônimo/forma alternativa "
        f"de redação) a: {lista_palavras_chave}, localizadas no texto ou nas notas por bloco. "
        "Preencha 'existe_passivo_fiscal', 'existe_execucao_fiscal', 'existe_parcelamento', "
        "'existe_transacao_tributaria' e 'existe_discussao_administrativa_judicial' cada um com "
        f"\"Sim\", \"Não\" ou \"{NAO_LOCALIZADO}\" (nunca conclua \"Não\" sem evidência explícita "
        "no texto — na dúvida, use \"" + NAO_LOCALIZADO + "\"). Em 'valor_passivo_fiscal' e "
        f"'valor_execucoes_fiscais', escreva exatamente \"{VALOR_FISCAL_NAO_LOCALIZADO}\" quando o "
        "valor não constar no documento. 'trechos_localizados' deve trazer, para cada menção "
        "relevante, a página, o trecho literal (verbatim, nunca parafraseado ou inventado) e o "
        "contexto — liste vazio ([]) se nada for encontrado, nunca invente um trecho. "
        "'avaliacao_estrategica' deve analisar, com base exclusivamente no que foi encontrado, "
        "como o passivo fiscal pode influenciar a Recuperação Judicial, a capacidade de "
        "negociação da empresa, pontos de atenção antes de uma eventual aquisição de créditos e "
        "possíveis impactos na formação de quórum ou andamento do plano — como apoio estratégico, "
        "SEM aconselhamento jurídico, garantia de resultado ou recomendação. 'grau_atencao' deve "
        "ser \"Baixo\", \"Médio\" ou \"Alto\", com 'justificativa_grau_atencao' baseada "
        "exclusivamente no conteúdo encontrado. Se NADA sobre passivo fiscal ou execução fiscal "
        f"for encontrado em nenhum bloco, defina 'resumo' como exatamente:\n\"{MENSAGEM_PASSIVO_FISCAL_AUSENTE}\"\n"
        "e mantenha todos os campos de situação como \"" + NAO_LOCALIZADO + "\", os valores como "
        f"\"{VALOR_FISCAL_NAO_LOCALIZADO}\", 'trechos_localizados' vazio e 'grau_atencao' como "
        "\"Baixo\" (justificando a ausência de menções no documento) — nunca afirme que não existe "
        "passivo fiscal, apenas que não foi encontrado no texto analisado.\n\n"
        "'resumo_final' deve ser um parecer executivo, técnico e objetivo, como se fosse "
        "entregue à Diretoria da AMF3 Capital.\n\n"
        f"Conteúdo:\n{texto_fonte}"
    )


def _chamar_modelo_json(prompt: str, instrucoes: str, temperatura: float = 0.2) -> dict:
    """Chama o modelo pedindo `response_format=json_object`; em caso de falha
    de parse, tenta mais uma vez com temperatura 0 e instrução reforçada.
    Se falhar de novo, propaga `json.JSONDecodeError` — o chamador decide o
    fallback, esta função nunca decide sozinha o que fazer com uma falha.
    """
    mensagens = [
        {"role": "system", "content": instrucoes},
        {"role": "user", "content": prompt},
    ]
    texto = _chamar_modelo_bruto(mensagens, temperatura=temperatura, response_format={"type": "json_object"})
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        logger.warning("Resposta da IA não veio em JSON válido na primeira tentativa; tentando novamente.")
        mensagens_reforcadas = [
            {
                "role": "system",
                "content": instrucoes + " Responda ESTRITAMENTE apenas com o objeto JSON, sem nenhum texto adicional.",
            },
            {"role": "user", "content": prompt},
        ]
        texto_retry = _chamar_modelo_bruto(
            mensagens_reforcadas, temperatura=0.0, response_format={"type": "json_object"}
        )
        return json.loads(texto_retry)


def _paginas_ocr_baixa_confianca(paginas: list[PaginaExtraida]) -> list[int]:
    """Heurística (não é confiança real do Tesseract, que não é exposta pelo
    pipeline de OCR atual): páginas via OCR cujo texto ficou anormalmente
    curto — sinal prático de leitura ruim, para sinalizar revisão manual.
    """
    return [p.numero for p in paginas if p.fonte == "ocr" and len(p.texto.strip()) < 40]


def _construir_relatorio(
    dados: dict,
    arquivo_nome: str,
    total_paginas: int,
    paginas_ocr: list[int],
    paginas_ocr_baixa_confianca: list[int],
    avisos: list[str],
) -> RelatorioPeticaoInicial:
    """Constrói o relatório a partir do dict retornado pela IA de forma
    defensiva: chaves ausentes viram o padrão do dataclass, itens de lista
    malformados são pulados individualmente em vez de derrubar tudo.
    """

    def _texto(chave: str) -> str:
        valor = dados.get(chave, "")
        return valor if isinstance(valor, str) else str(valor)

    sobre_empresa_dados = dados.get("sobre_empresa")
    if not isinstance(sobre_empresa_dados, dict):
        sobre_empresa_dados = {}
    sobre_empresa = DadosEmpresa(
        razao_social=str(sobre_empresa_dados.get("razao_social", NAO_LOCALIZADO)),
        nome_fantasia=str(sobre_empresa_dados.get("nome_fantasia", NAO_LOCALIZADO)),
        cnpj=str(sobre_empresa_dados.get("cnpj", NAO_LOCALIZADO)),
        segmento=str(sobre_empresa_dados.get("segmento", NAO_LOCALIZADO)),
        atividade=str(sobre_empresa_dados.get("atividade", NAO_LOCALIZADO)),
        grupo_economico=str(sobre_empresa_dados.get("grupo_economico", NAO_LOCALIZADO)),
        numero_funcionarios=str(sobre_empresa_dados.get("numero_funcionarios", NAO_LOCALIZADO)),
        filiais=str(sobre_empresa_dados.get("filiais", NAO_LOCALIZADO)),
        mercado_atuacao=str(sobre_empresa_dados.get("mercado_atuacao", NAO_LOCALIZADO)),
    )

    cronologia: list[EventoCronologia] = []
    for item in dados.get("cronologia_fatos") or []:
        try:
            cronologia.append(EventoCronologia(data=str(item["data"]), evento=str(item["evento"])))
        except (KeyError, TypeError):
            continue

    pontos_positivos: list[ItemComJustificativa] = []
    for item in dados.get("pontos_positivos") or []:
        try:
            pontos_positivos.append(ItemComJustificativa(ponto=str(item["ponto"]), justificativa=str(item["justificativa"])))
        except (KeyError, TypeError):
            continue

    pontos_atencao: list[ItemComJustificativa] = []
    for item in dados.get("pontos_atencao") or []:
        try:
            pontos_atencao.append(ItemComJustificativa(ponto=str(item["ponto"]), justificativa=str(item["justificativa"])))
        except (KeyError, TypeError):
            continue

    passivo_fiscal_dados = dados.get("passivo_fiscal")
    if not isinstance(passivo_fiscal_dados, dict):
        passivo_fiscal_dados = {}

    trechos_fiscais: list[TrechoFiscal] = []
    for item in passivo_fiscal_dados.get("trechos_localizados") or []:
        try:
            trechos_fiscais.append(
                TrechoFiscal(
                    pagina=str(item.get("pagina") or "-"),
                    trecho=str(item["trecho"]),
                    contexto=str(item.get("contexto") or ""),
                )
            )
        except (KeyError, TypeError, AttributeError):
            continue

    def _lista_str(chave: str) -> list[str]:
        valor = passivo_fiscal_dados.get(chave)
        if not isinstance(valor, list):
            return []
        return [str(item) for item in valor if str(item).strip()]

    passivo_fiscal = PassivoFiscal(
        existe_passivo_fiscal=str(passivo_fiscal_dados.get("existe_passivo_fiscal", NAO_LOCALIZADO)),
        existe_execucao_fiscal=str(passivo_fiscal_dados.get("existe_execucao_fiscal", NAO_LOCALIZADO)),
        existe_parcelamento=str(passivo_fiscal_dados.get("existe_parcelamento", NAO_LOCALIZADO)),
        existe_transacao_tributaria=str(passivo_fiscal_dados.get("existe_transacao_tributaria", NAO_LOCALIZADO)),
        existe_discussao_administrativa_judicial=str(
            passivo_fiscal_dados.get("existe_discussao_administrativa_judicial", NAO_LOCALIZADO)
        ),
        resumo=str(passivo_fiscal_dados.get("resumo") or MENSAGEM_PASSIVO_FISCAL_AUSENTE),
        valor_passivo_fiscal=str(passivo_fiscal_dados.get("valor_passivo_fiscal") or VALOR_FISCAL_NAO_LOCALIZADO),
        valor_execucoes_fiscais=str(passivo_fiscal_dados.get("valor_execucoes_fiscais") or VALOR_FISCAL_NAO_LOCALIZADO),
        quantidade_processos=str(passivo_fiscal_dados.get("quantidade_processos", NAO_LOCALIZADO)),
        tributos_envolvidos=_lista_str("tributos_envolvidos"),
        orgaos_envolvidos=_lista_str("orgaos_envolvidos"),
        trechos_localizados=trechos_fiscais,
        avaliacao_estrategica=str(passivo_fiscal_dados.get("avaliacao_estrategica", "")),
        grau_atencao=str(passivo_fiscal_dados.get("grau_atencao") or "Baixo"),
        justificativa_grau_atencao=str(passivo_fiscal_dados.get("justificativa_grau_atencao", "")),
    )

    return RelatorioPeticaoInicial(
        arquivo_nome=arquivo_nome,
        data_analise=date.today(),
        total_paginas=total_paginas,
        paginas_ocr=paginas_ocr,
        paginas_ocr_baixa_confianca=paginas_ocr_baixa_confianca,
        avisos=avisos,
        resumo_executivo=_texto("resumo_executivo"),
        sobre_empresa=sobre_empresa,
        historico_empresa=_texto("historico_empresa"),
        motivos_recuperacao_judicial=_texto("motivos_recuperacao_judicial"),
        situacao_financeira=_texto("situacao_financeira"),
        cronologia_fatos=cronologia,
        principais_riscos=_texto("principais_riscos"),
        pontos_positivos=pontos_positivos,
        pontos_atencao=pontos_atencao,
        visao_estrategica_aquisicao=_texto("visao_estrategica_aquisicao"),
        fatores_impacto_quorum=_texto("fatores_impacto_quorum"),
        passivo_fiscal=passivo_fiscal,
        resumo_final=_texto("resumo_final"),
    )


def gerar_relatorio_peticao_inicial(
    paginas: list[PaginaExtraida],
    arquivo_nome: str,
    progress_callback: Callable[[str], None] | None = None,
) -> RelatorioPeticaoInicial:
    """Gera o relatório completo (13 seções) de uma Petição Inicial já lida
    (`src.leitor_pdf.ler_pdf`). Documentos grandes são divididos em blocos
    (map) e consolidados numa única chamada final (reduce) — o usuário nunca
    vê os blocos, só o relatório final. `progress_callback`, se informado, é
    chamado com uma mensagem curta a cada fase (uso: atualizar a UI).
    """
    avisar = progress_callback or (lambda _msg: None)

    paginas_ocr = [p.numero for p in paginas if p.fonte == "ocr"]
    baixa_confianca = _paginas_ocr_baixa_confianca(paginas)
    avisos: list[str] = []

    paginas_indisponiveis = [p.numero for p in paginas if p.fonte == "ocr_indisponivel"]
    if paginas_indisponiveis:
        avisos.append(
            "OCR indisponível para as página(s) "
            + ", ".join(str(p) for p in paginas_indisponiveis)
            + " — o conteúdo dessas páginas não pôde ser lido e não está refletido no relatório."
        )

    texto_completo = _texto_paginas(paginas)

    if len(texto_completo) <= _LIMIAR_CARACTERES_TEXTO_UNICO:
        avisar(f"Consultando IA (documento único, {len(paginas)} página(s))...")
        texto_fonte = texto_completo
    else:
        blocos = _dividir_em_blocos(paginas)
        notas_blocos = []
        for indice, bloco in enumerate(blocos, start=1):
            avisar(f"Consultando IA (bloco {indice}/{len(blocos)})...")
            prompt_mapa = _prompt_mapa(
                _texto_paginas(bloco), indice, len(blocos), bloco[0].numero, bloco[-1].numero
            )
            nota = _chamar_modelo_bruto(
                [
                    {"role": "system", "content": _INSTRUCOES_PETICAO},
                    {"role": "user", "content": prompt_mapa},
                ],
                temperatura=0.2,
            )
            notas_blocos.append(
                f"=== Notas do bloco {indice}/{len(blocos)} "
                f"(páginas {bloco[0].numero}-{bloco[-1].numero}) ===\n{nota}"
            )
        avisos.append(
            f"Documento extenso: dividido em {len(blocos)} bloco(s) para análise pela IA e "
            "consolidado num único relatório."
        )
        texto_fonte = "\n\n".join(notas_blocos)

    avisar("Gerando relatório final...")
    prompt_final = _prompt_reducao(arquivo_nome, texto_fonte)
    try:
        dados = _chamar_modelo_json(prompt_final, _INSTRUCOES_PETICAO, temperatura=0.2)
    except json.JSONDecodeError:
        logger.error("Não foi possível interpretar a resposta da IA como JSON para '%s'.", arquivo_nome)
        mensagem_falha = (
            "Não foi possível gerar esta seção automaticamente (falha ao interpretar a resposta "
            "da IA). Tente gerar o relatório novamente."
        )
        avisos.append(mensagem_falha)
        dados_fallback = {
            chave: mensagem_falha
            for chave in (
                "resumo_executivo",
                "historico_empresa",
                "motivos_recuperacao_judicial",
                "situacao_financeira",
                "principais_riscos",
                "visao_estrategica_aquisicao",
                "fatores_impacto_quorum",
                "resumo_final",
            )
        }
        dados_fallback["passivo_fiscal"] = {
            "existe_passivo_fiscal": NAO_LOCALIZADO,
            "existe_execucao_fiscal": NAO_LOCALIZADO,
            "existe_parcelamento": NAO_LOCALIZADO,
            "existe_transacao_tributaria": NAO_LOCALIZADO,
            "existe_discussao_administrativa_judicial": NAO_LOCALIZADO,
            "resumo": mensagem_falha,
            "avaliacao_estrategica": mensagem_falha,
        }
        return _construir_relatorio(
            dados_fallback, arquivo_nome, len(paginas), paginas_ocr, baixa_confianca, avisos
        )

    return _construir_relatorio(dados, arquivo_nome, len(paginas), paginas_ocr, baixa_confianca, avisos)
