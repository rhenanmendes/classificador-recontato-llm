-- Indicadores de recontato e FCR por dimensão, em uma única passada,
-- usando GROUPING SETS (equivale a vários GROUP BY empilhados).
--
--   taxa_recontato = recontatos / total de contatos
--                    ("quanto da demanda é gente voltando")
--   fcr_janela     = 1 - contatos que geraram recontato / contatos observáveis
--                    ("quanto foi resolvido no primeiro contato")
--
-- O FCR usa só contatos com janela observável (ver 01_recontato.sql).

CREATE OR REPLACE TABLE indicadores AS
WITH agregado AS (
    SELECT
        CASE
            WHEN GROUPING(conta) = 0     THEN 'conta'
            WHEN GROUPING(produto) = 0   THEN 'produto'
            WHEN GROUPING(canal) = 0     THEN 'canal'
            WHEN GROUPING(agente_id) = 0 THEN 'agente'
            ELSE 'geral'
        END AS dimensao,
        CASE
            WHEN GROUPING(conta) = 0     THEN conta
            WHEN GROUPING(produto) = 0   THEN produto
            WHEN GROUPING(canal) = 0     THEN canal
            WHEN GROUPING(agente_id) = 0 THEN agente_id
            ELSE 'Total'
        END AS valor,
        count(*)                                                          AS contatos,
        count(*) FILTER (WHERE eh_recontato)                              AS recontatos,
        count(*) FILTER (WHERE janela_observavel)                         AS contatos_observaveis,
        count(*) FILTER (WHERE janela_observavel AND gerou_recontato)     AS geraram_recontato,
        median(horas_desde_anterior) FILTER (WHERE eh_recontato)          AS mediana_horas_ate_recontato
    FROM contatos_flag
    GROUP BY GROUPING SETS ((conta), (produto), (canal), (agente_id), ())
)
SELECT
    *,
    recontatos / contatos                                                 AS taxa_recontato,
    CASE WHEN contatos_observaveis > 0
         THEN 1 - geraram_recontato / contatos_observaveis END            AS fcr_janela
FROM agregado
WHERE valor IS NOT NULL;
