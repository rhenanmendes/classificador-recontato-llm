"""Etapa 3: valida o classificador contra rótulos humanos (gabarito).

A lógica é a mesma de uma auditoria de qualidade (QA) em operação:
uma amostra é rotulada por uma pessoa, sem ver a resposta do modelo, e a
concordância entre os dois é medida. Além da acurácia, o kappa de Cohen
desconta a concordância que aconteceria por acaso.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, cohen_kappa_score, f1_score, precision_recall_fscore_support

from .taxonomia import Taxonomia


def carregar_classificacoes(caminho: Path) -> pd.DataFrame:
    if not caminho.exists():
        raise FileNotFoundError(
            f"Nenhuma classificação encontrada em {caminho}. Rode a etapa 'classificar' antes."
        )
    linhas = [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not linhas:
        raise FileNotFoundError(f"O arquivo {caminho} ainda não tem classificações.")
    df = pd.DataFrame(linhas)
    df["recontato_id"] = df["recontato_id"].astype(str)
    return df.drop_duplicates("recontato_id", keep="last")


def carregar_gabarito(caminho: Path, taxonomia: Taxonomia) -> pd.DataFrame:
    # sep=None detecta vírgula ou ponto e vírgula (Excel em português salva com ";").
    gab = pd.read_csv(caminho, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    gab.columns = [c.strip().lower() for c in gab.columns]
    if not {"recontato_id", "motivo_real"} <= set(gab.columns):
        raise ValueError("O gabarito precisa das colunas recontato_id e motivo_real.")
    gab = gab[["recontato_id", "motivo_real"]].dropna()
    gab["motivo_real"] = gab["motivo_real"].str.strip().str.upper()
    invalidos = sorted(set(gab["motivo_real"]) - set(taxonomia.codigos))
    if invalidos:
        raise ValueError(f"Motivos fora da taxonomia no gabarito: {invalidos}")
    return gab


def avaliar(previsoes: pd.DataFrame, gabarito: pd.DataFrame, taxonomia: Taxonomia) -> dict:
    base = gabarito.merge(previsoes[["recontato_id", "motivo"]], on="recontato_id", how="inner")
    if base.empty:
        raise ValueError("Nenhum recontato do gabarito foi classificado ainda.")

    reais, previstos = base["motivo_real"], base["motivo"]
    rotulos = [c for c in taxonomia.codigos if c in set(reais) | set(previstos)]
    precisao, revocacao, f1, suporte = precision_recall_fscore_support(
        reais, previstos, labels=rotulos, zero_division=0
    )
    por_motivo = pd.DataFrame({
        "motivo": rotulos,
        "nome": [taxonomia.nome(r) for r in rotulos],
        "precisao": precisao,
        "revocacao": revocacao,
        "f1": f1,
        "suporte": suporte,
    }).sort_values("suporte", ascending=False)

    acionavel = {m.codigo: m.acionavel for m in taxonomia.motivos}
    matriz = pd.crosstab(
        pd.Categorical(reais, categories=rotulos),
        pd.Categorical(previstos, categories=rotulos),
        rownames=["real"], colnames=["previsto"], dropna=False,
    )

    return {
        "n": int(len(base)),
        "acuracia": float(accuracy_score(reais, previstos)),
        "f1_macro": float(f1_score(reais, previstos, labels=rotulos, average="macro", zero_division=0)),
        "kappa": float(cohen_kappa_score(reais, previstos)),
        # Visão de negócio: o modelo acerta se o recontato é falha de resolução ou não?
        "acuracia_acionavel": float(
            (reais.map(acionavel) == previstos.map(acionavel)).mean()
        ),
        "por_motivo": por_motivo,
        "matriz": matriz,
        "erros": base[reais != previstos],
    }


def exportar_planilha_rotulagem(
    recontatos: pd.DataFrame, taxonomia: Taxonomia, caminho: Path, n: int, semente: int
) -> Path:
    """Gera uma planilha para rotulagem manual às cegas (sem a resposta do modelo)."""
    amostra = recontatos.sample(n=min(n, len(recontatos)), random_state=semente)
    planilha = amostra[["recontato_id", "conta", "horas_desde_anterior", "transcricao_anterior", "transcricao_atual"]].copy()
    planilha["horas_desde_anterior"] = planilha["horas_desde_anterior"].round(1)
    planilha["motivo_real"] = ""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # ";" e utf-8-sig fazem o arquivo abrir certo no Excel em português.
    planilha.to_csv(caminho, sep=";", index=False, encoding="utf-8-sig")

    legenda = caminho.with_name(caminho.stem + "_legenda.csv")
    pd.DataFrame(
        [{"codigo": m.codigo, "nome": m.nome, "definicao": " ".join(m.definicao.split())} for m in taxonomia.motivos]
    ).to_csv(legenda, sep=";", index=False, encoding="utf-8-sig")
    return caminho
