-- Carrega a base de chamados B2B (atendimento a RHs de empresas-cliente)
-- no mesmo formato padrão de contatos usado pela base do Twitter.
-- Aqui a "conta" é a empresa-cliente e o "cliente" é a pessoa solicitante.

CREATE OR REPLACE TABLE contatos AS
SELECT
    ticket_id                                   AS contato_id,
    solicitante_id                              AS cliente_id,
    empresa_cliente                             AS conta,
    canal,
    produto,
    agente_id,
    CAST(aberto_em AS TIMESTAMP)                AS inicio,
    CAST(fechado_em AS TIMESTAMP)               AS fim,
    CAST(NULL AS BIGINT)                        AS msgs_cliente,
    CAST(NULL AS BIGINT)                        AS msgs_atendimento,
    CAST(NULL AS DOUBLE)                        AS minutos_primeira_resposta,
    transcricao
FROM read_csv('{arquivo}', header = true, all_varchar = true);

CREATE OR REPLACE TABLE contatos_sem_resposta AS
SELECT CAST(NULL AS VARCHAR) AS raiz_id, CAST(NULL AS TIMESTAMP) AS inicio
WHERE false;
