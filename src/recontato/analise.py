"""Etapa 4: transforma as classificações em leitura de negócio (Pareto, contas, agentes, custo)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .taxonomia import Taxonomia


@dataclass
class Analise:
    resumo_operacao: dict
    classificados: pd.DataFrame
    pareto: pd.DataFrame
    indicadores_conta: pd.DataFrame
    motivo_por_conta: pd.DataFrame
    indicadores_extras: dict[str, pd.DataFrame]
    motivo_por_dimensao: dict[str, pd.DataFrame]
    exemplos: pd.DataFrame
    desempenho_modelo: dict


def montar_base(con, previsoes: pd.DataFrame, taxonomia: Taxonomia) -> pd.DataFrame:
    recontatos = con.execute(
        "SELECT recontato_id, conta, canal, produto, agente_id, inicio, horas_desde_anterior FROM recontatos"
    ).df()
    base = previsoes.merge(recontatos, on="recontato_id", how="inner")
    base["nome_motivo"] = base["motivo"].map(taxonomia.nome)
    base["acionavel"] = base["motivo"].map({m.codigo: m.acionavel for m in taxonomia.motivos})
    return base


def calcular_pareto(base: pd.DataFrame, taxonomia: Taxonomia) -> pd.DataFrame:
    contagem = base["motivo"].value_counts()
    pareto = pd.DataFrame({"motivo": contagem.index, "quantidade": contagem.values})
    pareto["percentual"] = pareto["quantidade"] / pareto["quantidade"].sum()
    pareto["percentual_acumulado"] = pareto["percentual"].cumsum()
    info = {m.codigo: m for m in taxonomia.motivos}
    pareto["nome"] = pareto["motivo"].map(lambda c: info[c].nome)
    pareto["acionavel"] = pareto["motivo"].map(lambda c: info[c].acionavel)
    pareto["dono"] = pareto["motivo"].map(lambda c: info[c].dono)
    pareto["acao_sugerida"] = pareto["motivo"].map(lambda c: info[c].acao_sugerida)
    return pareto


def _distribuicao(base: pd.DataFrame, coluna: str, minimo: int) -> pd.DataFrame:
    """Percentual de cada motivo dentro de cada valor da dimensão (linhas somam 100%)."""
    dados = base.dropna(subset=[coluna])
    volumes = dados[coluna].value_counts()
    manter = volumes[volumes >= minimo].index
    if len(manter) == 0:
        return pd.DataFrame()
    tabela = pd.crosstab(dados.loc[dados[coluna].isin(manter), coluna], dados["nome_motivo"], normalize="index")
    tabela["(n classificados)"] = volumes.loc[tabela.index]
    return tabela.sort_values("(n classificados)", ascending=False)


def analisar(
    con, previsoes: pd.DataFrame, taxonomia: Taxonomia, config: dict, fonte: str
) -> Analise:
    base = montar_base(con, previsoes, taxonomia)
    if base.empty:
        raise ValueError("Nenhuma classificação corresponde aos recontatos desta base.")

    geral = con.execute("SELECT * FROM indicadores WHERE dimensao = 'geral'").df().iloc[0].to_dict()
    pareto = calcular_pareto(base, taxonomia)
    share_acionavel = float(base["acionavel"].mean())
    # Margem de erro (95%) da proporção estimada na amostra classificada.
    margem = 1.96 * (share_acionavel * (1 - share_acionavel) / len(base)) ** 0.5

    # Extrapola a participação da amostra para o total de recontatos da base.
    resumo = {
        "contatos": int(geral["contatos"]),
        "recontatos": int(geral["recontatos"]),
        "taxa_recontato": float(geral["taxa_recontato"]),
        "fcr_janela": float(geral["fcr_janela"]),
        "mediana_horas_ate_recontato": float(geral["mediana_horas_ate_recontato"] or 0),
        "classificados": int(len(base)),
        "share_acionavel": share_acionavel,
        "margem_erro_acionavel": margem,
        "taxa_recontato_acionavel": float(geral["taxa_recontato"]) * share_acionavel,
        "periodo": con.execute("SELECT min(inicio)::DATE, max(fim)::DATE FROM contatos").fetchone(),
    }

    minimo = int(config["relatorio"]["volume_minimo_ranking"])
    indicadores_conta = con.execute(
        """
        SELECT valor AS conta, contatos, recontatos, taxa_recontato, fcr_janela, mediana_horas_ate_recontato
        FROM indicadores
        WHERE dimensao = 'conta' AND contatos >= ?
        ORDER BY contatos DESC
        """,
        [minimo],
    ).df()
    if indicadores_conta.empty:  # bases pequenas (amostra): usa todas as contas
        indicadores_conta = con.execute(
            """
            SELECT valor AS conta, contatos, recontatos, taxa_recontato, fcr_janela, mediana_horas_ate_recontato
            FROM indicadores WHERE dimensao = 'conta' ORDER BY contatos DESC LIMIT 15
            """
        ).df()

    contas_top = indicadores_conta.head(10)["conta"].tolist()
    motivo_por_conta = _distribuicao(base[base["conta"].isin(contas_top)], "conta", 1)

    extras, por_dimensao = {}, {}
    for dimensao, coluna in (("produto", "produto"), ("canal", "canal"), ("agente", "agente_id")):
        tabela = con.execute(
            """
            SELECT valor, contatos, contatos_observaveis, geraram_recontato, taxa_recontato, fcr_janela
            FROM indicadores WHERE dimensao = ? ORDER BY fcr_janela
            """,
            [dimensao],
        ).df()
        if len(tabela) > 1:
            extras[dimensao] = tabela
            por_dimensao[dimensao] = _distribuicao(base, coluna, 5)

    exemplos = (
        base.sort_values(["motivo", "confianca"], ascending=[True, False])
        .groupby("motivo", group_keys=False)
        .head(int(config["relatorio"]["exemplos_por_motivo"]))
    )[["motivo", "nome_motivo", "conta", "evidencia", "resumo", "confianca"]]

    return Analise(
        resumo_operacao=resumo,
        classificados=base,
        pareto=pareto,
        indicadores_conta=indicadores_conta,
        motivo_por_conta=motivo_por_conta,
        indicadores_extras=extras,
        motivo_por_dimensao=por_dimensao,
        exemplos=exemplos,
        desempenho_modelo=desempenho_do_modelo(base, config),
    )


def desempenho_do_modelo(base: pd.DataFrame, config: dict) -> dict:
    """Tokens, latência e custo estimado por 1.000 classificações."""
    entrada = pd.to_numeric(base.get("tokens_entrada"), errors="coerce")
    saida = pd.to_numeric(base.get("tokens_saida"), errors="coerce")
    latencia = pd.to_numeric(base.get("latencia_s"), errors="coerce")
    resultado = {
        "provedor": base["provedor"].iloc[0],
        "modelo": base["modelo"].iloc[0],
        "versao_prompt": base["versao_prompt"].iloc[0],
        "classificacoes": int(len(base)),
        "taxa_erro_formato": float(base["erro"].notna().mean()),
        "tokens_entrada_medio": float(entrada.mean()) if entrada.notna().any() else None,
        "tokens_saida_medio": float(saida.mean()) if saida.notna().any() else None,
        "latencia_media_s": float(latencia.mean()) if latencia.notna().any() else None,
        "custo_por_mil_usd": None,
    }
    precos = config.get("llm", {}).get("custo_estimado", {}) or {}
    p_in, p_out = precos.get("entrada_usd_por_milhao"), precos.get("saida_usd_por_milhao")
    if p_in is not None and p_out is not None and resultado["tokens_entrada_medio"] is not None:
        custo_unit = (resultado["tokens_entrada_medio"] * p_in + (resultado["tokens_saida_medio"] or 0) * p_out) / 1e6
        resultado["custo_por_mil_usd"] = custo_unit * 1000
    return resultado
