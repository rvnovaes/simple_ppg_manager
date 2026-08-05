"""Fluxo real pelos endpoints de período letivo.

O que distingue estes testes dos de linha e projeto: período letivo é
institucional (ADR-007 dec. 4), então NÃO há escopo de programa. A
secretaria enxerga o calendário inteiro mesmo sem Person no programa, e o
AuditLog sai com program=None — está correto.
"""

import json

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.programs.models import AcademicTerm

pytestmark = pytest.mark.django_db

URL = "/api/v1/programs/terms/"


@pytest.fixture
def periodo(db) -> AcademicTerm:
    return AcademicTerm.objects.create(
        year=2026, half=1, starts_on="2026-02-02", ends_on="2026-06-30"
    )


def _post(client: Client, payload: dict):
    return client.post(URL, data=json.dumps(payload), content_type="application/json")


def _patch(client: Client, academic_term_id: int, payload: dict):
    return client.patch(
        f"{URL}{academic_term_id}/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_criar_periodo_devolve_201_e_grava_auditoria(client_secretaria):
    resposta = _post(
        client_secretaria,
        {
            "year": 2026,
            "half": 1,
            "starts_on": "2026-02-02",
            "ends_on": "2026-06-30",
        },
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["year"] == 2026
    assert corpo["half"] == 1
    assert corpo["label"] == "2026/1"
    assert corpo["is_active"] is True

    log = AuditLog.objects.get(event="programs.academic_term.create")
    assert log.actor.username == "secretaria"
    # Entidade institucional: sem chave de tenant, e isso é o esperado.
    assert log.program_id is None
    assert log.target_id == str(corpo["id"])


def test_criar_periodo_com_fim_antes_do_inicio_e_recusado(client_secretaria):
    resposta = _post(
        client_secretaria,
        {
            "year": 2026,
            "half": 1,
            "starts_on": "2026-06-30",
            "ends_on": "2026-02-02",
        },
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_term_range"
    assert not AcademicTerm.objects.exists()


def test_criar_periodo_duplicado_e_recusado(client_secretaria, periodo):
    """Ano e semestre repetidos viram 400, não IntegrityError 500."""
    resposta = _post(
        client_secretaria,
        {
            "year": 2026,
            "half": 1,
            "starts_on": "2026-03-01",
            "ends_on": "2026-07-31",
        },
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "duplicate_term"
    assert AcademicTerm.objects.count() == 1


def test_criar_periodo_com_semestre_invalido_e_recusado(client_secretaria):
    resposta = _post(
        client_secretaria,
        {
            "year": 2026,
            "half": 3,
            "starts_on": "2026-02-02",
            "ends_on": "2026-06-30",
        },
    )

    assert resposta.status_code == 422, resposta.content
    assert not AcademicTerm.objects.exists()


def test_criar_periodo_sem_permissao_devolve_403(client_sem_permissao):
    resposta = _post(
        client_sem_permissao,
        {
            "year": 2026,
            "half": 1,
            "starts_on": "2026-02-02",
            "ends_on": "2026-06-30",
        },
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not AcademicTerm.objects.exists()


def test_criar_periodo_sem_sessao_devolve_401(client):
    resposta = _post(
        client,
        {
            "year": 2026,
            "half": 1,
            "starts_on": "2026-02-02",
            "ends_on": "2026-06-30",
        },
    )

    assert resposta.status_code == 401


def test_listar_periodos_nao_escopa_por_programa(client_secretaria, periodo):
    """A secretaria não tem Person aqui — e mesmo assim lista, porque o
    calendário não é de programa nenhum."""
    AcademicTerm.objects.create(
        year=2025, half=2, starts_on="2025-08-04", ends_on="2025-12-19"
    )

    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200, resposta.content
    rotulos = [item["label"] for item in resposta.json()["items"]]
    # ordering do model: mais recente primeiro.
    assert rotulos == ["2026/1", "2025/2"]


def test_listar_periodos_exige_permissao(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 403


def test_alterar_periodo_devolve_200_e_grava_auditoria(client_secretaria, periodo):
    resposta = _patch(client_secretaria, periodo.id, {"ends_on": "2026-07-15"})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["ends_on"] == "2026-07-15"
    periodo.refresh_from_db()
    assert str(periodo.ends_on) == "2026-07-15"

    log = AuditLog.objects.get(event="programs.academic_term.update")
    assert log.program_id is None
    assert log.payload["fields"] == ["ends_on"]


def test_alterar_periodo_desativa(client_secretaria, periodo):
    resposta = _patch(client_secretaria, periodo.id, {"is_active": False})

    assert resposta.status_code == 200
    periodo.refresh_from_db()
    assert periodo.is_active is False


def test_alterar_periodo_para_intervalo_invalido_e_recusado(client_secretaria, periodo):
    resposta = _patch(client_secretaria, periodo.id, {"ends_on": "2026-01-01"})

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_term_range"
    periodo.refresh_from_db()
    assert str(periodo.ends_on) == "2026-06-30"


def test_alterar_periodo_para_ano_e_semestre_ja_usados_e_recusado(
    client_secretaria, periodo
):
    outro = AcademicTerm.objects.create(
        year=2025, half=2, starts_on="2025-08-04", ends_on="2025-12-19"
    )

    resposta = _patch(client_secretaria, outro.id, {"year": 2026, "half": 1})

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "duplicate_term"
    outro.refresh_from_db()
    assert outro.year == 2025


def test_alterar_periodo_inexistente_devolve_404(client_secretaria):
    assert _patch(client_secretaria, 9999, {"is_active": False}).status_code == 404


def test_alterar_periodo_sem_permissao_devolve_403(client_sem_permissao, periodo):
    resposta = _patch(client_sem_permissao, periodo.id, {"is_active": False})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_escrita_sem_token_csrf_e_recusada(secretaria):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    resposta = _post(
        client,
        {
            "year": 2026,
            "half": 1,
            "starts_on": "2026-02-02",
            "ends_on": "2026-06-30",
        },
    )

    assert resposta.status_code == 403
    assert not AcademicTerm.objects.exists()
