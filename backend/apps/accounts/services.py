"""Operações de conta que cruzam mais de um model.

Mora em accounts, e não em academic, porque papel de acesso é assunto de
conta: academic já depende de accounts, e a dependência nunca se inverte.
"""

from django.contrib.auth.models import Group
from django.db import transaction
from django.http import HttpRequest

from apps.core import audit

from .models import User


@transaction.atomic
def assign_role_group(
    user: User,
    *,
    group_name: str,
    request: HttpRequest | None = None,
) -> bool:
    """Põe o usuário no papel indicado. Idempotente.

    Devolve True quando o vínculo foi criado agora, False quando já existia
    — chamar duas vezes não duplica, não falha e não gera auditoria à toa.

    Quem chama decide o papel: Teacher vai para Docente; Student REGULAR vai
    para Discente; aluno ISOLATED/ELECTIVE não entra em grupo nesta versão.
    """
    group = Group.objects.get(name=group_name)
    if user.groups.filter(pk=group.pk).exists():
        return False

    user.groups.add(group)
    audit.record(
        "accounts.user.assign_role_group",
        request=request,
        target=user,
        username=user.username,
        group=group_name,
    )
    return True


@transaction.atomic
def revoke_role_group(
    user: User,
    *,
    group_name: str,
    request: HttpRequest | None = None,
) -> bool:
    """Tira o usuário do papel indicado. Idempotente, como `assign_role_group`.

    Devolve True quando o vínculo existia e foi removido agora, False quando
    já não existia — perder um papel é evento auditável, mas não perdê-lo
    duas vezes.

    Existe para as trocas de papel, em que ficar nos dois é errado: o
    candidato que vira aluno sai de Candidato e entra em Discente
    (`academic.services.enroll_isolated_request`).
    """
    group = Group.objects.get(name=group_name)
    if not user.groups.filter(pk=group.pk).exists():
        return False

    user.groups.remove(group)
    audit.record(
        "accounts.user.revoke_role_group",
        request=request,
        target=user,
        username=user.username,
        group=group_name,
    )
    return True
