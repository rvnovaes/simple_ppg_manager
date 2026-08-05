"""Fluxo real pelos endpoints do catálogo de disciplinas.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade, sem mock de
ORM. A secretaria precisa de uma Person ativa no programa — é dela que
current_program tira o tenant.
"""

import json

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Discipline, Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/programs/disciplines/"


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


def _patch(client: Client, discipline_id: int, payload: dict):
    return client.patch(
        f"{URL}{discipline_id}/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_criar_disciplina_devolve_201_e_grava_auditoria(
    client_secretaria, secretaria_no_programa, program
):
    resposta = _post(client_secretaria, {"code": "DIR001", "name": "Teoria do Estado"})

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["code"] == "DIR001"
    assert corpo["name"] == "Teoria do Estado"
    assert corpo["is_active"] is True
    # O programa vem da requisição, não do payload.
    assert corpo["program_id"] == program.id

    log = AuditLog.objects.get(event="programs.discipline.create")
    assert log.actor.username == "secretaria"
    assert log.program_id == program.id
    assert log.target_id == str(corpo["id"])
    assert log.payload["code"] == "DIR001"


def test_criar_disciplina_ignora_programa_do_payload(
    client_secretaria, secretaria_no_programa, program, outro_programa
):
    """Payload não escolhe tenant: campo extra é descartado pelo schema."""
    resposta = _post(
        client_secretaria,
        {
            "code": "DIR001",
            "name": "Teoria do Estado",
            "program_id": outro_programa.id,
        },
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["program_id"] == program.id


def test_criar_disciplina_com_codigo_repetido_devolve_400(
    client_secretaria, secretaria_no_programa, program
):
    Discipline.objects.create(program=program, code="DIR001", name="Teoria do Estado")

    resposta = _post(client_secretaria, {"code": "DIR001", "name": "Outra"})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_code"
    assert Discipline.objects.count() == 1


def test_criar_disciplina_com_codigo_repetido_em_outro_programa_e_permitido(
    client_secretaria, secretaria_no_programa, program, outro_programa
):
    """Código é único dentro do programa, não globalmente."""
    Discipline.objects.create(
        program=outro_programa, code="DIR001", name="Macroeconomia"
    )

    resposta = _post(client_secretaria, {"code": "DIR001", "name": "Teoria do Estado"})

    assert resposta.status_code == 201, resposta.content


def test_criar_disciplina_sem_permissao_devolve_403(client_sem_permissao):
    resposta = _post(client_sem_permissao, {"code": "DIR001", "name": "Teoria"})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not Discipline.objects.exists()


def test_criar_disciplina_sem_sessao_devolve_401(client):
    assert _post(client, {"code": "DIR001", "name": "Teoria"}).status_code == 401


def test_listar_disciplinas_escopa_pelo_programa_da_requisicao(
    client_secretaria, secretaria_no_programa, program, outro_programa
):
    Discipline.objects.create(program=program, code="DIR001", name="Teoria do Estado")
    Discipline.objects.create(program=outro_programa, code="ECO001", name="Macro")

    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200
    codigos = {item["code"] for item in resposta.json()["items"]}
    assert codigos == {"DIR001"}


def test_listar_disciplinas_filtra_por_is_active(
    client_secretaria, secretaria_no_programa, program
):
    Discipline.objects.create(program=program, code="DIR001", name="Teoria do Estado")
    Discipline.objects.create(
        program=program, code="DIR002", name="Antiga", is_active=False
    )

    ativas = client_secretaria.get(URL, {"is_active": "true"}).json()["items"]
    inativas = client_secretaria.get(URL, {"is_active": "false"}).json()["items"]

    assert {item["code"] for item in ativas} == {"DIR001"}
    assert {item["code"] for item in inativas} == {"DIR002"}
    # Sem o filtro, as duas aparecem.
    assert len(client_secretaria.get(URL).json()["items"]) == 2


def test_listar_disciplinas_busca_por_codigo_e_por_nome(
    client_secretaria, secretaria_no_programa, program
):
    Discipline.objects.create(program=program, code="DIR001", name="Teoria do Estado")
    Discipline.objects.create(program=program, code="ECO900", name="Direito Econômico")

    por_codigo = client_secretaria.get(URL, {"search": "eco9"}).json()["items"]
    por_nome = client_secretaria.get(URL, {"search": "teoria"}).json()["items"]

    # Uma caixa de busca só, insensível a caixa alta, sobre código OU nome.
    assert {item["code"] for item in por_codigo} == {"ECO900"}
    assert {item["code"] for item in por_nome} == {"DIR001"}


def test_listar_disciplinas_exige_permissao(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 403


def test_alterar_disciplina_devolve_200_e_grava_auditoria(
    client_secretaria, secretaria_no_programa, program
):
    disciplina = Discipline.objects.create(
        program=program, code="DIR001", name="Teoria do Estado"
    )

    resposta = _patch(client_secretaria, disciplina.id, {"name": "Teoria Geral"})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["name"] == "Teoria Geral"
    disciplina.refresh_from_db()
    assert disciplina.name == "Teoria Geral"

    log = AuditLog.objects.get(event="programs.discipline.update")
    assert log.program_id == program.id
    assert log.payload["fields"] == ["name"]


def test_alterar_disciplina_desativa(
    client_secretaria, secretaria_no_programa, program
):
    disciplina = Discipline.objects.create(
        program=program, code="DIR001", name="Teoria do Estado"
    )

    resposta = _patch(client_secretaria, disciplina.id, {"is_active": False})

    assert resposta.status_code == 200
    disciplina.refresh_from_db()
    assert disciplina.is_active is False
    # Campo ausente do corpo não é tocado.
    assert disciplina.name == "Teoria do Estado"


def test_alterar_disciplina_de_outro_programa_devolve_404(
    client_secretaria, secretaria_no_programa, outro_programa
):
    """Fora do escopo, a disciplina nem existe — não é 403, é 404."""
    disciplina = Discipline.objects.create(
        program=outro_programa, code="ECO001", name="Macro"
    )

    resposta = _patch(client_secretaria, disciplina.id, {"name": "Micro"})

    assert resposta.status_code == 404
    disciplina.refresh_from_db()
    assert disciplina.name == "Macro"


def test_alterar_disciplina_para_codigo_ja_usado_devolve_400(
    client_secretaria, secretaria_no_programa, program
):
    Discipline.objects.create(program=program, code="DIR001", name="Teoria do Estado")
    outra = Discipline.objects.create(program=program, code="DIR002", name="Processo")

    resposta = _patch(client_secretaria, outra.id, {"code": "DIR001"})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_code"


def test_alterar_disciplina_mantendo_o_proprio_codigo_e_permitido(
    client_secretaria, secretaria_no_programa, program
):
    """A checagem de duplicata não pode enxergar a própria disciplina."""
    disciplina = Discipline.objects.create(
        program=program, code="DIR001", name="Teoria do Estado"
    )

    resposta = _patch(
        client_secretaria, disciplina.id, {"code": "DIR001", "is_active": False}
    )

    assert resposta.status_code == 200, resposta.content


def test_alterar_disciplina_sem_permissao_devolve_403(client_sem_permissao, program):
    disciplina = Discipline.objects.create(
        program=program, code="DIR001", name="Teoria do Estado"
    )

    resposta = _patch(client_sem_permissao, disciplina.id, {"name": "Outro"})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_escrita_sem_token_csrf_e_recusada(secretaria, secretaria_no_programa):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    assert _post(client, {"code": "DIR001", "name": "Teoria"}).status_code == 403
    assert not Discipline.objects.exists()
