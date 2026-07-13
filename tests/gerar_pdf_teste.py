"""Gera um PDF sintético de relação de credores para testes manuais do pipeline.

Não faz parte do sistema em produção — uso interno de desenvolvimento.
"""

from __future__ import annotations

import fitz  # PyMuPDF

from config import PDFS_DIR

LINHAS_CREDORES = [
    "RELAÇÃO DE CREDORES - PROCESSO 0001234-56.2024.8.06.0001",
    "",
    "Nome                                CPF/CNPJ              Classe                        Valor",
    "JOAO DA SILVA SANTOS                111.444.777-35        Classe III - Quirografário    R$ 45.320,10",
    "MARIA OLIVEIRA COSTA                529.982.247-25        Classe I - Trabalhista         R$ 12.500,00",
    "BANCO EXEMPLO S.A.                  11.222.333/0001-81     Classe II - Garantia Real      R$ 1.230.450,90",
    "COMERCIO DE PECAS LTDA ME           22.333.444/0001-55     Classe IV - ME/EPP             R$ 8.760,45",
    "PEDRO ALVES FERREIRA                111.222.333-96        Classe III - Quirografário    R$ 320.000,00",
    "DOCUMENTO INVALIDO TESTE            123.456.789-00        Classe III - Quirografário    R$ 5.000,00",
    "CREDOR SEM VALOR TESTE              444.555.666-77        Classe III - Quirografário    ",
]


def gerar_pdf_teste(nome_arquivo: str = "exemplo_credores.pdf") -> str:
    doc = fitz.open()
    pagina = doc.new_page()
    y = 50
    for linha in LINHAS_CREDORES:
        pagina.insert_text((36, y), linha, fontsize=9, fontname="cour")
        y += 16

    caminho = PDFS_DIR / nome_arquivo
    doc.save(caminho)
    doc.close()
    return str(caminho)


if __name__ == "__main__":
    caminho = gerar_pdf_teste()
    print(f"PDF de teste gerado em: {caminho}")
