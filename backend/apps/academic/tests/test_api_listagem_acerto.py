"""Fluxo real pela listagem de acertos de matrícula, papel a papel.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade, sem mock de
ORM. O que este arquivo prova é o recorte que a permissão de grupo não
cobre — os quatro papéis têm `view_enrollmentadjustmentrequest`, mas cada
um vê um conjunto diferente. Todo papel precisa de uma Person ativa no
programa: é dela que `current_program` tira o tenant.
"""

from datetime import date

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import (
    EnrollmentAdjustmentItem,
    EnrollmentAdjustmentRequest,
    Student,
    Teacher,
)
from apps.accounts.models import User
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Discipline,
    Program,
    ResearchLine,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/enrollment-requests/"
SENHA = "senha-de-teste-123"


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Pós em Economia", acronym="PPGE")


def _projeto(program: Program, nome: str) -> CollectiveProject:
    linha = ResearchLine.objects.create(program=program, name=f"Linha {nome}")
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name=nome
    )


@pytest.fixture
def projeto(program) -> CollectiveProject:
    return _projeto(program, "Justiça e Trabalho")


@pytest.fixture
def periodo(db) -> AcademicTerm:
    return AcademicTerm.objects.create(
        year=2026, half=1, starts_on=date(2026, 3, 2), ends_on=date(2026, 7, 10)
    )


@pytest.fixture
def periodo_seguinte(db) -> AcademicTerm:
    return AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 12)
    )


@pytest.fixture
def disciplina(program) -> Discipline:
    return Discipline.objects.create(program=program, code="DIR001", name="Teoria")


def _pessoa_com_conta(
    *, program: Program, username: str, nome: str, papel: str
) -> Person:
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name=papel))
    return Person.objects.create(
        program=program,
        user=user,
        full_name=nome,
        primary_email=f"{username}@exemplo.br",
    )


def _docente(*, program: Program, username: str, nome: str) -> Teacher:
    return Teacher.objects.create(
        program=program,
        person=_pessoa_com_conta(
            program=program, username=username, nome=nome, papel="Docente"
        ),
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 1, 1),
    )


def _aluno(
    *,
    program: Program,
    username: str,
    nome: str,
    projeto: CollectiveProject,
    orientador: Teacher | None,
) -> Student:
    return Student.objects.create(
        program=program,
        person=_pessoa_com_conta(
            program=program, username=username, nome=nome, papel="Discente"
        ),
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        advisor=orientador,
        admission_date=date(2026, 3, 2),
    )


def _solicitacao(
    *,
    program: Program,
    student: Student,
    term: AcademicTerm,
    discipline: Discipline,
    status: str = EnrollmentAdjustmentRequest.Status.OPEN,
) -> EnrollmentAdjustmentRequest:
    pedido = EnrollmentAdjustmentRequest.objects.create(
        program=program,
        student=student,
        term=term,
        status=status,
        justification="Conflito de horário.",
    )
    EnrollmentAdjustmentItem.objects.create(
        request=pedido,
        discipline=discipline,
        action=EnrollmentAdjustmentItem.Action.ADD,
    )
    return pedido


@pytest.fixture
def orientadora(program) -> Teacher:
    return _docente(program=program, username="celia", nome="Célia Souza")


@pytest.fixture
def outro_docente(program) -> Teacher:
    return _docente(program=program, username="bruno", nome="Bruno Lima")


@pytest.fixture
def ana(program, projeto, orientadora) -> Student:
    return _aluno(
        program=program,
        username="ana",
        nome="Ana Ribeiro",
        projeto=projeto,
        orientador=orientadora,
    )


@pytest.fixture
def beto(program, projeto, outro_docente) -> Student:
    return _aluno(
        program=program,
        username="beto",
        nome="Beto Alves",
        projeto=projeto,
        orientador=outro_docente,
    )


@pytest.fixture
def acerto_da_ana(program, ana, periodo, disciplina) -> EnrollmentAdjustmentRequest:
    return _solicitacao(
        program=program, student=ana, term=periodo, discipline=disciplina
    )


@pytest.fixture
def acerto_do_beto(program, beto, periodo, disciplina) -> EnrollmentAdjustmentRequest:
    return _solicitacao(
        program=program, student=beto, term=periodo, discipline=disciplina
    )


@pytest.fixture
def acerto_de_outro_programa(outro_programa, periodo) -> EnrollmentAdjustmentRequest:
    aluno = _aluno(
        program=outro_programa,
        username="carlos",
        nome="Carlos Nunes",
        projeto=_projeto(outro_programa, "Macroeconomia"),
        orientador=None,
    )
    disciplina = Discipline.objects.create(
        program=outro_programa, code="ECO001", name="Micro"
    )
    return _solicitacao(
        program=outro_programa, student=aluno, term=periodo, discipline=disciplina
    )


