"""Detalhe e desativação de professor e aluno.

O sistema não apaga ninguém: professor recebe data de descredenciamento,
aluno vai para Excluído. É o que a tela chama de excluir, e o que protege
o histórico — as FKs para estes dois models são PROTECT.
"""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.academic.models import Student, Teacher
from apps.accounts.models import User
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine

SENHA = "senha-de-teste-123"


@pytest.fixture(autouse=True)
def pessoa_da_sessao(db, program, secretaria: User) -> Person:
    """`current_program` resolve o tenant pela Person ativa do usuário."""
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Sônia Barreto",
        primary_email="sonia@exemplo.br",
    )


@pytest.fixture
def professor(db, program) -> Teacher:
    pessoa = Person.objects.create(
        program=program, full_name="Ana Matos", primary_email="ana@exemplo.br"
    )
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2022, 3, 1),
    )


@pytest.fixture
def aluno(db, program, professor) -> Student:
    linha = ResearchLine.objects.create(program=program, name="Linha")
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto"
    )
    pessoa = Person.objects.create(
        program=program, full_name="Daniel Prado", primary_email="daniel@exemplo.br"
    )
    return Student.objects.create(
        program=program,
        person=pessoa,
        level=Student.Level.MASTERS,
        project=projeto,
        advisor=professor,
        admission_date=date(2025, 3, 3),
    )


# --------------------------------------------------------------------
# Detalhe
# --------------------------------------------------------------------


def test_detalhe_do_professor(client_secretaria, professor):
    resposta = client_secretaria.get(f"/api/v1/academic/teachers/{professor.id}/")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["person"]["full_name"] == "Ana Matos"


def test_detalhe_do_aluno(client_secretaria, aluno):
    resposta = client_secretaria.get(f"/api/v1/academic/students/{aluno.id}/")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["person"]["full_name"] == "Daniel Prado"


def test_detalhe_de_outro_programa_e_404_e_nao_403(client_secretaria, professor):
    """404 e nunca 403: 403 confirmaria que o id existe em algum lugar."""
    outro = Program.objects.create(acronym="PPGA", name="Outro")
    pessoa = Person.objects.create(
        program=outro, full_name="Alheia", primary_email="alheia@exemplo.br"
    )
    alheio = Teacher.objects.create(
        program=outro,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2022, 3, 1),
    )

    resposta = client_secretaria.get(f"/api/v1/academic/teachers/{alheio.id}/")

    assert resposta.status_code == 404


def test_detalhe_sem_permissao(client_sem_permissao, professor):
    resposta = client_sem_permissao.get(f"/api/v1/academic/teachers/{professor.id}/")

    assert resposta.status_code == 403


# --------------------------------------------------------------------
# Descredenciar professor
# --------------------------------------------------------------------


