"""Fluxo real pelos endpoints de professor.

Nível (b) da pirâmide: bate no endpoint, sem mock de ORM. Os casos que só
existem aqui são os do payload de duas caras (pessoa existente x pessoa
nova) e o do person_id de outro programa, que precisa ser recusado antes
de qualquer escrita.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/teachers/"


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
def projeto(program, linha) -> CollectiveProject:
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )


@pytest.fixture
def pessoa(program) -> Person:
    return Person.objects.create(
        program=program,
        full_name="Ana Ribeiro",
        primary_email="ana@exemplo.br",
    )


@pytest.fixture
def pessoa_de_outro_programa(outro_programa) -> Person:
    return Person.objects.create(
        program=outro_programa,
        full_name="Bruno Alves",
        primary_email="bruno@exemplo.br",
    )


VINCULO = {
    "category": "permanent",
    "accredited_since": "2026-03-01",
    "academic_degree": "doctorate",
}


def _post(client: Client, payload: dict):
    return client.post(URL, data=json.dumps(payload), content_type="application/json")


def _patch(client: Client, teacher_id: int, payload: dict):
    return client.patch(
        f"{URL}{teacher_id}/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_criar_professor_com_pessoa_existente(
    client_secretaria, secretaria_no_programa, program, pessoa, linha, projeto
):
    resposta = _post(
        client_secretaria,
        {
            **VINCULO,
            "person_id": pessoa.id,
            "research_line_ids": [linha.id],
            "project_ids": [projeto.id],
        },
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["person"]["full_name"] == "Ana Ribeiro"
    assert corpo["person"]["primary_email"] == "ana@exemplo.br"
    # O programa vem da requisição, não do payload.
    assert corpo["program_id"] == program.id
    assert corpo["research_line_ids"] == [linha.id]
    assert corpo["project_ids"] == [projeto.id]

    log = AuditLog.objects.get(event="academic.teacher.create")
    assert log.actor.username == "secretaria"
    assert log.program_id == program.id
    assert log.target_id == str(corpo["id"])


def test_criar_professor_com_pessoa_nova_cria_pessoa_usuario_e_papel(
    client_secretaria, secretaria_no_programa, program
):
    resposta = _post(
        client_secretaria,
        {
            **VINCULO,
            "full_name": "Ana Ribeiro",
            "primary_email": "ana@exemplo.br",
            "phone_number": "31999990000",
        },
    )

    assert resposta.status_code == 201, resposta.content
    pessoa = Person.objects.get(primary_email="ana@exemplo.br")
    assert pessoa.program_id == program.id
    assert pessoa.phone_number == "31999990000"
    assert pessoa.user is not None
    assert pessoa.user.groups.filter(name="Docente").exists()
    assert AuditLog.objects.filter(event="accounts.user.assign_role_group").exists()


def test_criar_professor_com_pessoa_existente_tambem_da_papel_docente(
    client_secretaria, secretaria_no_programa, program, pessoa
):
    # Conta própria: a UniqueConstraint unique_conta_por_programa proíbe
    # duas Person do mesmo programa apontando para o mesmo usuário.
    pessoa.user = User.objects.create_user(username="ana@exemplo.br")
    pessoa.save(update_fields=["user"])

    resposta = _post(client_secretaria, {**VINCULO, "person_id": pessoa.id})

    assert resposta.status_code == 201, resposta.content
    assert pessoa.user.groups.filter(name="Docente").exists()


def test_criar_professor_com_pessoa_de_outro_programa_devolve_404(
    client_secretaria, secretaria_no_programa, pessoa_de_outro_programa
):
    """Pessoa fora do tenant não existe para esta requisição — 404, e não
    403, que revelaria que o id existe."""
    resposta = _post(
        client_secretaria, {**VINCULO, "person_id": pessoa_de_outro_programa.id}
    )

    assert resposta.status_code == 404, resposta.content
    assert not Teacher.objects.exists()


def test_criar_professor_com_pessoa_inexistente_devolve_404(
    client_secretaria, secretaria_no_programa
):
    resposta = _post(client_secretaria, {**VINCULO, "person_id": 9999})

    assert resposta.status_code == 404
    assert not Teacher.objects.exists()


def test_criar_professor_com_person_id_e_pessoa_nova_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa
):
    resposta = _post(
        client_secretaria,
        {
            **VINCULO,
            "person_id": pessoa.id,
            "full_name": "Ana Ribeiro",
            "primary_email": "ana@exemplo.br",
        },
    )

    assert resposta.status_code == 422, resposta.content
    assert not Teacher.objects.exists()


def test_criar_professor_sem_pessoa_nenhuma_devolve_422(
    client_secretaria, secretaria_no_programa
):
    resposta = _post(client_secretaria, VINCULO)

    assert resposta.status_code == 422, resposta.content
    assert not Teacher.objects.exists()


def test_criar_professor_com_linha_de_outro_programa_e_recusado(
    client_secretaria, secretaria_no_programa, pessoa, outro_programa
):
    linha_de_fora = ResearchLine.objects.create(
        program=outro_programa, name="Macroeconomia"
    )

    resposta = _post(
        client_secretaria,
        {**VINCULO, "person_id": pessoa.id, "research_line_ids": [linha_de_fora.id]},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "program_mismatch"
    assert not Teacher.objects.exists()


def test_criar_professor_com_linha_inexistente_devolve_404(
    client_secretaria, secretaria_no_programa, pessoa
):
    resposta = _post(
        client_secretaria,
        {**VINCULO, "person_id": pessoa.id, "research_line_ids": [9999]},
    )

    assert resposta.status_code == 404
    assert not Teacher.objects.exists()


def test_criar_professor_com_categoria_invalida_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa
):
    resposta = _post(
        client_secretaria,
        {**VINCULO, "person_id": pessoa.id, "category": "eventual"},
    )

    assert resposta.status_code == 422, resposta.content


def test_criar_professor_sem_permissao_devolve_403(client_sem_permissao, pessoa):
    resposta = _post(client_sem_permissao, {**VINCULO, "person_id": pessoa.id})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not Teacher.objects.exists()


def test_criar_professor_sem_sessao_devolve_401(client, pessoa):
    assert _post(client, {**VINCULO, "person_id": pessoa.id}).status_code == 401


def _teacher(program, person, **extra) -> Teacher:
    extra.setdefault("category", Teacher.Category.PERMANENT)
    return Teacher.objects.create(
        program=program,
        person=person,
        accredited_since="2026-03-01",
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        **extra,
    )


def test_listar_professores_escopa_pelo_programa_da_requisicao(
    client_secretaria,
    secretaria_no_programa,
    program,
    pessoa,
    outro_programa,
    pessoa_de_outro_programa,
):
    _teacher(program, pessoa)
    _teacher(outro_programa, pessoa_de_outro_programa)

    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200
    nomes = {item["person"]["full_name"] for item in resposta.json()["items"]}
    assert nomes == {"Ana Ribeiro"}


def test_listar_professores_filtra_por_categoria(
    client_secretaria, secretaria_no_programa, program, pessoa
):
    outra_pessoa = Person.objects.create(
        program=program, full_name="Beto Lima", primary_email="beto@exemplo.br"
    )
    _teacher(program, pessoa)
    _teacher(program, outra_pessoa, category=Teacher.Category.VISITING)

    resposta = client_secretaria.get(URL, {"category": "visiting"})

    assert resposta.status_code == 200
    nomes = {item["person"]["full_name"] for item in resposta.json()["items"]}
    assert nomes == {"Beto Lima"}


def test_listar_professores_com_categoria_invalida_devolve_422(
    client_secretaria, secretaria_no_programa
):
    assert client_secretaria.get(URL, {"category": "eventual"}).status_code == 422


def test_listar_professores_exige_permissao(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 403


def test_alterar_professor_devolve_200_e_grava_auditoria(
    client_secretaria, secretaria_no_programa, program, pessoa, linha
):
    professor = _teacher(program, pessoa)

    resposta = _patch(
        client_secretaria,
        professor.id,
        {"category": "collaborator", "research_line_ids": [linha.id]},
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["category"] == "collaborator"
    assert corpo["research_line_ids"] == [linha.id]
    professor.refresh_from_db()
    assert professor.category == "collaborator"

    log = AuditLog.objects.get(event="academic.teacher.update")
    assert log.program_id == program.id
    assert log.payload["fields"] == ["category", "research_line_ids"]


def test_alterar_professor_de_outro_programa_devolve_404(
    client_secretaria, secretaria_no_programa, outro_programa, pessoa_de_outro_programa
):
    professor = _teacher(outro_programa, pessoa_de_outro_programa)

    resposta = _patch(client_secretaria, professor.id, {"category": "collaborator"})

    assert resposta.status_code == 404
    professor.refresh_from_db()
    assert professor.category == "permanent"


def test_alterar_professor_com_projeto_de_outro_programa_e_recusado(
    client_secretaria, secretaria_no_programa, program, pessoa, outro_programa
):
    professor = _teacher(program, pessoa)
    linha_de_fora = ResearchLine.objects.create(
        program=outro_programa, name="Macroeconomia"
    )
    projeto_de_fora = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha_de_fora, name="Inflação"
    )

    resposta = _patch(
        client_secretaria, professor.id, {"project_ids": [projeto_de_fora.id]}
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "program_mismatch"
    assert professor.projects.count() == 0


def test_alterar_professor_sem_permissao_devolve_403(
    client_sem_permissao, program, pessoa
):
    professor = _teacher(program, pessoa)

    assert (
        _patch(client_sem_permissao, professor.id, {"category": "visiting"}).status_code
        == 403
    )


def test_papel_docente_existe_para_o_grupo_da_migration(db):
    """Guarda-costas: o service depende do Group criado pela data migration."""
    assert Group.objects.filter(name="Docente").exists()


def test_pessoa_sem_conta_nao_pede_senha_inicial(
    client_secretaria, secretaria_no_programa, program, pessoa
):
    """Sem conta não há senha para definir — a tela não pode oferecer a ação."""
    _teacher(program, pessoa)

    corpo = client_secretaria.get(URL).json()["items"][0]

    assert corpo["person"]["user_id"] is None
    assert corpo["person"]["needs_initial_password"] is False


def test_conta_sem_senha_pede_senha_inicial_e_para_de_pedir_depois(
    client_secretaria, secretaria_no_programa, program
):
    resposta = _post(
        client_secretaria,
        {**VINCULO, "full_name": "Ana Ribeiro", "primary_email": "ana@exemplo.br"},
    )

    # A conta nasce com set_unusable_password(): a Secretaria ainda precisa
    # definir a primeira senha.
    assert resposta.json()["person"]["needs_initial_password"] is True

    usuario = Person.objects.get(primary_email="ana@exemplo.br").user
    assert usuario is not None
    usuario.set_initial_password("senha-forte-do-ppgd")
    usuario.save(update_fields=["password"])

    corpo = client_secretaria.get(URL).json()["items"][0]
    assert corpo["person"]["user_id"] == usuario.id
    assert corpo["person"]["needs_initial_password"] is False
