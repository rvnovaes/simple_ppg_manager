"""Encerramento do ciclo de isolada, pelo endpoint.

Nível (b) da pirâmide (Seção 9). O que se prova aqui é o recorte do lote:
o encerramento fecha exatamente os vínculos de isolada ATIVOS daquele
período e daquele programa, e não encosta em ninguém mais — aluno regular,
quem já saiu, isolada de outro semestre, isolada de outro tenant.
"""

import json
from datetime import UTC, date, datetime

import pytest
from django.test import Client

from apps.academic.models import (
    IsolatedEnrollmentCycle,
    Student,
)
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Program,
    ResearchLine,
)

pytestmark = pytest.mark.django_db


def _url(ciclo: IsolatedEnrollmentCycle) -> str:
    return f"/api/v1/academic/isolated/cycles/{ciclo.id}/close"


def _post(client: Client, url: str):
    return client.post(url, data=json.dumps({}), content_type="application/json")


@pytest.fixture
def secretaria_no_programa(secretaria: User, program: Program) -> Person:
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Pós em Economia", acronym="PPGE")


def criar_aluno(
    *,
    program: Program,
    periodo: AcademicTerm | None,
    nome: str,
    modality: str = Student.Modality.ISOLATED,
    status: str = Student.Status.ACTIVE,
    **kwargs,
) -> Student:
    pessoa = Person.objects.create(
        program=program,
        full_name=nome,
        primary_email=f"{nome.split()[0].lower()}@exemplo.br",
    )
    return Student.objects.create(
        program=program,
        person=pessoa,
        modality=modality,
        status=status,
        term=periodo,
        **kwargs,
    )


# --- o caso feliz ----------------------------------------------------


def test_encerrar_exclui_os_isolados_ativos_desativa_o_ciclo_e_audita(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    periodo: AcademicTerm,
    ciclo: IsolatedEnrollmentCycle,
):
    ana = criar_aluno(program=program, periodo=periodo, nome="Ana Souza")
    bruno = criar_aluno(program=program, periodo=periodo, nome="Bruno Lima")

    resposta = _post(client_secretaria, _url(ciclo))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo == {
        "cycle_id": ciclo.id,
        "is_active": False,
        "students_excluded": 2,
    }
    ana.refresh_from_db()
    bruno.refresh_from_db()
    assert ana.status == Student.Status.EXCLUDED
    assert bruno.status == Student.Status.EXCLUDED
    ciclo.refresh_from_db()
    assert ciclo.is_active is False

    registros = AuditLog.objects.filter(event="academic.isolated.close_cycle")
    # Um evento só, com a contagem no payload — e não um por aluno.
    assert registros.count() == 1
    registro = registros.get()
    assert registro.program_id == program.id
    assert registro.target_id == str(ciclo.id)
    assert registro.payload["students_excluded"] == 2
    assert registro.payload["term_id"] == periodo.id


def test_encerrar_ciclo_sem_aluno_algum_devolve_zero(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    ciclo: IsolatedEnrollmentCycle,
):
    resposta = _post(client_secretaria, _url(ciclo))

    assert resposta.status_code == 200
    assert resposta.json()["students_excluded"] == 0
    ciclo.refresh_from_db()
    assert ciclo.is_active is False


# --- o recorte do lote -----------------------------------------------


def test_encerrar_nao_toca_no_aluno_regular_do_mesmo_periodo(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    periodo: AcademicTerm,
    ciclo: IsolatedEnrollmentCycle,
):
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )
    regular = criar_aluno(
        program=program,
        periodo=None,
        nome="Diana Melo",
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2026, 3, 2),
        deadline=date(2028, 3, 2),
    )

    resposta = _post(client_secretaria, _url(ciclo))

    assert resposta.json()["students_excluded"] == 0
    regular.refresh_from_db()
    assert regular.status == Student.Status.ACTIVE


def test_encerrar_nao_reprocessa_quem_ja_estava_fora(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    periodo: AcademicTerm,
    ciclo: IsolatedEnrollmentCycle,
):
    """Quem já saiu fica como está.

    Mexer em quem já saiu apagaria a razão original da saída, e a contagem
    do AuditLog passaria a somar gente que o encerramento não fechou.
    Trancado não entra neste teste: `student_leave_only_when_regular` só
    admite o trancamento no regular, que já está fora do recorte.
    """
    excluido = criar_aluno(
        program=program,
        periodo=periodo,
        nome="Fabio Nunes",
        status=Student.Status.EXCLUDED,
    )
    ativo = criar_aluno(program=program, periodo=periodo, nome="Gina Alves")

    resposta = _post(client_secretaria, _url(ciclo))

    assert resposta.json()["students_excluded"] == 1
    excluido.refresh_from_db()
    ativo.refresh_from_db()
    assert excluido.status == Student.Status.EXCLUDED
    assert ativo.status == Student.Status.EXCLUDED


