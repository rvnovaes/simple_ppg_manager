"""Fixtures do processo seletivo, compartilhadas pelos testes com banco.

`MEDIA_ROOT` já cai em `tmp_path` pela fixture autouse `media_temporaria`
do `backend/conftest.py` — vale para este app também, então não é
repetida aqui. `program` vem do mesmo lugar.

`edital_regular` e `edital_suplementar` são editais publicados com a
janela de inscrição aberta (2026-01-01 → 2026-12-31) e as três etapas
padrão de cada tipo; testes de janela fechada ajustam as datas na hora.
"""

from datetime import UTC, date, datetime

import pytest

from apps.academic.models import Teacher
from apps.people.models import Person
from apps.programs.models import Program
from apps.selection.models import SelectionKind, SelectionProcess, SelectionStage

ABERTURA = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
ENCERRAMENTO = datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
PUBLICACAO = datetime(2025, 12, 15, 12, 0, tzinfo=UTC)

# (nome, posição no desempate) — dado do edital, não código do sistema.
ETAPAS_REGULAR = (("Resumo expandido", 1), ("Prova oral", 2), ("Entrevista", None))
ETAPAS_SUPLEMENTAR = (
    ("Memorial", 1),
    ("Prova oral", 2),
    ("Análise do projeto e memorial", None),
)


def _edital(program: Program, kind: str, title: str, etapas) -> SelectionProcess:
    edital = SelectionProcess(
        program=program,
        kind=kind,
        year=2027,
        title=title,
        submission_opens_at=ABERTURA,
        submission_closes_at=ENCERRAMENTO,
        convocation_subject="Convocação — {etapa} — {edital}",
        convocation_body=(
            "Prezado(a) {nome}, inscrição {protocolo}: compareça à etapa "
            "{etapa} em {data_hora}, no local {local}."
        ),
    )
    edital.clean()
    edital.publish(at=PUBLICACAO)
    edital.save()
    for ordem, (nome, desempate) in enumerate(etapas, start=1):
        etapa = SelectionStage(
            process=edital, name=nome, order=ordem, tiebreak_rank=desempate
        )
        etapa.clean()
        etapa.save()
    return edital


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
def edital_regular(program: Program) -> SelectionProcess:
    return _edital(
        program, SelectionKind.REGULAR, "Edital Regular 2027", ETAPAS_REGULAR
    )


@pytest.fixture
def edital_suplementar(program: Program) -> SelectionProcess:
    return _edital(
        program,
        SelectionKind.SUPPLEMENTARY,
        "Edital Suplementar 2027",
        ETAPAS_SUPLEMENTAR,
    )
