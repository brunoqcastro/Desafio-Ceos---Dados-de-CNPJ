"""
Parsing e carga dos arquivos do CNPJ (baixados por download.py) em uma base
DuckDB local.

Cada .zip baixado contem um unico CSV no layout oficial da Receita Federal:
";"-separado, campos entre aspas duplas, sem cabecalho, codificado em
Latin-1 (ISO-8859-1). Para cada arquivo:

  1. Streamamos o conteudo do zip e transcodificamos Latin-1 -> UTF-8 em um
     CSV temporario (byte a byte, sem carregar tudo em memoria).
  2. Usamos o COPY nativo do DuckDB (parser em C++, ordens de magnitude mais
     rapido que insercao linha a linha em Python) para carregar na tabela.

Todas as colunas sao carregadas como VARCHAR: varios codigos da Receita
(municipio, CNAE, natureza juridica, DDD...) tem zero a esquerda que se
perderia se fossem INTEGER, e usar apenas texto evita que um valor
inesperado aborte a carga de um arquivo inteiro de milhoes de linhas.
"""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path
from typing import Optional

import duckdb

# ---------------------------------------------------------------------------
# Layout oficial dos arquivos da Receita Federal (colunas na ordem do CSV)
# ---------------------------------------------------------------------------

TABLES: dict[str, dict] = {
    "empresas": {
        "prefix": "Empresas",
        "columns": [
            "cnpj_basico",
            "razao_social",
            "natureza_juridica",
            "qualificacao_responsavel",
            "capital_social",
            "porte_empresa",
            "ente_federativo_responsavel",
        ],
    },
    "estabelecimentos": {
        "prefix": "Estabelecimentos",
        "columns": [
            "cnpj_basico",
            "cnpj_ordem",
            "cnpj_dv",
            "identificador_matriz_filial",
            "nome_fantasia",
            "situacao_cadastral",
            "data_situacao_cadastral",
            "motivo_situacao_cadastral",
            "nome_cidade_exterior",
            "pais",
            "data_inicio_atividade",
            "cnae_fiscal_principal",
            "cnae_fiscal_secundaria",
            "tipo_logradouro",
            "logradouro",
            "numero",
            "complemento",
            "bairro",
            "cep",
            "uf",
            "municipio",
            "ddd1",
            "telefone1",
            "ddd2",
            "telefone2",
            "ddd_fax",
            "fax",
            "correio_eletronico",
            "situacao_especial",
            "data_situacao_especial",
        ],
    },
    "socios": {
        "prefix": "Socios",
        "columns": [
            "cnpj_basico",
            "identificador_socio",
            "nome_socio",
            "cnpj_cpf_socio",
            "qualificacao_socio",
            "data_entrada_sociedade",
            "pais",
            "representante_legal",
            "nome_representante",
            "qualificacao_representante_legal",
            "faixa_etaria",
        ],
    },
    "simples": {
        "prefix": "Simples",
        "columns": [
            "cnpj_basico",
            "opcao_pelo_simples",
            "data_opcao_simples",
            "data_exclusao_simples",
            "opcao_mei",
            "data_opcao_mei",
            "data_exclusao_mei",
        ],
    },
    "cnaes": {"prefix": "Cnaes", "columns": ["codigo", "descricao"]},
    "naturezas_juridicas": {"prefix": "Naturezas", "columns": ["codigo", "descricao"]},
    "qualificacoes_socios": {"prefix": "Qualificacoes", "columns": ["codigo", "descricao"]},
    "paises": {"prefix": "Paises", "columns": ["codigo", "descricao"]},
    "municipios": {"prefix": "Municipios", "columns": ["codigo", "descricao"]},
    "motivos_situacao_cadastral": {"prefix": "Motivos", "columns": ["codigo", "descricao"]},
}


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    for table, spec in TABLES.items():
        cols_sql = ", ".join(f'"{c}" VARCHAR' for c in spec["columns"])
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols_sql})")


