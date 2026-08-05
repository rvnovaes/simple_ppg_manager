"""Fluxo real pelos endpoints de aluno.

Nível (b) da pirâmide: bate no endpoint, sem mock de ORM. O que só existe
aqui são os casos da modalidade — o regular exige campos de grau, a
isolada e a eletiva os recusam — e o vínculo repetido da mesma pessoa em
períodos diferentes, que a FK de `Student.person` permite (ADR-007 dec. 2).
"""

import json
from datetime import date

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import Student, Teacher
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Program,
    ResearchLine,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/students/"


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


@pytest.fixture
def orientador(program) -> Teacher:
    pessoa = Person.objects.create(
        program=program, full_name="Célia Souza", primary_email="celia@exemplo.br"
    )
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 3, 1),
    )


@pytest.fixture
def periodo(db) -> AcademicTerm:
    return AcademicTerm.objects.create(
        year=2026, half=1, starts_on=date(2026, 3, 2), ends_on=date(2026, 7, 18)
    )


def _post(client: Client, payload: dict):
    return client.post(URL, data=json.dumps(payload), content_type="application/json")


def _patch(client: Client, student_id: int, payload: dict):
    return client.patch(
        f"{URL}{student_id}/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def _regular(projeto, **extra) -> dict:
    return {
        "modality": "regular",
        "level": "masters",
        "project_id": projeto.id,
        "admission_date": "2026-03-02",
        **extra,
    }


def _isolada(periodo, **extra) -> dict:
    return {"modality": "isolated", "term_id": periodo.id, **extra}


def test_criar_aluno_regular_com_pessoa_existente(
    client_secretaria, secretaria_no_programa, program, pessoa, projeto
):
    resposta = _post(client_secretaria, _regular(projeto, person_id=pessoa.id))

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["person"]["full_name"] == "Ana Ribeiro"
    assert corpo["program_id"] == program.id
    assert corpo["modality"] == "regular"
    assert corpo["status"] == "active"
    # Prazo regimental calculado pelo model: mestrado são 24 meses.
    assert corpo["deadline"] == "2028-03-02"

    log = AuditLog.objects.get(event="academic.student.create")
    assert log.actor.username == "secretaria"
    assert log.program_id == program.id
    assert log.payload["modality"] == "regular"


def test_criar_aluno_regular_com_pessoa_nova_cria_conta_e_papel_discente(
    client_secretaria, secretaria_no_programa, program, projeto
):
    resposta = _post(
        client_secretaria,
        _regular(
            projeto,
            full_name="Ana Ribeiro",
            primary_email="ana@exemplo.br",
            phone_number="31999990000",
        ),
    )

    assert resposta.status_code == 201, resposta.content
    pessoa = Person.objects.get(primary_email="ana@exemplo.br")
    assert pessoa.program_id == program.id
    assert pessoa.user is not None
    assert pessoa.user.groups.filter(name="Discente").exists()


def test_criar_aluno_de_isolada_nao_recebe_papel_discente(
    client_secretaria, secretaria_no_programa, periodo
):
    """Isolada dura um semestre e não dá acesso ao sistema do programa."""
    resposta = _post(
        client_secretaria,
        _isolada(periodo, full_name="Ana Ribeiro", primary_email="ana@exemplo.br"),
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["term_id"] == periodo.id
    pessoa = Person.objects.get(primary_email="ana@exemplo.br")
    assert not pessoa.user.groups.filter(name="Discente").exists()


def test_criar_aluno_regular_sem_projeto_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa
):
    resposta = _post(
        client_secretaria,
        {
            "modality": "regular",
            "person_id": pessoa.id,
            "level": "masters",
            "admission_date": "2026-03-02",
        },
    )

    assert resposta.status_code == 422, resposta.content
    assert not Student.objects.exists()


def test_criar_aluno_de_isolada_com_campo_de_grau_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa, periodo, projeto
):
    resposta = _post(
        client_secretaria,
        _isolada(periodo, person_id=pessoa.id, project_id=projeto.id),
    )

    assert resposta.status_code == 422, resposta.content
    assert not Student.objects.exists()


def test_criar_aluno_de_isolada_sem_periodo_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa
):
    resposta = _post(
        client_secretaria, {"modality": "isolated", "person_id": pessoa.id}
    )

    assert resposta.status_code == 422, resposta.content
    assert not Student.objects.exists()


