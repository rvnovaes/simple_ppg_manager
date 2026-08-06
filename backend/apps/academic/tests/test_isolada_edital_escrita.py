"""A secretaria monta o edital: cria e corrige o ciclo e as ofertas.

Nível (b) da pirâmide (Seção 9). O conjunto canônico de casos por recurso
(201 + auditoria, payload não escolhe tenant, duplicata com `code` estável,
403 sem permissão, 401 sem sessão, 404 de outro programa, CSRF) roda aqui
para os dois recursos, porque são duas rotas de escrita distintas.
"""

from datetime import UTC, date, datetime

import pytest
from django.test import Client

from apps.academic.models import (
    DisciplineOffering,
    IsolatedEnrollmentCycle,
    Teacher,
)
from apps.academic.tests.conftest import logar
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import AcademicTerm, Discipline, Program

pytestmark = pytest.mark.django_db

CICLOS = "/api/v1/academic/isolated/cycles/"
OFERTAS = "/api/v1/academic/isolated/offerings/"


@pytest.fixture
def client_da_secretaria(client: Client, secretaria: User, program: Program) -> Client:
    pessoa = Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    return logar(client, pessoa)


@pytest.fixture
def outro_periodo(db) -> AcademicTerm:
    return AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 19)
    )


def calendario(periodo: AcademicTerm) -> dict:
    return {
        "term_id": periodo.pk,
        "submission_opens_at": "2026-02-01T00:00:00Z",
        "submission_closes_at": "2026-02-10T00:00:00Z",
        "result_published_on": "2026-02-12",
        "appeal_opens_at": "2026-02-12T00:00:00Z",
        "appeal_closes_at": "2026-02-15T00:00:00Z",
        "final_result_on": "2026-02-17",
        "payment_closes_at": "2026-02-25T00:00:00Z",
    }


def _post(client: Client, url: str, corpo: dict):
    return client.post(url, data=corpo, content_type="application/json")


def _patch(client: Client, url: str, corpo: dict):
    return client.patch(url, data=corpo, content_type="application/json")


def test_cria_o_ciclo_e_registra_auditoria(
    client_da_secretaria: Client, periodo: AcademicTerm, program: Program
):
    resposta = _post(client_da_secretaria, CICLOS, calendario(periodo))

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["term_label"] == "2026/1"
    assert corpo["is_active"] is True
    ciclo = IsolatedEnrollmentCycle.objects.get(pk=corpo["id"])
    assert ciclo.program_id == program.pk
    registro = AuditLog.objects.get(event="academic.isolated_cycle.create")
    assert registro.program_id == program.pk


