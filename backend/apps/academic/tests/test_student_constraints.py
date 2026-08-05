"""As CheckConstraint de Student — nível (b) da pirâmide, com banco.

`clean()` protege quem passa pelo caminho do domínio; a constraint protege
o banco de qualquer caminho, inclusive o Admin e um shell. Por isso ela é
testada batendo no INSERT, e não chamando método.
"""

from datetime import date

import pytest
from django.db import IntegrityError, transaction

from apps.academic.models import Student, Teacher
from apps.people.models import Person
from apps.programs.models import AcademicTerm, CollectiveProject, Program, ResearchLine


@pytest.fixture
def pessoa(program: Program) -> Person:
    return Person.objects.create(
        program=program, full_name="Ana Lima", primary_email="ana@example.com"
    )


@pytest.fixture
def projeto(program: Program) -> CollectiveProject:
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto A"
    )


@pytest.fixture
def orientador(program: Program) -> Teacher:
    pessoa = Person.objects.create(
        program=program, full_name="Bruno Reis", primary_email="bruno@example.com"
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


def test_regular_sem_prazo_recebe_o_prazo_calculado_no_save(program, pessoa, projeto):
    aluno = Student.objects.create(
        program=program,
        person=pessoa,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2026, 3, 2),
    )

    assert aluno.deadline == date(2028, 3, 2)


def test_regular_sem_projeto_e_rejeitado_pela_constraint(program, pessoa):
    with pytest.raises(IntegrityError), transaction.atomic():
        Student.objects.create(
            program=program,
            person=pessoa,
            level=Student.Level.MASTERS,
            admission_date=date(2026, 3, 2),
        )


def test_isolada_com_orientador_e_rejeitada_pela_constraint(
    program, pessoa, periodo, orientador
):
    with pytest.raises(IntegrityError), transaction.atomic():
        Student.objects.create(
            program=program,
            person=pessoa,
            modality=Student.Modality.ISOLATED,
            term=periodo,
            advisor=orientador,
        )


def test_isolada_sem_periodo_e_rejeitada_pela_constraint(program, pessoa):
    with pytest.raises(IntegrityError), transaction.atomic():
        Student.objects.create(
            program=program, person=pessoa, modality=Student.Modality.ISOLATED
        )


def test_isolada_trancada_e_rejeitada_pela_constraint(program, pessoa, periodo):
    """Trancar não se aplica a quem cursa um semestre só."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Student.objects.create(
            program=program,
            person=pessoa,
            modality=Student.Modality.ISOLATED,
            status=Student.Status.LEAVE,
            term=periodo,
        )


def test_mesma_pessoa_em_dois_periodos_diferentes(program, pessoa, periodo):
    """`person` é FK e não OneToOne (ADR-007 dec. 2): a mesma pessoa cursa
    uma isolada em 2026/1 e outra em 2026/2.
    """
    outro_periodo = AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 19)
    )
    for termo in (periodo, outro_periodo):
        Student.objects.create(
            program=program,
            person=pessoa,
            modality=Student.Modality.ISOLATED,
            term=termo,
        )

    assert pessoa.student_records.count() == 2
