# CNPJ Explorer

Ingestao e visualizacao dos dados publicos do CNPJ (Receita Federal).

## Status

- [x] Download automatico dos arquivos publicos
- [ ] Parsing e carga em banco de dados local
- [ ] Interface web de consulta

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
