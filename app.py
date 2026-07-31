import os
import re
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _config(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return os.environ[key]


HUB_URL = _config("HUB_SUPABASE_URL").rstrip("/")
HUB_KEY = _config("HUB_SUPABASE_KEY")
PREP_URL = _config("PREP_SUPABASE_URL").rstrip("/")
PREP_KEY = _config("PREP_SUPABASE_KEY")

CATEGORIAS = [
    "Funilaria/Pintura",
    "Mecânica/Revisão",
    "Pneus",
    "Polimento/Estética",
    "Higienização/Limpeza",
    "Elétrica",
    "Vidros",
    "Outros",
]
NAO_CLASSIFICADO = "Não classificado"


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def normalize_doc(value) -> str:
    if not value:
        return ""
    return re.sub(r"\D", "", str(value))


def hub_fetch_solicitacoes() -> pd.DataFrame:
    rows = []
    offset = 0
    page_size = 1000
    cols = "id,empresa,tipo,status,valor,placa,benef_nome,benef_cpf_cnpj,descricao,created_at"
    while True:
        resp = requests.get(
            f"{HUB_URL}/rest/v1/solicitacoes",
            headers=_headers(HUB_KEY),
            params={
                "select": cols,
                "tipo": "in.(MANUTENCAO,POS_VENDAS)",
                "order": "created_at.desc",
                "limit": page_size,
                "offset": offset,
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["cnpj_norm"] = df["benef_cpf_cnpj"].apply(normalize_doc)
    return df


def prep_fetch_fornecedores() -> pd.DataFrame:
    resp = requests.get(
        f"{PREP_URL}/rest/v1/fornecedores",
        headers=_headers(PREP_KEY),
        params={"select": "*", "order": "nome.asc"},
        timeout=30,
    )
    if resp.status_code == 404:
        return pd.DataFrame(columns=["id", "cnpj_cpf", "nome", "categoria", "ativo"])
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    if not df.empty:
        df["cnpj_norm"] = df["cnpj_cpf"].apply(normalize_doc)
    return df


def prep_insert_fornecedor(cnpj_cpf: str, nome: str, categoria: str):
    resp = requests.post(
        f"{PREP_URL}/rest/v1/fornecedores",
        headers={**_headers(PREP_KEY), "Content-Type": "application/json", "Prefer": "return=representation"},
        json={"cnpj_cpf": cnpj_cpf, "nome": nome, "categoria": categoria, "ativo": True},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def prep_update_fornecedor(row_id: str, categoria: str, ativo: bool):
    resp = requests.patch(
        f"{PREP_URL}/rest/v1/fornecedores",
        headers={**_headers(PREP_KEY), "Content-Type": "application/json"},
        params={"id": f"eq.{row_id}"},
        json={"categoria": categoria, "ativo": ativo},
        timeout=30,
    )
    resp.raise_for_status()


st.set_page_config(page_title="Preparação — Custos", layout="wide")
st.title("Preparação e Pós-Venda — Custos")

tab_dashboard, tab_fornecedores = st.tabs(["📊 Dashboard", "🏷️ Fornecedores"])

with st.spinner("Carregando dados do hub..."):
    solicitacoes = hub_fetch_solicitacoes()
    fornecedores = prep_fetch_fornecedores()

if not fornecedores.empty:
    cat_map = dict(zip(fornecedores["cnpj_norm"], fornecedores["categoria"]))
    ativo_map = dict(zip(fornecedores["cnpj_norm"], fornecedores["ativo"]))
else:
    cat_map, ativo_map = {}, {}

if not solicitacoes.empty:
    solicitacoes["categoria"] = solicitacoes["cnpj_norm"].map(cat_map).fillna(NAO_CLASSIFICADO)

with tab_dashboard:
    if solicitacoes.empty:
        st.info("Nenhum registro de MANUTENCAO/POS_VENDAS encontrado no hub.")
    else:
        st.sidebar.header("Filtros")
        empresas = sorted(solicitacoes["empresa"].dropna().unique().tolist())
        empresa_sel = st.sidebar.multiselect("Empresa", empresas, default=empresas)

        status_opts = sorted(solicitacoes["status"].dropna().unique().tolist())
        default_status = [s for s in status_opts if s == "PAGO"] or status_opts
        status_sel = st.sidebar.multiselect("Status", status_opts, default=default_status)

        min_date = solicitacoes["created_at"].min().date()
        max_date = solicitacoes["created_at"].max().date()
        date_range = st.sidebar.date_input(
            "Período", value=(max(min_date, max_date - timedelta(weeks=12)), max_date),
            min_value=min_date, max_value=max_date,
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date, end_date = min_date, max_date

        df = solicitacoes[
            solicitacoes["empresa"].isin(empresa_sel)
            & solicitacoes["status"].isin(status_sel)
            & (solicitacoes["created_at"].dt.date >= start_date)
            & (solicitacoes["created_at"].dt.date <= end_date)
        ].copy()

        if df.empty:
            st.warning("Nenhum registro para os filtros selecionados.")
        else:
            total_geral = df["valor"].sum()
            nao_class = df[df["categoria"] == NAO_CLASSIFICADO]
            total_nao_class = nao_class["valor"].sum()

            c1, c2, c3 = st.columns(3)
            c1.metric("Gasto total no período", f"R$ {total_geral:,.2f}")
            c2.metric("Não classificado", f"R$ {total_nao_class:,.2f}",
                      f"{(total_nao_class / total_geral * 100 if total_geral else 0):.0f}% do total")
            c3.metric("Fornecedores cadastrados", int((fornecedores["ativo"] == True).sum()) if not fornecedores.empty else 0)

            df["semana"] = df["created_at"].dt.to_period("W").apply(lambda p: p.start_time.date())

            semanal = df.groupby(["semana", "categoria"], as_index=False)["valor"].sum()
            fig = px.bar(
                semanal, x="semana", y="valor", color="categoria",
                title="Gasto semanal por categoria", labels={"valor": "R$", "semana": "Semana"},
            )
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Resumo por categoria")
            resumo = (
                df.groupby(["semana", "categoria"])["valor"].sum().reset_index()
                .groupby("categoria")["valor"].agg(total="sum", media_semanal="mean", desvio="std")
                .reset_index()
            )
            ultima_semana = df["semana"].max()
            ultima = df[df["semana"] == ultima_semana].groupby("categoria")["valor"].sum()
            resumo["ultima_semana"] = resumo["categoria"].map(ultima).fillna(0)
            resumo["limite_alerta"] = resumo["media_semanal"] + resumo["desvio"].fillna(0)
            resumo["acima_do_normal"] = resumo["ultima_semana"] > resumo["limite_alerta"]
            resumo_display = resumo[["categoria", "total", "media_semanal", "ultima_semana", "acima_do_normal"]]
            resumo_display = resumo_display.rename(columns={
                "categoria": "Categoria", "total": "Total no período (R$)",
                "media_semanal": "Média semanal (R$)", "ultima_semana": "Última semana (R$)",
                "acima_do_normal": "Acima do normal?",
            })
            st.dataframe(resumo_display.style.format({
                "Total no período (R$)": "R$ {:,.2f}",
                "Média semanal (R$)": "R$ {:,.2f}",
                "Última semana (R$)": "R$ {:,.2f}",
            }), use_container_width=True)

            if total_nao_class > 0:
                with st.expander(f"⚠️ {len(nao_class)} pedidos ainda não classificados (R$ {total_nao_class:,.2f}) — cadastre o fornecedor na aba ao lado"):
                    pendentes = (
                        nao_class.groupby(["benef_nome", "benef_cpf_cnpj"], as_index=False)
                        .agg(qtd=("id", "count"), total=("valor", "sum"))
                        .sort_values("total", ascending=False)
                    )
                    st.dataframe(pendentes, use_container_width=True)

with tab_fornecedores:
    st.subheader("Cadastrar novo fornecedor")
    with st.form("novo_fornecedor", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        cnpj_input = col1.text_input("CNPJ/CPF (com ou sem pontuação)")
        nome_input = col2.text_input("Nome do fornecedor")
        categoria_input = col3.selectbox("Categoria", CATEGORIAS)
        submitted = st.form_submit_button("Cadastrar")
        if submitted:
            if not cnpj_input or not nome_input:
                st.error("Preencha CNPJ/CPF e nome.")
            else:
                try:
                    prep_insert_fornecedor(normalize_doc(cnpj_input), nome_input, categoria_input)
                    st.success(f"{nome_input} cadastrado como {categoria_input}.")
                    st.cache_data.clear()
                    st.rerun()
                except requests.HTTPError as e:
                    st.error(f"Erro ao cadastrar: {e.response.text}")

    st.subheader("Fornecedores cadastrados")
    if fornecedores.empty:
        st.info("Nenhum fornecedor cadastrado ainda.")
    else:
        edited = st.data_editor(
            fornecedores[["id", "nome", "cnpj_cpf", "categoria", "ativo"]],
            column_config={
                "id": None,
                "categoria": st.column_config.SelectboxColumn("categoria", options=CATEGORIAS),
            },
            disabled=["nome", "cnpj_cpf"],
            hide_index=True,
            use_container_width=True,
            key="fornecedores_editor",
        )
        if st.button("Salvar alterações"):
            changed = edited.merge(fornecedores[["id", "categoria", "ativo"]], on="id", suffixes=("", "_old"))
            changed = changed[(changed["categoria"] != changed["categoria_old"]) | (changed["ativo"] != changed["ativo_old"])]
            for _, row in changed.iterrows():
                prep_update_fornecedor(row["id"], row["categoria"], row["ativo"])
            st.success(f"{len(changed)} fornecedor(es) atualizado(s).")
            st.cache_data.clear()
            st.rerun()