def test_criar_aluno_de_isolada_trancado_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa, periodo
):
    resposta = _post(
        client_secretaria, _isolada(periodo, person_id=pessoa.id, status="leave")
    )

    assert resposta.status_code == 422, resposta.content
    assert not Student.objects.exists()


def test_criar_aluno_com_modalidade_invalida_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa
):
    resposta = _post(client_secretaria, {"modality": "ouvinte", "person_id": pessoa.id})

    assert resposta.status_code == 422, resposta.content


def test_criar_aluno_com_pessoa_de_outro_programa_devolve_404(
    client_secretaria, secretaria_no_programa, pessoa_de_outro_programa, projeto
):
    resposta = _post(
        client_secretaria, _regular(projeto, person_id=pessoa_de_outro_programa.id)
    )

    assert resposta.status_code == 404, resposta.content
    assert not Student.objects.exists()


def test_criar_aluno_com_projeto_de_outro_programa_devolve_404(
    client_secretaria, secretaria_no_programa, pessoa, outro_programa
):
    """Projeto fora do tenant não existe para esta requisição."""
    linha_de_fora = ResearchLine.objects.create(
        program=outro_programa, name="Macroeconomia"
    )
    projeto_de_fora = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha_de_fora, name="Inflação"
    )

    resposta = _post(client_secretaria, _regular(projeto_de_fora, person_id=pessoa.id))

    assert resposta.status_code == 404, resposta.content
    assert not Student.objects.exists()


def test_criar_aluno_com_person_id_e_pessoa_nova_devolve_422(
    client_secretaria, secretaria_no_programa, pessoa, projeto
):
    resposta = _post(
        client_secretaria,
        _regular(
            projeto,
            person_id=pessoa.id,
            full_name="Ana Ribeiro",
            primary_email="ana@exemplo.br",
        ),
    )

    assert resposta.status_code == 422, resposta.content
    assert not Student.objects.exists()


def test_criar_aluno_sem_permissao_devolve_403(client_sem_permissao, pessoa, projeto):
    resposta = _post(client_sem_permissao, _regular(projeto, person_id=pessoa.id))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not Student.objects.exists()


def test_criar_aluno_sem_sessao_devolve_401(client, pessoa, projeto):
    assert _post(client, _regular(projeto, person_id=pessoa.id)).status_code == 401


def test_mesma_pessoa_em_dois_periodos_diferentes_pela_api(
    client_secretaria, secretaria_no_programa, pessoa, periodo
):
    """`person` é FK e não OneToOne: a mesma pessoa cursa uma isolada em
    2026/1 e outra em 2026/2, e a API precisa aceitar as duas."""
    outro_periodo = AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 19)
    )

    primeira = _post(client_secretaria, _isolada(periodo, person_id=pessoa.id))
    segunda = _post(client_secretaria, _isolada(outro_periodo, person_id=pessoa.id))

    assert primeira.status_code == 201, primeira.content
    assert segunda.status_code == 201, segunda.content
    assert pessoa.student_records.count() == 2


def _student(program, person, projeto=None, **extra) -> Student:
    extra.setdefault("modality", Student.Modality.REGULAR)
    if extra["modality"] == Student.Modality.REGULAR:
        extra.setdefault("level", Student.Level.MASTERS)
        extra.setdefault("project", projeto)
        extra.setdefault("admission_date", date(2026, 3, 2))
    return Student.objects.create(program=program, person=person, **extra)


def test_listar_alunos_escopa_pelo_programa_da_requisicao(
    client_secretaria,
    secretaria_no_programa,
    program,
    pessoa,
    projeto,
    outro_programa,
    pessoa_de_outro_programa,
):
    _student(program, pessoa, projeto)
    linha_de_fora = ResearchLine.objects.create(
        program=outro_programa, name="Macroeconomia"
    )
    projeto_de_fora = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha_de_fora, name="Inflação"
    )
    _student(outro_programa, pessoa_de_outro_programa, projeto_de_fora)

    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200
    nomes = {item["person"]["full_name"] for item in resposta.json()["items"]}
    assert nomes == {"Ana Ribeiro"}


