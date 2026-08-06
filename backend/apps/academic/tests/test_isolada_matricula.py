"""Efetivação da matrícula da isolada, pelo endpoint.

Nível (b) da pirâmide (Seção 9). O que se prova aqui é o que só existe
depois de a transação inteira rodar: o `Student` que nasce passando nas
CheckConstraint do ADR-007, a troca de papel do candidato e o fato de a
mesma pessoa poder ter dois vínculos de ciclos diferentes.
"""

import json
from datetime import UTC, date, datetime

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from apps.academic.models import (
    DisciplineOffering,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
    IsolatedPaymentStatus,
    IsolatedRequestStatus,
    Student,
)
from apps.academic.tests.conftest import criar_candidato, logar
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import AcademicTerm, Discipline, Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/isolated/requests/"


def _url(requerimento: IsolatedEnrollmentRequest) -> str:
    return f"{URL}{requerimento.id}/enroll"


def _post(client: Client, url: str, payload: dict | None = None):
    return client.post(
        url, data=json.dumps(payload or {}), content_type="application/json"
    )


@pytest.fixture
def secretaria_no_programa(secretaria: User, program: Program) -> Person:
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


@pytest.fixture
def deferido(
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
) -> IsolatedEnrollmentRequest:
    """Deferido e pago: o estado exato em que a matrícula pode sair.

    O candidato tem conta (`criar_candidato`) porque a troca de papel é
    metade do que esta US faz.
    """
    pessoa = criar_candidato(program=program, username="ana", nome="Ana Souza")
    requerimento = IsolatedEnrollmentRequest.objects.create(
        program=program,
        cycle=ciclo,
        person=pessoa,
        status=IsolatedRequestStatus.DEFERRED,
        payment_status=IsolatedPaymentStatus.PAID,
        submitted_at=timezone.now(),
        decided_at=timezone.now(),
    )
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta, rank=1)
    return requerimento


# --- o caso feliz ----------------------------------------------------


