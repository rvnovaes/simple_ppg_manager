"""Programa corrente da requisição.

Testado pelo endpoint real (nível (b) da pirâmide, Seção 9): quem escapa
do escopo é a listagem, então é a listagem que prova o helper.
"""

import pytest

from apps.accounts.models import User
from apps.people.models import Person
from apps.programs.models import Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/people/"


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Pós em Economia", acronym="PPGE")


def _pessoa(program, *, user=None, nome="Ana Lima", email="ana@exemplo.br"):
    return Person.objects.create(
        program=program, user=user, full_name=nome, primary_email=email
    )


def test_lista_so_o_programa_do_usuario(
    client_secretaria, secretaria, program, outro_programa
):
    _pessoa(program, user=secretaria, nome="Carla Dias", email="carla@exemplo.br")
    _pessoa(program, nome="Ana Lima", email="ana@exemplo.br")
    _pessoa(outro_programa, nome="Beto Souza", email="beto@exemplo.br")

    corpo = client_secretaria.get(URL).json()

    nomes = {item["full_name"] for item in corpo["items"]}
    assert nomes == {"Carla Dias", "Ana Lima"}


def test_program_id_de_outro_programa_nao_vaza(
    client_secretaria, secretaria, program, outro_programa
):
    """O antigo filtro livre entregava qualquer tenant a quem pedisse."""
    _pessoa(program, user=secretaria, nome="Carla Dias", email="carla@exemplo.br")
    _pessoa(outro_programa, nome="Beto Souza", email="beto@exemplo.br")

    resposta = client_secretaria.get(URL, {"program_id": outro_programa.id})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "no_program"


def test_sem_pessoa_ativa_devolve_403(client_secretaria):
    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "no_program"


def test_pessoa_arquivada_nao_da_contexto(client_secretaria, secretaria, program):
    pessoa = _pessoa(program, user=secretaria)
    pessoa.archive()
    pessoa.save(update_fields=["status", "updated_at"])

    assert client_secretaria.get(URL).json()["code"] == "no_program"


def test_duas_pessoas_ativas_sem_program_id_devolve_400(
    client_secretaria, secretaria, program, outro_programa
):
    _pessoa(program, user=secretaria, nome="Carla Dias", email="carla@exemplo.br")
    _pessoa(
        outro_programa, user=secretaria, nome="Carla Dias", email="carla@exemplo.br"
    )

    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "program_required"


def test_duas_pessoas_ativas_com_program_id_escopa(
    client_secretaria, secretaria, program, outro_programa
):
    _pessoa(program, user=secretaria, nome="Carla Dias", email="carla@exemplo.br")
    _pessoa(
        outro_programa, user=secretaria, nome="Carla Dias", email="carla@exemplo.br"
    )
    _pessoa(outro_programa, nome="Beto Souza", email="beto@exemplo.br")

    corpo = client_secretaria.get(URL, {"program_id": outro_programa.id}).json()

    nomes = {item["full_name"] for item in corpo["items"]}
    assert nomes == {"Carla Dias", "Beto Souza"}


def test_program_id_invalido_devolve_400(client_secretaria, secretaria, program):
    _pessoa(program, user=secretaria)

    resposta = client_secretaria.get(URL, {"program_id": "abc"})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "program_required"


def test_superusuario_sem_pessoa_usa_program_id_explicito(client, db, program):
    sysadmin = User.objects.create_superuser(
        username="root", password="senha-de-teste-123"
    )
    client.force_login(sysadmin)
    _pessoa(program, nome="Ana Lima", email="ana@exemplo.br")

    corpo = client.get(URL, {"program_id": program.id}).json()

    assert [item["full_name"] for item in corpo["items"]] == ["Ana Lima"]


def test_superusuario_sem_pessoa_e_sem_program_id_devolve_403(client, db):
    sysadmin = User.objects.create_superuser(
        username="root", password="senha-de-teste-123"
    )
    client.force_login(sysadmin)

    resposta = client.get(URL)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "no_program"


def test_programa_inexistente_devolve_403(client, db):
    sysadmin = User.objects.create_superuser(
        username="root", password="senha-de-teste-123"
    )
    client.force_login(sysadmin)

    resposta = client.get(URL, {"program_id": 9999})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "no_program"