def create_indexes(con: duckdb.DuckDBPyConnection) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_empresas_cnpj ON empresas(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnpj ON estabelecimentos(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_estab_uf ON estabelecimentos(uf)",
        "CREATE INDEX IF NOT EXISTS idx_estab_municipio ON estabelecimentos(municipio)",
        "CREATE INDEX IF NOT EXISTS idx_estab_situacao ON estabelecimentos(situacao_cadastral)",
        "CREATE INDEX IF NOT EXISTS idx_estab_cnae ON estabelecimentos(cnae_fiscal_principal)",
        "CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS idx_simples_cnpj ON simples(cnpj_basico)",
    ]
    for sql in statements:
        con.execute(sql)


def find_family_files(raw_dir: Path, prefix: str) -> list[Path]:
    pattern = re.compile(rf"^{re.escape(prefix)}\d*\.zip$", re.IGNORECASE)
    return sorted((p for p in raw_dir.glob("*.zip") if pattern.match(p.name)), key=lambda p: p.name)


def zip_to_utf8_csv(zip_path: Path, out_path: Path, chunk_size: int = 8 * 1024 * 1024) -> None:
    """Extrai o unico CSV de dentro do zip, transcodificando Latin-1 -> UTF-8."""
    with zipfile.ZipFile(zip_path) as zf:
        member = zf.namelist()[0]
        with zf.open(member) as src, open(out_path, "wb") as dst:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk.decode("latin-1").encode("utf-8"))


def load_family(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[str],
    zip_paths: list[Path],
    tmp_dir: Path,
) -> int:
    col_list = ", ".join(f'"{c}"' for c in columns)
    for zip_path in zip_paths:
        tmp_csv = tmp_dir / (zip_path.stem + ".csv")
        print(f"  processando {zip_path.name}...")
        zip_to_utf8_csv(zip_path, tmp_csv)
        try:
            con.execute(
                f"""
                COPY {table} ({col_list}) FROM '{tmp_csv.as_posix()}'
                (DELIMITER ';', QUOTE '"', ESCAPE '"', HEADER false, STRICT_MODE false)
                """
            )
        finally:
            tmp_csv.unlink(missing_ok=True)
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def run_etl(raw_dir: Path, db_path: Path, only: Optional[list[str]] = None) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    create_schema(con)

    tmp_dir = raw_dir / "_staging"
    tmp_dir.mkdir(exist_ok=True)

    try:
        for table, spec in TABLES.items():
            if only and table not in only:
                continue
            files = find_family_files(raw_dir, spec["prefix"])
            if not files:
                print(f"[aviso] nenhum arquivo encontrado para '{table}' (prefixo {spec['prefix']}*.zip)")
                continue
            print(f"Carregando {table} ({len(files)} arquivo(s))...")
            con.execute(f"DELETE FROM {table}")
            rows = load_family(con, table, spec["columns"], files, tmp_dir)
            print(f"  -> {table}: {rows:,} linhas")

        print("Criando indices...")
        create_indexes(con)
    finally:
        con.close()
        try:
            tmp_dir.rmdir()
        except OSError:
            pass  # sobrou algo (ex: carga interrompida), deixa para inspecao manual

    print(f"Base pronta em {db_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Carrega os arquivos baixados do CNPJ em uma base DuckDB.")
    parser.add_argument(
        "--raw-dir", default=None, help="Pasta com os .zip baixados (default: data/raw/<mes mais recente>)"
    )
    parser.add_argument("--db", default="data/cnpj.duckdb", help="Caminho do arquivo DuckDB de saida")
    parser.add_argument(
        "--only", nargs="*", default=None, help="Carrega so essas tabelas, ex: --only cnaes municipios empresas"
    )
    args = parser.parse_args()

    if args.raw_dir:
        raw_dir = Path(args.raw_dir)
    else:
        raw_root = Path("data/raw")
        if not raw_root.exists():
            raise SystemExit("data/raw/ nao existe. Rode src/download.py primeiro.")
        months = sorted(p.name for p in raw_root.iterdir() if p.is_dir())
        if not months:
            raise SystemExit("Nenhuma pasta de mes em data/raw/. Rode src/download.py primeiro.")
        raw_dir = raw_root / months[-1]

    print(f"Lendo arquivos de: {raw_dir.resolve()}")
    run_etl(raw_dir, Path(args.db), args.only)


if __name__ == "__main__":
    main()
