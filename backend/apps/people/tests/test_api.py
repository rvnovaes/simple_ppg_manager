"""Fluxo real pelos endpoints.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade, sem mock de
ORM e sem testar "camada service" isolada.
"""

import json

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.people.models import Person

pytestmark = pytest.mark.django_db

URL = "/api/v1/people/"


def _post(client: Client, url: str, payload: dict):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def test_criar_pessoa_devolve_201_e_grava_auditoria(client_secretaria, program):
    resposta = _post(
        client_secretaria,
        URL,
        {
            "program_id": program.id,
            "full_name": "Ana Lima",
            "primary_email": "ana@exemplo.br",
            "phone_number": "(61) 99999-0000",
        },
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["full_name"] == "Ana Lima"
    assert corpo["status"] == Person.Status.ACTIVE

    log = AuditLog.objects.get(event="people.create")
    assert log.actor.username == "secretaria"
    assert log.program_id == program.id
    assert log.target_id == str(corpo["id"])


def test_criar_pessoa_sem_permissao_devolve_403(client_sem_permissao, program):
    resposta = _post(
        client_sem_permissao,
        URL,
        {
            "program_id": program.id,
            "full_name": "Ana Lima",
            "primary_email": "ana@exemplo.br",
        },
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not Person.objects.exists()


def test_criar_pessoa_sem_sessao_devolve_401(client, program):
    resposta = _post(
        client,
        URL,
        {
            "program_id": program.id,
            "full_name": "Ana Lima",
            "primary_email": "ana@exemplo.br",
        },
    )

    assert resposta.status_code == 401


def test_arquivar_duas_vezes_devolve_409_com_code(client_secretaria, program):
    person = Person.objects.create(
        program=program, full_name="Ana Lima", primary_email="ana@exemplo.br"
    )

    primeira = client_secretaria.post(f"{URL}{person.id}/archive")
    assert primeira.status_code == 200
    assert primeira.json()["status"] == Person.Status.ARCHIVED
    assert AuditLog.objects.filter(event="people.archive").count() == 1

    segunda = client_secretaria.post(f"{URL}{person.id}/archive")
    assert segunda.status_code == 409
    assert segunda.json()["code"] == "invalid_state_transition"
    # A segunda tentativa não pode ter gerado auditoria.
    assert AuditLog.objects.filter(event="people.archive").count() == 1


def test_listar_pessoas_exige_permissao(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 403


def test_escrita_sem_token_csrf_e_recusada(secretaria, program):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    resposta = _post(
        client,
        URL,
        {
            "program_id": program.id,
            "full_name": "Ana Lima",
            "primary_email": "ana@exemplo.br",
        },
    )

    assert resposta.status_code == 403
    assert not Person.objects.exists()


def test_listar_pessoas_filtra_por_email(client_secretaria, secretaria, program):
    """A tela procura a pessoa pelo e-mail antes de tentar criar outra e
    bater na UniqueConstraint (program, primary_email)."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    Person.objects.create(
        program=program, full_name="Ana Lima", primary_email="ana@exemplo.br"
    )

    resposta = client_secretaria.get(URL, {"email": "ANA@exemplo.br"})

    assert resposta.status_code == 200, resposta.content
    assert [item["full_name"] for item in resposta.json()["items"]] == ["Ana Lima"]


def test_listar_pessoas_com_email_inexistente_devolve_lista_vazia(
    client_secretaria, secretaria, program
):
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )

    resposta = client_secretaria.get(URL, {"email": "ninguem@exemplo.br"})

    assert resposta.status_code == 200
    assert resposta.json()["items"] == []
