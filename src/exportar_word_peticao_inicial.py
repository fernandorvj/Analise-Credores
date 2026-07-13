"""Exportação do relatório do módulo Petição Inicial para Word (.docx).

Estrutura: capa, sumário, as 12 seções do relatório (nesta ordem — ver
`SECOES` em `src/models_peticao_inicial.py`) e um bloco final de avisos sobre
a extração/geração. Reaproveita a marca visual e os helpers genéricos de
`src/exportar_word_base.py` (mesmo módulo usado pelo relatório de Credores),
nunca duplicando a lógica de capa/tabela/rodapé.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from docx import Document

from config import NOME_EMPRESA, configurar_logging
from src import exportar_word_base as base
from src.models_peticao_inicial import (
    SECOES,
    DadosEmpresa,
    EventoCronologia,
    ItemComJustificativa,
    RelatorioPeticaoInicial,
)

logger = configurar_logging()

_TEXTO_AVISO_CAPA = (
    "Este relatório é gerado com apoio de Inteligência Artificial a partir do documento "
    "enviado, refletindo exclusivamente o que foi identificado no texto. Não constitui "
    "aconselhamento jurídico ou financeiro e não garante resultado."
)


def _renderizar_dados_empresa(doc: Document, dados: DadosEmpresa) -> None:
    campos = [
        ("Razão Social", dados.razao_social),
        ("Nome Fantasia", dados.nome_fantasia),
        ("CNPJ", dados.cnpj),
        ("Segmento", dados.segmento),
        ("Atividade", dados.atividade),
        ("Grupo Econômico", dados.grupo_economico),
        ("Nº de Funcionários", dados.numero_funcionarios),
        ("Filiais", dados.filiais),
        ("Mercado de Atuação", dados.mercado_atuacao),
        *dados.outros_dados,
    ]
    base.adicionar_tabela_dataframe(doc, pd.DataFrame(campos, columns=["Campo", "Valor"]))


def _renderizar_secao(doc: Document, titulo: str, valor: object) -> None:
    doc.add_heading(titulo, level=1)

    if isinstance(valor, DadosEmpresa):
        _renderizar_dados_empresa(doc, valor)
        return

    if isinstance(valor, list):
        if not valor:
            doc.add_paragraph("Não foi possível identificar itens para esta seção no documento.")
        elif isinstance(valor[0], EventoCronologia):
            df = pd.DataFrame([{"Data": e.data, "Evento": e.evento} for e in valor])
            base.adicionar_tabela_dataframe(doc, df)
        elif isinstance(valor[0], ItemComJustificativa):
            df = pd.DataFrame([{"Ponto": i.ponto, "Justificativa": i.justificativa} for i in valor])
            base.adicionar_tabela_dataframe(doc, df)
        return

    doc.add_paragraph(str(valor) or "Não foi possível gerar esta seção automaticamente.")


def exportar_word_peticao_inicial(relatorio: RelatorioPeticaoInicial, caminho_saida: str | Path) -> Path:
    """Gera o relatório .docx completo (capa + sumário + 12 seções) a partir
    de um `RelatorioPeticaoInicial` já preenchido (ver `src/ia.py`).
    """
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    base.adicionar_capa(
        doc,
        relatorio.arquivo_nome,
        subtitulo_modulo="Relatório de Análise de Petição Inicial",
        texto_aviso=_TEXTO_AVISO_CAPA,
        pagina_isolada=True,
    )
    base.adicionar_sumario(doc)

    for titulo, chave in SECOES:
        _renderizar_secao(doc, titulo, getattr(relatorio, chave))

    if relatorio.paginas_ocr_baixa_confianca or relatorio.avisos:
        doc.add_heading("Avisos sobre a Extração/Geração", level=1)
        if relatorio.paginas_ocr_baixa_confianca:
            paginas = ", ".join(str(p) for p in relatorio.paginas_ocr_baixa_confianca)
            doc.add_paragraph(
                f"As páginas {paginas} foram lidas via OCR com possível baixa qualidade de "
                "reconhecimento — recomenda-se revisão manual dessas páginas no PDF original.",
                style="List Bullet",
            )
        for aviso in relatorio.avisos:
            doc.add_paragraph(aviso, style="List Bullet")

    base.adicionar_rodape_paginacao(doc, f"{NOME_EMPRESA} — Análise de Petição Inicial")

    doc.save(caminho_saida)
    logger.info("Word da Petição Inicial exportado em '%s' (%s).", caminho_saida, relatorio.arquivo_nome)
    return caminho_saida
