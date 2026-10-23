import json

from recontato.classificador import (
    carregar_prompt,
    classificar,
    interpretar_resposta,
    montar_prompt,
    rotulo_execucao,
    truncar,
)
from recontato.provedores import LimiteDeCotaAtingido, Resposta
from recontato.taxonomia import carregar_taxonomia

TAX = carregar_taxonomia()


def test_interpreta_json_valido():
    texto = json.dumps({
        "motivo": "PROMESSA_NAO_CUMPRIDA", "relacionado_ao_anterior": True,
        "confianca": 0.9, "evidencia": "você disse 3 dias", "resumo": "Reembolso prometido não caiu.",
    })
    r = interpretar_resposta(texto, TAX)
    assert r["motivo"] == "PROMESSA_NAO_CUMPRIDA"
    assert r["relacionado_ao_anterior"] is True
    assert r["erro"] is None


def test_interpreta_json_em_bloco_markdown_e_minusculo():
    texto = '```json\n{"motivo": "novo_assunto", "relacionado_ao_anterior": "false", "confianca": 2}\n```'
    r = interpretar_resposta(texto, TAX)
    assert r["motivo"] == "NOVO_ASSUNTO"
    assert r["relacionado_ao_anterior"] is False
    assert r["confianca"] == 1.0  # limitado a [0, 1]


def test_motivo_invalido_vira_indeterminado_com_erro():
    r = interpretar_resposta('{"motivo": "OUTRO"}', TAX)
    assert r["motivo"] == "INDETERMINADO"
    assert "fora da taxonomia" in r["erro"]
    assert interpretar_resposta("não sei", TAX)["erro"] == "resposta sem JSON"
    assert interpretar_resposta("{quebrado", TAX)["erro"] == "resposta sem JSON"


def test_truncar_mantem_inicio_e_fim():
    texto = "INICIO " + "x" * 500 + " FIM"
    cortado = truncar(texto, 100, manter_fim=True)
    assert cortado.startswith("INICIO") and cortado.endswith("FIM") and "[...]" in cortado
    assert truncar("curto", 100) == "curto"


def test_prompt_sem_placeholders_pendentes():
    registro = {
        "conta": "MarcaA", "horas_desde_anterior": 30.5,
        "transcricao_anterior": "Cliente: oi\nAtendimento: olá", "transcricao_atual": "Cliente: ainda não resolveu",
    }
    prompt = montar_prompt(carregar_prompt("classificar_recontato_v1"), TAX, registro, 1500)
    assert "$" not in prompt
    assert "PROMESSA_NAO_CUMPRIDA" in prompt and "ainda não resolveu" in prompt and "30.5" in prompt


def test_rotulo_execucao():
    assert rotulo_execucao("ollama", "qwen3:4b", "v1") == "ollama_qwen3-4b_v1"


class ProvedorFalso:
    nome = "falso"
    modelo = "teste"

    def __init__(self, parar_em=None):
        self.chamadas = 0
        self.parar_em = parar_em

    def gerar(self, prompt, esquema=None):
        self.chamadas += 1
        if self.parar_em and self.chamadas >= self.parar_em:
            raise LimiteDeCotaAtingido("cota diária")
        return Resposta('{"motivo": "PROBLEMA_NAO_RESOLVIDO", "relacionado_ao_anterior": true, '
                        '"confianca": 0.8, "evidencia": "x", "resumo": "y"}', 100, 20, 0.1)


def _registros(n):
    return [
        {"recontato_id": str(i), "conta": "A", "horas_desde_anterior": 5,
         "transcricao_anterior": "Cliente: a", "transcricao_atual": "Cliente: b"}
        for i in range(n)
    ]


def test_cache_retoma_de_onde_parou(tmp_path):
    arquivo = tmp_path / "saida.jsonl"

    # 1ª rodada: a cota acaba na 4ª chamada -> 3 classificações salvas
    r1 = classificar(_registros(6), ProvedorFalso(parar_em=4), TAX, "v1", arquivo)
    assert r1.classificados_agora == 3
    assert "cota" in r1.interrompido

    # 2ª rodada: só os 3 pendentes são enviados ao modelo
    provedor = ProvedorFalso()
    r2 = classificar(_registros(6), provedor, TAX, "v1", arquivo)
    assert r2.ja_classificados == 3 and r2.classificados_agora == 3 and provedor.chamadas == 3

    linhas = [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines()]
    assert len(linhas) == 6 and {l["recontato_id"] for l in linhas} == {str(i) for i in range(6)}
    assert linhas[0]["tokens_entrada"] == 100
