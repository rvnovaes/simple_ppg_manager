"""Liberação de acesso: senha do primeiro acesso e papel de domínio."""

import json

import pytest
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.services import assign_role_group, revoke_role_group
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError, InvalidStateTransition

pytestmark = pytest.mark.django_db

NOVA_SENHA = "primeiro-acesso-2026"


def _url(user: User) -> str:
    return f"/api/v1/accounts/users/{user.pk}/set-initial-password"


def _post(client, user: User, senha: str = NOVA_SENHA):
    return client.post(
        _url(user),
        data=json.dumps({"password": senha}),
        content_type="application/json",
    )


@pytest.fixture
def conta_nova(db) -> User:
    """Conta como create_person_with_user a cria: sem senha utilizável."""
    user = User.objects.create(username="docente@ufmg.br", email="docente@ufmg.br")
    user.set_unusable_password()
    user.save(update_fields=["password"])
    return user


def test_define_senha_em_conta_nova(client_secretaria, conta_nova):
    resposta = _post(client_secretaria, conta_nova)

    assert resposta.status_code == 200, resposta.content
    conta_nova.refresh_from_db()
    assert conta_nova.check_password(NOVA_SENHA)


def test_registra_auditoria_sem_a_senha(client_secretaria, conta_nova):
    _post(client_secretaria, conta_nova)

    log = AuditLog.objects.get(event="accounts.user.set_initial_password")
    assert log.target_id == str(conta_nova.pk)
    assert NOVA_SENHA not in json.dumps(log.payload)


def test_repetir_na_mesma_conta_devolve_409(client_secretaria, conta_nova):
    assert _post(client_secretaria, conta_nova).status_code == 200

    resposta = _post(client_secretaria, conta_nova, "outra-senha-2026")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "invalid_state_transition"
    conta_nova.refresh_from_db()
    # A senha anterior continua valendo: ninguém assume conta ativa.
    assert conta_nova.check_password(NOVA_SENHA)


def test_sem_permissao_devolve_403(client_sem_permissao, conta_nova):
    resposta = _post(client_sem_permissao, conta_nova)

    assert resposta.status_code == 403
    conta_nova.refresh_from_db()
    assert not conta_nova.has_usable_password()


def test_sem_sessao_devolve_401(client, conta_nova):
    assert _post(client, conta_nova).status_code == 401


def test_senha_fraca_e_recusada(client_secretaria, conta_nova):
    resposta = _post(client_secretaria, conta_nova, "123")

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "senha_invalida"


def test_invariante_sem_banco():
    """A regra é do model: instanciar em memória basta para verificá-la."""
    user = User(username="alguem")
    user.set_unusable_password()
    user.set_initial_password(NOVA_SENHA)

    assert user.has_usable_password()
    with pytest.raises(InvalidStateTransition):
        user.set_initial_password("outra-senha-2026")


def test_senha_fraca_levanta_domain_error():
    user = User(username="alguem")
    user.set_unusable_password()

    with pytest.raises(DomainError) as erro:
        user.set_initial_password("12345678")

    assert erro.value.code == "senha_invalida"


def test_assign_role_group_e_idempotente(conta_nova):
    assert assign_role_group(conta_nova, group_name="Docente") is True
    assert assign_role_group(conta_nova, group_name="Docente") is False

    assert list(conta_nova.groups.values_list("name", flat=True)) == ["Docente"]
    assert AuditLog.objects.filter(event="accounts.user.assign_role_group").count() == 1


def test_assign_role_group_nao_remove_papel_existente(conta_nova):
    conta_nova.groups.add(Group.objects.get(name="Discente"))

    assign_role_group(conta_nova, group_name="Docente")

    assert set(conta_nova.groups.values_list("name", flat=True)) == {
        "Docente",
        "Discente",
    }


def test_revoke_role_group_e_idempotente(conta_nova):
    assign_role_group(conta_nova, group_name="Docente")

    assert revoke_role_group(conta_nova, group_name="Docente") is True
    assert revoke_role_group(conta_nova, group_name="Docente") is False

    assert list(conta_nova.groups.values_list("name", flat=True)) == []
    assert AuditLog.objects.filter(event="accounts.user.revoke_role_group").count() == 1


def test_revoke_role_group_mexe_so_no_papel_pedido(conta_nova):
    conta_nova.groups.set(Group.objects.filter(name__in=("Docente", "Discente")))

    revoke_role_group(conta_nova, group_name="Docente")

    assert list(conta_nova.groups.values_list("name", flat=True)) == ["Discente"]
