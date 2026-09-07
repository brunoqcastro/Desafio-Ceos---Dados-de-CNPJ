# CNPJ Explorer

Ingestao e visualizacao dos dados publicos do CNPJ (Receita Federal).

## Status

- [x] Download automatico dos arquivos publicos
- [x] Parsing e carga em banco de dados local (DuckDB)
- [x] Interface web de consulta (Streamlit)

## Instalacao

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Download dos dados

Os arquivos sao baixados diretamente do repositorio publico da Receita Federal
(Nextcloud, via WebDAV) — o usuario nao precisa baixar nada manualmente.

Listar o que esta disponivel no mes mais recente, sem baixar:

```bash
python src/download.py --list-only
```

Baixar só um subconjunto pequeno para testar o pipeline (Cnaes, Municipios e o
primeiro arquivo de Empresas):

```bash
python src/download.py --only Cnaes Municipios Naturezas Empresas0
```

Baixar tudo do mes mais recente (~7 GB):

```bash
python src/download.py
```

Baixar um mes especifico:

```bash
python src/download.py --month 2026-07
```

Os arquivos vao para `data/raw/<mes>/`. O download suporta retomada (resume)
caso seja interrompido — basta rodar o comando de novo.

## Carga no banco de dados (DuckDB)

Depois de baixados, os `.zip` sao parseados e carregados em uma base DuckDB
local (`data/cnpj.duckdb`). O banco e escolhido porque le/agrega os arquivos
CSV enormes da Receita com desempenho de banco colunar, sem precisar de um
servidor rodando.

```bash
python src/etl.py
```

Isso detecta sozinho o mes mais recente em `data/raw/`, cria as tabelas
(`empresas`, `estabelecimentos`, `socios`, `simples`, `cnaes`,
`naturezas_juridicas`, `qualificacoes_socios`, `paises`, `municipios`,
`motivos_situacao_cadastral`) e carrega todos os arquivos correspondentes.

Carregar so algumas tabelas (util em testes, ou se voce so baixou parte dos
arquivos com `--only` no passo anterior):

```bash
python src/etl.py --only cnaes municipios empresas
```

Observacoes sobre o schema:

- Todas as colunas sao `VARCHAR`. Varios codigos da Receita (municipio, CNAE,
  natureza juridica, DDD) tem zero a esquerda que se perderia como inteiro —
  e manter tudo como texto evita que uma linha malformada no meio de um
  arquivo de milhoes de linhas aborte a carga inteira.
- Os arquivos csv dentro dos `.zip` sao `;`-separados, com aspas duplicadas
  (`""`) como escape de aspas dentro de campos, sem cabecalho, em Latin-1 —
  o `etl.py` transcodifica para UTF-8 em streaming antes de rodar o `COPY`
  nativo do DuckDB (muito mais rapido que insercao linha a linha em Python).

## Interface web

```bash
streamlit run src/app.py
```

Abre em `http://localhost:8501`. Duas abas:

- **Visao geral**: contagens totais e graficos (estabelecimentos por UF,
  situacao cadastral, top 10 CNAEs).
- **Buscar empresas**: busca por razao social, nome fantasia ou CNPJ (aceita
  CNPJ formatado ou so numeros, 8 digitos = raiz ou 14 digitos = CNPJ
  completo), com filtros de UF, municipio, situacao cadastral e CNAE
  principal na barra lateral. Ao selecionar uma empresa: dados cadastrais,
  todos os estabelecimentos (matriz + filiais), socios, e uma aba extra de
  **rede societaria** — grafo mostrando a empresa, seus socios e outras
  empresas onde esses mesmos socios tambem aparecem.

Codigos que a Receita documenta no layout mas nao distribui como arquivo
(situacao cadastral, matriz/filial, porte, faixa etaria) estao mapeados em
`src/lookups.py`.
