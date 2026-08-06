"""Listagem de pessoas recortada por vínculo (`?bond=`).

O que estes testes protegem é a decisão de desenho: os quatro recortes NÃO
são exclusivos. Quem coordena e dá aula é uma pessoa só, e some da tela de
alguém no dia em que "tipo de pessoa" virar um campo.
"""

from datetime import date

import pytest
from django.contrib.auth.models import Group

from apps.academic.models import (
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentRequest,
    Student,
    Teacher,
)
from apps.accounts.models import User
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Program,
    ResearchLine,
)

URL = "/api/v1/people/"


def nomes(resposta) -> list[str]:
    return sorted(item["full_name"] for item in resposta.json()["items"])


@pytest.fixture
def professora(db, program) -> Person:
    pessoa = Person.objects.create(
        program=program, full_name="Ana Matos", primary_email="ana@exemplo.br"
    )
    Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2022, 3, 1),
    )
    return pessoa


@pytest.fixture
def aluno(db, program, professora) -> Person:
    linha = ResearchLine.objects.create(program=program, name="Linha")
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto"
    )
    pessoa = Person.objects.create(
        program=program, full_name="Daniel Prado", primary_email="daniel@exemplo.br"
    )
    Student.objects.create(
        program=program,
        person=pessoa,
        level=Student.Level.MASTERS,
        project=projeto,
        advisor=professora.teacher_profile,
        admission_date=date(2025, 3, 3),
    )
    return pessoa


@pytest.fixture
def candidata(db, program) -> Person:
    pessoa = Person.objects.create(
        program=program, full_name="Karina Belo", primary_email="karina@exemplo.br"
    )
    termo = AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 19)
    )
    ciclo = IsolatedEnrollmentCycle.objects.create(
        program=program,
        term=termo,
        submission_opens_at="2026-07-01T00:00:00Z",
        submission_closes_at="2026-07-20T00:00:00Z",
        result_published_on=date(2026, 7, 25),
        appeal_opens_at="2026-07-26T00:00:00Z",
        appeal_closes_at="2026-07-30T00:00:00Z",
        final_result_on=date(2026, 8, 1),
        payment_closes_at="2026-08-10T00:00:00Z",
    )
    IsolatedEnrollmentRequest.objects.create(
        program=program, cycle=ciclo, person=pessoa
    )
    return pessoa


@pytest.fixture(autouse=True)
def administrativa(db, program, secretaria: User) -> Person:
    """A pessoa da sessão — e, de quebra, o caso administrativo.

    Autouse porque `current_program` resolve o tenant pela Person ativa do
    usuário: sem ela toda rota devolve 403 antes de chegar ao filtro.
    """
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Sônia Barreto",
        primary_email="sonia@exemplo.br",
    )


def test_sem_bond_devolve_todo_mundo(client_secretaria, professora, aluno, candidata):
    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200, resposta.content
    assert nomes(resposta) == [
        "Ana Matos",
        "Daniel Prado",
        "Karina Belo",
        "Sônia Barreto",
    ]


@pytest.mark.parametrize(
    ("bond", "esperado"),
    [
        ("teacher", ["Ana Matos"]),
        ("student", ["Daniel Prado"]),
        ("candidate", ["Karina Belo"]),
        ("staff", ["Sônia Barreto"]),
    ],
)
def test_cada_bond_traz_so_o_seu_vinculo(
    client_secretaria, professora, aluno, candidata, bond, esperado
):
    resposta = client_secretaria.get(URL, {"bond": bond})

    assert resposta.status_code == 200, resposta.content
    assert nomes(resposta) == esperado


def test_quem_coordena_e_da_aula_aparece_nos_dois(client_secretaria, program):
    """O caso que motiva os recortes não serem exclusivos.

    Se um dia isto falhar, alguém transformou vínculo num campo — e o
    coordenador que dá aula sumiu de uma das duas telas.
    """
    user = User.objects.create_user(username="claudio", password="x")
    user.groups.add(Group.objects.get(name="Coordenação"))
    pessoa = Person.objects.create(
        program=program,
        user=user,
        full_name="Cláudio Ferraz",
        primary_email="claudio@exemplo.br",
    )
    Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2021, 3, 1),
    )

    assert nomes(client_secretaria.get(URL, {"bond": "teacher"})) == ["Cláudio Ferraz"]
    # A pessoa da sessão também é administrativa, daí as duas.
    assert nomes(client_secretaria.get(URL, {"bond": "staff"})) == [
        "Cláudio Ferraz",
        "Sônia Barreto",
    ]


def test_aluno_com_varios_vinculos_aparece_uma_vez(
    client_secretaria, program, professora
):
    """Quem cursou duas isoladas e virou regular tem três Student — e
    apareceria três vezes sem o distinct."""
    linha = ResearchLine.objects.create(program=program, name="Linha")
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto"
    )
    pessoa = Person.objects.create(
        program=program, full_name="Heitor Lima", primary_email="heitor@exemplo.br"
    )
    for ano, semestre in ((2025, 1), (2025, 2)):
        termo = AcademicTerm.objects.create(
            year=ano,
            half=semestre,
            starts_on=date(ano, 3, 1),
            ends_on=date(ano, 7, 1),
        )
        Student.objects.create(
            program=program,
            person=pessoa,
            modality=Student.Modality.ISOLATED,
            term=termo,
        )
    Student.objects.create(
        program=program,
        person=pessoa,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2026, 3, 2),
    )

    resposta = client_secretaria.get(URL, {"bond": "student"})

    assert nomes(resposta) == ["Heitor Lima"]


def test_bond_invalido_e_recusado_na_borda(client_secretaria):
    """Enum no schema: valor fora dos quatro não chega ao queryset."""
    resposta = client_secretaria.get(URL, {"bond": "faxineiro"})

    assert resposta.status_code == 422


def test_bond_respeita_o_escopo_de_programa(client_secretaria, program):
    """O recorte é encadeado DEPOIS de for_program, nunca no lugar dele."""
    outro = Program.objects.create(acronym="PPGA", name="Outro programa")
    user = User.objects.create_user(username="externa", password="x")
    user.groups.add(Group.objects.get(name="Secretaria"))
    Person.objects.create(
        program=outro,
        user=user,
        full_name="Alheia ao PPGD",
        primary_email="alheia@exemplo.br",
    )

    resposta = client_secretaria.get(URL, {"bond": "staff"})

    assert resposta.status_code == 200, resposta.content
    assert "Alheia ao PPGD" not in nomes(resposta)
