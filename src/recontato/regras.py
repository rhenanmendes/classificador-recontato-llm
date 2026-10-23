"""Baseline sem LLM: classificação por palavras-chave.

É o jeito "tradicional" de categorizar motivos de contato (regras e tabulação).
Serve para duas coisas:
  1. Comparar: quanto o LLM acrescenta em acurácia sobre regras simples?
  2. Rodar o pipeline inteiro sem chave de API (demonstração e testes).
"""

from __future__ import annotations

import re
import time
import unicodedata

from .provedores import Resposta

# Ordem importa: o primeiro grupo que casar define o motivo.
REGRAS: list[tuple[str, list[str]]] = [
    ("PROMESSA_NAO_CUMPRIDA", [
        r"prometeu", r"prometeram", r"disseram que", r"disse que (ia|iria)", r"prazo",
        r"ate hoje", r"nao caiu", r"you said", r"promised", r"supposed to", r"still waiting for",
        r"was told", r"business days", r"dias uteis", r"ninguem ligou", r"combinad", r"garantiram",
    ]),
    ("DIRECIONAMENTO_SEM_RESOLUCAO", [
        r"transferi", r"mandaram (eu )?ligar", r"outro canal", r"ninguem atende", r"o link",
        r"the link", r"called the number", r"dm'?d", r"sent me to", r"redirect", r"no telefone",
        r"pela central", r"e-?mail que voces passaram", r"central que indicaram", r"support line",
    ]),
    ("DEMORA_OU_SEM_RETORNO", [
        r"ninguem (me )?respond", r"sem resposta", r"sem retorno", r"aguardando", r"any update",
        r"no reply", r"no response", r"hello\?", r"ola\?", r"cade", r"still no answer", r"ignor",
        r"alguma novidade", r"preciso de uma posicao", r"anyone there",
    ]),
    ("DISCORDANCIA_DA_SOLUCAO", [
        r"absurdo", r"supervisor", r"gerente", r"nao aceito", r"unacceptable", r"ridiculous",
        r"escalat", r"manager", r"inaceitavel", r"reclamacao formal", r"procon", r"cancelar o contrato",
    ]),
    ("AGRADECIMENTO_OU_CONFIRMACAO", [
        r"^(muito )?obrigad", r"deu certo", r"resolvido", r"thanks?,? (it|that) work", r"all good",
        r"thank you so much", r"funcionou", r"problem solved",
    ]),
    ("NOVO_ASSUNTO", [
        r"outra duvida", r"outro assunto", r"aproveitando", r"another question", r"different issue",
        r"unrelated", r"tambem queria", r"new question",
    ]),
    ("INFORMACAO_INCOMPLETA", [
        r"nao entendi", r"como faco", r"onde (fica|encontro)", r"what do you mean", r"how do i",
        r"where (do|can) i", r"nao ficou claro", r"which (option|setting)", r"qual opcao",
        r"nao encontrei", r"faltou explicar", r"qual (e|coluna)", r"next step",
    ]),
    ("PROBLEMA_NAO_RESOLVIDO", [
        r"ainda nao", r"continua", r"mesmo erro", r"mesmo problema", r"still (not|doesn|isn|broken)",
        r"same (issue|problem|error)", r"again", r"de novo", r"didn'?t (work|fix)", r"nao funcionou",
        r"not working", r"voltou a acontecer", r"e o mesmo", r"seguem sem", r"igual ontem",
    ]),
]

_COMPILADAS = [(motivo, [re.compile(p) for p in padroes]) for motivo, padroes in REGRAS]


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def falas_do_cliente(transcricao: str) -> str:
    linhas = [l.split(":", 1)[1].strip() for l in (transcricao or "").splitlines() if l.startswith("Cliente:")]
    return "\n".join(linhas) if linhas else (transcricao or "")


def classificar_por_regras(transcricao_atual: str) -> tuple[str, str]:
    """Retorna (motivo, padrão que casou)."""
    texto = _normalizar(falas_do_cliente(transcricao_atual))
    for linha_inicial in (texto.split("\n", 1)[0], texto):
        for motivo, padroes in _COMPILADAS:
            for padrao in padroes:
                if padrao.search(linha_inicial):
                    return motivo, padrao.pattern
    return "INDETERMINADO", ""


class ProvedorRegras:
    """Mesma interface dos provedores de LLM, mas recebe o registro, não um prompt."""

    nome = "regras"
    modelo = "palavras-chave-v1"

    def classificar_registro(self, registro: dict) -> Resposta:
        inicio = time.monotonic()
        motivo, padrao = classificar_por_regras(registro.get("transcricao_atual", ""))
        texto = (
            '{"motivo": "%s", "relacionado_ao_anterior": %s, "confianca": %s, '
            '"evidencia": "%s", "resumo": "Classificado por regra de palavra-chave."}'
            % (
                motivo,
                "false" if motivo == "NOVO_ASSUNTO" else "true",
                "0.5" if padrao else "0.0",
                padrao.replace("\\", "").replace('"', "'"),
            )
        )
        return Resposta(texto=texto, tokens_entrada=0, tokens_saida=0, latencia_s=round(time.monotonic() - inicio, 4))
