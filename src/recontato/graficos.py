"""Gráficos estáticos (PNG) para o relatório e o README."""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

SUPERFICIE = "#fcfcfb"
TEXTO = "#0b0b0b"
TEXTO_SECUNDARIO = "#52514e"
GRADE = "#e4e3df"
AZUL = "#2a78d6"
CINZA = "#b4b2ab"
SEQUENCIAL = LinearSegmentedColormap.from_list("azul", ["#f3f7fd", "#a9c8f0", "#2a78d6", "#123e73"])


def _estilo():
    plt.rcParams.update({
        "figure.facecolor": SUPERFICIE,
        "axes.facecolor": SUPERFICIE,
        "axes.edgecolor": GRADE,
        "axes.labelcolor": TEXTO_SECUNDARIO,
        "xtick.color": TEXTO_SECUNDARIO,
        "ytick.color": TEXTO,
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlecolor": TEXTO,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


def _quebrar(texto: str, largura: int = 32) -> str:
    return "\n".join(textwrap.wrap(str(texto), largura)) or str(texto)


def _salvar(fig, caminho: Path) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=160, bbox_inches="tight", facecolor=SUPERFICIE)
    plt.close(fig)
    return caminho


def pareto_motivos(pareto: pd.DataFrame, caminho: Path, subtitulo: str = "") -> Path:
    _estilo()
    dados = pareto.iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(dados) + 1.6))
    cores = [AZUL if a else CINZA for a in dados["acionavel"]]
    ax.barh(_rotulos(dados["nome"]), dados["percentual"] * 100, color=cores, height=0.62, edgecolor=SUPERFICIE, linewidth=2)
    for i, (pct, acum) in enumerate(zip(dados["percentual"], dados["percentual_acumulado"])):
        ax.text(pct * 100 + 0.6, i, f"{pct:.0%}  (acum. {acum:.0%})", va="center", color=TEXTO_SECUNDARIO, fontsize=9)
    ax.set_xlabel("% dos recontatos classificados")
    ax.set_xlim(0, dados["percentual"].max() * 100 * 1.45)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title("Pareto de motivos de recontato", pad=22 if subtitulo else 6)
    if subtitulo:
        ax.text(0.0, 1.01, subtitulo, color=TEXTO_SECUNDARIO, fontsize=9, transform=ax.transAxes, va="bottom")
    from matplotlib.patches import Patch

    ax.legend(
        handles=[Patch(color=AZUL, label="Acionável (falha de resolução)"), Patch(color=CINZA, label="Não acionável")],
        loc="lower right", frameon=False, fontsize=9,
    )
    return _salvar(fig, caminho)


def _rotulos(serie: pd.Series, largura: int = 32) -> list[str]:
    return [_quebrar(v, largura) for v in serie]


def barras_indicador(
    tabela: pd.DataFrame, coluna_rotulo: str, coluna_valor: str, titulo: str, rotulo_eixo: str, caminho: Path,
    referencia: float | None = None,
) -> Path:
    _estilo()
    dados = tabela.sort_values(coluna_valor)
    fig, ax = plt.subplots(figsize=(8.5, 0.42 * len(dados) + 1.5))
    ax.barh(_rotulos(dados[coluna_rotulo], 28), dados[coluna_valor] * 100, color=AZUL, height=0.62, edgecolor=SUPERFICIE, linewidth=2)
    for i, v in enumerate(dados[coluna_valor]):
        if v >= 0.15:  # rótulo dentro da barra, para não colidir com a linha de média
            ax.text(v * 100 - 1, i, f"{v:.0%}", va="center", ha="right", color="white", fontsize=9, fontweight="bold")
        else:
            ax.text(v * 100 + 0.8, i, f"{v:.0%}", va="center", color=TEXTO_SECUNDARIO, fontsize=9)
    if referencia is not None:
        ax.axvline(referencia * 100, color=TEXTO_SECUNDARIO, linestyle="--", linewidth=1)
        ax.text(referencia * 100, len(dados) - 0.4, f" média {referencia:.0%}", color=TEXTO_SECUNDARIO, fontsize=8, va="bottom")
    ax.set_xlim(0, max(100, dados[coluna_valor].max() * 100 * 1.12))
    ax.set_xlabel(rotulo_eixo)
    ax.grid(axis="x", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(titulo)
    return _salvar(fig, caminho)


def mapa_calor(tabela: pd.DataFrame, titulo: str, caminho: Path, formato: str = "pct", rotulo_linhas: str = "") -> Path:
    _estilo()
    valores = tabela.to_numpy(dtype=float)
    altura = 0.5 * len(tabela.index) + 2.4
    largura = 0.95 * len(tabela.columns) + 3.2
    fig, ax = plt.subplots(figsize=(max(largura, 7), max(altura, 3.5)))
    ax.imshow(valores, cmap=SEQUENCIAL, aspect="auto", vmin=0, vmax=max(valores.max(), 1e-9))
    ax.set_xticks(range(len(tabela.columns)), [_quebrar(c, 14) for c in tabela.columns], rotation=0, fontsize=8)
    ax.set_yticks(range(len(tabela.index)), [_quebrar(i, 26) for i in tabela.index], fontsize=9)
    ax.tick_params(length=0)
    limite = valores.max() * 0.55
    for i in range(valores.shape[0]):
        for j in range(valores.shape[1]):
            v = valores[i, j]
            if v == 0:
                continue
            texto = f"{v:.0%}" if formato == "pct" else f"{int(v)}"
            ax.text(j, i, texto, ha="center", va="center", fontsize=8, color="white" if v > limite else TEXTO)
    for lado in ax.spines.values():
        lado.set_visible(False)
    ax.set_title(titulo)
    if rotulo_linhas:
        ax.set_ylabel(rotulo_linhas)
    return _salvar(fig, caminho)


def matriz_confusao(matriz: pd.DataFrame, nomes: dict[str, str], caminho: Path) -> Path:
    tabela = matriz.copy()
    tabela.index = [nomes.get(i, i) for i in tabela.index]
    tabela.columns = [nomes.get(c, c) for c in tabela.columns]
    return mapa_calor(tabela, "Matriz de confusão (linhas: rótulo humano, colunas: modelo)", caminho, formato="n")


def proporcao_por_linha(tabela: pd.DataFrame) -> pd.DataFrame:
    """Remove a coluna de volume antes de desenhar o mapa de calor."""
    return tabela.drop(columns=[c for c in tabela.columns if str(c).startswith("(")], errors="ignore")
