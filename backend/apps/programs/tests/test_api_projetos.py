"""Fluxo real pelos endpoints de projeto coletivo.

Mesmo nível (b) da pirâmide do test_api_linhas: bate no endpoint, sem mock
de ORM. O caso que só existe aqui é o do projeto que aponta para linha de
outro programa — invariante do model, cobrado pela borda como 400.
"""

import json

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine

pytestmark = pytest.mark.django_db

URL = "/api/v1/programs/collective-projects/"


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


@pytest.fixture
def linha(program) -> ResearchLine:
    return ResearchLine.objects.create(program=program, name="Direito e Estado")


@pytest.fixture
def linha_de_outro_programa(outro_programa) -> ResearchLine:
    return ResearchLine.objects.create(program=outro_programa, name="Macroeconomia")


def _post(client: Client, payload: dict):
    return client.post(URL, data=json.dumps(payload), content_type="application/json")


def _patch(client: Client, projeto_id: int, payload: dict):
    return client.patch(
        f"{URL}{projeto_id}/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_criar_projeto_devolve_201_e_grava_auditoria(
    client_secretaria, secretaria_no_programa, program, linha
):
    resposta = _post(
        client_secretaria, {"research_line_id": linha.id, "name": "Justiça e Trabalho"}
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["name"] == "Justiça e Trabalho"
    assert corpo["research_line_id"] == linha.id
    assert corpo["is_active"] is True
    # O programa vem da requisição, não do payload.
    assert corpo["program_id"] == program.id

    log = AuditLog.objects.get(event="programs.collective_project.create")
    assert log.actor.username == "secretaria"
    assert log.program_id == program.id
    assert log.target_id == str(corpo["id"])


def test_criar_projeto_ignora_programa_do_payload(
    client_secretaria, secretaria_no_programa, program, outro_programa, linha
):
    resposta = _post(
        client_secretaria,
        {
            "research_line_id": linha.id,
            "name": "Justiça e Trabalho",
            "program_id": outro_programa.id,
        },
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["program_id"] == program.id


def test_criar_projeto_com_linha_de_outro_programa_e_recusado(
    client_secretaria, secretaria_no_programa, linha_de_outro_programa
):
    """O invariante do model é o que impede AuditLog com tenant errado."""
    resposta = _post(
        client_secretaria,
        {"research_line_id": linha_de_outro_programa.id, "name": "Justiça e Trabalho"},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "program_mismatch"
    assert not CollectiveProject.objects.exists()


def test_criar_projeto_com_linha_inexistente_devolve_404(
    client_secretaria, secretaria_no_programa
):
    resposta = _post(
        client_secretaria, {"research_line_id": 9999, "name": "Justiça e Trabalho"}
    )

    assert resposta.status_code == 404
    assert not CollectiveProject.objects.exists()


def test_criar_projeto_sem_permissao_devolve_403(client_sem_permissao, linha):
    resposta = _post(
        client_sem_permissao, {"research_line_id": linha.id, "name": "Justiça"}
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not CollectiveProject.objects.exists()


def test_criar_projeto_sem_sessao_devolve_401(client, linha):
    resposta = _post(client, {"research_line_id": linha.id, "name": "Justiça"})

    assert resposta.status_code == 401


def test_listar_projetos_escopa_pelo_programa_da_requisicao(
    client_secretaria,
    secretaria_no_programa,
    program,
    linha,
    outro_programa,
    linha_de_outro_programa,
):
    CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )
    CollectiveProject.objects.create(
        program=outro_programa,
        research_line=linha_de_outro_programa,
        name="Inflação e Câmbio",
    )

    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200
    nomes = {item["name"] for item in resposta.json()["items"]}
    assert nomes == {"Justiça e Trabalho"}


def test_listar_projetos_filtra_por_linha_de_pesquisa(
    client_secretaria, secretaria_no_programa, program, linha
):
    outra_linha = ResearchLine.objects.create(program=program, name="Direito Privado")
    CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )
    CollectiveProject.objects.create(
        program=program, research_line=outra_linha, name="Contratos"
    )

    resposta = client_secretaria.get(URL, {"research_line_id": outra_linha.id})

    assert resposta.status_code == 200
    nomes = {item["name"] for item in resposta.json()["items"]}
    assert nomes == {"Contratos"}


def test_listar_projetos_exige_permissao(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 403


def test_alterar_projeto_devolve_200_e_grava_auditoria(
    client_secretaria, secretaria_no_programa, program, linha
):
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )

    resposta = _patch(client_secretaria, projeto.id, {"name": "Justiça e Renda"})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["name"] == "Justiça e Renda"
    projeto.refresh_from_db()
    assert projeto.name == "Justiça e Renda"

    log = AuditLog.objects.get(event="programs.collective_project.update")
    assert log.program_id == program.id
    assert log.payload["fields"] == ["name"]


def test_alterar_projeto_troca_a_linha_de_pesquisa(
    client_secretaria, secretaria_no_programa, program, linha
):
    outra_linha = ResearchLine.objects.create(program=program, name="Direito Privado")
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )

    resposta = _patch(
        client_secretaria, projeto.id, {"research_line_id": outra_linha.id}
    )

    assert resposta.status_code == 200, resposta.content
    projeto.refresh_from_db()
    assert projeto.research_line_id == outra_linha.id
    # Campo ausente do corpo não é tocado.
    assert projeto.name == "Justiça e Trabalho"


def test_alterar_projeto_para_linha_de_outro_programa_e_recusado(
    client_secretaria, secretaria_no_programa, program, linha, linha_de_outro_programa
):
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )

    resposta = _patch(
        client_secretaria,
        projeto.id,
        {"research_line_id": linha_de_outro_programa.id},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "program_mismatch"
    projeto.refresh_from_db()
    assert projeto.research_line_id == linha.id


def test_alterar_projeto_desativa(
    client_secretaria, secretaria_no_programa, program, linha
):
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )

    resposta = _patch(client_secretaria, projeto.id, {"is_active": False})

    assert resposta.status_code == 200
    projeto.refresh_from_db()
    assert projeto.is_active is False


def test_alterar_projeto_de_outro_programa_devolve_404(
    client_secretaria, secretaria_no_programa, outro_programa, linha_de_outro_programa
):
    """Fora do escopo, o projeto nem existe — não é 403, é 404."""
    projeto = CollectiveProject.objects.create(
        program=outro_programa,
        research_line=linha_de_outro_programa,
        name="Inflação e Câmbio",
    )

    resposta = _patch(client_secretaria, projeto.id, {"name": "Outro"})

    assert resposta.status_code == 404
    projeto.refresh_from_db()
    assert projeto.name == "Inflação e Câmbio"


def test_alterar_projeto_sem_permissao_devolve_403(
    client_sem_permissao, program, linha
):
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )

    resposta = _patch(client_sem_permissao, projeto.id, {"name": "Outro"})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_escrita_sem_token_csrf_e_recusada(secretaria, secretaria_no_programa, linha):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    resposta = _post(client, {"research_line_id": linha.id, "name": "Justiça"})

    assert resposta.status_code == 403
    assert not CollectiveProject.objects.exists()
