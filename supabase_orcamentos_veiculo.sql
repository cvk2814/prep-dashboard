-- Rodar no SQL Editor do projeto Supabase "preparacao-dashboard"
-- (o mesmo banco onde já existe a tabela fornecedores)

create table if not exists orcamentos_veiculo (
    id uuid primary key default gen_random_uuid(),
    placa text not null,
    categoria text not null,
    valor numeric not null,
    observacao text,
    criado_em timestamptz not null default now()
);

create index if not exists orcamentos_veiculo_placa_idx on orcamentos_veiculo (placa);

alter table orcamentos_veiculo enable row level security;

-- Mesma política de acesso da tabela fornecedores (chave publishable com leitura/escrita).
create policy "orcamentos_veiculo_select" on orcamentos_veiculo
    for select using (true);
create policy "orcamentos_veiculo_insert" on orcamentos_veiculo
    for insert with check (true);
create policy "orcamentos_veiculo_update" on orcamentos_veiculo
    for update using (true);
create policy "orcamentos_veiculo_delete" on orcamentos_veiculo
    for delete using (true);
