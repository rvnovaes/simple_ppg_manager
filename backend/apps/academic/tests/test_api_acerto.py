"""Fluxo real pelo endpoint de abertura do acerto de matrícula.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade, sem mock de
ORM. O que só existe aqui são os dois bloqueios do vínculo — sem orientador
e fora da modalidade regular, ambos 409 — e a tentativa de abrir pedido em
nome de outro aluno.
"""

import json
from datetime import date

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import (
    EnrollmentAdjustmentItem,
    EnrollmentAdjustmentRequest,
    Student,
    Teacher,
)
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Discipline,
    Program,
    ResearchLine,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/enrollment-requests/"
SENHA = "senha-de-teste-123"


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Pós em Economia", acronym="PPGE")


@pytest.fixture
def projeto(program) -> CollectiveProject:
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )


@pytest.fixture
def periodo(db) -> AcademicTerm:
    return AcademicTerm.objects.create(
        year=2026, half=1, starts_on=date(2026, 3, 2), ends_on=date(2026, 7, 10)
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
        accredited_since=date(2020, 1, 1),
    )


@pytest.fixture
def disciplinas(program) -> list[Discipline]:
    return [
        Discipline.objects.create(program=program, code="DIR001", name="Teoria"),
        Discipline.objects.create(program=program, code="DIR002", name="Processo"),
    ]


def _criar_discente(*, program: Program, username: str, nome: str, **campos) -> Student:
    """Discente completo: usuário no papel, Person ativa e vínculo de aluno.

    A Person ativa não é detalhe de fixture — é dela que `current_program`
    tira o tenant da requisição.
    """
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name="Discente"))
    pessoa = Person.objects.create(
        program=program,
        user=user,
        full_name=nome,
        primary_email=f"{username}@exemplo.br",
    )
    return Student.objects.create(program=program, person=pessoa, **campos)


@pytest.fixture
def aluno(program, projeto, orientador) -> Student:
    return _criar_discente(
        program=program,
        username="ana",
        nome="Ana Ribeiro",
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        advisor=orientador,
        admission_date=date(2026, 3, 2),
    )


def _logar(client: Client, aluno: Student) -> Client:
    """`Person.user` é opcional no model (pessoa sem conta é registro
    histórico); aqui o discente sempre tem uma.
    """
    user = aluno.person.user
    assert user is not None
    client.force_login(user)
    return client


@pytest.fixture
def client_aluno(client: Client, aluno: Student) -> Client:
    return _logar(client, aluno)


def _post(client: Client, payload: dict):
    return client.post(URL, data=json.dumps(payload), content_type="application/json")


def _payload(periodo: AcademicTerm, disciplinas: list[Discipline], **extra) -> dict:
    return {
        "term_id": periodo.id,
        "items": [
            {"discipline_id": disciplinas[0].id, "action": "add"},
            {"discipline_id": disciplinas[1].id, "action": "drop"},
        ],
        **extra,
    }


