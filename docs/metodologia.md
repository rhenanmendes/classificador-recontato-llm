# Metodologia

Este documento detalha as decisões técnicas do projeto. O [README](../README.md) traz a visão geral.

## 1. Definições

| Termo | Definição |
|---|---|
| **Contato** | Uma conversa completa entre um cliente e uma conta (marca ou empresa). No Twitter, uma thread iniciada por um cliente; na base B2B, um chamado. |
| **Conta** | Quem atende: a marca no Twitter, a empresa-cliente na base B2B. |
| **Recontato** | Contato do mesmo cliente com a mesma conta que começa em até *N* dias (padrão: 7) depois do **fim** do contato anterior. |
| **Contato que gerou recontato** | O contato anterior a um recontato. É onde a resolução falhou. |
| **Taxa de recontato** | Recontatos ÷ total de contatos. Mede quanto da demanda é gente voltando. |
| **FCR (janela de N dias)** | 1 − (contatos que geraram recontato ÷ contatos com janela observável). Mede quanto foi resolvido sem retorno. |
| **Recontato acionável** | Recontato cujo motivo indica falha de resolução (exclui assunto novo, agradecimento e indeterminado). |
| **Taxa de recontato acionável** | Taxa de recontato × participação de recontatos acionáveis na amostra classificada. |

### Por que medir a partir do fim do contato anterior

Medir a partir do início penalizaria conversas longas: um cliente que passou dois dias trocando mensagens e voltou no terceiro dia teria "gasto" boa parte da janela dentro do próprio atendimento. Medir a partir do fim responde à pergunta certa: depois que o atendimento terminou, o cliente precisou voltar?

### Censura de janela

Contatos que terminaram a menos de *N* dias do fim da base ainda não tiveram tempo de gerar recontato. Incluí-los no denominador do FCR inflaria o indicador. Por isso eles recebem `janela_observavel = false` e ficam fora do cálculo do FCR (mas continuam contando como contatos e, se for o caso, como recontatos).

## 2. Do tweet ao contato (SQL)

A base do Twitter tem um tweet por linha, e cada tweet aponta só para o tweet que ele responde (`in_response_to_tweet_id`). Para agrupar tweets em conversas é preciso subir a cadeia até a raiz, o que é feito com uma CTE recursiva em DuckDB ([sql/twcs/02_conversas.sql](../sql/twcs/02_conversas.sql)):

1. **Raízes:** tweets que não respondem a ninguém, ou que respondem a um tweet ausente da base (a base é uma amostra e algumas cadeias chegam cortadas).
2. **Recursão:** a partir de cada raiz, desce nível a nível pelas respostas, levando o `raiz_id` adiante.

Depois ([sql/twcs/03_contatos.sql](../sql/twcs/03_contatos.sql)):

- Só entram conversas **iniciadas por um cliente** (`inbound = true` na raiz).
- A **marca** é a primeira conta de atendimento que respondeu. Conversas sem resposta vão para `contatos_sem_resposta`.
- Mensagens de terceiros que entraram na conversa são descartadas: a transcrição fica só com as falas do cliente e da marca.
- IDs numéricos de clientes citados no texto (`@115712`) são trocados por `@cliente`.

O recontato e os indicadores são calculados com funções de janela (`LAG`/`LEAD` particionado por cliente e conta) e `GROUPING SETS` ([sql/comum](../sql/comum)). A mesma lógica serve para qualquer base que chegue no formato padrão de contatos, como a base B2B.

## 3. Taxonomia de motivos

A taxonomia ([taxonomia/motivos_recontato.yaml](../taxonomia/motivos_recontato.yaml)) foi desenhada para **operação**, com três critérios:

1. **Mutuamente exclusiva pela causa.** Cada motivo descreve *por que* o cliente voltou, não o tom da mensagem. Um cliente irritado porque o reembolso prometido não caiu é "promessa não cumprida", não "discorda da solução".
2. **Cada motivo tem dono e alavanca.** Processos, Treinamento, WFM, Produto. O Pareto já sai como plano de ação com responsável.
3. **Separa o que é e o que não é falha.** Assunto novo e agradecimento contam como recontato pela regra de janela, mas não indicam problema. Separá-los evita perseguir o número errado.

| Motivo | Dono típico | Acionável |
|---|---|---|
| Problema não resolvido | Processos / Base de conhecimento | Sim |
| Informação incompleta ou confusa | Treinamento / Qualidade | Sim |
| Promessa ou prazo não cumprido | Processos / Backoffice | Sim |
| Direcionado para outro canal sem resolução | Processos / Roteamento | Sim |
| Demora ou ausência de retorno | Planejamento / WFM | Sim |
| Discorda da solução ou da política | Produto / Política comercial | Sim |
| Assunto novo | - | Não |
| Agradecimento ou confirmação | - | Não |
| Indeterminado | - | Não |

A taxonomia é um arquivo de configuração: dá para adaptar a outra operação sem mexer no código.

## 4. Classificação com LLM

**Unidade classificada:** o par (contato anterior, novo contato). Olhar só a nova mensagem não basta: "ainda nada" só vira "promessa não cumprida" quando se sabe que o atendimento anterior prometeu um prazo.