def test_efetivar_cria_o_aluno_isolado_muda_o_status_e_audita(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    ciclo: IsolatedEnrollmentCycle,
    deferido: IsolatedEnrollmentRequest,
):
    resposta = _post(
        client_secretaria, _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == IsolatedRequestStatus.ENROLLED
    deferido.refresh_from_db()
    assert deferido.status == IsolatedRequestStatus.ENROLLED

    aluno = Student.objects.get(person=deferido.person)
    assert aluno.modality == Student.Modality.ISOLATED
    assert aluno.status == Student.Status.ACTIVE
    assert aluno.registration_number == "2026123456"
    assert aluno.term_id == ciclo.term_id
    assert aluno.program_id == deferido.program_id
    assert AuditLog.objects.filter(
        event="academic.isolated.enroll", target_id=deferido.pk
    ).exists()


def test_o_aluno_criado_nao_tem_nenhum_campo_de_grau(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    """`student_non_regular_requires_term` exige os cinco vazios — se um
    deles fosse preenchido, o `save()` levantaria IntegrityError.
    """
    assert (
        _post(
            client_secretaria, _url(deferido), {"registration_number": "2026123456"}
        ).status_code
        == 200
    )

    aluno = Student.objects.get(person=deferido.person)
    assert aluno.level is None
    assert aluno.project_id is None
    assert aluno.advisor_id is None
    assert aluno.admission_date is None
    assert aluno.deadline is None
    assert aluno.defense_date is None


def test_efetivar_isento_dispensa_o_comprovante(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    """O servidor da UFMG já pagou com o contracheque que anexou."""
    deferido.payment_status = IsolatedPaymentStatus.EXEMPT
    deferido.is_ufmg_staff = True
    deferido.save(update_fields=["payment_status", "is_ufmg_staff"])

    resposta = _post(
        client_secretaria, _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 200
    assert Student.objects.filter(person=deferido.person).exists()


def test_a_mesma_pessoa_cursa_isoladas_em_dois_ciclos(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    docente,
    deferido: IsolatedEnrollmentRequest,
):
    """`Student.person` é FK e não OneToOne exatamente por isto
    (ADR-007 dec. 2): são dois vínculos, cada um com seu semestre.
    """
    assert (
        _post(
            client_secretaria, _url(deferido), {"registration_number": "2026123456"}
        ).status_code
        == 200
    )

    outro_periodo = AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 12)
    )
    outro_ciclo = IsolatedEnrollmentCycle.objects.create(
        program=program,
        term=outro_periodo,
        submission_opens_at=datetime(2026, 7, 1, tzinfo=UTC),
        submission_closes_at=datetime(2026, 7, 10, tzinfo=UTC),
        result_published_on=date(2026, 7, 12),
        appeal_opens_at=datetime(2026, 7, 12, tzinfo=UTC),
        appeal_closes_at=datetime(2026, 7, 15, tzinfo=UTC),
        final_result_on=date(2026, 7, 17),
        payment_closes_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    outra_oferta = DisciplineOffering.objects.create(
        program=program,
        cycle=outro_ciclo,
        discipline=Discipline.objects.create(
            program=program, code="DIR002", name="Direito Civil"
        ),
        teacher=docente,
        seats=2,
    )
    segundo = IsolatedEnrollmentRequest.objects.create(
        program=program,
        cycle=outro_ciclo,
        person=deferido.person,
        status=IsolatedRequestStatus.DEFERRED,
        payment_status=IsolatedPaymentStatus.PAID,
    )
    IsolatedEnrollmentItem.objects.create(
        request=segundo, offering=outra_oferta, rank=1
    )

    resposta = _post(
        client_secretaria, _url(segundo), {"registration_number": "2026999999"}
    )

    assert resposta.status_code == 200
    vinculos = Student.objects.filter(person=deferido.person)
    assert vinculos.count() == 2
    assert set(vinculos.values_list("term_id", flat=True)) == {
        deferido.cycle.term_id,
        outro_periodo.pk,
    }


# --- troca de papel --------------------------------------------------


def test_efetivar_troca_candidato_por_discente(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    """Ficar nos dois papéis deixaria o aluno vendo as telas do edital
    como se ainda estivesse concorrendo.
    """
    user = deferido.person.user
    assert user is not None

    assert (
        _post(
            client_secretaria, _url(deferido), {"registration_number": "2026123456"}
        ).status_code
        == 200
    )

    papeis = set(user.groups.values_list("name", flat=True))
    assert papeis == {"Discente"}
    assert AuditLog.objects.filter(
        event="accounts.user.revoke_role_group", target_id=user.pk
    ).exists()


def test_candidato_sem_conta_e_matriculado_do_mesmo_jeito(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    """Pessoa sem conta é registro histórico; não há papel a trocar."""
    Person.objects.filter(pk=deferido.person_id).update(user=None)

    resposta = _post(
        client_secretaria, _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 200
    assert Student.objects.filter(person_id=deferido.person_id).exists()


# --- o que barra -----------------------------------------------------


def test_efetivar_com_a_taxa_em_aberto_e_recusado(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    deferido.payment_status = IsolatedPaymentStatus.PENDING
    deferido.save(update_fields=["payment_status"])

    resposta = _post(
        client_secretaria, _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "payment_required"
    deferido.refresh_from_db()
    assert deferido.status == IsolatedRequestStatus.DEFERRED
    assert not Student.objects.filter(person=deferido.person).exists()


def test_efetivar_requerimento_nao_deferido_e_conflito(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    deferido.status = IsolatedRequestStatus.SUBMITTED
    deferido.save(update_fields=["status"])

    resposta = _post(
        client_secretaria, _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 409
    assert not Student.objects.filter(person=deferido.person).exists()


def test_efetivar_sem_a_matricula_e_recusado_na_borda(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    assert _post(client_secretaria, _url(deferido)).status_code == 422


def test_efetivar_com_matricula_em_branco_e_recusado(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    resposta = _post(client_secretaria, _url(deferido), {"registration_number": "   "})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "registration_number_required"
    deferido.refresh_from_db()
    assert deferido.status == IsolatedRequestStatus.DEFERRED


def test_matricula_repetida_e_recusada_sem_deixar_rastro(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    periodo: AcademicTerm,
    deferido: IsolatedEnrollmentRequest,
):
    """A matrícula é única no banco. Sem `full_clean()` isso sairia como
    IntegrityError 500 — e a transação inteira precisa voltar atrás.
    """
    outra_pessoa = Person.objects.create(
        program=program, full_name="Bia Lima", primary_email="bia@exemplo.br"
    )
    Student.objects.create(
        program=program,
        person=outra_pessoa,
        registration_number="2026123456",
        modality=Student.Modality.ISOLATED,
        status=Student.Status.ACTIVE,
        term=periodo,
    )

    resposta = _post(
        client_secretaria, _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_student"
    deferido.refresh_from_db()
    assert deferido.status == IsolatedRequestStatus.DEFERRED
    assert not Student.objects.filter(person=deferido.person).exists()


# --- quem efetiva ----------------------------------------------------


def test_candidato_nao_efetiva_a_propria_matricula(
    client: Client, deferido: IsolatedEnrollmentRequest
):
    """A permissão `change` é a mesma de montar o requerimento; o que
    separa é a posse, como em defer/reject/cancel.
    """
    resposta = _post(
        logar(client, deferido.person),
        _url(deferido),
        {"registration_number": "2026123456"},
    )

    assert resposta.status_code == 403
    assert not Student.objects.filter(person=deferido.person).exists()


def test_docente_nao_efetiva_matricula(
    client: Client, program: Program, deferido: IsolatedEnrollmentRequest
):
    pessoa = criar_candidato(program=program, username="bruno", nome="Bruno Reis")
    user = pessoa.user
    assert user is not None
    user.groups.set([Group.objects.get(name="Docente")])

    resposta = _post(
        logar(client, pessoa), _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 403


def test_sem_sessao_nao_efetiva(client: Client, deferido: IsolatedEnrollmentRequest):
    assert _post(client, _url(deferido)).status_code == 401


def test_requerimento_de_outro_programa_e_404(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    deferido: IsolatedEnrollmentRequest,
):
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    IsolatedEnrollmentRequest.objects.filter(pk=deferido.pk).update(program=outro)

    resposta = _post(
        client_secretaria, _url(deferido), {"registration_number": "2026123456"}
    )

    assert resposta.status_code == 404


def test_efetivar_sem_csrf_e_recusado(
    secretaria_no_programa: Person,
    secretaria: User,
    deferido: IsolatedEnrollmentRequest,
):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(secretaria)

    resposta = strict.post(
        _url(deferido),
        data=json.dumps({"registration_number": "2026123456"}),
        content_type="application/json",
    )

    assert resposta.status_code == 403
