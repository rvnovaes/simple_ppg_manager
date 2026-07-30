from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import Program


@admin.register(Program)
class ProgramAdmin(AuditedModelAdmin):
    """Criar tenant é operação de plataforma — é para isto que o Admin existe."""

    list_display = ("acronym", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("acronym", "name")