**Decisões de prompt** ([prompts/classificar_recontato_v1.md](../prompts/classificar_recontato_v1.md)):

- Papel e tarefa explícitos, lista fechada de motivos com definição e sinais típicos.
- Regras de desempate (causa > tom; assunto novo quando não há relação; indeterminado só em último caso).
- Proibição de inventar fatos.
- Pedido de **evidência** (trecho do novo contato) e **resumo**: tornam a classificação auditável e alimentam a etapa de hipóteses.
- Pedido de **confiança**, útil para priorizar revisão humana dos casos duvidosos.

**Decisões de execução:**

- **Saída estruturada:** esquema JSON com `enum` dos códigos (Gemini: `responseSchema`; Ollama: `format`). Respostas fora do esquema viram `INDETERMINADO` com o erro registrado, e a taxa de erro de formato aparece no relatório.
- **Temperatura 0**, para a mesma entrada gerar a mesma classificação.
- **Truncamento:** cada contato é limitado a 1.500 caracteres. No contato anterior, mantém-se o começo (o pedido) e o fim (o desfecho ou a promessa).
- **Prompt versionado:** o nome do arquivo de saída inclui provedor, modelo e versão do prompt. Mudar o prompt gera uma nova execução, comparável com a anterior.
- **Cache e retomada:** cada classificação é gravada assim que fica pronta. Se a cota acabar, o processo para e continua de onde parou na próxima execução.
- **Amostra reprodutível:** a seleção usa `md5(id || semente)`, então a mesma semente gera a mesma amostra em qualquer computador.

## 5. Validação

Classificação por LLM sem validação é opinião. O protocolo segue a lógica de uma auditoria de qualidade:

1. `python main.py rotular` exporta uma amostra aleatória **sem a resposta do modelo** (rotulagem às cegas, para evitar viés de ancoragem).
2. Uma pessoa preenche `motivo_real` usando a legenda da taxonomia.
3. `python main.py relatorio --gabarito ...` e `python main.py comparar ...` calculam:
   - **Acurácia:** % de casos em que modelo e pessoa concordam.
   - **Kappa de Cohen:** concordância descontando o acaso. Referência usual: acima de 0,6 é concordância substancial; acima de 0,8, quase perfeita.
   - **F1 macro:** média do F1 de cada motivo, sem deixar os motivos grandes esconderem os pequenos.
   - **Acerto acionável:** o modelo acerta se o recontato é falha de resolução ou não? É a decisão que mais importa para o indicador.
   - **Matriz de confusão e lista de erros**, para entender onde a taxonomia ou o prompt precisam de ajuste.

**Tamanho da amostra de rotulagem:** 150 casos dão margem de erro de cerca de ±8 p.p. para a acurácia (95% de confiança, no pior caso). 300 casos reduzem para cerca de ±6 p.p.

**Comparações:**

- **LLM × regras de palavras-chave:** mede o ganho real do LLM sobre a abordagem tradicional.
- **Gemini × modelo local (Ollama):** mostra o equilíbrio entre acurácia, latência, custo e privacidade (um modelo local não envia dados de clientes para fora da empresa).

## 6. Da classificação à ação

- **Pareto de motivos** com dono e alavanca.
- **Taxa de recontato acionável**, que separa o que é falha de resolução do que é demanda legítima.
- **Mix de motivos por conta, produto e agente:** duas contas com a mesma taxa de recontato podem precisar de ações diferentes.
- **Hipóteses de causa raiz (opcional):** para os três motivos acionáveis mais frequentes, o LLM lê os resumos dos casos e propõe padrões, hipóteses pela lógica dos 5 Porquês e ações com dono e indicador. São **hipóteses para investigar com a operação**, não conclusões.

### Extrapolação e margem de erro

A participação de cada motivo é estimada em uma amostra. Para uma proporção *p* estimada em *n* casos, a margem de erro (95%) é 1,96 × √(p(1−p)/n). Com 1.500 casos classificados, fica em no máximo ±2,5 p.p. O relatório mostra a margem para a participação de recontatos acionáveis.

## 7. Limitações

- **Proxy de caso:** o Twitter não tem número de protocolo. "Mesmo cliente + mesma marca em 7 dias" é uma aproximação. Na base B2B, ou em qualquer operação com ID de caso, a regra pode usar o ID diretamente.
- **Canal público:** muitas marcas levam a conversa para mensagem privada, que não está na base. Parte das resoluções (e dos retornos) fica invisível.
- **Idioma e época:** a base real é em inglês, de 2017, B2C. O método é o mesmo para CX B2B em português, mas os números não são comparáveis.
- **Erro do modelo:** o LLM erra, principalmente entre motivos vizinhos (problema não resolvido × promessa não cumprida). Por isso a validação humana faz parte do método, não é opcional.
- **Dados sintéticos:** as amostras em `data/amostra/` são geradas por modelos de texto. Servem para testar o pipeline. As regras de palavras-chave foram escritas conhecendo esses modelos, então a acurácia delas na amostra não vale como evidência. A comparação que importa é na base real, com rótulos humanos.
