"""Endpoints de programa: a listagem interna e a pública.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade. O que
interessa aqui é a fronteira entre as duas rotas — a de dentro exige
permissão e conta o estado do programa; a de fora não exige sessão e não
conta nada além de nome e sigla.
"""

import pytest
from django.test import Client

from apps.programs.models import Program

pytestmark = pytest.mark.django_db

URL_INTERNA = "/api/v1/programs/"
URL_PUBLICA = "/api/v1/programs/public"


@pytest.fixture
def aberto(db) -> Program:
    return Program.objects.create(
        name="Pós em Economia", acronym="PPGE", accepts_self_signup=True
    )


@pytest.fixture
def fechado(db) -> Program:
    return Program.objects.create(
        name="Pós em Filosofia", acronym="PPGFIL", accepts_self_signup=False
    )


@pytest.fixture
def inativo(db) -> Program:
    return Program.objects.create(
        name="Pós em Letras",
        acronym="PPGLET",
        is_active=False,
        accepts_self_signup=True,
    )


def _siglas(resposta) -> set[str]:
    return {programa["acronym"] for programa in resposta.json()}


def test_rota_publica_responde_sem_sessao(client: Client, aberto):
    resposta = client.get(URL_PUBLICA)

    assert resposta.status_code == 200, resposta.content
    assert "PPGE" in _siglas(resposta)


def test_rota_publica_omite_fechado_e_inativo(client: Client, aberto, fechado, inativo):
    siglas = _siglas(client.get(URL_PUBLICA))

    assert "PPGE" in siglas
    assert "PPGFIL" not in siglas
    assert "PPGLET" not in siglas


def test_rota_publica_nao_vaza_estado_interno(client: Client, aberto):
    corpo = client.get(URL_PUBLICA).json()

    programa = next(item for item in corpo if item["acronym"] == "PPGE")
    assert set(programa) == {"id", "name", "acronym"}


def test_rota_publica_limita_por_ip(client: Client, aberto):
    for _ in range(60):
        assert client.get(URL_PUBLICA).status_code == 200

    excedente = client.get(URL_PUBLICA)

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"


def test_listagem_interna_continua_exigindo_permissao(client: Client, aberto):
    assert client.get(URL_INTERNA).status_code in (401, 403)


def test_listagem_interna_mostra_o_flag(client_secretaria: Client, aberto):
    corpo = client_secretaria.get(URL_INTERNA).json()

    programa = next(item for item in corpo if item["acronym"] == "PPGE")
    assert programa["accepts_self_signup"] is True
    assert programa["is_active"] is True
