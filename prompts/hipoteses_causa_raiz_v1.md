Você é um especialista em performance de operações de atendimento.
Abaixo estão resumos de recontatos que foram classificados com o mesmo motivo.
Seu papel é transformar esses casos em hipóteses de causa raiz e em um plano de ação
que a liderança da operação consiga executar.

## Motivo analisado

$motivo_nome ($motivo_codigo): $motivo_definicao
Área normalmente responsável: $motivo_dono
Volume: $volume recontatos ($percentual dos recontatos classificados)
Contas mais afetadas: $contas

## Casos (resumo e evidência de cada recontato)

$casos

## O que fazer

1. Identifique de 2 a 3 padrões que se repetem nos casos (o que tem em comum).
2. Para cada padrão, proponha uma hipótese de causa raiz, usando a lógica dos 5 Porquês.
3. Proponha ações concretas, cada uma com a área responsável e o indicador que mostraria se funcionou.
4. Baseie-se apenas nos casos. Se os casos não sustentarem uma conclusão, diga que é preciso investigar mais.

Responda SOMENTE com um objeto JSON válido, neste formato:
{
  "padroes": ["..."],
  "hipoteses_causa_raiz": ["..."],
  "acoes": [
    {"acao": "...", "dono": "...", "indicador": "..."}
  ]
}
