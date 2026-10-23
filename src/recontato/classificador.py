"""Etapa 2: classifica o motivo de cada recontato com um LLM (ou com o baseline de regras).

Pontos de projeto:
  * Prompt versionado em arquivo (prompts/), para que mudanças sejam rastreáveis.
  * Saída estruturada (JSON com esquema e lista fechada de motivos).
  * Cache em JSONL: cada classificação é gravada assim que fica pronta. Se a
    cota do plano gratuito acabar ou o computador desligar, basta rodar de novo
    que o processo continua de onde parou, sem pagar duas vezes pela mesma chamada.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Iterable

import pandas as pd

from .config import RAIZ
from .provedores import ErroDeProvedor, LimiteDeCotaAtingido, Provedor
from .regras import ProvedorRegras
from .taxonomia import INDETERMINADO, Taxonomia

PASTA_PROMPTS = RAIZ / "prompts"


def carregar_prompt(nome: str) -> Template:
    return Template((PASTA_PROMPTS / f"{nome}.md").read_text(encoding="utf-8"))


def esquema_resposta(taxonomia: Taxonomia) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "motivo": {"type": "string", "enum": taxonomia.codigos},
            "relacionado_ao_anterior": {"type": "boolean"},
            "confianca": {"type": "number"},
            "evidencia": {"type": "string"},
            "resumo": {"type": "string"},
        },
        "required": ["motivo", "relacionado_ao_anterior", "confianca", "evidencia", "resumo"],
        "additionalProperties": False,
    }


def truncar(texto: str, limite: int, manter_fim: bool = False) -> str:
    """Corta textos longos. No contato anterior, mantém começo e fim (pedido e desfecho)."""
    texto = (texto or "").strip()
    if len(texto) <= limite:
        return texto
    if not manter_fim:
        return texto[:limite].rstrip() + " [...]"
    cabeca = int(limite * 0.6)
    cauda = limite - cabeca
    return texto[:cabeca].rstrip() + "\n[...]\n" + texto[-cauda:].lstrip()


def montar_prompt(modelo: Template, taxonomia: Taxonomia, registro: dict[str, Any], max_caracteres: int) -> str:
    horas = registro.get("horas_desde_anterior")
    return modelo.substitute(
        taxonomia=taxonomia.para_prompt(),
        conta=registro.get("conta") or "não informada",
        horas="desconhecido" if horas is None or pd.isna(horas) else f"{float(horas):.1f}",
        contato_anterior=truncar(registro.get("transcricao_anterior", ""), max_caracteres, manter_fim=True),
        contato_atual=truncar(registro.get("transcricao_atual", ""), max_caracteres),
    )


def interpretar_resposta(texto: str, taxonomia: Taxonomia) -> dict[str, Any]:
    """Converte a resposta do modelo em um registro validado. Nunca levanta exceção."""
    resultado: dict[str, Any] = {
        "motivo": INDETERMINADO,
        "relacionado_ao_anterior": None,
        "confianca": None,
        "evidencia": "",
        "resumo": "",
        "erro": None,
    }
    bruto = (texto or "").strip()
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", bruto)
    achado = re.search(r"\{.*\}", bruto, flags=re.DOTALL)
    if not achado:
        resultado["erro"] = "resposta sem JSON"
        return resultado
    try:
        dados = json.loads(achado.group(0))
    except json.JSONDecodeError:
        resultado["erro"] = "JSON inválido"
        return resultado
    if "erro" in dados and "motivo" not in dados:
        resultado["erro"] = str(dados["erro"])
        return resultado

    motivo = str(dados.get("motivo", "")).strip().upper()
    if motivo in taxonomia.codigos:
        resultado["motivo"] = motivo
    else:
        resultado["erro"] = f"motivo fora da taxonomia: {motivo or 'vazio'}"

    relacionado = dados.get("relacionado_ao_anterior")
    if isinstance(relacionado, str):
        relacionado = relacionado.strip().lower() in ("true", "sim", "yes")
    resultado["relacionado_ao_anterior"] = relacionado if isinstance(relacionado, bool) else None

    try:
        confianca = float(dados.get("confianca"))
        resultado["confianca"] = min(max(confianca, 0.0), 1.0)
    except (TypeError, ValueError):
        pass

    resultado["evidencia"] = str(dados.get("evidencia", ""))[:300]
    resultado["resumo"] = str(dados.get("resumo", ""))[:500]
    return resultado


def rotulo_execucao(provedor: str, modelo: str, versao_prompt: str) -> str:
    """Identificador da execução, usado no nome dos arquivos (ex.: gemini_gemini-3.5-flash-lite_v1)."""
    modelo_limpo = re.sub(r"[^A-Za-z0-9.\-]+", "-", modelo).strip("-")
    return f"{provedor}_{modelo_limpo}_{versao_prompt}"


def ler_cache(caminho: Path) -> dict[str, dict[str, Any]]:
    if not caminho.exists():
        return {}
    registros = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                item = json.loads(linha)
                registros[str(item["recontato_id"])] = item
    return registros


@dataclass
class ResultadoClassificacao:
    total_amostra: int
    ja_classificados: int
    classificados_agora: int
    erros: int
    interrompido: str | None
    arquivo: Path


def classificar(
    registros: Iterable[dict[str, Any]],
    provedor: Provedor | ProvedorRegras,
    taxonomia: Taxonomia,
    versao_prompt: str,
    arquivo_saida: Path,
    max_caracteres: int = 1500,
    progresso_a_cada: int = 10,
) -> ResultadoClassificacao:
    registros = list(registros)
    arquivo_saida.parent.mkdir(parents=True, exist_ok=True)
    cache = ler_cache(arquivo_saida)
    pendentes = [r for r in registros if str(r["recontato_id"]) not in cache]

    modelo_prompt = carregar_prompt(f"classificar_recontato_{versao_prompt}")
    esquema = esquema_resposta(taxonomia)

    print(
        f"  {len(registros)} recontatos na amostra | {len(registros) - len(pendentes)} já classificados "
        f"| {len(pendentes)} pendentes",
        flush=True,
    )

    feitos, erros, interrompido = 0, 0, None
    inicio = time.monotonic()
    with open(arquivo_saida, "a", encoding="utf-8") as saida:
        for registro in pendentes:
            try:
                if isinstance(provedor, ProvedorRegras):
                    resposta = provedor.classificar_registro(registro)
                else:
                    prompt = montar_prompt(modelo_prompt, taxonomia, registro, max_caracteres)
                    resposta = provedor.gerar(prompt, esquema)
            except LimiteDeCotaAtingido as erro:
                interrompido = str(erro)
                break
            except ErroDeProvedor as erro:
                interrompido = str(erro)
                break

            item = interpretar_resposta(resposta.texto, taxonomia)
            erros += item["erro"] is not None
            item.update(
                recontato_id=str(registro["recontato_id"]),
                provedor=provedor.nome,
                modelo=provedor.modelo,
                versao_prompt=versao_prompt,
                tokens_entrada=resposta.tokens_entrada,
                tokens_saida=resposta.tokens_saida,
                latencia_s=resposta.latencia_s,
                classificado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            saida.write(json.dumps(item, ensure_ascii=False) + "\n")
            saida.flush()
            feitos += 1

            if feitos % progresso_a_cada == 0 or feitos == len(pendentes):
                decorrido = time.monotonic() - inicio
                restante = decorrido / feitos * (len(pendentes) - feitos)
                print(
                    f"  {feitos}/{len(pendentes)} classificados "
                    f"(erros: {erros}, restante estimado: {restante / 60:.1f} min)",
                    flush=True,
                )

    return ResultadoClassificacao(
        total_amostra=len(registros),
        ja_classificados=len(registros) - len(pendentes),
        classificados_agora=feitos,
        erros=erros,
        interrompido=interrompido,
        arquivo=arquivo_saida,
    )


def selecionar_amostra(con, tamanho: int, semente: int, contas: list[str] | None = None) -> pd.DataFrame:
    """Amostra aleatória REPRODUTÍVEL: mesma semente, mesma amostra, em qualquer computador."""
    filtro = ""
    parametros: list[Any] = []
    if contas:
        filtro = f"WHERE conta IN ({', '.join('?' for _ in contas)})"
        parametros.extend(contas)
    parametros.extend([str(semente), int(tamanho)])
    return con.execute(
        f"""
        SELECT *
        FROM recontatos
        {filtro}
        ORDER BY md5(recontato_id || ?)
        LIMIT ?
        """,
        parametros,
    ).df()
