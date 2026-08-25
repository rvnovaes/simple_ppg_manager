"""Fixtures do processo seletivo, compartilhadas pelos testes com banco.

`MEDIA_ROOT` já cai em `tmp_path` pela fixture autouse `media_temporaria`
do `backend/conftest.py` — vale para este app também, então não é
repetida aqui. `program` vem do mesmo lugar.

`edital_regular` e `edital_suplementar` são stubs que pulam o teste até
os models existirem (`f0-process-stage`); assim os módulos de teste já
podem ser escritos contra os nomes definitivos.
"""

from datetime import date

import pytest

from apps.academic.models import Teacher
from apps.people.models import Person
from apps.programs.models import Program


@pytest.fixture
def docente(program: Program) -> Teacher:
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
def externo(program: Program) -> Teacher:
    pessoa = Person.objects.create(
        program=program, full_name="Carla Souza", primary_email="carla@example.com"
    )
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.EXTERNAL,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2026, 1, 1),
        home_institution="USP",
    )


@pytest.fixture
def edital_regular(program: Program):
    pytest.skip("SelectionProcess chega em f0-process-stage")


@pytest.fixture
def edital_suplementar(program: Program):
    pytest.skip("SelectionProcess chega em f0-process-stage")
