"""Testa a reconstrução de conversas e a regra de recontato em dados mínimos e conhecidos."""

import csv

import pytest

from recontato.config import Caminhos
from recontato.preparacao import conectar, preparar

COLUNAS = ["tweet_id", "author_id", "inbound", "created_at", "text", "response_tweet_id", "in_response_to_tweet_id"]


def _data(dia: int, hora: int = 10) -> str:
    return f"Mon Oct {dia:02d} {hora:02d}:00:00 +0000 2017"


@pytest.fixture
def base_twitter(tmp_path):
    linhas = [
        # Cliente 1 / Marca A: contato no dia 1, volta no dia 3 (recontato), volta no dia 20 (não é recontato)
        [1, "111", "True", _data(1), "@MarcaA meu pedido atrasou", "2", ""],
        [2, "MarcaA", "False", _data(1, 11), "@111 vamos verificar", "3", "1.0"],
        [3, "111", "True", _data(1, 12), "@MarcaA ok", "", "2.0"],
        [4, "111", "True", _data(3), "@MarcaA ainda nada do pedido", "5", ""],
        [5, "MarcaA", "False", _data(3, 11), "@111 desculpe", "", "4.0"],
        [6, "111", "True", _data(20), "@MarcaA outra dúvida", "7", ""],
        [7, "MarcaA", "False", _data(20, 11), "@111 claro", "", "6.0"],
        # Cliente 2: conversa sem resposta da marca
        [8, "222", "True", _data(2), "@MarcaA alguém?", "", ""],
        # Resposta a um tweet que não está na base: vira raiz, mas não é de cliente
        [9, "MarcaA", "False", _data(4), "@333 oi", "", "99999.0"],
        # Terceiro entrando na conversa do cliente 4 (deve ser descartado)
        [10, "444", "True", _data(5), "@MarcaB cobrança indevida @555", "11,12", ""],
        [11, "MarcaB", "False", _data(5, 11), "@444 vamos ver", "", "10.0"],
        [12, "999", "True", _data(5, 12), "@444 comigo também!", "", "10.0"],
        # Contato tardio (dia 30) para dar janela observável aos anteriores
        [13, "777", "True", _data(30), "@MarcaB oi", "14", ""],
        [14, "MarcaB", "False", _data(30, 11), "@777 olá", "", "13.0"],
    ]
    arquivo = tmp_path / "twcs_teste.csv"
    with open(arquivo, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUNAS)
        w.writerows(linhas)
    return arquivo


def test_conversas_e_recontato(base_twitter, tmp_path):
    caminhos = Caminhos("twcs", raiz=tmp_path)
    resumo = preparar("twcs", base_twitter, 7, caminhos)

    assert resumo["tweets_lidos"] == 14
    assert resumo["conversas_iniciadas_por_cliente_sem_resposta"] == 1  # tweet 8

    con = conectar(caminhos, somente_leitura=True)
    contatos = con.execute("SELECT * FROM contatos_flag ORDER BY inicio").df().set_index("contato_id")

    # 1, 4, 6, 10 e 13 viram contatos; 8 (sem resposta) e 9 (raiz da marca) não
    assert sorted(contatos.index) == sorted(["1", "4", "6", "10", "13"])
    assert contatos.loc["4", "eh_recontato"]
    assert contatos.loc["1", "gerou_recontato"]
    assert not contatos.loc["6", "eh_recontato"]  # 17 dias depois: fora da janela
    assert contatos.loc["10", "conta"] == "MarcaB"

    # O terceiro (999) que entrou na conversa não aparece na transcrição
    assert "comigo também" not in contatos.loc["10", "transcricao"]
    assert contatos.loc["1", "transcricao"].startswith("Cliente:")
    assert "@cliente vamos verificar" in contatos.loc["1", "transcricao"]  # ID do cliente anonimizado

    recontatos = con.execute("SELECT * FROM recontatos").df()
    assert recontatos["recontato_id"].tolist() == ["4"]
    assert recontatos.loc[0, "contato_anterior_id"] == "1"
    assert recontatos.loc[0, "horas_desde_anterior"] == pytest.approx(46.0)

    # Censura: o contato do dia 30 é o último da base, então não tem janela observável
    assert not contatos.loc["13", "janela_observavel"]
    geral = con.execute("SELECT * FROM indicadores WHERE dimensao = 'geral'").df().iloc[0]
    assert geral["contatos"] == 5
    assert geral["recontatos"] == 1
    assert geral["contatos_observaveis"] == 4
    assert geral["fcr_janela"] == pytest.approx(0.75)
    con.close()


def test_janela_configuravel(base_twitter, tmp_path):
    caminhos = Caminhos("twcs", raiz=tmp_path)
    preparar("twcs", base_twitter, 1, caminhos)  # janela de 1 dia: volta em ~46 h não conta
    con = conectar(caminhos, somente_leitura=True)
    assert con.execute("SELECT count(*) FROM recontatos").fetchone()[0] == 0
    con.close()
