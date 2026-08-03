import os
import re
from datetime import date, timedelta

import pandas as pd
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

CATEGORIAS_PADRAO = [
    "Funilaria/Pintura",
    "Micropintura",
    "Martelinho de Ouro",
    "Mecânica/Revisão",
    "Peças",
    "Pneus",
    "Polimento/Estética",
    "Higienização/Limpeza",
    "Elétrica",
    "Vidros",
    "Outros",
]
NOVA_CATEGORIA = "+ Nova categoria..."
NAO_CLASSIFICADO = "Não classificado"

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def label_mes(periodo) -> str:
    return f"{MESES_PT[periodo.month]}/{periodo.year}"


def categoria_options(fornecedores: pd.DataFrame) -> list:
    existentes = set(fornecedores["categoria"].dropna()) if not fornecedores.empty else set()
    return sorted(set(CATEGORIAS_PADRAO) | existentes) + [NOVA_CATEGORIA]


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
    cols = "id,empresa,tipo,status,valor,placa,benef_nome,benef_cpf_cnpj,descricao,created_at,lote"
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


def gasto_por_veiculo(df: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for _, row in df.iterrows():
        itens = row.get("lote")
        if isinstance(itens, list) and itens:
            for item in itens:
                linhas.append({
                    "placa": (item.get("placa") or "").strip().upper() or "Sem placa",
                    "valor": item.get("valor") or 0,
                    "categoria": row["categoria"],
                    "empresa": row["empresa"],
                    "created_at": row["created_at"],
                })
        else:
            linhas.append({
                "placa": (row["placa"] or "").strip().upper() if row["placa"] else "Sem placa",
                "valor": row["valor"],
                "categoria": row["categoria"],
                "empresa": row["empresa"],
                "created_at": row["created_at"],
            })
    return pd.DataFrame(linhas)


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


def prep_fetch_orcamentos() -> pd.DataFrame:
    resp = requests.get(
        f"{PREP_URL}/rest/v1/orcamentos_veiculo",
        headers=_headers(PREP_KEY),
        params={"select": "*", "order": "criado_em.desc"},
        timeout=30,
    )
    if resp.status_code == 404:
        return pd.DataFrame(columns=["id", "placa", "categoria", "valor", "observacao", "criado_em"])
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    if not df.empty:
        df["placa"] = df["placa"].str.strip().str.upper()
        df["criado_em"] = pd.to_datetime(df["criado_em"])
    return df


def prep_insert_orcamento(placa: str, categoria: str, valor: float, observacao: str):
    resp = requests.post(
        f"{PREP_URL}/rest/v1/orcamentos_veiculo",
        headers={**_headers(PREP_KEY), "Content-Type": "application/json", "Prefer": "return=representation"},
        json={"placa": placa.strip().upper(), "categoria": categoria, "valor": valor, "observacao": observacao or None},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def prep_delete_orcamento(row_id: str):
    resp = requests.delete(
        f"{PREP_URL}/rest/v1/orcamentos_veiculo",
        headers=_headers(PREP_KEY),
        params={"id": f"eq.{row_id}"},
        timeout=30,
    )
    resp.raise_for_status()


def categoria_picker(fornecedores: pd.DataFrame, key_prefix: str, categoria_atual: str | None = None) -> str:
    opcoes = categoria_options(fornecedores)
    index = opcoes.index(categoria_atual) if categoria_atual in opcoes else 0
    escolha = st.selectbox("Categoria", opcoes, index=index, key=f"{key_prefix}_categoria")
    if escolha == NOVA_CATEGORIA:
        return st.text_input("Nome da nova categoria", key=f"{key_prefix}_nova_categoria").strip()
    return escolha


@st.dialog("Pagamentos")
def dialog_pagamentos_categoria(df: pd.DataFrame, categoria: str):
    pagamentos = df[df["categoria"] == categoria].sort_values("created_at", ascending=False)
    st.markdown(f"### 🏷️ {categoria}")
    st.caption(f"{len(pagamentos)} pagamento(s) — R$ {pagamentos['valor'].sum():,.2f} no total")
    st.write("")
    dia_atual = None
    for _, p in pagamentos.iterrows():
        dia = p["created_at"].strftime("%d/%m/%Y")
        if dia != dia_atual:
            st.markdown(f"**{dia}**")
            dia_atual = dia
        placa_txt = f" • placa {p['placa']}" if pd.notna(p.get("placa")) else ""
        st.write(f"R$ {p['valor']:,.2f}{placa_txt}")
        st.caption(p["benef_nome"])
    st.write("")
    if st.button("Fechar", use_container_width=True):
        st.rerun()


@st.dialog("Detalhe do veículo")
def dialog_detalhe_veiculo(veiculos: pd.DataFrame, fornecedores: pd.DataFrame, orcamentos: pd.DataFrame, placa: str, total: float):
    st.markdown(f"### 🚗 {placa}")

    orc_placa = orcamentos[orcamentos["placa"] == placa] if not orcamentos.empty else orcamentos
    total_orcado = orc_placa["valor"].sum() if not orc_placa.empty else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("Gasto real", f"R$ {total:,.2f}")
    c2.metric("Orçado", f"R$ {total_orcado:,.2f}")
    if total_orcado > 0:
        diferenca = total - total_orcado
        c3.metric("Diferença", f"R$ {diferenca:,.2f}")
        c3.caption("🔺 Acima do orçado" if diferenca > 0 else "✅ Dentro do orçado")
    else:
        c3.metric("Diferença", "—")
    st.write("")

    detalhe_real = (
        veiculos[veiculos["placa"] == placa]
        .groupby("categoria", as_index=False)["valor"].sum()
        .rename(columns={"valor": "gasto_real"})
    )
    detalhe_orc = (
        orc_placa.groupby("categoria", as_index=False)["valor"].sum().rename(columns={"valor": "orcado"})
        if not orc_placa.empty else pd.DataFrame(columns=["categoria", "orcado"])
    )
    comparativo = pd.merge(detalhe_real, detalhe_orc, on="categoria", how="outer").fillna(0)
    comparativo = comparativo.sort_values("gasto_real", ascending=False)

    if not comparativo.empty:
        st.markdown("**Por categoria**")
        for _, c in comparativo.iterrows():
            col_nome, col_orc, col_real = st.columns([2, 2, 2])
            col_nome.write(c["categoria"])
            col_orc.caption(f"Orçado: R$ {c['orcado']:,.2f}")
            excedeu = c["orcado"] > 0 and c["gasto_real"] > c["orcado"]
            marcador = " 🔺" if excedeu else ""
            col_real.write(f"Real: R$ {c['gasto_real']:,.2f}{marcador}")
        st.write("")

    st.divider()
    st.markdown("**Itens orçados**")
    if orc_placa.empty:
        st.caption("Nenhum item orçado lançado ainda.")
    else:
        for _, o in orc_placa.sort_values("criado_em", ascending=False).iterrows():
            col_cat, col_valor, col_del = st.columns([2, 3, 1])
            col_cat.write(o["categoria"])
            texto_valor = f"R$ {o['valor']:,.2f}"
            if o.get("observacao"):
                texto_valor += f" — {o['observacao']}"
            col_valor.write(texto_valor)
            if col_del.button("🗑️", key=f"del_orc_{o['id']}"):
                prep_delete_orcamento(o["id"])
                st.cache_data.clear()
                st.rerun()

    st.write("")
    st.markdown("**Lançar item orçado**")
    categoria_orc = categoria_picker(fornecedores, f"orc_{placa}")
    valor_orc = st.number_input("Valor orçado (R$)", min_value=0.0, step=50.0, key=f"valor_orc_{placa}")
    obs_orc = st.text_input("Observação (opcional)", key=f"obs_orc_{placa}", placeholder="Ex: troca de para-choque")
    if st.button("➕ Adicionar", key=f"add_orc_{placa}", use_container_width=True):
        if not categoria_orc or valor_orc <= 0:
            st.error("Escolha uma categoria e informe um valor maior que zero.")
        else:
            prep_insert_orcamento(placa, categoria_orc, valor_orc, obs_orc)
            st.cache_data.clear()
            st.rerun()

    st.write("")
    if st.button("Fechar", use_container_width=True, key=f"fechar_{placa}"):
        st.rerun()


@st.dialog("Novo fornecedor")
def dialog_novo_fornecedor(fornecedores: pd.DataFrame):
    st.caption("Preencha os dados do fornecedor. É rápido!")
    nome = st.text_input("Nome do fornecedor", key="novo_nome", placeholder="Ex: Jm Funilaria e Pintura")
    cnpj = st.text_input("CNPJ ou CPF", key="novo_cnpj", placeholder="Só números ou com pontuação, tanto faz")
    categoria = categoria_picker(fornecedores, "novo")

    st.write("")
    col1, col2 = st.columns(2)
    if col1.button("✅ Cadastrar", type="primary", use_container_width=True):
        if not nome or not cnpj or not categoria:
            st.error("Preencha todos os campos.")
        else:
            try:
                prep_insert_fornecedor(normalize_doc(cnpj), nome, categoria)
                st.cache_data.clear()
                st.success(f"{nome} cadastrado!")
                st.rerun()
            except requests.HTTPError as e:
                if "duplicate key" in e.response.text:
                    st.error("Já existe um fornecedor cadastrado com esse CNPJ/CPF.")
                else:
                    st.error(f"Erro ao cadastrar: {e.response.text}")
    if col2.button("Cancelar", use_container_width=True):
        st.rerun()


@st.dialog("Editar fornecedor")
def dialog_editar_fornecedor(fornecedores: pd.DataFrame, row: pd.Series):
    st.markdown(f"**{row['nome']}**")
    st.caption(row["cnpj_cpf"])
    categoria = categoria_picker(fornecedores, f"edit_{row['id']}", categoria_atual=row["categoria"])
    ativo = st.toggle("Fornecedor ativo", value=bool(row["ativo"]), key=f"edit_{row['id']}_ativo",
                       help="Desative se esse fornecedor não é mais usado. Ele some da lista de classificação, mas o histórico continua.")

    st.write("")
    col1, col2 = st.columns(2)
    if col1.button("💾 Salvar", type="primary", use_container_width=True):
        if not categoria:
            st.error("Escolha ou digite uma categoria.")
        else:
            prep_update_fornecedor(row["id"], categoria, ativo)
            st.cache_data.clear()
            st.rerun()
    if col2.button("Cancelar", use_container_width=True):
        st.rerun()


st.set_page_config(page_title="Preparação — Custos", layout="wide", page_icon="🔧")
st.title("🔧 Preparação e Pós-Venda — Custos")

tab_dashboard, tab_comparativo, tab_veiculos, tab_fornecedores = st.tabs(
    ["📊 Painel de custos", "📅 Comparar meses", "🚗 Por veículo", "🏷️ Fornecedores"]
)

with st.spinner("Carregando dados..."):
    solicitacoes = hub_fetch_solicitacoes()
    fornecedores = prep_fetch_fornecedores()
    orcamentos = prep_fetch_orcamentos()

if not fornecedores.empty:
    cat_map = dict(zip(fornecedores["cnpj_norm"], fornecedores["categoria"]))
    ativo_map = dict(zip(fornecedores["cnpj_norm"], fornecedores["ativo"]))
else:
    cat_map, ativo_map = {}, {}

if not solicitacoes.empty:
    solicitacoes["categoria"] = solicitacoes["cnpj_norm"].map(cat_map).fillna(NAO_CLASSIFICADO)

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

    base_meses = solicitacoes[
        solicitacoes["empresa"].isin(empresa_sel) & solicitacoes["status"].isin(status_sel)
    ].copy()
    base_meses["ano_mes"] = base_meses["created_at"].dt.to_period("M")
else:
    df = solicitacoes
    base_meses = solicitacoes

with tab_dashboard:
    if solicitacoes.empty:
        st.info("Nenhum registro de MANUTENCAO/POS_VENDAS encontrado no hub.")
    else:
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

            st.subheader("Onde o dinheiro está indo")
            por_categoria_total = df.groupby("categoria", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
            maior_valor = por_categoria_total["valor"].max()
            for _, cat in por_categoria_total.iterrows():
                c_nome, c_barra, c_valor = st.columns([2, 3, 2])
                c_nome.write(cat["categoria"])
                c_barra.progress(cat["valor"] / maior_valor if maior_valor else 0)
                c_valor.write(f"R$ {cat['valor']:,.2f}")

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
            resumo = resumo.sort_values("total", ascending=False)

            cols = st.columns(3)
            for i, (_, cat) in enumerate(resumo.iterrows()):
                with cols[i % 3]:
                    with st.container(border=True):
                        titulo = cat["categoria"]
                        if cat["acima_do_normal"]:
                            titulo += " ⚠️"
                        st.markdown(f"**{titulo}**")
                        st.metric("Total no período", f"R$ {cat['total']:,.2f}")
                        st.caption(f"Média semanal: R$ {cat['media_semanal']:,.2f}")
                        if cat["acima_do_normal"]:
                            st.caption("🔺 Última semana acima do normal")
                        if st.button("Ver pagamentos", key=f"ver_pagamentos_{cat['categoria']}", use_container_width=True):
                            dialog_pagamentos_categoria(df, cat["categoria"])

            if total_nao_class > 0:
                with st.expander(f"⚠️ {len(nao_class)} pedidos ainda não classificados (R$ {total_nao_class:,.2f}) — cadastre o fornecedor na aba 🏷️ Fornecedores"):
                    pendentes = (
                        nao_class.groupby(["benef_nome", "benef_cpf_cnpj"], as_index=False)
                        .agg(qtd=("id", "count"), total=("valor", "sum"))
                        .sort_values("total", ascending=False)
                    )
                    pendentes = pendentes.rename(columns={
                        "benef_nome": "Fornecedor", "benef_cpf_cnpj": "CNPJ/CPF",
                        "qtd": "Qtd. pedidos", "total": "Total (R$)",
                    })
                    st.dataframe(pendentes.style.format({"Total (R$)": "R$ {:,.2f}"}), use_container_width=True, hide_index=True)

with tab_comparativo:
    if solicitacoes.empty:
        st.info("Nenhum registro de MANUTENCAO/POS_VENDAS encontrado no hub.")
    else:
        meses_disponiveis = sorted(base_meses["ano_mes"].unique(), reverse=True)
        if len(meses_disponiveis) < 2:
            st.warning("Ainda não há dados de pelo menos 2 meses diferentes para comparar.")
        else:
            opcoes_mes = {label_mes(p): p for p in meses_disponiveis}
            labels = list(opcoes_mes.keys())
            col_a, col_b = st.columns(2)
            label_a = col_a.selectbox("Mês A", labels, index=min(1, len(labels) - 1))
            label_b = col_b.selectbox("Mês B", labels, index=0)
            periodo_a, periodo_b = opcoes_mes[label_a], opcoes_mes[label_b]

            categorias_disponiveis = sorted(base_meses["categoria"].dropna().unique().tolist())
            categoria_filtro = st.multiselect(
                "Categoria", categorias_disponiveis,
                placeholder="Todas as categorias (deixe em branco pra ver tudo)",
            )

            gasto_a = base_meses[base_meses["ano_mes"] == periodo_a].groupby("categoria")["valor"].sum()
            gasto_b = base_meses[base_meses["ano_mes"] == periodo_b].groupby("categoria")["valor"].sum()
            comparativo = pd.DataFrame({"a": gasto_a, "b": gasto_b}).fillna(0).reset_index()
            comparativo["variacao"] = comparativo["b"] - comparativo["a"]
            comparativo["variacao_pct"] = comparativo.apply(
                lambda r: (r["variacao"] / r["a"] * 100) if r["a"] else (100.0 if r["b"] else 0.0), axis=1
            )
            if categoria_filtro:
                comparativo = comparativo[comparativo["categoria"].isin(categoria_filtro)]
            comparativo = comparativo.sort_values("b", ascending=False)

            if comparativo.empty:
                st.warning("Nenhum gasto nessa(s) categoria(s) em nenhum dos dois meses selecionados.")
            else:
                total_a, total_b = comparativo["a"].sum(), comparativo["b"].sum()
                c1, c2, c3 = st.columns(3)
                c1.metric(label_a, f"R$ {total_a:,.2f}")
                c2.metric(label_b, f"R$ {total_b:,.2f}")
                variacao_total = total_b - total_a
                pct_total = (variacao_total / total_a * 100) if total_a else 0
                c3.metric("Variação", f"R$ {variacao_total:,.2f}", f"{pct_total:+.0f}%")

                st.write("")
                st.subheader("Por categoria")
                maior_valor = comparativo[["a", "b"]].max().max()
                for _, cat in comparativo.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**{cat['categoria']}**")
                        c_label, c_barra, c_valor = st.columns([1, 3, 2])
                        c_label.caption(label_a)
                        c_barra.progress(cat["a"] / maior_valor if maior_valor else 0)
                        c_valor.write(f"R$ {cat['a']:,.2f}")
                        c_label, c_barra, c_valor = st.columns([1, 3, 2])
                        c_label.caption(label_b)
                        c_barra.progress(cat["b"] / maior_valor if maior_valor else 0)
                        c_valor.write(f"R$ {cat['b']:,.2f}")
                        seta = "🔺" if cat["variacao"] > 0 else ("🔻" if cat["variacao"] < 0 else "➖")
                        st.caption(f"{seta} {cat['variacao_pct']:+.0f}% (R$ {cat['variacao']:,.2f})")

with tab_veiculos:
    if solicitacoes.empty or df.empty:
        st.info("Nenhum registro para mostrar.")
    else:
        veiculos = gasto_por_veiculo(df)
        placa_busca = st.text_input("🔍 Buscar placa", key="busca_placa", placeholder="Ex: ABC1D23")

        resumo_veiculos = (
            veiculos.groupby("placa", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
        )
        if placa_busca:
            resumo_veiculos = resumo_veiculos[resumo_veiculos["placa"].str.contains(placa_busca.upper(), na=False)]

        if resumo_veiculos.empty:
            st.warning("Nenhum veículo encontrado.")
        else:
            total_encontrados = len(resumo_veiculos)
            LIMITE = 25
            ver_todos = False
            if placa_busca or total_encontrados <= LIMITE:
                st.caption(f"{total_encontrados} veículo(s) — do mais caro para o mais barato")
            else:
                st.caption(f"Mostrando os {LIMITE} veículos com maior gasto (de {total_encontrados} no total). Use a busca para achar uma placa específica.")
                ver_todos = st.checkbox(f"Mostrar todos os {total_encontrados}")

            if not ver_todos and not placa_busca:
                resumo_veiculos = resumo_veiculos.head(LIMITE)

            for _, v in resumo_veiculos.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    c1.markdown(f"**🚗 {v['placa']}**")
                    c2.markdown(f"**R$ {v['valor']:,.2f}**")
                    if c3.button("Ver", key=f"ver_{v['placa']}", use_container_width=True):
                        dialog_detalhe_veiculo(veiculos, fornecedores, orcamentos, v["placa"], v["valor"])

with tab_fornecedores:
    col_titulo, col_busca, col_novo = st.columns([2, 3, 2])
    col_titulo.subheader("Fornecedores")
    busca = col_busca.text_input(
        "Buscar", key="busca_fornecedor", placeholder="🔍 Buscar por nome...", label_visibility="collapsed"
    )
    if col_novo.button("➕ Novo fornecedor", type="primary", use_container_width=True):
        dialog_novo_fornecedor(fornecedores)

    st.write("")

    if fornecedores.empty:
        st.info("Nenhum fornecedor cadastrado ainda. Clique em **➕ Novo fornecedor** para começar.")
    else:
        lista = fornecedores.sort_values("nome")
        if busca:
            lista = lista[lista["nome"].str.contains(busca, case=False, na=False)]

        if lista.empty:
            st.warning(f"Nenhum fornecedor encontrado para '{busca}'.")

        for _, row in lista.iterrows():
            with st.container(border=True):
                c_nome, c_categoria, c_status, c_acao = st.columns([3, 2, 1, 1])
                c_nome.markdown(f"**{row['nome']}**")
                c_nome.caption(row["cnpj_cpf"])
                c_categoria.markdown(f"🏷️ {row['categoria']}")
                if row["ativo"]:
                    c_status.markdown(":green[Ativo]")
                else:
                    c_status.markdown(":gray[Inativo]")
                if c_acao.button("Editar", key=f"editar_{row['id']}", use_container_width=True):
                    dialog_editar_fornecedor(fornecedores, row)
