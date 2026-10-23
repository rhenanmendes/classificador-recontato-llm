-- Reconstrói as conversas (threads) a partir dos tweets.
--
-- Cada tweet aponta só para o tweet que ele responde. Para saber a qual conversa
-- ele pertence, é preciso subir a cadeia até a raiz. Isso é feito com uma CTE
-- recursiva: começa nas raízes e desce nível a nível pelas respostas.
--
-- Raiz = tweet que não responde a ninguém, ou que responde a um tweet ausente
-- da base (a base é uma amostra, então algumas cadeias chegam "cortadas").

CREATE OR REPLACE TABLE tweet_conversa AS
WITH RECURSIVE
raizes AS (
    SELECT t.tweet_id
    FROM tweets t
    LEFT JOIN tweets pai ON t.responde_a = pai.tweet_id
    WHERE t.responde_a IS NULL
       OR pai.tweet_id IS NULL
),
arvore (tweet_id, raiz_id, profundidade) AS (
    SELECT tweet_id, tweet_id, 0
    FROM raizes

    UNION ALL

    SELECT filho.tweet_id, a.raiz_id, a.profundidade + 1
    FROM tweets filho
    JOIN arvore a ON filho.responde_a = a.tweet_id
    WHERE a.profundidade < 500   -- trava de segurança contra cadeias anômalas
)
SELECT tweet_id, raiz_id, profundidade
FROM arvore;
