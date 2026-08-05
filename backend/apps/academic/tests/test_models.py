"""Invariantes da vida acadêmica.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
Os pks são atribuídos à mão só para as FKs terem id — nada é salvo.
"""

from datetime import date

import pytest

from apps.academic.models import Teacher
from apps.core.exceptions import DomainError
from apps.people.models import Person
from apps.programs.models import Program


def _professor(*, program: Program, person: Person) -> Teacher:
    return Teacher(
        program=program,
        person=person,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 3, 1),
    )


def test_clean_aceita_professor_no_mesmo_programa_da_pessoa():
    programa = Program(pk=1, acronym="PPGD")
    pessoa = Person(pk=1, program=programa, full_name="Ana Lima")

    _professor(program=programa, person=pessoa).clean()


def test_clean_rejeita_professor_em_programa_diferente_do_da_pessoa():
    pessoa = Person(pk=1, program=Program(pk=1, acronym="PPGD"), full_name="Ana Lima")
    outro = Program(pk=2, acronym="PPGA")

    with pytest.raises(DomainError) as exc:
        _professor(program=outro, person=pessoa).clean()

    assert exc.value.code == "program_mismatch"
    assert exc.value.status_code == 400


def test_clean_sem_pessoa_nao_levanta():
    """Obrigatoriedade da pessoa é da borda e do NOT NULL, não deste invariante."""
    professor = Teacher(
        program=Program(pk=1, acronym="PPGD"),
        category=Teacher.Category.VISITING,
        academic_degree=Teacher.AcademicDegree.HABILITATION,
        accredited_since=date(2020, 3, 1),
    )

    professor.clean()
