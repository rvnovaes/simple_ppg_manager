"""Vínculo entre Person e User.

Antes de existir a FK, Person e User ficavam ligados só por coincidência
de e-mail: editar qualquer um dos lados desfazia a associação em silêncio.
Estes testes existem para que isso não volte.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.accounts.models import User
from apps.people.models import Person
from apps.people.services import create_person_with_user
from apps.programs.models import Program

pytestmark = pytest.mark.django_db


def test_service_grava_a_fk_e_nao_so_o_email(program):
    pessoa = create_person_with_user(
        program=program, full_name="Ana Lima", email="ana@exemplo.br"
    )

    assert pessoa.user is not None
    assert pessoa.user.username == "ana@exemplo.br"
    # O caminho de volta também precisa existir.
    assert list(pessoa.user.people.all()) == [pessoa]


def test_pessoa_sem_conta_e_permitida(program):
    """Egresso, registro histórico, quem nunca vai logar."""
    pessoa = Person.objects.create(
        program=program, full_name="Beto Souza", primary_email="beto@exemplo.br"
    )

    assert pessoa.user is None


def test_mesma_conta_nao_se_repete_no_mesmo_programa(program):
    create_person_with_user(
        program=program, full_name="Ana Lima", email="ana@exemplo.br"
    )
    conta = User.objects.get(username="ana@exemplo.br")

    with pytest.raises(IntegrityError), transaction.atomic():
        Person.objects.create(
            program=program,
            user=conta,
            full_name="Ana Lima (duplicada)",
            primary_email="outro@exemplo.br",
        )


def test_mesma_conta_em_programas_diferentes_e_permitida(program):
    """O caso multi-tenant: uma pessoa física atuando em dois programas."""
    pessoa = create_person_with_user(
        program=program, full_name="Ana Lima", email="ana@exemplo.br"
    )
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")

    segunda = Person.objects.create(
        program=outro,
        user=pessoa.user,
        full_name="Ana Lima",
        primary_email="ana@exemplo.br",
    )

    assert pessoa.user.people.count() == 2
    assert {p.program.acronym for p in pessoa.user.people.all()} == {"PPGD", "PPGE"}
    assert segunda.user == pessoa.user


def test_conta_com_pessoa_nao_pode_ser_apagada(program):
    """PROTECT: apagar a conta levaria o dado de negócio junto."""
    pessoa = create_person_with_user(
        program=program, full_name="Ana Lima", email="ana@exemplo.br"
    )

    with pytest.raises(ProtectedError):
        pessoa.user.delete()


def test_me_devolve_as_pessoas_da_conta(client, program, secretaria):
    """O front precisa saber qual pessoa do domínio é a conta logada."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client.force_login(secretaria)

    corpo = client.get("/api/v1/auth/me").json()

    assert len(corpo["people"]) == 1
    assert corpo["people"][0]["full_name"] == "Carla Dias"
    assert corpo["people"][0]["program_acronym"] == "PPGD"


def test_me_sem_pessoa_devolve_lista_vazia(client, secretaria):
    """Sysadmin não tem Person e ainda assim precisa poder usar a API."""
    client.force_login(secretaria)

    assert client.get("/api/v1/auth/me").json()["people"] == []
