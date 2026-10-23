"""Gera as bases de AMOSTRA do projeto (dados 100% sintéticos e fictícios).

1. data/amostra/twcs_amostra.csv
   Mesmo formato (colunas e tipos) da base real "Customer Support on Twitter" do
   Kaggle, com marcas inventadas. Serve para testar o pipeline de ponta a ponta
   antes de baixar a base real de ~2,8 milhões de tweets.

2. data/amostra/b2b_beneficios_chamados.csv
   Chamados em português de uma empresa FICTÍCIA de benefícios corporativos
   ("Benefix"), atendendo RHs de empresas-cliente. Ilustra como o mesmo método
   se aplica a uma operação de CX B2B.

Cada base vem com um gabarito (*_gabarito.csv) com o motivo real de cada
recontato, para medir a acurácia do classificador.

Uso:
    python scripts/gerar_dados_amostra.py
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "data" / "amostra"
SEMENTE = 2026

# Distribuição dos motivos dos recontatos gerados (pesos relativos).
PESOS_MOTIVO = {
    "PROBLEMA_NAO_RESOLVIDO": 22,
    "PROMESSA_NAO_CUMPRIDA": 18,
    "INFORMACAO_INCOMPLETA": 14,
    "DIRECIONAMENTO_SEM_RESOLUCAO": 12,
    "DEMORA_OU_SEM_RETORNO": 10,
    "NOVO_ASSUNTO": 9,
    "DISCORDANCIA_DA_SOLUCAO": 7,
    "AGRADECIMENTO_OU_CONFIRMACAO": 6,
    "INDETERMINADO": 2,
}

# ---------------------------------------------------------------------------
# Base 1: formato Twitter (inglês)
# ---------------------------------------------------------------------------

MARCAS_TW = {
    "AcmeMobileHelp": [("my phone signal", "no signal since this morning"), ("my bill", "I was charged twice this month"), ("my data plan", "my data stopped working")],
    "NovaBankCares": [("my card", "my debit card got blocked at the store"), ("my transfer", "a transfer has been pending for 2 days"), ("the app", "I can't log into the app")],
    "SwiftShipSupport": [("my package", "my package shows delivered but I never got it"), ("my order", "my order is 4 days late"), ("the box", "my package arrived damaged")],
    "StreamBoxHelp": [("the app", "the app keeps crashing on my TV"), ("my subscription", "I was charged after cancelling"), ("my account", "my profile settings reset")],
    "PixelStoreCare": [("my refund", "I returned an item and need a refund"), ("my order", "I got the wrong item"), ("the voucher", "my voucher code is not accepted")],
}

PRIMEIRA_RESPOSTA_TW = {
    "PROBLEMA_NAO_RESOLVIDO": ["Sorry about that! Please restart your device and reinstall the app, that usually fixes it.", "Thanks for reaching out. Try clearing the cache and logging in again, it should be sorted."],
    "INFORMACAO_INCOMPLETA": ["Please update your settings and verify your account, that should do it.", "You can fix this in your account preferences. Let us know!"],
    "PROMESSA_NAO_CUMPRIDA": ["We've processed it on our side, it should be back within 3 business days.", "We've escalated this and someone will call you back tomorrow."],
    "DIRECIONAMENTO_SEM_RESOLUCAO": ["Please call our support line so the team can help you directly.", "Please check this help article: https://t.co/hlp123 It has all the steps."],
    "DEMORA_OU_SEM_RETORNO": ["We're looking into this and will get back to you shortly.", "Thanks, we've passed this to the team. We'll reply here soon."],
    "DISCORDANCIA_DA_SOLUCAO": ["Per our policy, a replacement fee applies in this case.", "Unfortunately this is outside the refund window, so we can't refund it."],
    "NOVO_ASSUNTO": ["Done! It's fixed on our end. Anything else?", "All sorted, thanks for your patience!"],
    "AGRADECIMENTO_OU_CONFIRMACAO": ["We've fixed it on our side, please check now.", "It should be working now, let us know!"],
    "INDETERMINADO": ["Thanks for reaching out, we're checking.", "Happy to help, can you tell us more?"],
}

RECONTATO_TW = {
    "PROBLEMA_NAO_RESOLVIDO": [
        "I did everything you suggested and {item} is still not working",
        "restarted like you said, same issue with {item}. nothing changed",
        "your fix didn't work, {item} is broken again",
        "hey, tried it all again this morning and {item} still acts up exactly like before",
    ],
    "INFORMACAO_INCOMPLETA": [
        "you told me to update the settings but which option exactly? I can't find it",
        "sorry, what do you mean by verify the account? where do I do that",
        "I opened the app but there's no menu like you described. what's the next step?",
        "ok but after I go to preferences there are like 10 options for {item}, which one?",
    ],
    "PROMESSA_NAO_CUMPRIDA": [
        "you said it would be back in 3 business days. it's been 6 and nothing",
        "I was told someone would call me back yesterday. no call at all",
        "still waiting for the refund you promised for {item}",
        "it's thursday and the money from monday's mistake is still not in my account",
    ],
    "DIRECIONAMENTO_SEM_RESOLUCAO": [
        "I called the number you gave me and waited 40 minutes, nobody picked up",
        "the link you sent just goes to the FAQ, it doesn't help with {item}",
        "phone support sent me back to twitter. so who actually fixes {item}?",
        "that article doesn't cover my case at all, I'm back to square one",
    ],
    "DEMORA_OU_SEM_RETORNO": [
        "any update on {item}? nobody replied since monday",
        "hello?? been waiting two days for an answer",
        "still no answer about {item}",
        "it has been 3 days, is anyone there?",
    ],
    "DISCORDANCIA_DA_SOLUCAO": [
        "so I have to pay the fee even though it was your error? this is unacceptable",
        "that policy makes no sense. I want to speak to a manager",
        "your answer is ridiculous, I'm not paying for a replacement",
        "I've been a customer for 8 years and that's the best you can do? not ok",
    ],
    "NOVO_ASSUNTO": [
        "different question: how do I add a second user to my plan?",
        "hi, can you tell me your opening hours for the holidays?",
        "quick one, do you ship to Canada?",
        "hey, is there a student discount?",
    ],
    "AGRADECIMENTO_OU_CONFIRMACAO": [
        "just wanted to say thanks, it worked!",
        "all good now, thank you so much for the help",
        "problem solved, appreciate it",
        "checked this morning and {item} is perfect now. cheers!",
    ],
    "INDETERMINADO": ["...", "https://t.co/xYz9a1", "??"],
}

RESPOSTA_RECONTATO_TW = [
    "Sorry to hear that. Please send us a DM with your account details and we'll take a look.",
    "We're sorry for the trouble. Can you share more details so we can check?",
    "Thanks for the update, we're on it.",
]

ASSINATURAS = ["^AB", "^JM", "^KT", "^LS", "^RP", "-DW", "-MC"]


@dataclass
class Tweet:
    tweet_id: int
    author_id: str
    inbound: bool
    created_at: datetime
    text: str
    in_response_to: int | None = None
    respostas: list[int] = field(default_factory=list)


def _fmt_data_twitter(d: datetime) -> str:
    return d.strftime("%a %b %d %H:%M:%S +0000 %Y")


def gerar_twitter(rng: random.Random) -> tuple[list[Tweet], list[tuple[str, str]]]:
    tweets: list[Tweet] = []
    gabarito: list[tuple[str, str]] = []
    proximo_id = [1000]

    def novo(author, inbound, quando, texto, pai: Tweet | None = None) -> Tweet:
        proximo_id[0] += rng.randint(1, 7)
        t = Tweet(proximo_id[0], author, inbound, quando, texto, pai.tweet_id if pai else None)
        if pai:
            pai.respostas.append(t.tweet_id)
        tweets.append(t)
        return t

    def conversa(cliente, marca, inicio, texto_cliente, resposta_marca, fecha_cliente=None) -> tuple[Tweet, datetime]:
        raiz = novo(cliente, True, inicio, f"@{marca} {texto_cliente}")
        if resposta_marca is None:
            return raiz, inicio
        quando = inicio + timedelta(minutes=rng.randint(3, 240))
        r1 = novo(marca, False, quando, f"@{cliente} {resposta_marca} {rng.choice(ASSINATURAS)}", raiz)
        fim = quando
        if fecha_cliente:
            fim = quando + timedelta(minutes=rng.randint(2, 90))
            novo(cliente, True, fim, f"@{marca} {fecha_cliente}", r1)
        return raiz, fim

    motivos = list(PESOS_MOTIVO)
    pesos = list(PESOS_MOTIVO.values())
    base = datetime(2017, 10, 2, 8, 0)
    id_cliente = 115000

    for marca, temas in MARCAS_TW.items():
        for _ in range(70):
            id_cliente += rng.randint(1, 40)
            cliente = str(id_cliente)
            item, problema = rng.choice(temas)
            inicio = base + timedelta(days=rng.uniform(0, 45), minutes=rng.randint(0, 600))

            # 5% das conversas nunca recebem resposta da marca
            if rng.random() < 0.05:
                conversa(cliente, marca, inicio, problema, None)
                continue

            motivo = rng.choices(motivos, pesos)[0]
            _, fim = conversa(
                cliente, marca, inicio, problema, rng.choice(PRIMEIRA_RESPOSTA_TW[motivo]),
                fecha_cliente=rng.choice([None, "ok thanks", "will try"]),
            )

            sorteio = rng.random()
            if sorteio < 0.60:
                # recontato dentro da janela de 7 dias
                volta = fim + timedelta(hours=rng.uniform(2, 24 * 6.5))
                texto = rng.choice(RECONTATO_TW[motivo]).format(item=item)
                raiz, novo_fim = conversa(cliente, marca, volta, texto, rng.choice(RESPOSTA_RECONTATO_TW))
                gabarito.append((str(raiz.tweet_id), motivo))

                # alguns clientes voltam uma terceira vez
                if motivo not in ("AGRADECIMENTO_OU_CONFIRMACAO", "NOVO_ASSUNTO") and rng.random() < 0.25:
                    motivo3 = rng.choice(["DEMORA_OU_SEM_RETORNO", "DISCORDANCIA_DA_SOLUCAO", "PROBLEMA_NAO_RESOLVIDO"])
                    volta3 = novo_fim + timedelta(hours=rng.uniform(3, 72))
                    raiz3, _ = conversa(cliente, marca, volta3, rng.choice(RECONTATO_TW[motivo3]).format(item=item), rng.choice(RESPOSTA_RECONTATO_TW))
                    gabarito.append((str(raiz3.tweet_id), motivo3))
            elif sorteio < 0.75:
                # volta depois da janela: NÃO é recontato
                volta = fim + timedelta(days=rng.uniform(9, 20))
                conversa(cliente, marca, volta, rng.choice(RECONTATO_TW["NOVO_ASSUNTO"]), rng.choice(RESPOSTA_RECONTATO_TW))

    tweets.sort(key=lambda t: t.tweet_id)
    return tweets, gabarito


def salvar_twitter(tweets: list[Tweet], gabarito: list[tuple[str, str]]) -> None:
    with open(PASTA / "twcs_amostra.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tweet_id", "author_id", "inbound", "created_at", "text", "response_tweet_id", "in_response_to_tweet_id"])
        for t in tweets:
            w.writerow([
                t.tweet_id, t.author_id, str(t.inbound), _fmt_data_twitter(t.created_at), t.text,
                ",".join(map(str, t.respostas)), f"{float(t.in_response_to):.1f}" if t.in_response_to else "",
            ])
    with open(PASTA / "twcs_amostra_gabarito.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["recontato_id", "motivo_real"])
        w.writerows(gabarito)


# ---------------------------------------------------------------------------
# Base 2: CX B2B de benefícios (português) - empresa fictícia "Benefix"
# ---------------------------------------------------------------------------

EMPRESAS = [
    "Construtora Horizonte", "Rede Farma Vida", "Agro Campos Gerais", "Logística Rota Sul", "Clínica Bem Estar",
    "Escola Novo Saber", "Metalúrgica Aço Forte", "Supermercados Boa Compra", "TechNova Sistemas", "Hotel Mar Azul",
    "Transportadora Veloz", "Indústria Têxtil Fios", "Contabilidade Exata", "Padaria Pão Dourado", "Grupo Saúde Integral",
    "Editora Página Viva", "Laboratório BioTeste", "Restaurante Sabor Caseiro", "Energia Solar Brasil", "Academia Corpo Ativo",
    "Imobiliária Lar Certo", "Gráfica Cor Total", "Consultoria Prisma", "Auto Peças Motor", "Seguradora Confiança",
    "Moda Estilo Urbano", "Distribuidora Água Pura", "Farmácia Popular Vida", "Startup Pagaí", "Clínica Odonto Sorriso",
]

PRODUTOS = {
    "Cartão Multibenefícios": [
        ("a recarga do mês", "A recarga do mês não caiu para parte dos colaboradores."),
        ("o cartão do colaborador", "Um colaborador está com o cartão bloqueado e não consegue usar no mercado."),
        ("a inclusão no pedido", "Preciso incluir 12 novos colaboradores no pedido deste mês e o portal dá erro."),
        ("o saldo de alimentação", "O saldo de refeição foi para a carteira de alimentação de alguns colaboradores."),
    ],
    "Despesas Corporativas": [
        ("o reembolso", "Um reembolso de despesa foi recusado sem motivo aparente."),
        ("o cartão corporativo", "O cartão corporativo do nosso diretor foi recusado no hotel durante a viagem."),
        ("o relatório de despesas", "O relatório de despesas não exporta para o nosso ERP."),
        ("o limite do cartão", "Preciso aumentar o limite do cartão corporativo de um gestor."),
    ],
    "Premiações": [
        ("o crédito da premiação", "O crédito da campanha de premiação não apareceu para os vendedores."),
        ("a planilha de premiação", "Dá erro ao importar a planilha de premiação no portal."),
        ("a nota fiscal da premiação", "Não recebemos a nota fiscal do pedido de premiação."),
    ],
}

PRIMEIRA_RESPOSTA_B2B = {
    "PROBLEMA_NAO_RESOLVIDO": ["Reprocessei o pedido aqui. Peço que aguarde algumas horas e verifique novamente.", "Desbloqueei pelo sistema. Peça para o colaborador tentar de novo."],
    "INFORMACAO_INCOMPLETA": ["É só ajustar no portal, na área de configurações.", "Basta reenviar a planilha no layout correto."],
    "PROMESSA_NAO_CUMPRIDA": ["Abri a solicitação para o financeiro. O crédito cai em até 2 dias úteis.", "Vou pedir para o time responsável te ligar amanhã com a resposta."],
    "DIRECIONAMENTO_SEM_RESOLUCAO": ["Esse assunto é tratado pelo time de cadastro. Por favor, envie um e-mail para cadastro@benefix.exemplo.", "Para esse caso, ligue na nossa central de atendimento."],
    "DEMORA_OU_SEM_RETORNO": ["Encaminhei internamente e retorno assim que tiver novidades.", "Vou verificar com a área e te respondo por aqui."],
    "DISCORDANCIA_DA_SOLUCAO": ["Pela política do contrato, a reemissão do cartão tem taxa.", "Infelizmente o prazo para contestação já passou, então não conseguimos estornar."],
    "NOVO_ASSUNTO": ["Pronto, ajustado. O problema foi resolvido.", "Feito! Já está normalizado."],
    "AGRADECIMENTO_OU_CONFIRMACAO": ["Corrigi aqui. Pode verificar, por favor?", "Ajuste realizado, deve estar funcionando agora."],
    "INDETERMINADO": ["Estou verificando, um momento.", "Pode me passar mais detalhes?"],
}

RECONTATO_B2B = {
    "PROBLEMA_NAO_RESOLVIDO": [
        "Oi, fiz o procedimento que vocês passaram, mas {item} continua com o mesmo problema.",
        "Voltando aqui: reprocessamos como orientado e o erro é o mesmo.",
        "Bom dia. Os colaboradores seguem sem conseguir usar, igual ontem.",
        "O problema com {item} voltou a acontecer hoje cedo.",
    ],
    "INFORMACAO_INCOMPLETA": [
        "Vocês falaram para ajustar no portal, mas não encontrei essa opção. Onde fica?",
        "Não entendi a orientação sobre o layout da planilha. Qual coluna devo preencher?",
        "Recebi a resposta, mas faltou explicar o passo de aprovação do gestor. Depois de enviar, o que acontece?",
        "Qual é exatamente o layout correto? Não veio nenhum modelo junto.",
    ],
    "PROMESSA_NAO_CUMPRIDA": [
        "Disseram que o crédito cairia em até 2 dias úteis e até hoje nada.",
        "Fiquei de receber uma ligação do time responsável ontem e ninguém ligou.",
        "Já é quinta-feira e o estorno combinado na segunda não apareceu no extrato.",
        "Me garantiram que {item} estaria regularizado ontem. Os colaboradores continuam cobrando.",
    ],
    "DIRECIONAMENTO_SEM_RESOLUCAO": [
        "Pediram para eu mandar e-mail para o cadastro, mandei e ninguém respondeu por lá.",
        "Me transferiram para outro setor e a ligação caiu.",
        "Liguei na central que indicaram e me mandaram voltar para o chat.",
        "O e-mail que vocês passaram voltou com erro de entrega.",
    ],
    "DEMORA_OU_SEM_RETORNO": [
        "Estou aguardando um retorno desde segunda, alguma novidade?",
        "Ninguém me respondeu sobre {item}.",
        "Olá? Mandei mensagem há 3 dias.",
        "Preciso de uma posição hoje, o fechamento da folha é amanhã.",
    ],
    "DISCORDANCIA_DA_SOLUCAO": [
        "Não aceito pagar a taxa de reemissão, o erro foi de vocês.",
        "Quero falar com um supervisor, essa regra não faz sentido para nossa empresa.",
        "Somos clientes há 4 anos e essa resposta não é razoável. Precisamos de uma exceção.",
        "Se for assim vamos rever o contrato com vocês.",
    ],
    "NOVO_ASSUNTO": [
        "Aproveitando, outra dúvida: como incluo um novo centro de custo?",
        "Bom dia! Agora é sobre a nota fiscal de setembro, onde baixo?",
        "Oi, preciso da segunda via do boleto do pedido de outubro.",
        "Vocês têm treinamento do portal para novos usuários do RH?",
    ],
    "AGRADECIMENTO_OU_CONFIRMACAO": [
        "Obrigada, deu certo! Todos receberam.",
        "Só para confirmar que funcionou, obrigado pelo suporte.",
        "Conferimos aqui e {item} está ok agora. Valeu!",
    ],
    "INDETERMINADO": ["Oi", "?", "Segue anexo."],
}

RESPOSTA_RECONTATO_B2B = [
    "Entendo, peço desculpas pelo transtorno. Vou verificar agora mesmo.",
    "Obrigado pelo retorno. Vou analisar o caso e já te atualizo.",
    "Sinto muito por isso. Vou escalar para a área responsável.",
]

# Agentes com perfil diferente, para que a análise por agente tenha o que mostrar.
AGENTES = [f"AG-{i:02d}" for i in range(1, 13)]
AGENTES_COM_RESPOSTA_GENERICA = {"AG-03", "AG-07"}


def gerar_b2b(rng: random.Random) -> tuple[list[dict], list[tuple[str, str]]]:
    chamados: list[dict] = []
    gabarito: list[tuple[str, str]] = []
    contador = [0]
    base = datetime(2026, 4, 1, 8, 0)
    canais = ["chat", "chat", "chat", "e-mail", "telefone"]

    def chamado(solicitante, empresa, produto, agente, abertura, texto_cliente, resposta) -> datetime:
        contador[0] += 1
        duracao = timedelta(minutes=rng.randint(6, 45)) if rng.random() < 0.8 else timedelta(hours=rng.uniform(2, 20))
        fechamento = abertura + duracao
        chamados.append({
            "ticket_id": f"TCK-{contador[0]:05d}",
            "solicitante_id": solicitante,
            "empresa_cliente": empresa,
            "produto": produto,
            "canal": rng.choice(canais),
            "agente_id": agente,
            "aberto_em": abertura.strftime("%Y-%m-%d %H:%M:%S"),
            "fechado_em": fechamento.strftime("%Y-%m-%d %H:%M:%S"),
            "transcricao": f"Cliente: {texto_cliente}\nAgente: {resposta}",
        })
        return fechamento

    motivos = list(PESOS_MOTIVO)
    numero_solicitante = 0
    for empresa in EMPRESAS:
        for _ in range(rng.randint(2, 4)):
            numero_solicitante += 1
            solicitante = f"SOL-{numero_solicitante:04d}"
            # Cada solicitante tem vários casos independentes, espaçados por mais
            # que a janela de recontato, para que só os retornos gerados de
            # propósito virem recontato (e tenham gabarito).
            cursor = base + timedelta(days=rng.uniform(0, 8))
            for _ in range(rng.randint(3, 6)):
                produto = rng.choices(list(PRODUTOS), [5, 3, 2])[0]
                item, problema = rng.choice(PRODUTOS[produto])
                agente = rng.choice(AGENTES)
                abertura = cursor + timedelta(days=rng.uniform(8, 16), minutes=rng.randint(0, 540))

                pesos = dict(PESOS_MOTIVO)
                if agente in AGENTES_COM_RESPOSTA_GENERICA:
                    pesos["INFORMACAO_INCOMPLETA"] *= 3
                    pesos["PROBLEMA_NAO_RESOLVIDO"] *= 2
                if produto == "Premiações":
                    pesos["PROMESSA_NAO_CUMPRIDA"] *= 3
                motivo = rng.choices(motivos, list(pesos.values()))[0]

                fim = chamado(solicitante, empresa, produto, agente, abertura, problema, rng.choice(PRIMEIRA_RESPOSTA_B2B[motivo]))

                chance_recontato = 0.75 if agente in AGENTES_COM_RESPOSTA_GENERICA else 0.35
                sorteio = rng.random()
                if sorteio < chance_recontato:
                    volta = fim + timedelta(hours=rng.uniform(1, 24 * 6.5))
                    texto = rng.choice(RECONTATO_B2B[motivo]).format(item=item)
                    fim = chamado(solicitante, empresa, produto, rng.choice(AGENTES), volta, texto, rng.choice(RESPOSTA_RECONTATO_B2B))
                    gabarito.append((chamados[-1]["ticket_id"], motivo))
                elif sorteio < chance_recontato + 0.1:
                    volta = fim + timedelta(days=rng.uniform(10, 25))
                    fim = chamado(solicitante, empresa, produto, rng.choice(AGENTES), volta, rng.choice(RECONTATO_B2B["NOVO_ASSUNTO"]), rng.choice(RESPOSTA_RECONTATO_B2B))
                cursor = fim

    chamados.sort(key=lambda c: c["aberto_em"])
    return chamados, gabarito


def salvar_b2b(chamados: list[dict], gabarito: list[tuple[str, str]]) -> None:
    with open(PASTA / "b2b_beneficios_chamados.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(chamados[0]))
        w.writeheader()
        w.writerows(chamados)
    with open(PASTA / "b2b_beneficios_gabarito.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["recontato_id", "motivo_real"])
        w.writerows(gabarito)


def main() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEMENTE)
    tweets, gab_tw = gerar_twitter(rng)
    salvar_twitter(tweets, gab_tw)
    chamados, gab_b2b = gerar_b2b(rng)
    salvar_b2b(chamados, gab_b2b)
    print(f"Twitter (amostra): {len(tweets)} tweets, {len(gab_tw)} recontatos rotulados")
    print(f"B2B benefícios:    {len(chamados)} chamados, {len(gab_b2b)} recontatos rotulados")


if __name__ == "__main__":
    main()
