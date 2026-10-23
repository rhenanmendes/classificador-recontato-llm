import pandas as pd
import pytest

from recontato.avaliacao import avaliar
from recontato.regras import classificar_por_regras
from recontato.taxonomia import carregar_taxonomia

TAX = carregar_taxonomia()


@pytest.mark.parametrize("texto, esperado", [
    ("Cliente: Disseram que o crédito cairia em 2 dias úteis e até hoje nada.", "PROMESSA_NAO_CUMPRIDA"),
    ("Cliente: you said 3 business days, still nothing", "PROMESSA_NAO_CUMPRIDA"),
    ("Cliente: Obrigado, deu certo!", "AGRADECIMENTO_OU_CONFIRMACAO"),
    ("Cliente: o erro continua igual", "PROBLEMA_NAO_RESOLVIDO"),
    ("Cliente: 👍", "INDETERMINADO"),
])
def test_regras(texto, esperado):
    assert classificar_por_regras(texto)[0] == esperado


def test_regras_ignoram_fala_do_atendimento():
    texto = "Cliente: oi\nAtendimento: o prazo é de 3 dias úteis"
    assert classificar_por_regras(texto)[0] == "INDETERMINADO"


def test_avaliacao_metricas():
    gabarito = pd.DataFrame({
        "recontato_id": ["1", "2", "3", "4"],
        "motivo_real": ["PROBLEMA_NAO_RESOLVIDO", "NOVO_ASSUNTO", "PROMESSA_NAO_CUMPRIDA", "NOVO_ASSUNTO"],
    })
    previsoes = pd.DataFrame({
        "recontato_id": ["1", "2", "3", "4", "5"],
        "motivo": ["PROBLEMA_NAO_RESOLVIDO", "NOVO_ASSUNTO", "PROBLEMA_NAO_RESOLVIDO", "NOVO_ASSUNTO", "NOVO_ASSUNTO"],
    })
    r = avaliar(previsoes, gabarito, TAX)
    assert r["n"] == 4
    assert r["acuracia"] == pytest.approx(0.75)
    # O erro (promessa -> problema) troca o motivo, mas ambos são acionáveis
    assert r["acuracia_acionavel"] == pytest.approx(1.0)
    assert r["matriz"].loc["PROMESSA_NAO_CUMPRIDA", "PROBLEMA_NAO_RESOLVIDO"] == 1
    assert len(r["erros"]) == 1
