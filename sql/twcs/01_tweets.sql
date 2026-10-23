-- Carrega a base "Customer Support on Twitter" (Kaggle) e padroniza tipos.
-- Tudo é lido como texto e convertido explicitamente, para não depender
-- da inferência automática de tipos em um arquivo de ~2,8 milhões de linhas.

CREATE OR REPLACE TABLE tweets AS
SELECT
    CAST(tweet_id AS BIGINT)                                        AS tweet_id,
    author_id,
    lower(trim(inbound)) = 'true'                                   AS inbound,
    CAST(strptime(created_at, '%a %b %d %H:%M:%S %z %Y') AS TIMESTAMP) AS criado_em,
    text                                                            AS texto,
    -- No CSV original esse campo vem como número decimal (ex.: "119237.0")
    TRY_CAST(TRY_CAST(in_response_to_tweet_id AS DOUBLE) AS BIGINT) AS responde_a
FROM read_csv(
    '{arquivo}',
    header = true,
    all_varchar = true,
    ignore_errors = true
)
WHERE TRY_CAST(tweet_id AS BIGINT) IS NOT NULL;
