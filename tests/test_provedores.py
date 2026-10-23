"""Testa os clientes de LLM sem acessar a internet (respostas HTTP simuladas)."""

import copy
import json

import pytest
import requests

from recontato.provedores import (
    ErroDeProvedor,
    LimiteDeCotaAtingido,
    ProvedorGemini,
    ProvedorOllama,
    _esquema_para_gemini,
)


class RespostaHTTP:
    def __init__(self, status, dados):
        self.status_code = status
        self._dados = dados
        self.text = json.dumps(dados)

    def json(self):
        return self._dados


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.enviados = []

    def post(self, url, **kwargs):
        self.enviados.append((url, copy.deepcopy(kwargs)))
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


OK_GEMINI = RespostaHTTP(200, {
    "candidates": [{"content": {"parts": [{"text": '{"motivo": "NOVO_ASSUNTO"}'}]}}],
    "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 60},
})


def _gemini(respostas, **kw):
    sessao = SessaoFalsa(respostas)
    esperas = []
    p = ProvedorGemini("modelo-x", chave="abc", requisicoes_por_minuto=None, sessao=sessao, dormir=esperas.append, **kw)
    return p, sessao, esperas


def test_gemini_sucesso_e_formato_da_requisicao():
    p, sessao, _ = _gemini([OK_GEMINI])
    r = p.gerar("prompt", {"type": "object", "properties": {"motivo": {"type": "string", "enum": ["A"]}}})
    assert r.texto == '{"motivo": "NOVO_ASSUNTO"}'
    assert (r.tokens_entrada, r.tokens_saida) == (800, 60)
    url, kwargs = sessao.enviados[0]
    assert url.endswith("/models/modelo-x:generateContent")
    assert kwargs["headers"]["x-goog-api-key"] == "abc"
    config = kwargs["json"]["generationConfig"]
    assert config["temperature"] == 0 and config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["properties"]["motivo"]["type"] == "STRING"


def test_gemini_429_espera_e_tenta_de_novo():
    limite = RespostaHTTP(429, {"error": {"message": "rate", "details": [{"retryDelay": "7s"}]}})
    p, _, esperas = _gemini([limite, OK_GEMINI])
    assert p.gerar("x").tokens_entrada == 800
    assert esperas == [8.0]  # 7 s sugeridos + 1 de folga


def test_gemini_cota_diaria_para_imediatamente():
    diaria = RespostaHTTP(429, {"error": {"message": "quota", "details": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}})
    p, sessao, _ = _gemini([diaria, OK_GEMINI])
    with pytest.raises(LimiteDeCotaAtingido):
        p.gerar("x")
    assert len(sessao.enviados) == 1


def test_gemini_modelo_inexistente():
    p, _, _ = _gemini([RespostaHTTP(404, {"error": {"message": "not found"}})])
    with pytest.raises(ErroDeProvedor, match="não encontrado"):
        p.gerar("x")


def test_gemini_sem_chave(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ErroDeProvedor, match="GEMINI_API_KEY"):
        ProvedorGemini("modelo-x")


def test_esquema_convertido_para_gemini():
    esquema = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "array", "items": {"type": "string"}}}}
    convertido = _esquema_para_gemini(esquema)
    assert convertido == {"type": "OBJECT", "properties": {"a": {"type": "ARRAY", "items": {"type": "STRING"}}}}


def test_ollama_sucesso_e_retentativa_sem_think():
    sem_think = RespostaHTTP(400, {"error": "model does not support thinking"})
    ok = RespostaHTTP(200, {"message": {"content": '{"motivo": "INDETERMINADO"}'}, "prompt_eval_count": 500, "eval_count": 30})
    sessao = SessaoFalsa([sem_think, ok])
    p = ProvedorOllama("modelo-local", think=False, sessao=sessao)
    r = p.gerar("x", {"type": "object"})
    assert r.texto == '{"motivo": "INDETERMINADO"}' and r.tokens_saida == 30
    assert "think" in sessao.enviados[0][1]["json"] and "think" not in sessao.enviados[1][1]["json"]
    assert sessao.enviados[1][1]["json"]["format"] == {"type": "object"}


def test_ollama_desligado():
    p = ProvedorOllama("modelo-local", sessao=SessaoFalsa([requests.ConnectionError()]))
    with pytest.raises(ErroDeProvedor, match="Ollama"):
        p.gerar("x")
