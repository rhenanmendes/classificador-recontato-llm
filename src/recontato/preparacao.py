"""Etapa 1: carrega a base bruta, monta os contatos e deriva o recontato (tudo em SQL/DuckDB)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb

from .config import RAIZ, Caminhos

PASTA_SQL = RAIZ / "sql"

ROTEIROS = {
    "twcs": ["twcs/01_tweets.sql", "twcs/02_conversas.sql", "twcs/03_contatos.sql"],
    "b2b": ["b2b/01_contatos.sql"],
}
ROTEIROS_COMUNS = ["comum/01_recontato.sql", "comum/02_indicadores.sql"]


def _sql(nome: str, **parametros: object) -> str:
    texto = (PASTA_SQL / nome).read_text(encoding="utf-8")
    for chave, valor in parametros.items():
        texto = texto.replace("{" + chave + "}", str(valor))
    return texto


def _caminho_sql(caminho: Path) -> str:
    # Barras normais funcionam no Windows também, e aspas simples precisam ser escapadas.
    return caminho.resolve().as_posix().replace("'", "''")


def conectar(caminhos: Caminhos, somente_leitura: bool = False) -> duckdb.DuckDBPyConnection:
    if somente_leitura and not caminhos.banco.exists():
        raise FileNotFoundError(
            f"Banco {caminhos.banco} não encontrado. Rode primeiro: python main.py preparar --fonte {caminhos.fonte}"
        )
    con = duckdb.connect(str(caminhos.banco), read_only=somente_leitura)
    con.execute("SET TimeZone = 'UTC'")
    return con


def preparar(fonte: str, arquivo: Path, janela_dias: int, caminhos: Caminhos) -> dict:
    if not arquivo.exists():
        raise FileNotFoundError(f"Arquivo de entrada não encontrado: {arquivo}")

    caminhos.criar()
    if caminhos.banco.exists():
        caminhos.banco.unlink()

    inicio = time.time()
    con = conectar(caminhos)
    try:
        for roteiro in ROTEIROS[fonte]:
            print(f"  executando {roteiro} ...", flush=True)
            con.execute(_sql(roteiro, arquivo=_caminho_sql(arquivo)))
        for roteiro in ROTEIROS_COMUNS:
            print(f"  executando {roteiro} ...", flush=True)
            con.execute(_sql(roteiro, janela=int(janela_dias)))

        resumo = _resumo(con, fonte, janela_dias)
    finally:
        con.close()

    resumo["segundos"] = round(time.time() - inicio, 1)
    (caminhos.saida / "resumo_preparacao.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return resumo


def _resumo(con: duckdb.DuckDBPyConnection, fonte: str, janela_dias: int) -> dict:
    resumo: dict = {"fonte": fonte, "janela_dias": janela_dias}
    if fonte == "twcs":
        resumo["tweets_lidos"] = con.execute("SELECT count(*) FROM tweets").fetchone()[0]
        resumo["conversas_iniciadas_por_cliente_sem_resposta"] = con.execute(
            "SELECT count(*) FROM contatos_sem_resposta"
        ).fetchone()[0]

    geral = con.execute(
        """
        SELECT contatos, recontatos, contatos_observaveis, geraram_recontato,
               taxa_recontato, fcr_janela, mediana_horas_ate_recontato
        FROM indicadores WHERE dimensao = 'geral'
        """
    ).fetchone()
    chaves = [
        "contatos", "recontatos", "contatos_observaveis", "geraram_recontato",
        "taxa_recontato", "fcr_janela", "mediana_horas_ate_recontato",
    ]
    resumo.update(dict(zip(chaves, geral)))
    periodo = con.execute("SELECT min(inicio), max(fim) FROM contatos").fetchone()
    resumo["periodo_inicio"], resumo["periodo_fim"] = periodo
    resumo["clientes"] = con.execute("SELECT count(DISTINCT cliente_id) FROM contatos").fetchone()[0]
    resumo["contas"] = con.execute("SELECT count(DISTINCT conta) FROM contatos").fetchone()[0]
    return resumo