def test_payload_nao_escolhe_o_programa_do_ciclo(
    client_da_secretaria: Client, periodo: AcademicTerm, program: Program
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")

    resposta = _post(
        client_da_secretaria, CICLOS, calendario(periodo) | {"program_id": outro.pk}
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["program_id"] == program.pk


def test_ciclo_com_datas_fora_de_ordem_e_400(
    client_da_secretaria: Client, periodo: AcademicTerm
):
    corpo = calendario(periodo) | {"appeal_opens_at": "2026-02-05T00:00:00Z"}

    resposta = _post(client_da_secretaria, CICLOS, corpo)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_cycle_dates"


def test_segundo_ciclo_no_mesmo_periodo_e_400(
    client_da_secretaria: Client, ciclo: IsolatedEnrollmentCycle, periodo: AcademicTerm
):
    resposta = _post(client_da_secretaria, CICLOS, calendario(periodo))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_cycle"


def test_periodo_inexistente_e_404(client_da_secretaria: Client, periodo: AcademicTerm):
    resposta = _post(client_da_secretaria, CICLOS, calendario(periodo) | {"term_id": 0})

    assert resposta.status_code == 404


def test_prorrogar_o_prazo_do_ciclo(
    client_da_secretaria: Client, ciclo: IsolatedEnrollmentCycle
):
    resposta = _patch(
        client_da_secretaria,
        f"{CICLOS}{ciclo.pk}/",
        {"submission_closes_at": "2026-02-11T00:00:00Z"},
    )

    assert resposta.status_code == 200, resposta.content
    ciclo.refresh_from_db()
    assert ciclo.submission_closes_at == datetime(2026, 2, 11, tzinfo=UTC)
    assert AuditLog.objects.filter(event="academic.isolated_cycle.update").exists()


def test_prorrogacao_incoerente_e_400(
    client_da_secretaria: Client, ciclo: IsolatedEnrollmentCycle
):
    resposta = _patch(
        client_da_secretaria,
        f"{CICLOS}{ciclo.pk}/",
        {"submission_closes_at": "2026-02-20T00:00:00Z"},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_cycle_dates"


def test_alterar_ciclo_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_periodo: AcademicTerm
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    alheio = IsolatedEnrollmentCycle.objects.create(
        program=outro,
        term=outro_periodo,
        submission_opens_at=datetime(2026, 8, 1, tzinfo=UTC),
        submission_closes_at=datetime(2026, 8, 10, tzinfo=UTC),
        result_published_on=date(2026, 8, 12),
        appeal_opens_at=datetime(2026, 8, 12, tzinfo=UTC),
        appeal_closes_at=datetime(2026, 8, 15, tzinfo=UTC),
        final_result_on=date(2026, 8, 17),
        payment_closes_at=datetime(2026, 8, 25, tzinfo=UTC),
    )

    resposta = _patch(
        client_da_secretaria, f"{CICLOS}{alheio.pk}/", {"final_result_on": "2026-08-18"}
    )

    assert resposta.status_code == 404


def test_criar_ciclo_sem_permissao_e_403(
    client_sem_permissao: Client, periodo: AcademicTerm
):
    resposta = _post(client_sem_permissao, CICLOS, calendario(periodo))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_ciclo_sem_sessao_e_401(client: Client, periodo: AcademicTerm):
    assert _post(client, CICLOS, calendario(periodo)).status_code == 401


def test_criar_oferta_e_registra_auditoria(
    client_da_secretaria: Client,
    ciclo: IsolatedEnrollmentCycle,
    docente: Teacher,
    program: Program,
):
    disciplina = Discipline.objects.create(
        program=program, code="DIR020", name="Direito Ambiental"
    )

    resposta = _post(
        client_da_secretaria,
        OFERTAS,
        {
            "cycle_id": ciclo.pk,
            "discipline_id": disciplina.pk,
            "teacher_id": docente.pk,
            "seats": 4,
        },
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["discipline_code"] == "DIR020"
    assert corpo["seats_available"] == 4
    assert DisciplineOffering.objects.get(pk=corpo["id"]).program_id == program.pk
    assert AuditLog.objects.filter(event="academic.discipline_offering.create").exists()


def test_oferta_repetida_no_mesmo_ciclo_e_400(
    client_da_secretaria: Client, oferta: DisciplineOffering
):
    resposta = _post(
        client_da_secretaria,
        OFERTAS,
        {
            "cycle_id": oferta.cycle_id,
            "discipline_id": oferta.discipline_id,
            "teacher_id": oferta.teacher_id,
            "seats": 1,
        },
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_offering"


def test_oferta_sem_vaga_e_400(
    client_da_secretaria: Client,
    ciclo: IsolatedEnrollmentCycle,
    docente: Teacher,
    program: Program,
):
    disciplina = Discipline.objects.create(
        program=program, code="DIR021", name="Direito Digital"
    )

    resposta = _post(
        client_da_secretaria,
        OFERTAS,
        {
            "cycle_id": ciclo.pk,
            "discipline_id": disciplina.pk,
            "teacher_id": docente.pk,
            "seats": 0,
        },
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_seats"


def test_disciplina_de_outro_programa_e_404(
    client_da_secretaria: Client, ciclo: IsolatedEnrollmentCycle, docente: Teacher
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    alheia = Discipline.objects.create(
        program=outro, code="DIR030", name="Disciplina alheia"
    )

    resposta = _post(
        client_da_secretaria,
        OFERTAS,
        {
            "cycle_id": ciclo.pk,
            "discipline_id": alheia.pk,
            "teacher_id": docente.pk,
            "seats": 2,
        },
    )

    assert resposta.status_code == 404


def test_alterar_vagas_e_responsavel_da_oferta(
    client_da_secretaria: Client, oferta: DisciplineOffering, program: Program
):
    outra_pessoa = Person.objects.create(
        program=program, full_name="Diego Melo", primary_email="diego@example.com"
    )
    outro_docente = Teacher.objects.create(
        program=program,
        person=outra_pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2021, 3, 1),
    )

    resposta = _patch(
        client_da_secretaria,
        f"{OFERTAS}{oferta.pk}/",
        {"seats": 5, "teacher_id": outro_docente.pk},
    )

    assert resposta.status_code == 200, resposta.content
    oferta.refresh_from_db()
    assert oferta.seats == 5
    assert oferta.teacher_id == outro_docente.pk
    registro = AuditLog.objects.get(event="academic.discipline_offering.update")
    assert registro.payload["fields"] == ["seats", "teacher_id"]


def test_alterar_oferta_sem_permissao_e_403(
    client_sem_permissao: Client, oferta: DisciplineOffering
):
    resposta = _patch(client_sem_permissao, f"{OFERTAS}{oferta.pk}/", {"seats": 9})

    assert resposta.status_code == 403


def test_escrita_de_oferta_sem_token_csrf_e_recusada(
    secretaria: User, ciclo: IsolatedEnrollmentCycle, docente: Teacher, program: Program
):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    disciplina = Discipline.objects.create(
        program=program, code="DIR040", name="Direito Tributário"
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    resposta = _post(
        client,
        OFERTAS,
        {
            "cycle_id": ciclo.pk,
            "discipline_id": disciplina.pk,
            "teacher_id": docente.pk,
            "seats": 2,
        },
    )

    assert resposta.status_code == 403
    assert not DisciplineOffering.objects.filter(discipline=disciplina).exists()


# --- casos de sucesso de clean() (consultam a duplicata, logo pedem banco)


def test_clean_aceita_ciclo_com_as_datas_em_ordem(
    program: Program, periodo: AcademicTerm
):
    IsolatedEnrollmentCycle(
        program=program,
        term=periodo,
        submission_opens_at=datetime(2026, 2, 1, tzinfo=UTC),
        submission_closes_at=datetime(2026, 2, 10, tzinfo=UTC),
        result_published_on=date(2026, 2, 12),
        # Encadear recurso e inscrição no mesmo instante é o edital sem
        # intervalo entre as fases, e é legítimo.
        appeal_opens_at=datetime(2026, 2, 10, tzinfo=UTC),
        appeal_closes_at=datetime(2026, 2, 15, tzinfo=UTC),
        final_result_on=date(2026, 2, 17),
        payment_closes_at=datetime(2026, 2, 25, tzinfo=UTC),
    ).clean()


def test_clean_aceita_oferta_com_tudo_no_mesmo_programa(
    program: Program, ciclo: IsolatedEnrollmentCycle, docente: Teacher
):
    disciplina = Discipline.objects.create(
        program=program, code="DIR050", name="Direito Penal"
    )

    DisciplineOffering(
        program=program,
        cycle=ciclo,
        discipline=disciplina,
        teacher=docente,
        seats=10,
    ).clean()
