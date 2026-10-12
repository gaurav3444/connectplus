-- Run this in Supabase's SQL Editor, after `create extension if not exists vector;`
-- (that command was step 2 of the setup checklist).

create table if not exists chunks (
    id              text primary key,   -- from stage 03: "{doc_id}-chunk-{order_idx}", stable across re-runs
    doc_id          text not null,
    url             text not null,
    domain          text not null,
    title           text,
    lang            text,
    fetched_at      timestamptz,
    heading_path    text[],
    text            text not null,
    token_count     int,
    order_idx       int,
    embedding       vector(1024),       -- BGE-m3's dense output dimension, confirmed via search
    embedding_model text not null,      -- README: "store model name and dimensions ... need to be able to tell"
    embedding_dim   int not null,
    indexed_at      timestamptz not null default now()
);

-- Keyword search - README's stack table: "Postgres tsvector | Already in the same database"
--
-- 'english' is deliberate, and it is also a known limit worth stating.
-- Both approved domains are English-language Australian government sites,
-- so English stemming is correct for the overwhelming majority of the
-- corpus. But the index does hold confirmed non-English chunks (Vietnamese,
-- Chinese, Hindi, Greek translated pages), and those are NOT usefully
-- keyword-searchable here - they are reachable through vector search only.
--
-- 'simple' would not rescue them: Postgres cannot tokenise CJK text at all,
-- so an unspaced Chinese sentence becomes one single unmatched token under
-- any configuration. The fix lives upstream instead - connectplus-llm's
-- stage 07 rewrites the question into ENGLISH before calling retrieve().
alter table chunks
    add column if not exists tsv tsvector
    generated always as (to_tsvector('english', coalesce(text, ''))) stored;

create index if not exists chunks_tsv_idx
    on chunks using gin (tsv);

-- Vector search - README's stack table: "pgvector (HNSW)"
create index if not exists chunks_embedding_hnsw_idx
    on chunks using hnsw (embedding vector_cosine_ops);

-- Screen 3a (Browse topics), written by `python -m rag.main browse --build`.
-- A snapshot of rag.browse() for every subcategory, so the app reads it
-- straight from Supabase: no Python, no model, no endpoint in between.
-- Rebuilt in full (delete + insert, one transaction) after each re-index.
-- Read-only and public on purpose: it lists public pages of approved sites.
create table if not exists browse_resources (
    category_id       text not null,
    category_title    text not null,
    category_pos      int  not null,
    subcategory_id    text not null,
    subcategory_title text not null,
    subcategory_pos   int  not null,
    resource_pos      int  not null,
    resource_id       text not null,   -- 'domain/path' of the section
    url               text not null,
    domain            text not null,
    title             text not null,
    pages             jsonb not null,  -- [{doc_id, url, title}], landing page first: the steps
    built_at          timestamptz not null default now(),
    primary key (category_id, subcategory_id, resource_pos)
);

alter table browse_resources enable row level security;
drop policy if exists "browse is readable by anyone" on browse_resources;
create policy "browse is readable by anyone" on browse_resources for select using (true);
