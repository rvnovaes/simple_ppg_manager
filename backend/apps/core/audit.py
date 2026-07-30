"""Registro de auditoria — ponto de entrada único.

Seção 3 do CLAUDE.md: toda escrita relevante grava um AuditLog, dentro do
mesmo transaction.atomic() da escrita. Ninguém cria AuditLog direto; todos
chamam record().
"""

from typing import Any

from django.db import models
from django.http import HttpRequest

from apps.audit.models import AuditLog
from apps.programs.models import Program


def record(
    event: str,
    *,
    request: HttpRequest | None = None,
    target: models.Model | None = None,
    program: Program | None = None,
    **payload: Any,
) -> AuditLog:
    """Grava uma entrada de auditoria: quem, quando, o quê, alvo.

    `event` é hierárquico e estável ("people.create", "auth.login").
    `program` é inferido do alvo quando o alvo tem essa chave; passe
    explícito quando não tiver (ex.: login, que não tem alvo de negócio).
    """
    actor = None
    if request is not None:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            actor = user

    if program is None and target is not None:
        program = getattr(target, "program", None)

    target_type = ""
    target_id = ""
    if target is not None:
        target_type = f"{target._meta.app_label}.{target._meta.model_name}"
        target_id = str(target.pk)

    return AuditLog.objects.create(
        program=program,
        actor=actor,
        event=event,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
    )
