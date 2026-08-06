"""Fixtures do fluxo de disciplina isolada, compartilhadas pelos módulos
de teste com banco (`test_isolada_*.py`).

O edital inteiro pende de um ciclo com calendário coerente e de uma oferta
dentro dele; repetir esse arranjo em cada módulo é como as fixtures saem de
sincronia. Testes em memória (`test_models.py`) não usam nada daqui.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.academic.models import (
    DisciplineOffering,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentRequest,
    RequestDocument,
    Teacher,
)
from apps.accounts.models import User
from apps.people.models import Person
from apps.programs.models import AcademicTerm, Discipline, Program

DENTRO_DA_INSCRICAO = datetime(2026, 2, 5, tzinfo=UTC)
SENHA = "senha-de-teste-123"


@pytest.fixture
def periodo(db) -> AcademicTerm:
    return AcademicTerm.objects.create(
        year=2026, half=1, starts_on=date(2026, 3, 2), ends_on=date(2026, 7, 18)
    )


@pytest.fixture
def ciclo(program: Program, periodo: AcademicTerm) -> IsolatedEnrollmentCycle:
    return IsolatedEnrollmentCycle.objects.create(
        program=program,
        term=periodo,
        submission_opens_at=datetime(2026, 2, 1, tzinfo=UTC),
        submission_closes_at=datetime(2026, 2, 10, tzinfo=UTC),
        result_published_on=date(2026, 2, 12),
        appeal_opens_at=datetime(2026, 2, 12, tzinfo=UTC),
        appeal_closes_at=datetime(2026, 2, 15, tzinfo=UTC),
        final_result_on=date(2026, 2, 17),
        payment_closes_at=datetime(2026, 2, 25, tzinfo=UTC),
    )


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
def oferta(
    program: Program, ciclo: IsolatedEnrollmentCycle, docente: Teacher
) -> DisciplineOffering:
    disciplina = Discipline.objects.create(
        program=program, code="DIR001", name="Teoria do Direito"
    )
    return DisciplineOffering.objects.create(
        program=program, cycle=ciclo, discipline=disciplina, teacher=docente, seats=2
    )


def criar_candidato(*, program: Program, username: str, nome: str) -> Person:
    """Candidato completo: conta no papel Candidato e Person ativa.

    A Person ativa não é detalhe de fixture — é dela que `current_program`
    tira o tenant da requisição.
    """
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name="Candidato"))
    return Person.objects.create(
        program=program,
        user=user,
        full_name=nome,
        primary_email=f"{username}@exemplo.br",
    )


def logar(client: Client, pessoa: Person) -> Client:
    """`Person.user` é opcional no model (pessoa sem conta é registro
    histórico); quem se loga aqui sempre tem uma.
    """
    user = pessoa.user
    assert user is not None
    client.force_login(user)
    return client


def criar_requerimento(
    *, program: Program, ciclo: IsolatedEnrollmentCycle, nome: str, **kwargs
) -> IsolatedEnrollmentRequest:
    pessoa = Person.objects.create(
        program=program,
        full_name=nome,
        primary_email=f"{nome.split()[0].lower()}@example.com",
    )
    return IsolatedEnrollmentRequest.objects.create(
        program=program, cycle=ciclo, person=pessoa, **kwargs
    )


@pytest.fixture
def requerimento(
    program: Program, ciclo: IsolatedEnrollmentCycle
) -> IsolatedEnrollmentRequest:
    return criar_requerimento(program=program, ciclo=ciclo, nome="Carla Reis")


@pytest.fixture
def ciclo_aberto(program: Program) -> IsolatedEnrollmentCycle:
    """Edital com a janela de inscrição em torno de agora.

    As rotas do candidato resolvem o ciclo por `timezone.now()` — elas são
    o formulário de quem se inscreve, e não recebem `at` de ninguém. Por
    isso este ciclo é relativo ao relógio, ao contrário do `ciclo`, que
    tem datas fixas para os testes de janela.

    Período letivo próprio: `unique_ciclo_isolada_por_programa_e_periodo`
    impede os dois ciclos de dividirem o mesmo semestre.
    """
    periodo = AcademicTerm.objects.create(
        year=2027, half=1, starts_on=date(2027, 3, 1), ends_on=date(2027, 7, 17)
    )
    agora = timezone.now()
    fecha = agora + timedelta(days=1)
    return IsolatedEnrollmentCycle.objects.create(
        program=program,
        term=periodo,
        submission_opens_at=agora - timedelta(days=1),
        submission_closes_at=fecha,
        result_published_on=date(2027, 2, 12),
        appeal_opens_at=fecha + timedelta(days=1),
        appeal_closes_at=fecha + timedelta(days=3),
        final_result_on=date(2027, 2, 17),
        payment_closes_at=fecha + timedelta(days=10),
    )


@pytest.fixture
def ofertas_abertas(
    program: Program, ciclo_aberto: IsolatedEnrollmentCycle, docente: Teacher
) -> list[DisciplineOffering]:
    return [
        DisciplineOffering.objects.create(
            program=program,
            cycle=ciclo_aberto,
            discipline=Discipline.objects.create(
                program=program, code=codigo, name=nome
            ),
            teacher=docente,
            seats=vagas,
        )
        for codigo, nome, vagas in (
            ("DIR010", "Direito e Trabalho", 2),
            ("DIR011", "Processo Constitucional", 3),
            ("DIR012", "Filosofia do Direito", 1),
        )
    ]


def anexar_documentos_obrigatorios(
    requerimento: IsolatedEnrollmentRequest,
) -> None:
    """Anexa exatamente o que aquele requerimento exige.

    Usa `required_document_kinds()` de propósito: o teste do caso feliz
    não deve congelar a lista do edital, senão acrescentar um documento
    obrigatório quebra todo teste que só queria um requerimento válido.
    """
    for kind in requerimento.required_document_kinds():
        RequestDocument.objects.create(
            request=requerimento,
            kind=kind,
            file=SimpleUploadedFile(f"{kind}.pdf", b"conteudo"),
        )
