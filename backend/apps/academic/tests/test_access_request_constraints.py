"""As constraints de `AccessRequest` — nível (b) da pirâmide, com banco.

`clean()` protege quem passa pelo caminho do domínio; a constraint protege
o banco de qualquer caminho, inclusive o Admin e um shell. Por isso ela é
testada batendo no INSERT, e não chamando método.
"""

import pytest
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction

from apps.academic.models import AccessRequest, Teacher
from apps.people.models import Person
from apps.programs.models import Program


@pytest.fixture
def pessoa(program: Program) -> Person:
    return Person.objects.create(
        program=program, full_name="Ana Lima", primary_email="ana@example.com"
    )


def _solicitar(*, program: Program, person: Person, **kwargs) -> AccessRequest:
    campos = {"profile": AccessRequest.Profile.STUDENT}
    campos.update(kwargs)
    return AccessRequest.objects.create(program=program, person=person, **campos)


def test_duas_pendentes_da_mesma_pessoa_sao_rejeitadas(program, pessoa):
    _solicitar(program=program, person=pessoa)

    with pytest.raises(IntegrityError), transaction.atomic():
        _solicitar(program=program, person=pessoa)


def test_pendente_depois_de_recusada_e_aceita(program, pessoa):
    """O índice é PARCIAL: quem foi recusado pode se cadastrar de novo."""
    _solicitar(
        program=program,
        person=pessoa,
        status=AccessRequest.Status.REJECTED,
        decision_note="Não localizamos o vínculo.",
    )

    _solicitar(program=program, person=pessoa)

    assert pessoa.access_requests.count() == 2
    assert pessoa.access_requests.pending().count() == 1


def test_docente_sem_categoria_e_rejeitado(program, pessoa):
    with pytest.raises(IntegrityError), transaction.atomic():
        _solicitar(
            program=program,
            person=pessoa,
            profile=AccessRequest.Profile.TEACHER,
            academic_degree=Teacher.AcademicDegree.DOCTORATE,
        )


def test_docente_sem_titulacao_e_rejeitado(program, pessoa):
    with pytest.raises(IntegrityError), transaction.atomic():
        _solicitar(
            program=program,
            person=pessoa,
            profile=AccessRequest.Profile.TEACHER,
            teacher_category=Teacher.Category.PERMANENT,
        )


def test_docente_externo_sem_instituicao_e_rejeitado(program, pessoa):
    with pytest.raises(IntegrityError), transaction.atomic():
        _solicitar(
            program=program,
            person=pessoa,
            profile=AccessRequest.Profile.TEACHER,
            teacher_category=Teacher.Category.EXTERNAL,
            academic_degree=Teacher.AcademicDegree.DOCTORATE,
        )


def test_nao_docente_com_campo_de_docente_e_rejeitado(program, pessoa):
    with pytest.raises(IntegrityError), transaction.atomic():
        _solicitar(
            program=program,
            person=pessoa,
            profile=AccessRequest.Profile.STUDENT,
            academic_degree=Teacher.AcademicDegree.DOCTORATE,
        )


def test_docente_permanente_completo_e_aceito(program, pessoa):
    solicitacao = _solicitar(
        program=program,
        person=pessoa,
        profile=AccessRequest.Profile.TEACHER,
        teacher_category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
    )

    assert solicitacao.status == AccessRequest.Status.PENDING


@pytest.mark.django_db
def test_marcador_cadastro_pendente_nao_concede_nada() -> None:
    """O grupo "Cadastro pendente" é marcador de estado, não papel: a tela de
    espera o reconhece pelo nome, e zero permissão é o que garante que ele
    não abre nenhuma rota enquanto a secretaria não decide.
    """
    assert Group.objects.get(name="Cadastro pendente").permissions.count() == 0
