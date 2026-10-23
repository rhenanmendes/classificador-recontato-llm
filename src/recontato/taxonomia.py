"""Taxonomia de motivos de recontato (lida de taxonomia/motivos_recontato.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import RAIZ

ARQUIVO_TAXONOMIA = RAIZ / "taxonomia" / "motivos_recontato.yaml"
INDETERMINADO = "INDETERMINADO"


@dataclass(frozen=True)
class Motivo:
    codigo: str
    nome: str
    definicao: str
    dono: str
    acao_sugerida: str
    acionavel: bool
    sinais: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Taxonomia:
    versao: str
    motivos: tuple[Motivo, ...]

    @property
    def codigos(self) -> list[str]:
        return [m.codigo for m in self.motivos]

    def __getitem__(self, codigo: str) -> Motivo:
        for motivo in self.motivos:
            if motivo.codigo == codigo:
                return motivo
        raise KeyError(codigo)

    def nome(self, codigo: str) -> str:
        try:
            return self[codigo].nome
        except KeyError:
            return codigo

    def para_prompt(self) -> str:
        linhas = []
        for m in self.motivos:
            sinais = f" Sinais típicos: {'; '.join(m.sinais)}." if m.sinais else ""
            linhas.append(f"- {m.codigo} ({m.nome}): {' '.join(m.definicao.split())}{sinais}")
        return "\n".join(linhas)


def carregar_taxonomia(caminho: Path = ARQUIVO_TAXONOMIA) -> Taxonomia:
    with open(caminho, encoding="utf-8") as f:
        dados = yaml.safe_load(f)
    motivos = tuple(
        Motivo(
            codigo=m["codigo"],
            nome=m["nome"],
            definicao=m["definicao"].strip(),
            dono=m.get("dono", "-"),
            acao_sugerida=m.get("acao_sugerida", ""),
            acionavel=bool(m.get("acionavel", True)),
            sinais=tuple(m.get("sinais") or ()),
        )
        for m in dados["motivos"]
    )
    codigos = [m.codigo for m in motivos]
    if len(set(codigos)) != len(codigos):
        raise ValueError("Há códigos de motivo duplicados na taxonomia.")
    if INDETERMINADO not in codigos:
        raise ValueError(f"A taxonomia precisa ter o motivo {INDETERMINADO}.")
    return Taxonomia(versao=str(dados.get("versao", "")), motivos=motivos)
