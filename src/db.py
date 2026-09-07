"""
Acesso a base DuckDB (data/cnpj.duckdb) para a interface web (app.py).

Toda consulta pesada usa @st.cache_data para nao reprocessar a cada
interacao do usuario; a conexao em si e um singleton via @st.cache_resource.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cnpj.duckdb"


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Banco nao encontrado em {DB_PATH}.\n"
            "Rode primeiro: python src/download.py  e depois  python src/etl.py"
        )
    return duckdb.connect(str(DB_PATH), read_only=True)


# ---------------------------------------------------------------------------
# Helpers de formatacao
# ---------------------------------------------------------------------------


def clean(value) -> str:
    """Converte None/NaN (vindos de colunas opcionais lidas via pandas) em string vazia."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def format_cnpj(basico: str, ordem: str = "0001", dv: str = "00") -> str:
    b = (basico or "").zfill(8)
    o = (ordem or "0001").zfill(4)
    d = (dv or "00").zfill(2)
    return f"{b[0:2]}.{b[2:5]}.{b[5:8]}/{o}-{d}"


def format_money(raw: Optional[str]) -> str:
    if not raw:
        return "-"
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return raw
    text = f"{value:,.2f}"
    text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"


def format_socios_preview(preview, total) -> str:
    preview = clean(preview)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    if not total:
        return "-"
    restantes = total - 3
    return f"{preview} (+{restantes})" if restantes > 0 else preview


def format_date(raw: Optional[str]) -> str:
    if not raw or raw == "0" or len(raw) != 8:
        return "-"
    return f"{raw[6:8]}/{raw[4:6]}/{raw[0:4]}"


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def get_overview() -> dict:
    con = get_connection()
    overview = {
        "total_empresas": con.execute("SELECT count(*) FROM empresas").fetchone()[0],
        "total_estabelecimentos": con.execute("SELECT count(*) FROM estabelecimentos").fetchone()[0],
        "total_socios": con.execute("SELECT count(*) FROM socios").fetchone()[0],
        "total_municipios": con.execute(
            "SELECT count(DISTINCT municipio) FROM estabelecimentos"
        ).fetchone()[0],
    }
    overview["por_uf"] = con.execute(
        """
        SELECT uf, count(*) AS total
        FROM estabelecimentos
        WHERE uf IS NOT NULL AND uf != ''
        GROUP BY uf
        ORDER BY total DESC
        """
    ).fetchdf()
    overview["por_situacao"] = con.execute(
        """
        SELECT situacao_cadastral, count(*) AS total
        FROM estabelecimentos
        GROUP BY situacao_cadastral
        ORDER BY total DESC
        """
    ).fetchdf()
    overview["top_cnaes"] = con.execute(
        """
        SELECT c.descricao AS cnae, count(*) AS total
        FROM estabelecimentos e
        LEFT JOIN cnaes c ON c.codigo = e.cnae_fiscal_principal
        GROUP BY c.descricao
        ORDER BY total DESC
        LIMIT 10
        """
    ).fetchdf()
    return overview


@st.cache_data(show_spinner=False)
def list_ufs() -> list[str]:
    con = get_connection()
    rows = con.execute(
        "SELECT DISTINCT uf FROM estabelecimentos WHERE uf IS NOT NULL AND uf != '' ORDER BY uf"
    ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(show_spinner=False)
def list_municipios(uf: Optional[str]) -> pd.DataFrame:
    con = get_connection()
    if uf:
        return con.execute(
            """
            SELECT DISTINCT e.municipio AS codigo, m.descricao AS nome
            FROM estabelecimentos e
            LEFT JOIN municipios m ON m.codigo = e.municipio
            WHERE e.uf = ?
            ORDER BY nome
            """,
            [uf],
        ).fetchdf()
    return con.execute(
        """
        SELECT DISTINCT e.municipio AS codigo, m.descricao AS nome
        FROM estabelecimentos e
        LEFT JOIN municipios m ON m.codigo = e.municipio
        ORDER BY nome
        """
    ).fetchdf()


@st.cache_data(show_spinner=False)
def list_cnaes() -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        """
        SELECT DISTINCT c.codigo, c.descricao
        FROM cnaes c
        JOIN estabelecimentos e ON e.cnae_fiscal_principal = c.codigo
        ORDER BY c.descricao
        """
    ).fetchdf()


