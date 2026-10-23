"""Clientes de LLM: Gemini (API gratuita) e Ollama (modelo local).

Os dois expõem a mesma interface, `gerar(prompt, esquema) -> Resposta`, então o
resto do pipeline não sabe (nem precisa saber) qual modelo está por trás.
Trocar de provedor é uma linha no config.yaml ou um parâmetro na linha de comando.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests


class ErroDeProvedor(RuntimeError):
    """Erro que não adianta tentar de novo (chave inválida, modelo inexistente...)."""


class LimiteDeCotaAtingido(RuntimeError):
    """A cota do plano gratuito acabou. O progresso fica salvo; basta rodar de novo depois."""


@dataclass
class Resposta:
    texto: str
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    latencia_s: float | None = None


class LimitadorDeTaxa:
    """Garante um intervalo mínimo entre chamadas (ex.: 5 por minuto = 1 a cada 12 s)."""

    def __init__(self, requisicoes_por_minuto: float | None):
        self.intervalo = 60.0 / requisicoes_por_minuto if requisicoes_por_minuto else 0.0
        self._ultima = 0.0

    def aguardar(self) -> None:
        if not self.intervalo:
            return
        espera = self._ultima + self.intervalo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        self._ultima = time.monotonic()


class Provedor:
    nome = "base"
    modelo = ""

    def gerar(self, prompt: str, esquema: dict[str, Any] | None = None) -> Resposta:
        raise NotImplementedError


def _esquema_para_gemini(esquema: dict[str, Any]) -> dict[str, Any]:
    """O Gemini usa um subconjunto do OpenAPI, com os tipos em maiúsculas."""
    convertido: dict[str, Any] = {}
    for chave, valor in esquema.items():
        if chave == "type" and isinstance(valor, str):
            convertido[chave] = valor.upper()
        elif chave == "additionalProperties":
            continue
        elif isinstance(valor, dict):
            convertido[chave] = (
                {k: _esquema_para_gemini(v) for k, v in valor.items()}
                if chave == "properties"
                else _esquema_para_gemini(valor)
            )
        else:
            convertido[chave] = valor
    return convertido


class ProvedorGemini(Provedor):
    nome = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"

    def __init__(
        self,
        modelo: str,
        chave: str | None = None,
        requisicoes_por_minuto: float | None = 5,
        max_tentativas: int = 5,
        timeout_segundos: int = 120,
        sessao: requests.Session | None = None,
        dormir=time.sleep,
    ):
        self.modelo = modelo
        self.chave = chave or os.getenv("GEMINI_API_KEY")
        if not self.chave or self.chave == "cole_sua_chave_aqui":
            raise ErroDeProvedor(
                "GEMINI_API_KEY não encontrada. Copie .env.example para .env e cole sua chave "
                "(crie em https://aistudio.google.com/apikey)."
            )
        self.limitador = LimitadorDeTaxa(requisicoes_por_minuto)
        self.max_tentativas = max_tentativas
        self.timeout = timeout_segundos
        self.sessao = sessao or requests.Session()
        self._dormir = dormir

    def gerar(self, prompt: str, esquema: dict[str, Any] | None = None) -> Resposta:
        config: dict[str, Any] = {"temperature": 0, "responseMimeType": "application/json"}
        if esquema:
            config["responseSchema"] = _esquema_para_gemini(esquema)
        corpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}

        for tentativa in range(1, self.max_tentativas + 1):
            self.limitador.aguardar()
            inicio = time.monotonic()
            try:
                r = self.sessao.post(
                    self.URL.format(modelo=self.modelo),
                    headers={"x-goog-api-key": self.chave, "Content-Type": "application/json"},
                    json=corpo,
                    timeout=self.timeout,
                )
            except requests.RequestException as erro:
                if tentativa == self.max_tentativas:
                    raise ErroDeProvedor(f"Falha de conexão com o Gemini: {erro}") from erro
                self._dormir(min(2**tentativa, 60))
                continue

            if r.status_code == 200:
                return self._ler_resposta(r.json(), time.monotonic() - inicio)

            mensagem = _mensagem_de_erro(r)
            if r.status_code == 429:
                if _cota_diaria(r):
                    raise LimiteDeCotaAtingido(f"Cota diária do Gemini esgotada: {mensagem}")
                if tentativa == self.max_tentativas:
                    raise LimiteDeCotaAtingido(f"Limite de requisições do Gemini: {mensagem}")
                self._dormir(_atraso_sugerido(r) or min(10 * 2**tentativa, 120))
                continue
            if r.status_code >= 500:
                if tentativa == self.max_tentativas:
                    raise ErroDeProvedor(f"Gemini indisponível ({r.status_code}): {mensagem}")
                self._dormir(min(2**tentativa, 60))
                continue
            if r.status_code == 404:
                raise ErroDeProvedor(
                    f"Modelo '{self.modelo}' não encontrado. Confira o nome no Google AI Studio "
                    f"e ajuste llm.gemini.modelo no config.yaml. Detalhe: {mensagem}"
                )
            raise ErroDeProvedor(f"Erro {r.status_code} do Gemini: {mensagem}")

        raise ErroDeProvedor("Número máximo de tentativas atingido.")  # pragma: no cover

    @staticmethod
    def _ler_resposta(dados: dict[str, Any], latencia: float) -> Resposta:
        uso = dados.get("usageMetadata", {})
        try:
            partes = dados["candidates"][0]["content"]["parts"]
            texto = "".join(p.get("text", "") for p in partes)
        except (KeyError, IndexError, TypeError):
            motivo = (dados.get("candidates") or [{}])[0].get("finishReason") or dados.get("promptFeedback")
            texto = ""
            if motivo:
                texto = f'{{"erro": "resposta vazia do modelo: {motivo}"}}'
        return Resposta(
            texto=texto,
            tokens_entrada=uso.get("promptTokenCount"),
            tokens_saida=(uso.get("candidatesTokenCount") or 0) + (uso.get("thoughtsTokenCount") or 0),
            latencia_s=round(latencia, 3),
        )


def _mensagem_de_erro(r: requests.Response) -> str:
    try:
        return r.json().get("error", {}).get("message", r.text)[:500]
    except ValueError:
        return r.text[:500]


def _cota_diaria(r: requests.Response) -> bool:
    texto = r.text
    return "PerDay" in texto or "per day" in texto.lower()


def _atraso_sugerido(r: requests.Response) -> float | None:
    """Lê o tempo de espera que o Gemini sugere em erros 429 (campo RetryInfo)."""
    try:
        detalhes = r.json().get("error", {}).get("details", [])
    except ValueError:
        return None
    for detalhe in detalhes:
        atraso = detalhe.get("retryDelay")
        if atraso:
            achado = re.match(r"([\d.]+)s", atraso)
            if achado:
                return float(achado.group(1)) + 1
    return None


class ProvedorOllama(Provedor):
    nome = "ollama"

    def __init__(
        self,
        modelo: str,
        url: str = "http://localhost:11434",
        think: bool | None = False,
        timeout_segundos: int = 180,
        sessao: requests.Session | None = None,
    ):
        self.modelo = modelo
        self.url = url.rstrip("/")
        self.think = think
        self.timeout = timeout_segundos
        self.sessao = sessao or requests.Session()

    def gerar(self, prompt: str, esquema: dict[str, Any] | None = None) -> Resposta:
        corpo: dict[str, Any] = {
            "model": self.modelo,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": esquema or "json",
            "options": {"temperature": 0},
        }
        if self.think is not None:
            corpo["think"] = self.think

        inicio = time.monotonic()
        try:
            r = self.sessao.post(f"{self.url}/api/chat", json=corpo, timeout=self.timeout)
            if r.status_code == 400 and "think" in r.text.lower() and "think" in corpo:
                # Modelo sem suporte ao parâmetro "think": tenta de novo sem ele.
                corpo.pop("think")
                self.think = None
                r = self.sessao.post(f"{self.url}/api/chat", json=corpo, timeout=self.timeout)
        except requests.ConnectionError as erro:
            raise ErroDeProvedor(
                f"Não foi possível conectar ao Ollama em {self.url}. Ele está aberto? "
                f"Instale em https://ollama.com e rode: ollama pull {self.modelo}"
            ) from erro

        if r.status_code == 404:
            raise ErroDeProvedor(f"Modelo '{self.modelo}' não baixado. Rode: ollama pull {self.modelo}")
        if r.status_code != 200:
            raise ErroDeProvedor(f"Erro {r.status_code} do Ollama: {r.text[:500]}")

        dados = r.json()
        return Resposta(
            texto=dados.get("message", {}).get("content", ""),
            tokens_entrada=dados.get("prompt_eval_count"),
            tokens_saida=dados.get("eval_count"),
            latencia_s=round(time.monotonic() - inicio, 3),
        )


def criar_provedor(nome: str, config_llm: dict[str, Any]) -> Provedor:
    if nome == "gemini":
        c = config_llm.get("gemini", {})
        return ProvedorGemini(
            modelo=c.get("modelo", "gemini-3.5-flash-lite"),
            requisicoes_por_minuto=c.get("requisicoes_por_minuto", 5),
            max_tentativas=c.get("max_tentativas", 5),
        )
    if nome == "ollama":
        c = config_llm.get("ollama", {})
        return ProvedorOllama(
            modelo=c.get("modelo", "qwen3:4b"),
            url=c.get("url", "http://localhost:11434"),
            think=c.get("think", False),
            timeout_segundos=c.get("timeout_segundos", 180),
        )
    raise ValueError(f"Provedor de LLM desconhecido: {nome}")
