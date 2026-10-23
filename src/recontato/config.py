"""Leitura de configuração e caminhos padrão do projeto."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[2]

FONTES = ("twcs", "b2b")

# Arquivo de entrada padrão de cada fonte, quando --arquivo não é informado.
ARQUIVO_PADRAO = {
    "twcs": RAIZ / "data" / "raw" / "twcs.csv",
    "b2b": RAIZ / "data" / "amostra" / "b2b_beneficios_chamados.csv",
}

# Como a "conta" é chamada em cada fonte, para textos e gráficos.
ROTULO_CONTA = {"twcs": "Marca", "b2b": "Empresa-cliente"}


@dataclass(frozen=True)
class Caminhos:
    """Onde cada etapa lê e grava, por fonte de dados."""

    fonte: str
    raiz: Path = RAIZ

    @property
    def banco(self) -> Path:
        return self.raiz / "data" / "processed" / f"{self.fonte}.duckdb"

    @property
    def saida(self) -> Path:
        return self.raiz / "outputs" / self.fonte

    @property
    def relatorio(self) -> Path:
        return self.raiz / "reports" / self.fonte

    def classificacoes(self, provedor: str) -> Path:
        return self.saida / f"classificacoes_{provedor}.jsonl"

    def criar(self) -> "Caminhos":
        for pasta in (self.banco.parent, self.saida, self.relatorio):
            pasta.mkdir(parents=True, exist_ok=True)
        return self


def carregar_config(caminho: Path | None = None) -> dict[str, Any]:
    caminho = caminho or RAIZ / "config.yaml"
    with open(caminho, encoding="utf-8") as f:
        return yaml.safe_load(f)


def mesclar(base: dict[str, Any], sobrescrever: dict[str, Any]) -> dict[str, Any]:
    """Mescla dicionários aninhados; valores None em `sobrescrever` são ignorados."""
    resultado = copy.deepcopy(base)
    for chave, valor in sobrescrever.items():
        if valor is None:
            continue
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave] = mesclar(resultado[chave], valor)
        else:
            resultado[chave] = valor
    return resultado
