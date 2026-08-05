"""Fluxo de sessão: login, identidade e logout."""

import json

import pytest

from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
SENHA = "senha-de-teste-123"


def _post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def test_login_valido_cria_sessao_e_audita(client, secretaria):
    resposta = _post(client, LOGIN, {"username": "secretaria", "password": SENHA})

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["username"] == "secretaria"
    assert "people.add_person" in corpo["permissions"]
    # O papel vem junto porque há tela cujo público não se distingue por
    # permissão — ver o comentário em UserOut.groups.
    assert corpo["groups"] == ["Secretaria"]

    assert AuditLog.objects.filter(event="auth.login").count() == 1
    # A sessão vale para as demais rotas.
    assert client.get(ME).status_code == 200


def test_login_invalido_devolve_401(client, secretaria):
    resposta = _post(client, LOGIN, {"username": "secretaria", "password": "errada"})

    assert resposta.status_code == 401
    assert resposta.json()["code"] == "invalid_credentials"
    assert not AuditLog.objects.filter(event="auth.login").exists()


def test_me_sem_sessao_devolve_401(client):
    assert client.get(ME).status_code == 401


def test_logout_encerra_a_sessao(client_secretaria):
    assert client_secretaria.post(LOGOUT).status_code == 200
    assert AuditLog.objects.filter(event="auth.logout").count() == 1
    assert client_secretaria.get(ME).status_code == 401


def test_endpoint_de_csrf_e_publico_e_planta_o_cookie(client):
    resposta = client.get("/api/v1/auth/csrf")

    assert resposta.status_code == 200
    assert "csrftoken" in resposta.cookies
