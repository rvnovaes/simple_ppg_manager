from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import Program, ResearchLine


@admin.register(Program)
class ProgramAdmin(AuditedModelAdmin):
    """Criar tenant é operação de plataforma — é para isto que o Admin existe."""

    list_display = ("acronym", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("acronym", "name")


@admin.register(ResearchLine)
class ResearchLineAdmin(AuditedModelAdmin):
    """Quebra-vidro: a rotina da secretaria é a tela Svelte (ADR-006)."""

    list_display = ("name", "program", "is_active")
    list_filter = ("program", "is_active")
    search_fields = ("name",)