def test_listar_alunos_filtra_por_modalidade_e_periodo(
    client_secretaria, secretaria_no_programa, program, pessoa, projeto, periodo
):
    outra_pessoa = Person.objects.create(
        program=program, full_name="Beto Lima", primary_email="beto@exemplo.br"
    )
    _student(program, pessoa, projeto)
    _student(program, outra_pessoa, modality=Student.Modality.ISOLATED, term=periodo)

    por_modalidade = client_secretaria.get(URL, {"modality": "isolated"})
    por_periodo = client_secretaria.get(URL, {"term_id": periodo.id})

    assert por_modalidade.status_code == 200
    assert {i["person"]["full_name"] for i in por_modalidade.json()["items"]} == {
        "Beto Lima"
    }
    assert {i["person"]["full_name"] for i in por_periodo.json()["items"]} == {
        "Beto Lima"
    }


def test_listar_alunos_filtra_por_orientador_e_situacao(
    client_secretaria, secretaria_no_programa, program, pessoa, projeto, orientador
):
    outra_pessoa = Person.objects.create(
        program=program, full_name="Beto Lima", primary_email="beto@exemplo.br"
    )
    _student(program, pessoa, projeto, advisor=orientador)
    _student(program, outra_pessoa, projeto, status=Student.Status.LEAVE)

    por_orientador = client_secretaria.get(URL, {"advisor_id": orientador.id})
    por_situacao = client_secretaria.get(URL, {"status": "leave"})

    assert {i["person"]["full_name"] for i in por_orientador.json()["items"]} == {
        "Ana Ribeiro"
    }
    assert {i["person"]["full_name"] for i in por_situacao.json()["items"]} == {
        "Beto Lima"
    }


def test_listar_alunos_com_modalidade_invalida_devolve_422(
    client_secretaria, secretaria_no_programa
):
    assert client_secretaria.get(URL, {"modality": "ouvinte"}).status_code == 422


def test_listar_alunos_exige_permissao(client_sem_permissao):
    assert client_sem_permissao.get(URL).status_code == 403


def test_alterar_situacao_do_aluno_audita_valor_anterior_e_novo(
    client_secretaria, secretaria_no_programa, program, pessoa, projeto
):
    aluno = _student(program, pessoa, projeto)

    resposta = _patch(client_secretaria, aluno.id, {"status": "leave"})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["status"] == "leave"
    aluno.refresh_from_db()
    assert aluno.status == "leave"

    log = AuditLog.objects.get(event="academic.student.update")
    assert log.program_id == program.id
    assert log.payload["status_anterior"] == "active"
    assert log.payload["status_novo"] == "leave"


def test_alterar_aluno_sem_mexer_na_situacao_nao_registra_valor_anterior(
    client_secretaria, secretaria_no_programa, program, pessoa, projeto, orientador
):
    aluno = _student(program, pessoa, projeto)

    resposta = _patch(client_secretaria, aluno.id, {"advisor_id": orientador.id})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["advisor_id"] == orientador.id
    log = AuditLog.objects.get(event="academic.student.update")
    assert log.payload["fields"] == ["advisor"]
    assert "status_anterior" not in log.payload


def test_trancar_aluno_de_isolada_devolve_400(
    client_secretaria, secretaria_no_programa, program, pessoa, periodo
):
    """A CheckConstraint garante o mesmo no banco; pela API o erro é de
    negócio (400), e não IntegrityError."""
    aluno = _student(program, pessoa, modality=Student.Modality.ISOLATED, term=periodo)

    resposta = _patch(client_secretaria, aluno.id, {"status": "leave"})

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "leave_not_allowed"
    aluno.refresh_from_db()
    assert aluno.status == "active"


def test_alterar_aluno_de_outro_programa_devolve_404(
    client_secretaria,
    secretaria_no_programa,
    outro_programa,
    pessoa_de_outro_programa,
):
    linha_de_fora = ResearchLine.objects.create(
        program=outro_programa, name="Macroeconomia"
    )
    projeto_de_fora = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha_de_fora, name="Inflação"
    )
    aluno = _student(outro_programa, pessoa_de_outro_programa, projeto_de_fora)

    resposta = _patch(client_secretaria, aluno.id, {"status": "excluded"})

    assert resposta.status_code == 404
    aluno.refresh_from_db()
    assert aluno.status == "active"


def test_alterar_aluno_sem_permissao_devolve_403(
    client_sem_permissao, program, pessoa, projeto
):
    aluno = _student(program, pessoa, projeto)

    assert (
        _patch(client_sem_permissao, aluno.id, {"status": "leave"}).status_code == 403
    )


def test_papel_discente_existe_para_o_grupo_da_migration(db):
    """Guarda-costas: o service depende do Group criado pela data migration."""
    assert Group.objects.filter(name="Discente").exists()