@st.cache_data(show_spinner=False)
def search_estabelecimentos(
    termo: str = "",
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    situacao: Optional[str] = None,
    cnae: Optional[str] = None,
    socio: Optional[str] = None,
    limit: int = 200,
) -> pd.DataFrame:
    con = get_connection()
    conditions: list[str] = []
    params: list[str] = []

    termo = (termo or "").strip()
    digits = only_digits(termo)

    if len(digits) == 14:
        conditions.append("(es.cnpj_basico || es.cnpj_ordem || es.cnpj_dv) = ?")
        params.append(digits)
    elif len(digits) == 8:
        conditions.append("es.cnpj_basico = ?")
        params.append(digits)
    elif termo:
        conditions.append("(e.razao_social ILIKE ? OR es.nome_fantasia ILIKE ?)")
        params.extend([f"%{termo}%", f"%{termo}%"])

    if uf:
        conditions.append("es.uf = ?")
        params.append(uf)
    if municipio:
        conditions.append("es.municipio = ?")
        params.append(municipio)
    if situacao:
        conditions.append("es.situacao_cadastral = ?")
        params.append(situacao)
    if cnae:
        conditions.append("es.cnae_fiscal_principal = ?")
        params.append(cnae)
    socio = (socio or "").strip()
    if socio:
        conditions.append(
            "EXISTS (SELECT 1 FROM socios s WHERE s.cnpj_basico = es.cnpj_basico AND s.nome_socio ILIKE ?)"
        )
        params.append(f"%{socio}%")

    where_sql = " AND ".join(conditions) if conditions else "1=1"
    query = f"""
        SELECT
            e.cnpj_basico, e.razao_social, e.porte_empresa, e.capital_social,
            es.cnpj_ordem, es.cnpj_dv, es.nome_fantasia, es.uf, es.municipio,
            m.descricao AS municipio_nome, es.situacao_cadastral,
            es.cnae_fiscal_principal, c.descricao AS cnae_descricao,
            es.identificador_matriz_filial,
            (
                SELECT string_agg(nome_socio, ', ')
                FROM (
                    SELECT nome_socio FROM socios s2
                    WHERE s2.cnpj_basico = es.cnpj_basico
                    ORDER BY nome_socio LIMIT 3
                )
            ) AS socios_preview,
            (SELECT count(*) FROM socios s3 WHERE s3.cnpj_basico = es.cnpj_basico) AS socios_total
        FROM estabelecimentos es
        JOIN empresas e ON e.cnpj_basico = es.cnpj_basico
        LEFT JOIN municipios m ON m.codigo = es.municipio
        LEFT JOIN cnaes c ON c.codigo = es.cnae_fiscal_principal
        WHERE {where_sql}
        ORDER BY es.identificador_matriz_filial ASC, e.razao_social ASC
        LIMIT {int(limit)}
    """
    return con.execute(query, params).fetchdf()


@st.cache_data(show_spinner=False)
def get_empresa(cnpj_basico: str) -> Optional[dict]:
    con = get_connection()
    row = con.execute(
        """
        SELECT e.*, n.descricao AS natureza_juridica_descricao, q.descricao AS qualificacao_descricao
        FROM empresas e
        LEFT JOIN naturezas_juridicas n ON n.codigo = e.natureza_juridica
        LEFT JOIN qualificacoes_socios q ON q.codigo = e.qualificacao_responsavel
        WHERE e.cnpj_basico = ?
        """,
        [cnpj_basico],
    ).fetchdf()
    if row.empty:
        return None
    return row.iloc[0].to_dict()


@st.cache_data(show_spinner=False)
def get_estabelecimentos(cnpj_basico: str) -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        """
        SELECT es.*, m.descricao AS municipio_nome, c.descricao AS cnae_descricao,
               p.descricao AS pais_descricao
        FROM estabelecimentos es
        LEFT JOIN municipios m ON m.codigo = es.municipio
        LEFT JOIN cnaes c ON c.codigo = es.cnae_fiscal_principal
        LEFT JOIN paises p ON p.codigo = es.pais
        WHERE es.cnpj_basico = ?
        ORDER BY es.identificador_matriz_filial ASC, es.cnpj_ordem ASC
        """,
        [cnpj_basico],
    ).fetchdf()


@st.cache_data(show_spinner=False)
def get_socios(cnpj_basico: str) -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        """
        SELECT s.*, q.descricao AS qualificacao_descricao, p.descricao AS pais_descricao
        FROM socios s
        LEFT JOIN qualificacoes_socios q ON q.codigo = s.qualificacao_socio
        LEFT JOIN paises p ON p.codigo = s.pais
        WHERE s.cnpj_basico = ?
        ORDER BY s.nome_socio
        """,
        [cnpj_basico],
    ).fetchdf()


@st.cache_data(show_spinner=False)
def get_simples(cnpj_basico: str) -> Optional[dict]:
    con = get_connection()
    row = con.execute("SELECT * FROM simples WHERE cnpj_basico = ?", [cnpj_basico]).fetchdf()
    if row.empty:
        return None
    return row.iloc[0].to_dict()


@st.cache_data(show_spinner=False)
def get_socio_network(cnpj_basico: str, max_outros_por_socio: int = 15) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna (socios_diretos, outras_empresas_dos_socios) para montar o grafo."""
    con = get_connection()
    socios = con.execute(
        "SELECT cnpj_cpf_socio, nome_socio FROM socios WHERE cnpj_basico = ? AND cnpj_cpf_socio IS NOT NULL",
        [cnpj_basico],
    ).fetchdf()

    if socios.empty:
        return socios, pd.DataFrame(columns=["cnpj_cpf_socio", "cnpj_basico", "razao_social"])

    outras = con.execute(
        """
        SELECT s.cnpj_cpf_socio, s.cnpj_basico, e.razao_social
        FROM socios s
        JOIN empresas e ON e.cnpj_basico = s.cnpj_basico
        WHERE s.cnpj_cpf_socio IN (SELECT cnpj_cpf_socio FROM socios WHERE cnpj_basico = ?)
          AND s.cnpj_basico != ?
        QUALIFY row_number() OVER (PARTITION BY s.cnpj_cpf_socio ORDER BY e.razao_social) <= ?
        """,
        [cnpj_basico, cnpj_basico, max_outros_por_socio],
    ).fetchdf()
    return socios, outras
