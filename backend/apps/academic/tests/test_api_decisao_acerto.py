"""Fluxo real pelos endpoints de decisão do acerto de matrícula.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade, sem mock de
ORM. O que só existe aqui é a checagem que a permissão de grupo não cobre —
`change_enrollmentadjustmentrequest` diz que docente decide acerto, não QUAL
acerto — e a transição inválida da solicitação já decidida.
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

SENHA = "senha-de-teste-123"


def _url(solicitacao: EnrollmentAdjustmentRequest, acao: str) -> str:
    return f"/api/v1/academic/enrollment-requests/{solicitacao.id}/{acao}"


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
def disciplina(program) -> Discipline:
    return Discipline.objects.create(program=program, code="DIR001", name="Teoria")


def _criar_docente(*, program: Program, username: str, nome: str) -> Teacher:
    """Docente com conta no papel e Person ativa.

    A Person ativa não é detalhe de fixture — é dela que `current_program`
    tira o tenant da requisição, e é por ela que o router liga o usuário
    logado ao Teacher que orienta.
    """
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    pessoa = Person.objects.create(
        program=program,
        user=user,
        full_name=nome,
        primary_email=f"{username}@exemplo.br",
    )
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 1, 1),
    )


@pytest.fixture
def orientador(program) -> Teacher:
    return _criar_docente(program=program, username="celia", nome="Célia Souza")


@pytest.fixture
def aluno(program, projeto, orientador) -> Student:
    user = User.objects.create_user(username="ana", password=SENHA)
    user.groups.add(Group.objects.get(name="Discente"))
    pessoa = Person.objects.create(
        program=program,
        user=user,
        full_name="Ana Ribeiro",
        primary_email="ana@exemplo.br",
    )
    return Student.objects.create(
        program=program,
        person=pessoa,
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        advisor=orientador,
        admission_date=date(2026, 3, 2),
    )


@pytest.fixture
def solicitacao(program, aluno, periodo, disciplina) -> EnrollmentAdjustmentRequest:
    pedido = EnrollmentAdjustmentRequest.objects.create(
        program=program,
        student=aluno,
        term=periodo,
        justification="Conflito de horário.",
    )
    EnrollmentAdjustmentItem.objects.create(
        request=pedido,
        discipline=disciplina,
        action=EnrollmentAdjustmentItem.Action.ADD,
    )
    return pedido


def _logar(client: Client, teacher: Teacher) -> Client:
    """`Person.user` é opcional no model (pessoa sem conta é registro
    histórico); aqui o docente sempre tem uma.
    """
    user = teacher.person.user
    assert user is not None
    client.force_login(user)
    return client


@pytest.fixture
def client_orientador(client: Client, orientador: Teacher) -> Client:
    return _logar(client, orientador)


def _post(client: Client, url: str, payload: dict):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def test_aprovar_devolve_200_e_grava_auditoria(client_orientador, solicitacao, program):
    resposta = _post(client_orientador, _url(solicitacao, "approve"), {})

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == "approved"
    assert corpo["decided_at"] is not None
    assert corpo["decision_note"] == ""
    # A decisão é sobre o conjunto: os itens continuam na resposta.
    assert [item["discipline_code"] for item in corpo["items"]] == ["DIR001"]

    solicitacao.refresh_from_db()
    assert solicitacao.status == EnrollmentAdjustmentRequest.Status.APPROVED
    assert solicitacao.decided_at is not None

    log = AuditLog.objects.get(event="academic.enrollment_adjustment.approve")
    assert log.actor.username == "celia"
    assert log.program_id == program.id
    assert log.target_id == str(solicitacao.id)
    assert log.payload["student_id"] == solicitacao.student_id


def test_aprovar_com_nota_guarda_a_nota(client_orientador, solicitacao):
    resposta = _post(
        client_orientador, _url(solicitacao, "approve"), {"note": "De acordo."}
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["decision_note"] == "De acordo."


def test_recusar_devolve_200_e_grava_auditoria(client_orientador, solicitacao, program):
    resposta = _post(
        client_orientador,
        _url(solicitacao, "reject"),
        {"note": "Disciplina não conta para o seu plano."},
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == "rejected"
    assert corpo["decision_note"] == "Disciplina não conta para o seu plano."
    assert corpo["decided_at"] is not None

    log = AuditLog.objects.get(event="academic.enrollment_adjustment.reject")
    assert log.actor.username == "celia"
    assert log.program_id == program.id
    assert log.payload["note"] == "Disciplina não conta para o seu plano."


def test_recusar_sem_motivo_devolve_400(client_orientador, solicitacao):
    """Recusa sem motivo é porta fechada sem explicação: o model barra."""
    resposta = _post(client_orientador, _url(solicitacao, "reject"), {"note": "   "})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "rejection_requires_note"
    solicitacao.refresh_from_db()
    assert solicitacao.status == EnrollmentAdjustmentRequest.Status.OPEN


def test_recusar_sem_o_campo_note_devolve_422(client_orientador, solicitacao):
    assert _post(client_orientador, _url(solicitacao, "reject"), {}).status_code == 422


@pytest.mark.parametrize("acao", ["approve", "reject"])
def test_decidir_solicitacao_ja_decidida_devolve_409(
    client_orientador, solicitacao, acao
):
    """Decidir de novo é erro do chamador, não no-op silencioso."""
    solicitacao.approve()
    solicitacao.save()

    resposta = _post(client_orientador, _url(solicitacao, acao), {"note": "Motivo."})

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "invalid_state_transition"
    solicitacao.refresh_from_db()
    assert solicitacao.status == EnrollmentAdjustmentRequest.Status.APPROVED


@pytest.mark.parametrize("acao", ["approve", "reject"])
def test_outro_docente_do_programa_nao_decide(client, program, solicitacao, acao):
    """A permissão de grupo diz que docente decide acerto, não QUAL acerto."""
    outro = _criar_docente(program=program, username="davi", nome="Davi Nunes")
    _logar(client, outro)

    resposta = _post(client, _url(solicitacao, acao), {"note": "Motivo."})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    solicitacao.refresh_from_db()
    assert solicitacao.status == EnrollmentAdjustmentRequest.Status.OPEN


def test_solicitacao_de_outro_programa_devolve_404(
    client, outro_programa, periodo, disciplina, program, orientador
):
    """Fora do escopo, a solicitação nem existe — não é 403, é 404."""
    docente_alheio = _criar_docente(
        program=outro_programa, username="edu", nome="Eduardo Reis"
    )
    pessoa = Person.objects.create(
        program=outro_programa,
        full_name="Fábio Luz",
        primary_email="fabio@exemplo.br",
    )
    linha_alheia = ResearchLine.objects.create(program=outro_programa, name="Macro")
    projeto_alheio = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha_alheia, name="Câmbio"
    )
    aluno_alheio = Student.objects.create(
        program=outro_programa,
        person=pessoa,
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto_alheio,
        advisor=docente_alheio,
        admission_date=date(2026, 3, 2),
    )
    alheia = EnrollmentAdjustmentRequest.objects.create(
        program=outro_programa, student=aluno_alheio, term=periodo
    )

    _logar(client, orientador)
    resposta = _post(client, _url(alheia, "approve"), {})

    assert resposta.status_code == 404


def test_aluno_nao_decide_a_propria_solicitacao(client, aluno, solicitacao):
    """O Discente abre, o Docente decide (US-003)."""
    user = aluno.person.user
    assert user is not None
    client.force_login(user)

    resposta = _post(client, _url(solicitacao, "approve"), {})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_secretaria_nao_decide(client_secretaria, secretaria, program, solicitacao):
    """A Secretaria acompanha o acerto, mas não decide (US-003)."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )

    resposta = _post(client_secretaria, _url(solicitacao, "approve"), {})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_decidir_sem_sessao_devolve_401(client, solicitacao):
    assert _post(client, _url(solicitacao, "approve"), {}).status_code == 401


def test_escrita_sem_token_csrf_e_recusada(orientador, solicitacao):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    _logar(client, orientador)

    assert _post(client, _url(solicitacao, "approve"), {}).status_code == 403
    solicitacao.refresh_from_db()
    assert solicitacao.status == EnrollmentAdjustmentRequest.Status.OPEN