def test_descredenciar_professor_sem_data_usa_hoje(client_secretaria, professor):
    resposta = client_secretaria.post(
        f"/api/v1/academic/teachers/{professor.id}/deaccredit",
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 200, resposta.content
    professor.refresh_from_db()
    assert professor.accredited_until == timezone.localdate()
    # Não apaga: o registro continua lá, com o histórico intacto.
    assert Teacher.objects.filter(pk=professor.pk).exists()


def test_descredenciar_professor_com_data_retroativa(client_secretaria, professor):
    """A portaria costuma sair depois do fato."""
    ontem = timezone.localdate() - timedelta(days=1)

    resposta = client_secretaria.post(
        f"/api/v1/academic/teachers/{professor.id}/deaccredit",
        data={"on": ontem.isoformat()},
        content_type="application/json",
    )

    assert resposta.status_code == 200, resposta.content
    professor.refresh_from_db()
    assert professor.accredited_until == ontem


def test_descredenciar_duas_vezes_e_409(client_secretaria, professor):
    url = f"/api/v1/academic/teachers/{professor.id}/deaccredit"
    client_secretaria.post(url, data={}, content_type="application/json")

    resposta = client_secretaria.post(url, data={}, content_type="application/json")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "already_deaccredited"


def test_descredenciar_antes_do_credenciamento_e_400(client_secretaria, professor):
    resposta = client_secretaria.post(
        f"/api/v1/academic/teachers/{professor.id}/deaccredit",
        data={"on": "2020-01-01"},
        content_type="application/json",
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_deaccreditation_date"


def test_descredenciar_sem_permissao(client_sem_permissao, professor):
    resposta = client_sem_permissao.post(
        f"/api/v1/academic/teachers/{professor.id}/deaccredit",
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 403
    professor.refresh_from_db()
    assert professor.accredited_until is None


def test_descredenciar_professor_de_outro_programa_e_404(client_secretaria):
    outro = Program.objects.create(acronym="PPGA", name="Outro")
    pessoa = Person.objects.create(
        program=outro, full_name="Alheia", primary_email="alheia@exemplo.br"
    )
    alheio = Teacher.objects.create(
        program=outro,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2022, 3, 1),
    )

    resposta = client_secretaria.post(
        f"/api/v1/academic/teachers/{alheio.id}/deaccredit",
        data={},
        content_type="application/json",
    )

    assert resposta.status_code == 404
    alheio.refresh_from_db()
    assert alheio.accredited_until is None


# --------------------------------------------------------------------
# Excluir aluno
# --------------------------------------------------------------------


def test_excluir_aluno_muda_situacao_e_nao_apaga(client_secretaria, aluno):
    resposta = client_secretaria.post(f"/api/v1/academic/students/{aluno.id}/exclude")

    assert resposta.status_code == 200, resposta.content
    aluno.refresh_from_db()
    assert aluno.status == Student.Status.EXCLUDED
    assert Student.objects.filter(pk=aluno.pk).exists()


def test_excluir_aluno_duas_vezes_e_409(client_secretaria, aluno):
    url = f"/api/v1/academic/students/{aluno.id}/exclude"
    client_secretaria.post(url)

    resposta = client_secretaria.post(url)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "already_excluded"


def test_excluir_aluno_sem_permissao(client_sem_permissao, aluno):
    resposta = client_sem_permissao.post(
        f"/api/v1/academic/students/{aluno.id}/exclude"
    )

    assert resposta.status_code == 403
    aluno.refresh_from_db()
    assert aluno.status == Student.Status.ACTIVE


def test_excluir_aluno_de_outro_programa_e_404(client_secretaria, program):
    outro = Program.objects.create(acronym="PPGA", name="Outro")
    linha = ResearchLine.objects.create(program=outro, name="Linha")
    projeto = CollectiveProject.objects.create(
        program=outro, research_line=linha, name="Projeto"
    )
    pessoa = Person.objects.create(
        program=outro, full_name="Alheio", primary_email="alheio@exemplo.br"
    )
    alheio = Student.objects.create(
        program=outro,
        person=pessoa,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2025, 3, 3),
    )

    resposta = client_secretaria.post(f"/api/v1/academic/students/{alheio.id}/exclude")

    assert resposta.status_code == 404
    alheio.refresh_from_db()
    assert alheio.status == Student.Status.ACTIVE


# --------------------------------------------------------------------
# Arquivar pessoa: o escopo de tenant que faltava
# --------------------------------------------------------------------


def test_arquivar_pessoa_de_outro_programa_e_404(client_secretaria):
    """Sem escopo na busca, a secretaria de um programa arquivava pessoa
    de outro só sabendo o id."""
    outro = Program.objects.create(acronym="PPGA", name="Outro")
    user = User.objects.create_user(username="externa", password=SENHA)
    user.groups.add(Group.objects.get(name="Secretaria"))
    alheia = Person.objects.create(
        program=outro,
        user=user,
        full_name="Alheia ao PPGD",
        primary_email="alheia@exemplo.br",
    )

    resposta = client_secretaria.post(f"/api/v1/people/{alheia.id}/archive")

    assert resposta.status_code == 404
    alheia.refresh_from_db()
    assert alheia.status == Person.Status.ACTIVE


def test_detalhe_da_pessoa(client_secretaria, pessoa_da_sessao):
    resposta = client_secretaria.get(f"/api/v1/people/{pessoa_da_sessao.id}/")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["full_name"] == "Sônia Barreto"
