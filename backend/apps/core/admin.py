"""Base de ModelAdmin que registra auditoria.

Escrita feita no Admin é quebra-vidro: quem está ali é sysadmin, tem poder
total e **desvia das regras do model** (editar `status` num `<select>` não
chama `Person.archive()`). Justamente por isso é onde o rastro mais
importa — Seção 5 do CLAUDE.md e ADR-006.

Todo ModelAdmin de dado de negócio herda de AuditedModelAdmin.
"""

from typing import Any

from django.contrib import admin
from django.db import models, transaction
from django.http import HttpRequest

from . import audit


class AuditedModelAdmin(admin.ModelAdmin):
    """ModelAdmin que grava AuditLog em toda criação, alteração e exclusão.

    O evento nasce do próprio model: `people.person.admin_create`,
    `people.person.admin_update`, `people.person.admin_delete`. O sufixo
    `admin_` deixa explícito, na consulta da auditoria, que aquilo não
    passou pelo domínio.
    """

    def _evento(self, obj: models.Model, acao: str) -> str:
        meta = obj._meta
        return f"{meta.app_label}.{meta.model_name}.admin_{acao}"

    def save_model(
        self, request: HttpRequest, obj: models.Model, form: Any, change: bool
    ) -> None:
        acao = "update" if change else "create"
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            audit.record(
                self._evento(obj, acao),
                request=request,
                target=obj,
                # Só os campos que o formulário realmente mudou; o valor
                # anterior não é guardado para não duplicar dado sensível.
                campos_alterados=sorted(form.changed_data) if change else [],
                via="django-admin",
            )

    def delete_model(self, request: HttpRequest, obj: models.Model) -> None:
        with transaction.atomic():
            # A auditoria vem antes: depois do delete não há mais pk.
            audit.record(
                self._evento(obj, "delete"),
                request=request,
                target=obj,
                representacao=str(obj),
                via="django-admin",
            )
            super().delete_model(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: models.QuerySet) -> None:
        """Exclusão em lote pela action padrão do Admin.

        Sem este override a action apagaria tudo sem passar por
        delete_model, e o lote sairia sem rastro nenhum.
        """
        with transaction.atomic():
            for obj in queryset:
                audit.record(
                    self._evento(obj, "delete"),
                    request=request,
                    target=obj,
                    representacao=str(obj),
                    via="django-admin-lote",
                )
            super().delete_queryset(request, queryset)
