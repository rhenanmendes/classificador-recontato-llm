"""Hipóteses de causa raiz geradas por LLM para os principais motivos do Pareto.

É o passo que conecta "classificar" a "agir": para cada um dos motivos mais
frequentes, o modelo lê os resumos dos casos e propõe padrões, hipóteses
(lógica dos 5 Porquês) e ações com dono e indicador de acompanhamento.
As hipóteses são ponto de partida para a investigação, não conclusão.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .classificador import carregar_prompt
from .provedores import ErroDeProvedor, LimiteDeCotaAtingido, Provedor
from .taxonomia import Taxonomia

ESQUEMA_HIPOTESES = {
    "type": "object",
    "properties": {
        "padroes": {"type": "array", "items": {"type": "string"}},
        "hipoteses_causa_raiz": {"type": "array", "items": {"type": "string"}},
        "acoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "acao": {"type": "string"},
                    "dono": {"type": "string"},
                    "indicador": {"type": "string"},
                },
                "required": ["acao", "dono", "indicador"],
            },
        },
    },
    "required": ["padroes", "hipoteses_causa_raiz", "acoes"],
}


def gerar_hipoteses(
    provedor: Provedor,
    taxonomia: Taxonomia,
    base: pd.DataFrame,
    pareto: pd.DataFrame,
    arquivo_cache: Path,
    top: int = 3,
    max_casos: int = 25,
) -> list[dict]:
    cache = json.loads(arquivo_cache.read_text(encoding="utf-8")) if arquivo_cache.exists() else {}
    modelo = carregar_prompt("hipoteses_causa_raiz_v1")
    resultados = []

    for _, linha in pareto[pareto["acionavel"]].head(top).iterrows():
        codigo = linha["motivo"]
        if codigo in cache:
            resultados.append(cache[codigo])
            continue

        casos = base[base["motivo"] == codigo].sort_values("confianca", ascending=False).head(max_casos)
        texto_casos = "\n".join(
            f"- [{c.conta}] {c.resumo} | evidência: \"{c.evidencia}\"" for c in casos.itertuples()
        )
        contas = ", ".join(base.loc[base["motivo"] == codigo, "conta"].value_counts().head(5).index)
        motivo = taxonomia[codigo]
        prompt = modelo.substitute(
            motivo_nome=motivo.nome,
            motivo_codigo=codigo,
            motivo_definicao=" ".join(motivo.definicao.split()),
            motivo_dono=motivo.dono,
            volume=int(linha["quantidade"]),
            percentual=f"{linha['percentual']:.0%}",
            contas=contas or "-",
            casos=texto_casos,
        )
        try:
            resposta = provedor.gerar(prompt, ESQUEMA_HIPOTESES)
            dados = json.loads(resposta.texto)
        except (LimiteDeCotaAtingido, ErroDeProvedor) as erro:
            print(f"  hipóteses interrompidas: {erro}")
            break
        except json.JSONDecodeError:
            dados = {"padroes": [], "hipoteses_causa_raiz": [], "acoes": [], "erro": "resposta inválida"}

        item = {"motivo": codigo, "nome": motivo.nome, **dados}
        cache[codigo] = item
        resultados.append(item)
        arquivo_cache.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return resultados