def test_criar_solicitacao_devolve_201_e_grava_auditoria(
    client_aluno, aluno, program, periodo, disciplinas
):
    resposta = _post(
        client_aluno,
        _payload(periodo, disciplinas, justification="Conflito de horário."),
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == "open"
    assert corpo["student_id"] == aluno.id
    assert corpo["term_id"] == periodo.id
    assert corpo["program_id"] == program.id
    assert corpo["justification"] == "Conflito de horário."
    assert corpo["decided_at"] is None
    # Um pedido só, com os dois itens dentro (ADR do acerto: a decisão é
    # sobre o conjunto).
    assert [(item["discipline_code"], item["action"]) for item in corpo["items"]] == [
        ("DIR001", "add"),
        ("DIR002", "drop"),
    ]

    log = AuditLog.objects.get(event="academic.enrollment_adjustment.create")
    assert log.actor.username == "ana"
    assert log.program_id == program.id
    assert log.target_id == str(corpo["id"])
    assert log.payload["student_id"] == aluno.id
    assert len(log.payload["items"]) == 2


def test_criar_solicitacao_ignora_programa_do_payload(
    client_aluno, program, periodo, disciplinas, outro_programa
):
    """Payload não escolhe tenant: campo extra é descartado pelo schema."""
    resposta = _post(
        client_aluno,
        _payload(periodo, disciplinas, program_id=outro_programa.id),
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["program_id"] == program.id


def test_criar_solicitacao_com_student_id_proprio_e_permitido(
    client_aluno, aluno, periodo, disciplinas
):
    resposta = _post(client_aluno, _payload(periodo, disciplinas, student_id=aluno.id))

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["student_id"] == aluno.id


def test_criar_solicitacao_em_nome_de_outro_aluno_devolve_403(
    client_aluno, program, projeto, orientador, periodo, disciplinas
):
    outro = _criar_discente(
        program=program,
        username="bruno",
        nome="Bruno Alves",
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        advisor=orientador,
        admission_date=date(2026, 3, 2),
    )

    resposta = _post(client_aluno, _payload(periodo, disciplinas, student_id=outro.id))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not EnrollmentAdjustmentRequest.objects.exists()


def test_criar_solicitacao_sem_orientador_devolve_409(
    client, program, projeto, periodo, disciplinas
):
    """Sem orientador a solicitação nasceria presa: ninguém a decidiria."""
    aluno = _criar_discente(
        program=program,
        username="carlos",
        nome="Carlos Lima",
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2026, 3, 2),
    )
    _logar(client, aluno)

    resposta = _post(client, _payload(periodo, disciplinas))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "advisor_required"
    assert not EnrollmentAdjustmentRequest.objects.exists()


def test_criar_solicitacao_de_aluno_de_isolada_devolve_409(
    client, program, periodo, disciplinas
):
    """Acerto é do vínculo regular (ADR-007): isolada dura um semestre."""
    aluno = _criar_discente(
        program=program,
        username="dora",
        nome="Dora Melo",
        modality=Student.Modality.ISOLATED,
        term=periodo,
    )
    _logar(client, aluno)

    resposta = _post(client, _payload(periodo, disciplinas))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "regular_students_only"
    assert not EnrollmentAdjustmentRequest.objects.exists()


def test_criar_solicitacao_sem_itens_devolve_422(client_aluno, periodo):
    resposta = _post(client_aluno, {"term_id": periodo.id, "items": []})

    assert resposta.status_code == 422
    assert not EnrollmentAdjustmentRequest.objects.exists()


def test_criar_solicitacao_com_item_repetido_devolve_422(
    client_aluno, periodo, disciplinas
):
    """A UniqueConstraint barraria com 500; a borda barra com 422."""
    resposta = _post(
        client_aluno,
        {
            "term_id": periodo.id,
            "items": [
                {"discipline_id": disciplinas[0].id, "action": "add"},
                {"discipline_id": disciplinas[0].id, "action": "add"},
            ],
        },
    )

    assert resposta.status_code == 422
    assert not EnrollmentAdjustmentItem.objects.exists()


def test_incluir_e_excluir_a_mesma_disciplina_e_permitido(
    client_aluno, periodo, disciplinas
):
    """A unicidade é por (solicitação, disciplina, AÇÃO) — quem julga o
    pedido contraditório é o orientador, não o schema.
    """
    resposta = _post(
        client_aluno,
        {
            "term_id": periodo.id,
            "items": [
                {"discipline_id": disciplinas[0].id, "action": "add"},
                {"discipline_id": disciplinas[0].id, "action": "drop"},
            ],
        },
    )

    assert resposta.status_code == 201, resposta.content


def test_criar_solicitacao_com_disciplina_de_outro_programa_devolve_404(
    client_aluno, periodo, disciplinas, outro_programa
):
    """Fora do escopo, a disciplina nem existe — não é 403, é 404."""
    alheia = Discipline.objects.create(
        program=outro_programa, code="ECO001", name="Macro"
    )

    resposta = _post(
        client_aluno,
        {
            "term_id": periodo.id,
            "items": [{"discipline_id": alheia.id, "action": "add"}],
        },
    )

    assert resposta.status_code == 404
    assert not EnrollmentAdjustmentRequest.objects.exists()


def test_criar_solicitacao_com_periodo_inexistente_devolve_404(
    client_aluno, disciplinas, periodo
):
    resposta = _post(
        client_aluno,
        {
            "term_id": periodo.id + 999,
            "items": [{"discipline_id": disciplinas[0].id, "action": "add"}],
        },
    )

    assert resposta.status_code == 404


def test_criar_solicitacao_sem_permissao_devolve_403(
    client_sem_permissao, periodo, disciplinas
):
    resposta = _post(client_sem_permissao, _payload(periodo, disciplinas))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not EnrollmentAdjustmentRequest.objects.exists()


def test_criar_solicitacao_sem_sessao_devolve_401(client, periodo, disciplinas):
    assert _post(client, _payload(periodo, disciplinas)).status_code == 401


def test_secretaria_nao_abre_solicitacao(client_secretaria, secretaria, program):
    """A Secretaria acompanha o acerto, mas não abre (US-003)."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )

    # Payload válido de propósito: a barreira é a permissão, não o schema.
    resposta = _post(
        client_secretaria,
        {"term_id": 1, "items": [{"discipline_id": 1, "action": "add"}]},
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_escrita_sem_token_csrf_e_recusada(aluno, periodo, disciplinas):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    _logar(client, aluno)

    assert _post(client, _payload(periodo, disciplinas)).status_code == 403
    assert not EnrollmentAdjustmentRequest.objects.exists()
