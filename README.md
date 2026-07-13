# RJ Análise de Credores

Sistema interno da **AMF3 Capital** para transformar a relação de credores de um processo de
Recuperação Judicial (PDF) em uma plataforma de análise: extração estruturada, cálculos de
quórum por classe, simulações de aquisição de crédito e exportação de relatórios.

> As análises geradas por este sistema são **cenários técnicos baseados exclusivamente nos
> dados extraídos do PDF**. Não constituem aconselhamento jurídico ou financeiro.

## Requisitos

- Python 3.11+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) instalado no Windows (para PDFs escaneados)
- Uma chave de API da OpenAI válida

### Tesseract OCR — status nesta máquina

Já instalado via `winget install UB-Mannheim.TesseractOCR` (v5.4.0, executável em
`C:\Program Files\Tesseract-OCR\tesseract.exe`).

O instalador silencioso não inclui o pacote de idioma português. Como a instalação em
`Program Files` exige privilégio de administrador, o pacote `por.traineddata` foi colocado em
uma pasta alternativa gravável pelo usuário:

```
%LOCALAPPDATA%\RJ_Analise_Credores\tessdata\   (eng.traineddata, osd.traineddata, por.traineddata)
```

`src/ocr.py` aponta o Tesseract para essa pasta automaticamente via a variável de ambiente
`TESSDATA_PREFIX`, sem precisar de admin. Para usar outra pasta (ex.: em outra máquina), defina
`TESSDATA_DIR=caminho\para\tessdata` no `.env` — essa variável tem prioridade sobre a pasta padrão.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copie `.env.example` para `.env` e preencha `OPENAI_API_KEY` caso ainda não exista um `.env`
configurado.

## Executando

```bash
streamlit run app.py
```

## Estrutura do projeto

```
RJ_Analise_Credores/
├── app.py                  # ponto de entrada Streamlit
├── config.py                # caminhos, segredos, constantes
├── src/
│   ├── models.py             # dataclasses Credor / ResultadoExtracao
│   ├── utils.py               # validação de CPF/CNPJ, parsing de valores
│   ├── leitor_pdf.py          # triagem digital/escaneado + extração de texto/tabelas
│   ├── ocr.py                  # OCR via Tesseract para páginas escaneadas
│   ├── parser_credores.py      # extração estruturada dos registros de credores
│   ├── analise_quorum.py       # totais, percentuais, ranking por classe
│   ├── estrategia.py            # simulações de aquisição e formação de quórum
│   ├── exportar_excel.py        # exportação .xlsx
│   ├── exportar_word.py          # exportação .docx
│   └── ia.py                      # integração com a API da OpenAI
└── interface/
    └── dashboard.py                # componentes da interface Streamlit
```

## Segurança da chave de API

A chave é lida exclusivamente de `.env` (fora do controle de versão) por `config.py`, e nunca é
impressa em logs, código-fonte ou na interface. O logger em `config.py` filtra automaticamente
qualquer ocorrência da chave (e da senha de acesso) antes de gravar em `logs/app.log`.

## Publicando (Streamlit Community Cloud)

O app processa dados de crédito de recuperação judicial e consome uma chave paga da OpenAI —
**nunca publique sem login/senha de acesso** (`APP_USERNAME`/`APP_PASSWORD`, ver abaixo).

1. **Suba o projeto para um repositório no GitHub** (pode ser privado). `.env` e
   `.streamlit/secrets.toml` já estão no `.gitignore` — nunca sobem para o repositório.
2. Em [share.streamlit.io](https://share.streamlit.io), conecte sua conta GitHub e crie um novo
   app apontando para o repositório, branch `main` e arquivo principal `app.py`.
3. Na tela de deploy, abra **"Advanced settings" → Secrets** e cole:
   ```toml
   OPENAI_API_KEY = "sua_chave_aqui"
   OPENAI_MODEL = "gpt-4o-mini"
   APP_USERNAME = "escolha_um_usuario"
   APP_PASSWORD = "escolha_uma_senha_forte"
   ```
4. Clique em **Deploy**. O Tesseract (`packages.txt`, na raiz do projeto) é instalado
   automaticamente pelo Streamlit Cloud — nenhuma configuração extra necessária para OCR.
5. Compartilhe a URL gerada (`https://SEU-APP.streamlit.app`) e o login apenas com quem deve
   acessar. Cada visitante precisa digitar usuário e senha antes de ver qualquer dado.

**Limitações do plano gratuito:** o armazenamento é temporário (PDFs enviados e relatórios
exportados não persistem entre reinicializações do app — isso já é esperado, pois o fluxo é
enviar, analisar e baixar na hora) e os recursos (RAM/CPU) são limitados; para uso mais pesado,
migre para um VPS com Docker.
