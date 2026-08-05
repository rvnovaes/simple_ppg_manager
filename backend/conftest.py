"""Fixtures compartilhadas pelos testes.

Os Groups vêm da data migration (programs.0002), então usá-los aqui também
verifica que a migration continua criando os papéis certos.
"""

import pytest
from django.contrib.auth.models import Group
from django.test import Client

# Import direto do model (e não get_user_model) para o mypy conseguir tipar
# as fixtures. Em código de aplicação, prefira get_user_model.
from apps.accounts.models import User
from apps.programs.models import Program

SENHA = "senha-de-teste-123"


@pytest.fixture
def program(db) -> Program:
    return Program.objects.get(acronym="PPGD")


@pytest.fixture
def secretaria(db) -> User:
    """Usuário com o papel Secretaria: pode ver, criar e alterar pessoas."""
    user = User.objects.create_user(username="secretaria", password=SENHA)
    user.groups.add(Group.objects.get(name="Secretaria"))
    return user


@pytest.fixture
def sem_permissao(db) -> User:
    """Usuário autenticado, mas sem nenhum papel."""
    return User.objects.create_user(username="visitante", password=SENHA)


@pytest.fixture
def client_secretaria(client: Client, secretaria: User) -> Client:
    client.force_login(secretaria)
    return client


@pytest.fixture
def client_sem_permissao(client: Client, sem_permissao: User) -> Client:
    client.force_login(sem_permissao)
    return client


@pytest.fixture(autouse=True)
def media_temporaria(settings, tmp_path) -> None:
    """Todo upload de teste cai num diretório descartável.

    Sem isto, um `FileField` exercitado em teste grava de verdade em
    `backend/media/` e o lixo fica no checkout — é autouse porque quem
    escreve o teste não tem como lembrar de uma pegadinha que só aparece
    no `git status` de outra pessoa.
    """
    settings.MEDIA_ROOT = tmp_path / "media"
