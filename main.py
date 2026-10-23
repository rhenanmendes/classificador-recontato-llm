"""Linha de comando do projeto.

Etapas (rode na ordem):
    python main.py preparar    --fonte twcs           # monta contatos e deriva recontato (SQL)
    python main.py classificar --fonte twcs           # classifica uma amostra de recontatos com LLM
    python main.py rotular     --fonte twcs --n 150   # exporta planilha para rotulagem manual
    python main.py relatorio   --fonte twcs --gabarito data/rotulagem/twcs_rotulado.csv --hipoteses
    python main.py comparar    --fonte twcs --gabarito ... --provedores regras gemini ollama

Atalho para ver tudo funcionando sem chave de API e sem baixar nada:
    python main.py demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from recontato.analise import analisar  # noqa: E402
from recontato.avaliacao import (  # noqa: E402
    avaliar,
    carregar_classificacoes,
    carregar_gabarito,
    exportar_planilha_rotulagem,
)
from recontato.classificador import classificar, rotulo_execucao, selecionar_amostra  # noqa: E402
from recontato.config import ARQUIVO_PADRAO, FONTES, RAIZ, Caminhos, carregar_config, mesclar  # noqa: E402
from recontato.insights import gerar_hipoteses  # noqa: E402
from recontato.preparacao import conectar, preparar  # noqa: E402
from recontato.provedores import ErroDeProvedor, criar_provedor  # noqa: E402
from recontato.regras import ProvedorRegras  # noqa: E402
from recontato.relatorio import gerar_relatorio  # noqa: E402
from recontato.taxonomia import carregar_taxonomia  # noqa: E402

AMOSTRAS = {
    "twcs": (RAIZ / "data/amostra/twcs_amostra.csv", RAIZ / "data/amostra/twcs_amostra_gabarito.csv"),
    "b2b": (RAIZ / "data/amostra/b2b_beneficios_chamados.csv", RAIZ / "data/amostra/b2b_beneficios_gabarito.csv"),
}


def _modelo(config: dict, provedor: str) -> str:
    if provedor == "regras":
        return ProvedorRegras.modelo
    return config["llm"][provedor]["modelo"]


def _rotulo(config: dict, provedor: str) -> str:
    return rotulo_execucao(provedor, _modelo(config, provedor), config["llm"]["versao_prompt"])


def _instanciar(config: dict, provedor: str):
    if provedor == "regras":
        return ProvedorRegras()
    return criar_provedor(provedor, config["llm"])


def _eh_amostra(fonte: str, caminhos: Caminhos) -> bool:
    resumo = caminhos.saida / "resumo_preparacao.json"
    if fonte == "b2b":
        return True  # a base B2B é sempre sintética neste projeto
    if resumo.exists():
        return json.loads(resumo.read_text(encoding="utf-8")).get("arquivo", "").endswith("twcs_amostra.csv")
    return False


# ----------------------------------------------------------------------------- comandos

def cmd_preparar(args, config) -> None:
    caminhos = Caminhos(args.fonte)
    arquivo = Path(args.arquivo) if args.arquivo else ARQUIVO_PADRAO[args.fonte]
    janela = config["recontato"]["janela_dias"]
    print(f"Preparando '{args.fonte}' a partir de {arquivo} (janela de {janela} dias)")
    resumo = preparar(args.fonte, arquivo, janela, caminhos)
    resumo["arquivo"] = str(arquivo)
    (caminhos.saida / "resumo_preparacao.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"\nPronto em {resumo['segundos']} s: {resumo['contatos']:,} contatos, {resumo['recontatos']:,} recontatos | "
        f"taxa de recontato {resumo['taxa_recontato']:.1%} | FCR {resumo['fcr_janela']:.1%}"
    )


def cmd_classificar(args, config) -> None:
    caminhos = Caminhos(args.fonte).criar()
    taxonomia = carregar_taxonomia()
    provedor = _instanciar(config, args.provedor)
    con = conectar(caminhos, somente_leitura=True)
    try:
        amostra = selecionar_amostra(
            con, config["classificacao"]["tamanho_amostra"], config["classificacao"]["semente"], args.contas
        )
    finally:
        con.close()
    if amostra.empty:
        print("Nenhum recontato encontrado para classificar.")
        return

    arquivo = caminhos.classificacoes(_rotulo(config, args.provedor))
    print(f"Classificando com {provedor.nome} ({provedor.modelo}) -> {arquivo.relative_to(RAIZ)}")
    resultado = classificar(
        amostra.to_dict("records"), provedor, taxonomia, config["llm"]["versao_prompt"], arquivo,
        max_caracteres=config["classificacao"]["max_caracteres_contato"],
        progresso_a_cada=500 if args.provedor == "regras" else 10,
    )
    total = resultado.ja_classificados + resultado.classificados_agora
    print(f"\n{total}/{resultado.total_amostra} classificados (erros de formato nesta rodada: {resultado.erros}).")
    if resultado.interrompido:
        print(f"\nInterrompido: {resultado.interrompido}")
        print("O progresso foi salvo. Rode o mesmo comando de novo (mais tarde, se for limite de cota) para continuar.")


def cmd_rotular(args, config) -> None:
    caminhos = Caminhos(args.fonte)
    taxonomia = carregar_taxonomia()
    con = conectar(caminhos, somente_leitura=True)
    try:
        amostra = selecionar_amostra(
            con, config["classificacao"]["tamanho_amostra"], config["classificacao"]["semente"], args.contas
        )
    finally:
        con.close()
    destino = RAIZ / "data" / "rotulagem" / f"{args.fonte}_para_rotular.csv"
    exportar_planilha_rotulagem(amostra, taxonomia, destino, args.n, config["classificacao"]["semente"])
    print(f"Planilha criada: {destino.relative_to(RAIZ)}")
    print("Preencha a coluna motivo_real com os códigos da legenda (arquivo *_legenda.csv ao lado).")
    print("Dica: rotule sem olhar a resposta do modelo, para a avaliação ser justa.")


def cmd_relatorio(args, config) -> None:
    caminhos = Caminhos(args.fonte).criar()
    taxonomia = carregar_taxonomia()
    rotulo = _rotulo(config, args.provedor)
    previsoes = carregar_classificacoes(caminhos.classificacoes(rotulo))

    con = conectar(caminhos, somente_leitura=True)
    try:
        analise = analisar(con, previsoes, taxonomia, config, args.fonte)
    finally:
        con.close()

    avaliacao = None
    if args.gabarito:
        avaliacao = avaliar(previsoes, carregar_gabarito(Path(args.gabarito), taxonomia), taxonomia)
        print(
            f"Avaliação ({avaliacao['n']} casos): acurácia {avaliacao['acuracia']:.1%} | "
            f"kappa {avaliacao['kappa']:.2f} | F1 macro {avaliacao['f1_macro']:.2f}"
        )
        avaliacao["erros"].to_csv(caminhos.saida / f"erros_{rotulo}.csv", index=False, encoding="utf-8-sig")

    hipoteses = None
    if args.hipoteses:
        if args.provedor == "regras":
            print("Hipóteses de causa raiz precisam de um LLM: use --provedor gemini ou ollama.")
        else:
            hipoteses = gerar_hipoteses(
                _instanciar(config, args.provedor), taxonomia, analise.classificados, analise.pareto,
                caminhos.saida / f"hipoteses_{rotulo}.json",
            )

    # Exporta a base classificada (usada também pela integração com Google Sheets).
    exportar = analise.classificados.drop(columns=["tokens_entrada", "tokens_saida"], errors="ignore")
    exportar.to_csv(caminhos.saida / f"classificacoes_{rotulo}.csv", index=False, encoding="utf-8-sig")

    caminho = gerar_relatorio(
        args.fonte, analise, taxonomia, caminhos.relatorio, rotulo, config["recontato"]["janela_dias"],
        avaliacao=avaliacao, hipoteses=hipoteses, dados_sinteticos=_eh_amostra(args.fonte, caminhos),
    )
    print(f"Relatório: {caminho.relative_to(RAIZ)}")


def cmd_comparar(args, config) -> None:
    caminhos = Caminhos(args.fonte).criar()
    taxonomia = carregar_taxonomia()
    gabarito = carregar_gabarito(Path(args.gabarito), taxonomia)
    linhas = []
    for provedor in args.provedores:
        rotulo = _rotulo(config, provedor)
        try:
            previsoes = carregar_classificacoes(caminhos.classificacoes(rotulo))
        except FileNotFoundError:
            print(f"  (sem classificações de {provedor}, pulando)")
            continue
        aval = avaliar(previsoes, gabarito, taxonomia)
        latencia = previsoes["latencia_s"].astype(float).mean()
        linhas.append(
            f"| {provedor} | `{_modelo(config, provedor)}` | {aval['n']} | {aval['acuracia']:.1%} | "
            f"{aval['kappa']:.2f} | {aval['f1_macro']:.2f} | {aval['acuracia_acionavel']:.1%} | {latencia:.2f} s |"
        )
    if not linhas:
        print("Nenhuma execução encontrada para comparar.")
        return
    tabela = "\n".join([
        "| Classificador | Modelo | Casos | Acurácia | Kappa | F1 macro | Acerto acionável | Latência média |",
        "|---|---|---|---|---|---|---|---|",
        *linhas,
    ])
    destino = caminhos.relatorio / "comparacao_classificadores.md"
    destino.write_text(f"# Comparação de classificadores ({args.fonte})\n\n{tabela}\n", encoding="utf-8")
    print(tabela)
    print(f"\nSalvo em {destino.relative_to(RAIZ)}")


def cmd_demo(args, config) -> None:
    """Roda o pipeline inteiro nas duas amostras, com o baseline de regras (sem API)."""
    for fonte, (arquivo, gabarito) in AMOSTRAS.items():
        print(f"\n=== {fonte} (amostra sintética) ===")
        base = argparse.Namespace(fonte=fonte, arquivo=str(arquivo), provedor="regras", contas=None)
        cmd_preparar(base, config)
        cmd_classificar(base, config)
        cmd_relatorio(argparse.Namespace(**vars(base), gabarito=str(gabarito), hipoteses=False), config)


# ----------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> None:
    load_dotenv(RAIZ / ".env")
    parser = argparse.ArgumentParser(description="Classificador de motivos de recontato com LLM")
    parser.add_argument("--config", help="caminho de um config.yaml alternativo")
    sub = parser.add_subparsers(dest="comando", required=True)

    def com_fonte(p):
        p.add_argument("--fonte", choices=FONTES, required=True, help="twcs (Twitter/Kaggle) ou b2b (amostra em português)")
        return p

    def com_provedor(p):
        p.add_argument("--provedor", choices=["gemini", "ollama", "regras"], help="padrão: o do config.yaml")
        p.add_argument("--modelo", help="sobrescreve o modelo do provedor escolhido")
        return p

    p = com_fonte(sub.add_parser("preparar", help="monta os contatos e deriva o recontato"))
    p.add_argument("--arquivo", help="CSV de entrada (padrão: data/raw/twcs.csv ou a amostra B2B)")
    p.add_argument("--janela", type=int, help="janela de recontato em dias (padrão: config.yaml)")

    p = com_provedor(com_fonte(sub.add_parser("classificar", help="classifica uma amostra de recontatos")))
    p.add_argument("--n", type=int, help="tamanho da amostra (padrão: config.yaml)")
    p.add_argument("--contas", nargs="+", help="restringe a amostra a algumas marcas/empresas")

    p = com_fonte(sub.add_parser("rotular", help="exporta planilha para rotulagem manual"))
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--contas", nargs="+")

    p = com_provedor(com_fonte(sub.add_parser("relatorio", help="gera o relatório de negócio")))
    p.add_argument("--gabarito", help="CSV com recontato_id e motivo_real para medir a acurácia")
    p.add_argument("--hipoteses", action="store_true", help="pede ao LLM hipóteses de causa raiz dos principais motivos")

    p = com_fonte(sub.add_parser("comparar", help="compara a acurácia de vários classificadores"))
    p.add_argument("--gabarito", required=True)
    p.add_argument("--provedores", nargs="+", default=["regras", "gemini", "ollama"])

    sub.add_parser("demo", help="roda tudo nas amostras sintéticas, sem API")

    args = parser.parse_args(argv)
    config = carregar_config(Path(args.config) if args.config else None)

    provedor = getattr(args, "provedor", None) or config["llm"]["provedor"]
    if hasattr(args, "provedor"):
        args.provedor = provedor
    sobrescrever = {
        "recontato": {"janela_dias": getattr(args, "janela", None)},
        "classificacao": {"tamanho_amostra": getattr(args, "n", None) if args.comando == "classificar" else None},
        "llm": {provedor: {"modelo": getattr(args, "modelo", None)}} if provedor in ("gemini", "ollama") else {},
    }
    config = mesclar(config, sobrescrever)

    comandos = {
        "preparar": cmd_preparar, "classificar": cmd_classificar, "rotular": cmd_rotular,
        "relatorio": cmd_relatorio, "comparar": cmd_comparar, "demo": cmd_demo,
    }
    try:
        comandos[args.comando](args, config)
    except (FileNotFoundError, ValueError, ErroDeProvedor) as erro:
        print(f"\nErro: {erro}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
