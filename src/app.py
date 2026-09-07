"""
Interface web do CNPJ Explorer (Streamlit).

Rodar com:  streamlit run src/app.py
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

import db
import graph
from lookups import (
    FAIXA_ETARIA,
    IDENTIFICADOR_MATRIZ_FILIAL,
    IDENTIFICADOR_SOCIO,
    PORTE_EMPRESA,
    SITUACAO_CADASTRAL,
)

st.set_page_config(page_title="CNPJ Explorer", page_icon="\U0001F50D", layout="wide")

if "cnpj_selecionado" not in st.session_state:
    st.session_state.cnpj_selecionado = None


def _situacao_label(codigo: str) -> str:
    return SITUACAO_CADASTRAL.get(codigo, codigo or "-")


# ---------------------------------------------------------------------------
# Verificacao inicial: banco existe?
# ---------------------------------------------------------------------------
try:
    db.get_connection()
except FileNotFoundError as exc:
    st.title("CNPJ Explorer")
    st.error(str(exc))
    st.stop()


st.title("CNPJ Explorer")
st.caption("Ingestao e consulta dos dados publicos do CNPJ (Receita Federal)")

tab_visao, tab_busca = st.tabs(["Visao geral", "Buscar empresas"])

# ---------------------------------------------------------------------------
# Aba 1 - Visao geral
# ---------------------------------------------------------------------------
with tab_visao:
    overview = db.get_overview()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Empresas", f"{overview['total_empresas']:,}".replace(",", "."))
    c2.metric("Estabelecimentos", f"{overview['total_estabelecimentos']:,}".replace(",", "."))
    c3.metric("Socios", f"{overview['total_socios']:,}".replace(",", "."))
    c4.metric("Municipios com dados", f"{overview['total_municipios']:,}".replace(",", "."))

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Estabelecimentos por UF")
        df_uf = overview["por_uf"].set_index("uf")
        st.bar_chart(df_uf["total"])

    with col_b:
        st.subheader("Situacao cadastral")
        df_sit = overview["por_situacao"].copy()
        df_sit["situacao"] = df_sit["situacao_cadastral"].map(_situacao_label)
        st.bar_chart(df_sit.set_index("situacao")["total"])

    st.subheader("Top 10 CNAEs principais")
    df_cnae = overview["top_cnaes"].set_index("cnae")
    st.bar_chart(df_cnae["total"])

# ---------------------------------------------------------------------------
# Aba 2 - Busca
# ---------------------------------------------------------------------------
with tab_busca:
    st.sidebar.header("Filtros")

    ufs = [""] + db.list_ufs()
    uf_filtro = st.sidebar.selectbox("UF", ufs, format_func=lambda v: v or "Todas")

    municipios_df = db.list_municipios(uf_filtro or None)
    municipio_opcoes = [("", "Todos")] + list(
        zip(municipios_df["codigo"], municipios_df["nome"].fillna(municipios_df["codigo"]))
    )
    municipio_filtro = st.sidebar.selectbox(
        "Municipio",
        options=[c for c, _ in municipio_opcoes],
        format_func=lambda c: dict(municipio_opcoes).get(c, c),
    )

    situacao_opcoes = [("", "Todas")] + list(SITUACAO_CADASTRAL.items())
    situacao_filtro = st.sidebar.selectbox(
        "Situacao cadastral",
        options=[c for c, _ in situacao_opcoes],
        format_func=lambda c: dict(situacao_opcoes).get(c, c),
    )

    cnaes_df = db.list_cnaes()
    cnae_opcoes = [("", "Todos")] + list(zip(cnaes_df["codigo"], cnaes_df["descricao"]))
    cnae_filtro = st.sidebar.selectbox(
        "CNAE principal",
        options=[c for c, _ in cnae_opcoes],
        format_func=lambda c: dict(cnae_opcoes).get(c, c),
    )

    termo = st.text_input(
        "Buscar por razao social, nome fantasia ou CNPJ",
        placeholder="Ex: PADARIA SAO JOSE   ou   12.345.678/0001-90",
    )

    tem_filtro = any([termo.strip(), uf_filtro, municipio_filtro, situacao_filtro, cnae_filtro])

    if not tem_filtro:
        st.info("Digite um termo de busca ou aplique um filtro na barra lateral.")
    else:
        resultados = db.search_estabelecimentos(
            termo=termo,
            uf=uf_filtro or None,
            municipio=municipio_filtro or None,
            situacao=situacao_filtro or None,
            cnae=cnae_filtro or None,
        )

        if resultados.empty:
            st.warning("Nenhum resultado encontrado.")
        else:
            st.write(f"{len(resultados)} resultado(s) (limitado a 200)")

            opcoes = {}
            for _, r in resultados.iterrows():
                cnpj_fmt = db.format_cnpj(r["cnpj_basico"], r["cnpj_ordem"], r["cnpj_dv"])
                tipo = IDENTIFICADOR_MATRIZ_FILIAL.get(r["identificador_matriz_filial"], "")
                municipio_nome = db.clean(r["municipio_nome"])
                uf_nome = db.clean(r["uf"])
                label = f"{r['razao_social']} — {cnpj_fmt} — {tipo} — {municipio_nome}/{uf_nome}"
                opcoes[label] = r["cnpj_basico"]

            escolhido = st.selectbox("Selecione uma empresa para ver os detalhes", list(opcoes.keys()))
            if st.button("Ver detalhes", type="primary"):
                st.session_state.cnpj_selecionado = opcoes[escolhido]

            with st.expander("Ver todos os resultados em tabela"):
                st.dataframe(
                    resultados[
                        ["razao_social", "nome_fantasia", "uf", "municipio_nome", "situacao_cadastral", "cnae_descricao"]
                    ].rename(
                        columns={
                            "razao_social": "Razao social",
                            "nome_fantasia": "Nome fantasia",
                            "uf": "UF",
                            "municipio_nome": "Municipio",
                            "situacao_cadastral": "Situacao",
                            "cnae_descricao": "CNAE principal",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )

    # -----------------------------------------------------------------
    # Detalhe da empresa selecionada
    # -----------------------------------------------------------------
    if st.session_state.cnpj_selecionado:
        st.divider()
        cnpj_basico = st.session_state.cnpj_selecionado
        empresa = db.get_empresa(cnpj_basico)

        if empresa is None:
            st.error("Empresa nao encontrada.")
        else:
            st.header(empresa["razao_social"])

            porte_codigo = db.clean(empresa["porte_empresa"])
            col1, col2, col3 = st.columns(3)
            col1.metric("Porte", PORTE_EMPRESA.get(porte_codigo, porte_codigo or "-"))
            col2.metric("Capital social", db.format_money(empresa["capital_social"]))
            col3.metric("Natureza juridica", db.clean(empresa["natureza_juridica_descricao"]) or "-")

            sub_estab, sub_socios, sub_rede = st.tabs(["Estabelecimentos", "Socios", "Rede societaria"])

            with sub_estab:
                estabs = db.get_estabelecimentos(cnpj_basico)
                for _, es in estabs.iterrows():
                    tipo = IDENTIFICADOR_MATRIZ_FILIAL.get(es["identificador_matriz_filial"], "-")
                    cnpj_fmt = db.format_cnpj(es["cnpj_basico"], es["cnpj_ordem"], es["cnpj_dv"])
                    nome_fantasia = db.clean(es["nome_fantasia"]) or "(sem nome fantasia)"
                    cnae_desc = db.clean(es["cnae_descricao"]) or db.clean(es["cnae_fiscal_principal"])
                    with st.container(border=True):
                        st.markdown(f"**{tipo}** — `{cnpj_fmt}` — {nome_fantasia}")
                        st.write(f"Situacao: {_situacao_label(es['situacao_cadastral'])} desde {db.format_date(es['data_situacao_cadastral'])}")
                        st.write(f"Atividade principal: {cnae_desc}")
                        st.write(f"Inicio das atividades: {db.format_date(es['data_inicio_atividade'])}")
                        endereco = (
                            f"{db.clean(es['tipo_logradouro'])} {db.clean(es['logradouro'])}, "
                            f"{db.clean(es['numero']) or 's/n'} {db.clean(es['complemento'])} - "
                            f"{db.clean(es['bairro'])}, {db.clean(es['municipio_nome'])}/{db.clean(es['uf'])} "
                            f"CEP {db.clean(es['cep']) or '-'}"
                        )
                        st.write(f"Endereco: {endereco}")
                        contato = []
                        telefone1 = db.clean(es["telefone1"])
                        email = db.clean(es["correio_eletronico"])
                        if telefone1:
                            contato.append(f"({db.clean(es['ddd1'])}) {telefone1}")
                        if email:
                            contato.append(email)
                        if contato:
                            st.write("Contato: " + " | ".join(contato))

            with sub_socios:
                socios = db.get_socios(cnpj_basico)
                if socios.empty:
                    st.info("Nenhum socio cadastrado para esta empresa.")
                else:
                    st.dataframe(
                        socios.assign(
                            tipo=socios["identificador_socio"].map(IDENTIFICADOR_SOCIO),
                            faixa_etaria=socios["faixa_etaria"].map(FAIXA_ETARIA),
                            data_entrada=socios["data_entrada_sociedade"].map(db.format_date),
                        )[["nome_socio", "tipo", "qualificacao_descricao", "data_entrada", "faixa_etaria"]].rename(
                            columns={
                                "nome_socio": "Nome",
                                "tipo": "Tipo",
                                "qualificacao_descricao": "Qualificacao",
                                "data_entrada": "Entrada na sociedade",
                                "faixa_etaria": "Faixa etaria",
                            }
                        ),
                        width="stretch",
                        hide_index=True,
                    )

            with sub_rede:
                st.caption(
                    "Rede formada pela empresa, seus socios diretos e outras empresas onde "
                    "esses mesmos socios tambem aparecem (ate 15 por socio)."
                )
                socios_diretos, outras_empresas = db.get_socio_network(cnpj_basico)
                if socios_diretos.empty:
                    st.info("Sem socios cadastrados para montar a rede.")
                else:
                    html = graph.build_socio_network_html(
                        cnpj_basico, empresa["razao_social"], socios_diretos, outras_empresas
                    )
                    components.html(html, height=540, scrolling=False)
