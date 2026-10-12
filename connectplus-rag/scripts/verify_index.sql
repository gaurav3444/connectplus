-- 1. Row counts per domain - should be 1184 (scamwatch.gov.au) and 4148 (beconnected.esafety.gov.au)
select domain, count(*) as chunk_count
from chunks
group by domain;

-- 2. Confirm every row actually has a real embedding (not null)
select count(*) as total_rows,
       count(*) filter (where embedding is null) as missing_embeddings
from chunks;

-- 3. Spot-check a handful of real rows by eye
select url, heading_path, token_count, left(text, 200) as text_preview
from chunks
where domain = 'scamwatch.gov.au'
order by random()
limit 5;

-- 4. Confirm the keyword-search column actually works
select url, left(text, 150) as text_preview
from chunks
where tsv @@ to_tsquery('english', 'scam & text')
limit 5;