def test_encerrar_nao_toca_em_isolada_de_outro_periodo(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    periodo: AcademicTerm,
    ciclo: IsolatedEnrollmentCycle,
):
    outro_periodo = AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 18)
    )
    outro_semestre = criar_aluno(
        program=program, periodo=outro_periodo, nome="Hugo Reis"
    )

    resposta = _post(client_secretaria, _url(ciclo))

    assert resposta.json()["students_excluded"] == 0
    outro_semestre.refresh_from_db()
    assert outro_semestre.status == Student.Status.ACTIVE


def test_encerrar_nao_atravessa_o_tenant(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    periodo: AcademicTerm,
    ciclo: IsolatedEnrollmentCycle,
    outro_programa: Program,
):
    """O período letivo é institucional (ADR-007 dec. 4): o mesmo semestre
    tem aluno de isolada em vários programas, e encerrar o edital de um não
    pode fechar o vínculo de outro.
    """
    de_fora = criar_aluno(program=outro_programa, periodo=periodo, nome="Ivo Castro")

    resposta = _post(client_secretaria, _url(ciclo))

    assert resposta.json()["students_excluded"] == 0
    de_fora.refresh_from_db()
    assert de_fora.status == Student.Status.ACTIVE


# --- estado, escopo e acesso ------------------------------------------


def test_encerrar_duas_vezes_devolve_409_e_nao_mexe_em_ninguem(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    periodo: AcademicTerm,
    ciclo: IsolatedEnrollmentCycle,
):
    assert _post(client_secretaria, _url(ciclo)).status_code == 200
    # Aluno que entrou depois do encerramento (correção de matrícula pelo
    # Admin, por exemplo) não é fechado por um segundo clique.
    tardio = criar_aluno(program=program, periodo=periodo, nome="Joana Melo")

    resposta = _post(client_secretaria, _url(ciclo))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "cycle_already_closed"
    tardio.refresh_from_db()
    assert tardio.status == Student.Status.ACTIVE
    assert AuditLog.objects.filter(event="academic.isolated.close_cycle").count() == 1


def test_encerrar_ciclo_de_outro_programa_devolve_404(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    outro_programa: Program,
):
    periodo = AcademicTerm.objects.create(
        year=2028, half=1, starts_on=date(2028, 3, 1), ends_on=date(2028, 7, 15)
    )
    de_fora = IsolatedEnrollmentCycle.objects.create(
        program=outro_programa,
        term=periodo,
        submission_opens_at=datetime(2028, 2, 1, tzinfo=UTC),
        submission_closes_at=datetime(2028, 2, 10, tzinfo=UTC),
        result_published_on=date(2028, 2, 12),
        appeal_opens_at=datetime(2028, 2, 12, tzinfo=UTC),
        appeal_closes_at=datetime(2028, 2, 15, tzinfo=UTC),
        final_result_on=date(2028, 2, 17),
        payment_closes_at=datetime(2028, 2, 25, tzinfo=UTC),
    )

    resposta = _post(client_secretaria, _url(de_fora))

    assert resposta.status_code == 404
    de_fora.refresh_from_db()
    assert de_fora.is_active is True


def test_encerrar_sem_permissao_devolve_403(
    client_sem_permissao: Client, ciclo: IsolatedEnrollmentCycle
):
    resposta = _post(client_sem_permissao, _url(ciclo))

    assert resposta.status_code == 403
    ciclo.refresh_from_db()
    assert ciclo.is_active is True


def test_encerrar_sem_sessao_devolve_401(
    client: Client, ciclo: IsolatedEnrollmentCycle
):
    resposta = _post(client, _url(ciclo))

    assert resposta.status_code == 401


def test_encerrar_sem_csrf_devolve_403(
    secretaria: User, secretaria_no_programa: Person, ciclo: IsolatedEnrollmentCycle
):
    cliente = Client(enforce_csrf_checks=True)
    cliente.force_login(secretaria)

    resposta = _post(cliente, _url(ciclo))

    assert resposta.status_code == 403
    ciclo.refresh_from_db()
    assert ciclo.is_active is True
