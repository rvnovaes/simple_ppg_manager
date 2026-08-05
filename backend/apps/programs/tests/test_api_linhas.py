"""Fluxo real pelos endpoints de linha de pesquisa.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade, sem mock de
ORM. A secretaria precisa de uma Person ativa no programa — é dela que
current_program tira o tenant.
"""

import json

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program, ResearchLine

pytestmark = pytest.mark.django_db

URL = "/api/v1/programs/research-lines/"


@pytest.fixture
def secretaria_no_programa(secretaria, program) -> Person:
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Pós em Economia", acronym="PPGE")


def _post(client: Client, payload: dict):
    return client.post(URL, data=json.dumps(payload), content_type="application/json")


def _patch(client: Client, research_line_id: int, payload: dict):
    return client.patch(
        f"{URL}{research_line_id}/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_criar_linha_devolve_201_e_grava_auditoria(
    client_secretaria, secretaria_no_programa, program
):
    resposta = _post(client_secretaria, {"name": "Direito e Estado"})

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["name"] == "Direito e Estado"
    assert corpo["is_active"] is True
    # O programa vem da requisição, não do payload.
    assert corpo["program_id"] == program.id

    log = AuditLog.objects.get(event="programs.research_line.create")
    assert log.actor.username == "secretaria"
    assert log.program_id == program.id
    assert log.target_id == str(corpo["id"])


def test_criar_linha_ignora_programa_do_payload(
    client_secretaria, secretaria_no_programa, program, outro_programa
):
    """Payload não escolhe tenant: campo extra é descartado pelo schema."""
    resposta = _post(
        client_secretaria, {"name": "Direito e Estado", "program_id": outro_programa.id}
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["program_id"] == program.id


def test_criar_linha_com_nome_repetido_devolve_400(
    client_secretaria, secretaria_no_programa, program
):
    ResearchLine.objects.create(program=program, name="Direito e Estado")

    resposta = _post(client_secretaria, {"name": "Direito e Estado"})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_name"
    assert ResearchLine.objects.count() == 1


def test_criar_linha_sem_permissao_devolve_403(client_sem_permissao):
    resposta = _post(client_sem_permissao, {"name": "Direito e Estado"})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not ResearchLine.objects.exists()


def test_criar_linha_sem_sessao_devolve_401(client):
    assert _post(client, {"name": "Direito e Estado"}).status_code == 401


def test_listar_linhas_escopa_pelo_programa_da_requisicao(
    client_secretaria, secretaria_no_programa, program, outro_programa
):
    ResearchLine.objects.create(program=program, name="Direito e Estado")
    ResearchLine.objects.create(program=outro_programa, name="Macroeconomia")

    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200
    nomes = {item["name"] for item in resposta.json()["items"]}
    assert nomes == {"Direito e Estado"}


def test_listar_linhas_exige_permissao(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 403


def test_alterar_linha_devolve_200_e_grava_auditoria(
    client_secretaria, secretaria_no_programa, program
):
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")

    resposta = _patch(client_secretaria, linha.id, {"name": "Direito e Sociedade"})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["name"] == "Direito e Sociedade"
    linha.refresh_from_db()
    assert linha.name == "Direito e Sociedade"

    log = AuditLog.objects.get(event="programs.research_line.update")
    assert log.program_id == program.id
    assert log.payload["fields"] == ["name"]


def test_alterar_linha_desativa(client_secretaria, secretaria_no_programa, program):
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")

    resposta = _patch(client_secretaria, linha.id, {"is_active": False})

    assert resposta.status_code == 200
    linha.refresh_from_db()
    assert linha.is_active is False
    # Campo ausente do corpo não é tocado.
    assert linha.name == "Direito e Estado"


def test_alterar_linha_de_outro_programa_devolve_404(
    client_secretaria, secretaria_no_programa, outro_programa
):
    """Fora do escopo, a linha nem existe — não é 403, é 404."""
    linha = ResearchLine.objects.create(program=outro_programa, name="Macroeconomia")

    resposta = _patch(client_secretaria, linha.id, {"name": "Microeconomia"})

    assert resposta.status_code == 404
    linha.refresh_from_db()
    assert linha.name == "Macroeconomia"


def test_alterar_linha_para_nome_ja_usado_devolve_400(
    client_secretaria, secretaria_no_programa, program
):
    ResearchLine.objects.create(program=program, name="Direito e Estado")
    outra = ResearchLine.objects.create(program=program, name="Direito e Sociedade")

    resposta = _patch(client_secretaria, outra.id, {"name": "Direito e Estado"})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_name"


def test_alterar_linha_mantendo_o_proprio_nome_e_permitido(
    client_secretaria, secretaria_no_programa, program
):
    """A checagem de duplicata não pode enxergar a própria linha."""
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")

    resposta = _patch(
        client_secretaria, linha.id, {"name": "Direito e Estado", "is_active": False}
    )

    assert resposta.status_code == 200, resposta.content


def test_alterar_linha_sem_permissao_devolve_403(client_sem_permissao, program):
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")

    resposta = _patch(client_sem_permissao, linha.id, {"name": "Outro"})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_escrita_sem_token_csrf_e_recusada(secretaria, secretaria_no_programa):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    assert _post(client, {"name": "Direito e Estado"}).status_code == 403
    assert not ResearchLine.objects.exists()
