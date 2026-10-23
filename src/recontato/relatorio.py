"""Etapa 5: monta o relatório em Markdown (lido direto no GitHub), com gráficos e tabelas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from . import graficos
from .analise import Analise
from .config import ROTULO_CONTA
from .taxonomia import Taxonomia

NOME_FONTE = {
    "twcs": "Customer Support on Twitter (Kaggle)",
    "b2b": "Chamados B2B de benefícios corporativos (empresa fictícia)",
}


def _pct(v, casas: int = 1) -> str:
    return "-" if v is None or pd.isna(v) else f"{v * 100:.{casas}f}%".replace(".", ",")


def _num(v, casas: int = 0) -> str:
    if v is None or pd.isna(v):
        return "-"
    texto = f"{v:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _tabela(df: pd.DataFrame, colunas: dict[str, tuple[str, callable]]) -> str:
    """Tabela Markdown: colunas = {coluna_df: (titulo, formatador)}."""
    titulos = [t for t, _ in colunas.values()]
    linhas = ["| " + " | ".join(titulos) + " |", "|" + "|".join("---" for _ in titulos) + "|"]
    for _, linha in df.iterrows():
        celulas = [str(fmt(linha[c])).replace("|", "/").replace("\n", " ") for c, (_, fmt) in colunas.items()]
        linhas.append("| " + " | ".join(celulas) + " |")
    return "\n".join(linhas)


def gerar_relatorio(
    fonte: str,
    analise: Analise,
    taxonomia: Taxonomia,
    pasta: Path,
    rotulo: str,
    janela_dias: int,
    avaliacao: dict | None = None,
    hipoteses: list[dict] | None = None,
    dados_sinteticos: bool = False,
) -> Path:
    pasta_fig = pasta / "figuras" / rotulo
    rotulo_conta = ROTULO_CONTA[fonte]
    r = analise.resumo_operacao
    d = analise.desempenho_modelo
    md: list[str] = []

    titulo = NOME_FONTE[fonte]
    if dados_sinteticos and fonte == "twcs":
        titulo = "amostra sintética no formato Customer Support on Twitter"
    md.append(f"# Relatório de recontato: {titulo}\n")
    md.append(
        f"Gerado em {datetime.now():%d/%m/%Y %H:%M} · classificador `{d['provedor']}` "
        f"(`{d['modelo']}`, prompt `{d['versao_prompt']}`) · janela de recontato de {janela_dias} dias · "
        f"período {r['periodo'][0]:%d/%m/%Y} a {r['periodo'][1]:%d/%m/%Y}\n"
    )
    if dados_sinteticos:
        md.append(
            "> **Atenção:** este relatório foi gerado a partir de dados SINTÉTICOS de amostra, "
            "criados para testar o pipeline. Os números ilustram o formato da análise e não "
            "representam nenhuma operação real.\n"
        )

    # ---------------------------------------------------------------- resumo executivo
    pareto_acionavel = analise.pareto[analise.pareto["acionavel"]]
    top3 = pareto_acionavel.head(3)
    concentracao = top3["quantidade"].sum() / analise.pareto["quantidade"].sum()
    diferenca_pp = (r["taxa_recontato"] - r["taxa_recontato_acionavel"]) * 100

    md.append("## Resumo executivo\n")
    md.append(
        f"- **{_num(r['contatos'])} contatos** analisados, com **taxa de recontato de {_pct(r['taxa_recontato'])}** "
        f"e **FCR de {_pct(r['fcr_janela'])}** (resolução sem retorno em {janela_dias} dias). "
        f"A mediana de tempo até o cliente voltar é de {_num(r['mediana_horas_ate_recontato'], 0)} horas."
    )
    md.append(
        f"- Dos {_num(r['classificados'])} recontatos classificados, **{_pct(r['share_acionavel'], 0)} indicam falha "
        f"de resolução** (margem de erro de ±{_num(r['margem_erro_acionavel'] * 100, 1)} p.p.). Descontando assuntos novos, agradecimentos e casos indeterminados, a **taxa de recontato acionável é "
        f"{_pct(r['taxa_recontato_acionavel'])}**: {_num(diferenca_pp, 1)} p.p. do indicador bruto não indicam "
        f"falha de resolução identificável."
    )
    if not top3.empty:
        lista = "; ".join(f"{l.nome} ({_pct(l.percentual, 0)}, dono: {l.dono})" for l in top3.itertuples())
        md.append(f"- **Os 3 principais motivos acionáveis concentram {_pct(concentracao, 0)} dos recontatos:** {lista}.")
    if len(analise.indicadores_conta) > 1:
        pior = analise.indicadores_conta.sort_values("fcr_janela").iloc[0]
        md.append(
            f"- {rotulo_conta} com menor FCR: **{pior['conta']}** ({_pct(pior['fcr_janela'])}, "
            f"contra {_pct(r['fcr_janela'])} no total)."
        )
    if "agente" in analise.indicadores_extras:
        ag = analise.indicadores_extras["agente"]
        abaixo = ag[ag["fcr_janela"] < r["fcr_janela"] - 0.10]
        if not abaixo.empty:
            md.append(
                f"- **{len(abaixo)} agente(s) com FCR mais de 10 p.p. abaixo da média** "
                f"({', '.join(abaixo['valor'])}): candidatos a coaching direcionado pelo motivo predominante."
            )
    md.append("")

    # ---------------------------------------------------------------- Pareto
    graficos.pareto_motivos(analise.pareto, pasta_fig / "pareto_motivos.png", f"{_num(r['classificados'])} recontatos classificados")
    md.append("## Por que os clientes voltam\n")
    md.append("![Pareto de motivos](figuras/pareto_motivos.png)\n")
    md.append(_tabela(analise.pareto, {
        "nome": ("Motivo", str),
        "quantidade": ("Qtd.", _num),
        "percentual": ("%", lambda v: _pct(v, 0)),
        "percentual_acumulado": ("% acum.", lambda v: _pct(v, 0)),
        "dono": ("Área responsável", str),
        "acao_sugerida": ("Alavanca sugerida", str),
    }))
    md.append("")

    # ---------------------------------------------------------------- contas
    tabela_contas = analise.indicadores_conta
    if len(tabela_contas) > 1:
        graficos.barras_indicador(
            tabela_contas.head(15), "conta", "fcr_janela", f"FCR por {rotulo_conta.lower()}",
            f"FCR ({janela_dias} dias)", pasta_fig / "fcr_por_conta.png", referencia=r["fcr_janela"],
        )
        md.append(f"## Indicadores por {rotulo_conta.lower()}\n")
        md.append("![FCR por conta](figuras/fcr_por_conta.png)\n")
        md.append(_tabela(tabela_contas.head(15), {
            "conta": (rotulo_conta, str),
            "contatos": ("Contatos", _num),
            "recontatos": ("Recontatos", _num),
            "taxa_recontato": ("Taxa de recontato", _pct),
            "fcr_janela": ("FCR", _pct),
            "mediana_horas_ate_recontato": ("Mediana h até voltar", lambda v: _num(v, 0)),
        }))
        md.append("")

    if not analise.motivo_por_conta.empty and len(analise.motivo_por_conta) > 1:
        graficos.mapa_calor(
            graficos.proporcao_por_linha(analise.motivo_por_conta),
            f"Mix de motivos por {rotulo_conta.lower()} (% dos recontatos de cada linha)",
            pasta_fig / "motivo_por_conta.png",
        )
        md.append(f"### Mix de motivos por {rotulo_conta.lower()}\n")
        md.append(
            "Duas contas com a mesma taxa de recontato podem pedir ações diferentes: "
            "o mix de motivos mostra onde está a alavanca de cada uma.\n"
        )
        md.append("![Motivos por conta](figuras/motivo_por_conta.png)\n")

    # ---------------------------------------------------------------- dimensões extras (B2B)
    titulos = {"produto": "produto", "canal": "canal", "agente": "agente"}
    for dimensao, tabela in analise.indicadores_extras.items():
        if dimensao == "canal" and len(tabela) < 2:
            continue
        nome_arquivo = f"fcr_por_{dimensao}.png"
        graficos.barras_indicador(
            tabela, "valor", "fcr_janela", f"FCR por {titulos[dimensao]}", f"FCR ({janela_dias} dias)",
            pasta_fig / nome_arquivo, referencia=r["fcr_janela"],
        )
        md.append(f"## FCR por {titulos[dimensao]}\n")
        md.append(f"![FCR por {dimensao}](figuras/{nome_arquivo})\n")
        mix = analise.motivo_por_dimensao.get(dimensao)
        if mix is not None and not mix.empty:
            nome_mix = f"motivo_por_{dimensao}.png"
            graficos.mapa_calor(
                graficos.proporcao_por_linha(mix), f"Mix de motivos por {titulos[dimensao]}", pasta_fig / nome_mix
            )
            md.append(f"![Motivos por {dimensao}](figuras/{nome_mix})\n")
        if dimensao == "agente":
            md.append(
                "> O agente considerado é o do contato que **gerou** o recontato (onde a resolução falhou). "
                "Use como insumo para calibração e coaching, nunca como ranking punitivo isolado: "
                "volume baixo e mix de casos distorcem a comparação.\n"
            )

    # ---------------------------------------------------------------- hipóteses
    if hipoteses:
        md.append("## Hipóteses de causa raiz (geradas por LLM)\n")
        md.append(
            "Para os motivos acionáveis mais frequentes, o modelo leu os resumos dos casos e propôs padrões, "
            "hipóteses e ações. **São hipóteses para investigar com a operação**, não conclusões.\n"
        )
        for h in hipoteses:
            md.append(f"### {h['nome']}\n")
            if h.get("padroes"):
                md.append("**Padrões observados**\n")
                md.extend(f"- {p}" for p in h["padroes"])
                md.append("")
            if h.get("hipoteses_causa_raiz"):
                md.append("**Hipóteses de causa raiz**\n")
                md.extend(f"- {p}" for p in h["hipoteses_causa_raiz"])
                md.append("")
            if h.get("acoes"):
                md.append(_tabela(pd.DataFrame(h["acoes"]), {
                    "acao": ("Ação", str), "dono": ("Dono", str), "indicador": ("Indicador de acompanhamento", str),
                }))
                md.append("")

    # ---------------------------------------------------------------- exemplos
    md.append("## Exemplos por motivo\n")
    md.append(_tabela(analise.exemplos, {
        "nome_motivo": ("Motivo", str),
        "conta": (rotulo_conta, str),
        "evidencia": ("Evidência no novo contato", lambda v: f"_{v}_" if v else "-"),
        "resumo": ("Resumo do modelo", str),
    }))
    md.append("")

    # ---------------------------------------------------------------- qualidade
    if avaliacao:
        nomes = {m.codigo: m.nome for m in taxonomia.motivos}
        graficos.matriz_confusao(avaliacao["matriz"], nomes, pasta_fig / "matriz_confusao.png")
        md.append("## Qualidade do classificador\n")
        md.append(
            f"Comparação com {avaliacao['n']} recontatos rotulados por uma pessoa, sem ver a resposta do modelo.\n"
        )
        md.append("| Métrica | Valor |\n|---|---|")
        md.append(f"| Acurácia | {_pct(avaliacao['acuracia'])} |")
        md.append(f"| F1 macro | {_num(avaliacao['f1_macro'], 2)} |")
        md.append(f"| Kappa de Cohen | {_num(avaliacao['kappa'], 2)} |")
        md.append(f"| Acerto acionável x não acionável | {_pct(avaliacao['acuracia_acionavel'])} |")
        md.append("")
        md.append(_tabela(avaliacao["por_motivo"], {
            "nome": ("Motivo", str),
            "precisao": ("Precisão", lambda v: _pct(v, 0)),
            "revocacao": ("Revocação", lambda v: _pct(v, 0)),
            "f1": ("F1", lambda v: _num(v, 2)),
            "suporte": ("Casos", _num),
        }))
        md.append("\n![Matriz de confusão](figuras/matriz_confusao.png)\n")

    # ---------------------------------------------------------------- desempenho
    md.append("## Custo e desempenho do classificador\n")
    md.append("| Item | Valor |\n|---|---|")
    md.append(f"| Classificações | {_num(d['classificacoes'])} |")
    md.append(f"| Respostas fora do formato | {_pct(d['taxa_erro_formato'])} |")
    md.append(f"| Tokens de entrada (média) | {_num(d['tokens_entrada_medio'])} |")
    md.append(f"| Tokens de saída (média) | {_num(d['tokens_saida_medio'])} |")
    md.append(f"| Latência média por chamada | {_num(d['latencia_media_s'], 2)} s |")
    custo = d["custo_por_mil_usd"]
    md.append(
        f"| Custo estimado por 1.000 classificações | "
        f"{'US$ ' + _num(custo, 2) if custo is not None else 'configure os preços em config.yaml'} |"
    )
    md.append("")
    md.append("---\nMetodologia completa em [docs/metodologia.md](../../docs/metodologia.md).\n")

    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"relatorio_{rotulo}.md"
    texto = "\n".join(md).replace("](figuras/", f"](figuras/{rotulo}/")
    caminho.write_text(texto, encoding="utf-8")
    return caminho
