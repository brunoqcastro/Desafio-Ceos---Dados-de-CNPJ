"""
Interface web do CNPJ Explorer (Streamlit).

Rodar com:  streamlit run src/app.py
"""

from __future__ import annotations

import math

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
if "pagina_busca" not in st.session_state:
    st.session_state.pagina_busca = 1


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

tab_busca, tab_visao = st.tabs(["Buscar empresas", "Visao geral"])

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
RESULTADOS_POR_PAGINA = 50
LIMITE_BUSCA = 500

with tab_busca:
    st.subheader("Filtros")
    col_uf, col_municipio, col_situacao, col_cnae, col_socio = st.columns(5)

    with col_uf:
        ufs = [""] + db.list_ufs()
        uf_filtro = st.selectbox("UF", ufs, format_func=lambda v: v or "Todas")

    with col_municipio:
        municipios_df = db.list_municipios(uf_filtro or None)
        municipio_opcoes = [("", "Todos")] + list(
            zip(municipios_df["codigo"], municipios_df["nome"].fillna(municipios_df["codigo"]))
        )
        municipio_filtro = st.selectbox(
            "Municipio",
            options=[c for c, _ in municipio_opcoes],
            format_func=lambda c: dict(municipio_opcoes).get(c, c),
        )

    with col_situacao:
        situacao_opcoes = [("", "Todas")] + list(SITUACAO_CADASTRAL.items())
        situacao_filtro = st.selectbox(
            "Situacao cadastral",
            options=[c for c, _ in situacao_opcoes],
            format_func=lambda c: dict(situacao_opcoes).get(c, c),
        )

    with col_cnae:
        cnaes_df = db.list_cnaes()
        cnae_opcoes = [("", "Todos")] + list(zip(cnaes_df["codigo"], cnaes_df["descricao"]))
        cnae_filtro = st.selectbox(
            "CNAE principal",
            options=[c for c, _ in cnae_opcoes],
            format_func=lambda c: dict(cnae_opcoes).get(c, c),
        )

    with col_socio:
        socio_filtro = st.text_input("Socio (nome)", placeholder="Ex: JOAO DA SILVA")

    termo = st.text_input(
        "Buscar por razao social, nome fantasia ou CNPJ",
        placeholder="Ex: PADARIA SAO JOSE   ou   12.345.678/0001-90",
    )

    tem_filtro = any(
        [termo.strip(), uf_filtro, municipio_filtro, situacao_filtro, cnae_filtro, socio_filtro.strip()]
    )

    if not tem_filtro:
        st.info("Digite um termo de busca ou aplique um filtro acima.")
    else:
        resultados = db.search_estabelecimentos(
            termo=termo,
            uf=uf_filtro or None,
            municipio=municipio_filtro or None,
            situacao=situacao_filtro or None,
            cnae=cnae_filtro or None,
            socio=socio_filtro or None,
            limit=LIMITE_BUSCA,
        )

        if resultados.empty:
            st.warning("Nenhum resultado encontrado.")
        else:
            filtro_atual = (termo, uf_filtro, municipio_filtro, situacao_filtro, cnae_filtro, socio_filtro)
            if st.session_state.get("filtro_busca_anterior") != filtro_atual:
                st.session_state.pagina_busca = 1
                st.session_state.filtro_busca_anterior = filtro_atual

            total = len(resultados)
            total_paginas = math.ceil(total / RESULTADOS_POR_PAGINA)
            pagina = min(st.session_state.get("pagina_busca", 1), total_paginas)

            sufixo_limite = f" (limitado a {LIMITE_BUSCA})" if total >= LIMITE_BUSCA else ""
            st.write(f"{total} resultado(s){sufixo_limite} — pagina {pagina} de {total_paginas}")

            inicio = (pagina - 1) * RESULTADOS_POR_PAGINA
            pagina_df = resultados.iloc[inicio : inicio + RESULTADOS_POR_PAGINA]

            larguras = [2.6, 1.8, 0.7, 1.7, 1.3, 2.4, 2.2, 1.3]
            cabecalho = st.columns(larguras)
            for col, titulo in zip(
                cabecalho,
                ["Razao social", "Nome fantasia", "UF", "Municipio", "Situacao", "CNAE principal", "Socios", ""],
            ):
                col.markdown(f"**{titulo}**")

            for pos, (idx, r) in enumerate(pagina_df.iterrows()):
                linha = st.columns(larguras)
                linha[0].write(r["razao_social"])
                linha[1].write(db.clean(r["nome_fantasia"]) or "-")
                linha[2].write(db.clean(r["uf"]) or "-")
                linha[3].write(db.clean(r["municipio_nome"]) or "-")
                linha[4].write(_situacao_label(r["situacao_cadastral"]))
                linha[5].write(db.clean(r["cnae_descricao"]) or db.clean(r["cnae_fiscal_principal"]) or "-")
                linha[6].write(db.format_socios_preview(r["socios_preview"], r["socios_total"]))
                chave_botao = f"detalhes_{pagina}_{pos}_{r['cnpj_basico']}_{r['cnpj_ordem']}"
                if linha[7].button("Ver detalhes", key=chave_botao):
                    st.session_state.cnpj_selecionado = r["cnpj_basico"]

            if total_paginas > 1:
                nav_prev, nav_info, nav_next = st.columns([1, 2, 1])
                with nav_prev:
                    if st.button("< Anterior", disabled=pagina <= 1):
                        st.session_state.pagina_busca = pagina - 1
                        st.rerun()
                with nav_info:
                    st.markdown(f"<div style='text-align:center'>Pagina {pagina} de {total_paginas}</div>", unsafe_allow_html=True)
                with nav_next:
                    if st.button("Proxima >", disabled=pagina >= total_paginas):
                        st.session_state.pagina_busca = pagina + 1
                        st.rerun()

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
                    "esses mesmos socios tambem aparecem (ate 15 por socio). Clique em uma "
                    "empresa do grafo para abrir a ficha dela."
                )
                socios_diretos, outras_empresas = db.get_socio_network(cnpj_basico)
                if socios_diretos.empty:
                    st.info("Sem socios cadastrados para montar a rede.")
                else:
                    # components.html roda num iframe sandboxed sem permissao de navegacao
                    # (nao da pra fazer window.parent.location = ... dali). Em vez disso, o
                    # clique num no de empresa do grafo aciona (via JS, acessando o DOM da
                    # pagina pai - permitido pois o iframe tem allow-same-origin) um botao
                    # comum do Streamlit correspondente aquela empresa, escondido via CSS.
                    # Um clique real em <button> passa pelo pipeline normal de eventos do
                    # React/Streamlit, ao contrario de tentar simular digitação num input.
                    empresas_no_grafo = {cnpj_basico} | set(outras_empresas["cnpj_basico"].tolist())
                    with st.container(key="grafo_botoes_ocultos"):
                        for cnpj_alvo in empresas_no_grafo:
                            if st.button(f"abrir_empresa_{cnpj_alvo}", key=f"btn_grafo_{cnpj_basico}_{cnpj_alvo}"):
                                st.session_state.cnpj_selecionado = cnpj_alvo
                                st.rerun()
                    st.markdown(
                        "<style>div.st-key-grafo_botoes_ocultos { display: none; }</style>",
                        unsafe_allow_html=True,
                    )
                    html = graph.build_socio_network_html(
                        cnpj_basico, empresa["razao_social"], socios_diretos, outras_empresas
                    )
                    components.html(html, height=540, scrolling=False)