def _logar(client: Client, pessoa: Person) -> Client:
    """`Person.user` é opcional no model (pessoa sem conta é registro
    histórico); nestas fixtures todas têm.
    """
    user = pessoa.user
    assert user is not None
    client.force_login(user)
    return client


@pytest.fixture
def secretaria_no_programa(secretaria, program) -> Person:
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


@pytest.fixture
def coordenacao_no_programa(program) -> Person:
    return _pessoa_com_conta(
        program=program,
        username="coordenacao",
        nome="Dora Prado",
        papel="Coordenação",
    )


def _ids(resposta) -> list[int]:
    assert resposta.status_code == 200, resposta.content
    return [item["id"] for item in resposta.json()["items"]]


def test_aluno_ve_apenas_as_proprias(client, ana, acerto_da_ana, acerto_do_beto):
    resposta = _logar(client, ana.person).get(URL)

    assert _ids(resposta) == [acerto_da_ana.id]


def test_orientador_ve_apenas_as_dos_seus_orientandos(
    client, orientadora, acerto_da_ana, acerto_do_beto
):
    resposta = _logar(client, orientadora.person).get(URL)

    assert _ids(resposta) == [acerto_da_ana.id]


def test_secretaria_ve_todas_as_do_programa(
    client_secretaria, secretaria_no_programa, acerto_da_ana, acerto_do_beto
):
    resposta = client_secretaria.get(URL)

    assert sorted(_ids(resposta)) == sorted([acerto_da_ana.id, acerto_do_beto.id])


def test_coordenacao_ve_todas_as_do_programa(
    client, coordenacao_no_programa, acerto_da_ana, acerto_do_beto
):
    resposta = _logar(client, coordenacao_no_programa).get(URL)

    assert sorted(_ids(resposta)) == sorted([acerto_da_ana.id, acerto_do_beto.id])


def test_visao_de_programa_nao_atravessa_o_tenant(
    client_secretaria,
    secretaria_no_programa,
    acerto_da_ana,
    acerto_de_outro_programa,
):
    """Ver o programa inteiro é ver UM programa inteiro."""
    resposta = client_secretaria.get(URL)

    assert _ids(resposta) == [acerto_da_ana.id]


def test_docente_sem_orientando_com_acerto_ve_lista_vazia(
    client, outro_docente, acerto_da_ana
):
    resposta = _logar(client, outro_docente.person).get(URL)

    assert _ids(resposta) == []


def test_a_listagem_traz_itens_e_nome_do_aluno(
    client_secretaria, secretaria_no_programa, acerto_da_ana
):
    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200, resposta.content
    (item,) = resposta.json()["items"]
    assert item["student_name"] == "Ana Ribeiro"
    # A tela da secretaria (US-011) mostra quem decide; sem o campo aqui ela
    # teria de cruzar com a listagem de docentes por solicitação.
    assert item["advisor_name"] == "Célia Souza"
    assert item["status"] == "open"
    assert [mudanca["discipline_code"] for mudanca in item["items"]] == ["DIR001"]


def test_filtro_por_status(
    client_secretaria,
    secretaria_no_programa,
    program,
    ana,
    periodo,
    disciplina,
    acerto_da_ana,
):
    aprovada = _solicitacao(
        program=program,
        student=ana,
        term=periodo,
        discipline=disciplina,
        status=EnrollmentAdjustmentRequest.Status.APPROVED,
    )

    assert _ids(client_secretaria.get(URL, {"status": "approved"})) == [aprovada.id]
    assert _ids(client_secretaria.get(URL, {"status": "open"})) == [acerto_da_ana.id]


def test_filtro_por_periodo(
    client_secretaria,
    secretaria_no_programa,
    program,
    ana,
    periodo_seguinte,
    disciplina,
    acerto_da_ana,
):
    do_semestre_seguinte = _solicitacao(
        program=program, student=ana, term=periodo_seguinte, discipline=disciplina
    )

    resposta = client_secretaria.get(URL, {"term_id": periodo_seguinte.id})

    assert _ids(resposta) == [do_semestre_seguinte.id]


def test_status_invalido_e_recusado_na_borda(
    client_secretaria, secretaria_no_programa, acerto_da_ana
):
    resposta = client_secretaria.get(URL, {"status": "quase"})

    assert resposta.status_code == 422, resposta.content


def test_sem_permissao_devolve_403(client_sem_permissao, acerto_da_ana):
    resposta = client_sem_permissao.get(URL)

    assert resposta.status_code == 403, resposta.content


def test_sem_sessao_devolve_401(client, acerto_da_ana):
    resposta = client.get(URL)

    assert resposta.status_code == 401, resposta.content
