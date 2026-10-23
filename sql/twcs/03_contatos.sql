-- Transforma cada conversa em um "contato" no formato padrão do projeto.
--
-- Regras:
--   * Só entram conversas iniciadas por um cliente (tweet raiz com inbound = true).
--   * A marca do contato é a primeira conta de atendimento que respondeu.
--   * Conversas sem nenhuma resposta da marca ficam na tabela contatos_sem_resposta
--     (não são "atendimentos", mas são um indicador útil por si só).
--   * Mensagens de terceiros que entraram na conversa são descartadas.
--   * IDs numéricos de clientes citados no texto (@123456) são anonimizados.

CREATE OR REPLACE TABLE _msgs AS
SELECT
    c.raiz_id,
    t.tweet_id,
    t.author_id,
    t.inbound,
    t.criado_em,
    t.texto,
    raiz.author_id AS cliente_id
FROM tweet_conversa c
JOIN tweets t    ON t.tweet_id = c.tweet_id
JOIN tweets raiz ON raiz.tweet_id = c.raiz_id
WHERE raiz.inbound;

CREATE OR REPLACE TABLE _marca AS
SELECT raiz_id, arg_min(author_id, criado_em) AS conta
FROM _msgs
WHERE NOT inbound
GROUP BY raiz_id;

CREATE OR REPLACE TABLE contatos_sem_resposta AS
SELECT m.raiz_id, min(m.criado_em) AS inicio
FROM _msgs m
ANTI JOIN _marca USING (raiz_id)
GROUP BY m.raiz_id;

CREATE OR REPLACE TABLE contatos AS
WITH mensagens AS (
    SELECT
        m.*,
        k.conta,
        CASE
            WHEN m.inbound AND m.author_id = m.cliente_id THEN 'Cliente'
            WHEN NOT m.inbound AND m.author_id = k.conta  THEN 'Atendimento'
        END AS papel
    FROM _msgs m
    JOIN _marca k USING (raiz_id)
)
SELECT
    CAST(raiz_id AS VARCHAR)                        AS contato_id,
    any_value(cliente_id)                           AS cliente_id,
    any_value(conta)                                AS conta,
    'twitter'                                       AS canal,
    CAST(NULL AS VARCHAR)                           AS produto,
    CAST(NULL AS VARCHAR)                           AS agente_id,
    min(criado_em)                                  AS inicio,
    max(criado_em)                                  AS fim,
    count(*) FILTER (WHERE papel = 'Cliente')       AS msgs_cliente,
    count(*) FILTER (WHERE papel = 'Atendimento')   AS msgs_atendimento,
    date_diff(
        'second',
        min(criado_em),
        min(criado_em) FILTER (WHERE papel = 'Atendimento')
    ) / 60.0                                        AS minutos_primeira_resposta,
    string_agg(
        papel || ': ' || regexp_replace(texto, '@[0-9]+', '@cliente', 'g'),
        chr(10)
        ORDER BY criado_em, tweet_id
    )                                               AS transcricao
FROM mensagens
WHERE papel IS NOT NULL
GROUP BY raiz_id;

DROP TABLE _msgs;
DROP TABLE _marca;
