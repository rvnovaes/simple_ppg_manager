"""Invariantes de `AccessRequest` — nível (a) da pirâmide (Seção 9).

Objeto em memória, sem banco e sem mock: os pks são atribuídos à mão só
para as FKs terem id. O que o banco precisa garantir por si (uma pendente
por pessoa, campos de docente coerentes) é testado em
`test_access_request_constraints.py`, batendo no INSERT.
"""

import pytest

from apps.academic.models import AccessRequest, Teacher
from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.people.models import Person
from apps.programs.models import Program


def _solicitacao(**kwargs) -> AccessRequest:
    programa = Program(pk=1, acronym="PPGD")
    pessoa = Person(pk=1, program=programa, full_name="Ana Lima")
    campos = {
        "program": programa,
        "person": pessoa,
        "profile": AccessRequest.Profile.STUDENT,
    }
    campos.update(kwargs)
    return AccessRequest(**campos)


def test_decidir_duas_vezes_e_recusado():
    """Decidir de novo criaria um segundo vínculo para a mesma pessoa."""
    solicitacao = _solicitacao()
    solicitacao.approve()

    with pytest.raises(InvalidStateTransition) as exc:
        solicitacao.reject(note="Mudei de ideia.")

    assert exc.value.code == "already_decided"
    assert solicitacao.status == AccessRequest.Status.APPROVED


def test_aprovar_carimba_a_data_da_decisao():
    solicitacao = _solicitacao()

    solicitacao.approve()

    assert solicitacao.status == AccessRequest.Status.APPROVED
    assert solicitacao.decided_at is not None


def test_recusar_sem_motivo_e_recusado():
    solicitacao = _solicitacao()

    with pytest.raises(DomainError) as exc:
        solicitacao.reject(note="   ")

    assert exc.value.code == "rejection_requires_note"
    assert solicitacao.status == AccessRequest.Status.PENDING


def test_recusar_com_motivo_guarda_o_motivo():
    solicitacao = _solicitacao()

    solicitacao.reject(note="Não localizamos o vínculo com o programa.")

    assert solicitacao.status == AccessRequest.Status.REJECTED
    assert solicitacao.decision_note == "Não localizamos o vínculo com o programa."
    assert solicitacao.decided_at is not None


def test_clean_recusa_programa_diferente_do_da_pessoa():
    """FK `program` direta (ADR-007 dec. 5) pode divergir da da pessoa —
    divergir é AuditLog com a chave de tenant errada.
    """
    solicitacao = _solicitacao(program=Program(pk=2, acronym="PPGA"))

    with pytest.raises(DomainError) as exc:
        solicitacao.clean()

    assert exc.value.code == "program_mismatch"


def test_clean_recusa_externo_sem_instituicao_de_origem():
    solicitacao = _solicitacao(
        profile=AccessRequest.Profile.TEACHER,
        teacher_category=Teacher.Category.EXTERNAL,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        home_institution="   ",
    )

    with pytest.raises(DomainError) as exc:
        solicitacao.clean()

    assert exc.value.code == "home_institution_required"


def test_clean_aceita_externo_com_instituicao_de_origem():
    solicitacao = _solicitacao(
        profile=AccessRequest.Profile.TEACHER,
        teacher_category=Teacher.Category.EXTERNAL,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        home_institution="UFMG",
    )

    solicitacao.clean()
