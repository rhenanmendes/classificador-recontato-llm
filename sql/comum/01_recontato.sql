-- Deriva o indicador de recontato a partir da tabela padrão de contatos.
--
-- Definição: um contato é RECONTATO quando o mesmo cliente volta à mesma conta
-- (marca ou empresa-cliente) em até {janela} dias após o FIM do contato anterior.
-- O contato anterior, nesse caso, "gerou recontato" (falha de resolução no
-- primeiro contato, o oposto do FCR).
--
-- Censura de janela: contatos que terminaram a menos de {janela} dias do fim da
-- base não tiveram tempo de gerar recontato. Eles ficam marcados como
-- janela_observavel = false e saem do cálculo de FCR, para não inflar o indicador.

CREATE OR REPLACE TABLE contatos_flag AS
WITH sequencia AS (
    SELECT
        c.*,
        row_number()       OVER w AS seq_contato,
        lag(contato_id)    OVER w AS contato_anterior_id,
        lag(fim)           OVER w AS fim_anterior,
        lead(contato_id)   OVER w AS proximo_contato_id,
        lead(inicio)       OVER w AS inicio_proximo
    FROM contatos c
    WINDOW w AS (PARTITION BY cliente_id, conta ORDER BY inicio, contato_id)
),
limite AS (
    SELECT max(fim) AS fim_da_base FROM contatos
)
SELECT
    s.*,
    s.contato_anterior_id IS NOT NULL
        AND s.inicio <= s.fim_anterior + INTERVAL '{janela} days'      AS eh_recontato,
    s.proximo_contato_id IS NOT NULL
        AND s.inicio_proximo <= s.fim + INTERVAL '{janela} days'       AS gerou_recontato,
    s.fim <= l.fim_da_base - INTERVAL '{janela} days'                  AS janela_observavel,
    date_diff('minute', s.fim_anterior, s.inicio) / 60.0               AS horas_desde_anterior
FROM sequencia s
CROSS JOIN limite l;

-- Pares (contato anterior -> recontato), que são a unidade classificada pelo LLM.
-- O agente e o produto são os do contato ANTERIOR: é ali que a resolução falhou.
CREATE OR REPLACE TABLE recontatos AS
SELECT
    r.contato_id            AS recontato_id,
    r.cliente_id,
    r.conta,
    r.canal,
    a.produto,
    a.agente_id,
    r.inicio,
    r.horas_desde_anterior,
    a.contato_id            AS contato_anterior_id,
    a.transcricao           AS transcricao_anterior,
    r.transcricao           AS transcricao_atual
FROM contatos_flag r
JOIN contatos_flag a ON a.contato_id = r.contato_anterior_id
WHERE r.eh_recontato;
