"""Admin restrito a sysadmin e escrita auditada (ADR-006).

Estes testes existem para que a regra do ADR-006 seja verificável, e não
apenas combinada. Se alguém reabrir o Admin para is_staff, aqui quebra.
"""

import pytest
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"


@pytest.fixture
def sysadmin() -> User:
    return User.objects.create_superuser(username="sysadmin", password=SENHA)


def test_usuario_de_negocio_nao_entra_no_admin(client, secretaria):
    """Papel de domínio não abre o Admin, mesmo pertencendo a um Group."""
    client.force_login(secretaria)

    resposta = client.get("/admin/", follow=True)

    assert resposta.status_code == 200
    # Cai na tela de login do Admin em vez de ver o painel.
    assert resposta.redirect_chain, "deveria ter sido redirecionado para o login"
    assert "/admin/login/" in resposta.redirect_chain[-1][0]


def test_is_staff_sozinho_nao_basta(client):
    """A brecha que o Django deixa aberta por padrão fica fechada aqui."""
    staff = User.objects.create_user(username="operador", password=SENHA, is_staff=True)
    client.force_login(staff)

    resposta = client.get("/admin/", follow=True)

    assert resposta.redirect_chain
    assert "/admin/login/" in resposta.redirect_chain[-1][0]


def test_superusuario_entra(client, sysadmin):
    client.force_login(sysadmin)

    assert client.get("/admin/").status_code == 200


def test_escrita_no_admin_gera_auditoria(client, sysadmin, program):
    client.force_login(sysadmin)

    resposta = client.post(
        "/admin/people/person/add/",
        {
            "program": program.id,
            "full_name": "Ana Lima",
            "primary_email": "ana@exemplo.br",
            "phone_number": "",
            "status": Person.Status.ACTIVE,
        },
    )

    assert resposta.status_code == 302, resposta.content
    pessoa = Person.objects.get(full_name="Ana Lima")

    log = AuditLog.objects.get(event="people.person.admin_create")
    assert log.actor == sysadmin
    assert log.target_id == str(pessoa.id)
    assert log.payload["via"] == "django-admin"


def test_mudanca_de_permissao_de_papel_e_auditada(client, sysadmin):
    """'Mudar permissão' é evento auditável pela Seção 3 do CLAUDE.md."""
    client.force_login(sysadmin)
    grupo = Group.objects.get(name="Coordenação")

    resposta = client.post(
        f"/admin/auth/group/{grupo.id}/change/",
        {"name": "Coordenação", "permissions": []},
    )

    assert resposta.status_code == 302, resposta.content
    log = AuditLog.objects.get(event="auth.group.admin_update")
    assert log.actor == sysadmin
    assert "permissions" in log.payload["campos_alterados"]
