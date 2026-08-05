"""Invariantes da vida acadêmica.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
Os pks são atribuídos à mão só para as FKs terem id — nada é salvo.
"""

from datetime import date

import pytest

from apps.academic.models import Student, Teacher
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


def _aluno(**kwargs) -> Student:
    campos = {
        "program": Program(pk=1, acronym="PPGD"),
        "level": Student.Level.MASTERS,
        "admission_date": date(2026, 3, 2),
    }
    campos.update(kwargs)
    return Student(**campos)


def test_prazo_padrao_do_mestrado_e_de_dois_anos():
    assert _aluno().default_deadline() == date(2028, 3, 2)


def test_prazo_padrao_do_doutorado_e_de_quatro_anos():
    aluno = _aluno(level=Student.Level.DOCTORATE)

    assert aluno.default_deadline() == date(2030, 3, 2)


def test_prazo_a_partir_de_29_de_fevereiro_cai_em_28():
    """2024 é bissexto, 2026 não — o mestrado que entrou em 29/02/2024
    vence em 28/02/2026. Aritmética de ano, sem python-dateutil.
    """
    aluno = _aluno(admission_date=date(2024, 2, 29))

    assert aluno.default_deadline() == date(2026, 2, 28)


def test_prazo_a_partir_de_29_de_fevereiro_para_ano_bissexto_mantem_o_dia():
    aluno = _aluno(admission_date=date(2024, 2, 29), level=Student.Level.DOCTORATE)

    assert aluno.default_deadline() == date(2028, 2, 29)


def test_prazo_sem_ingresso_ou_nivel_e_none():
    assert _aluno(admission_date=None).default_deadline() is None
    assert _aluno(level=None).default_deadline() is None


def test_clean_rejeita_aluno_em_programa_diferente_do_da_pessoa():
    pessoa = Person(pk=1, program=Program(pk=1, acronym="PPGD"), full_name="Ana Lima")
    aluno = _aluno(program=Program(pk=2, acronym="PPGA"), person=pessoa)

    with pytest.raises(DomainError) as exc:
        aluno.clean()

    assert exc.value.code == "program_mismatch"
