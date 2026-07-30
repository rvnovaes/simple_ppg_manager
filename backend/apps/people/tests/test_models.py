"""Invariantes de Person.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
É por isso que a regra mora no model.
"""

import pytest

from apps.core.exceptions import InvalidStateTransition
from apps.people.models import Person


def test_archive_muda_status_para_arquivada():
    person = Person(full_name="Ana Lima", primary_email="ana@exemplo.br")

    person.archive()

    assert person.status == Person.Status.ARCHIVED


def test_archive_duas_vezes_levanta_invalid_state_transition():
    person = Person(
        full_name="Ana Lima",
        primary_email="ana@exemplo.br",
        status=Person.Status.ARCHIVED,
    )

    with pytest.raises(InvalidStateTransition) as exc:
        person.archive()

    assert exc.value.code == "invalid_state_transition"
    assert exc.value.status_code == 409


def test_pessoa_nasce_ativa():
    assert Person(full_name="Ana Lima").status == Person.Status.ACTIVE
