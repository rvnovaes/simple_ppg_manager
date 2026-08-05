from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import AcademicTerm, CollectiveProject, Program, ResearchLine


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


@admin.register(CollectiveProject)
class CollectiveProjectAdmin(AuditedModelAdmin):
    """Quebra-vidro: a rotina da secretaria é a tela Svelte (ADR-006)."""

    list_display = ("name", "research_line", "program", "is_active")
    list_filter = ("program", "research_line", "is_active")
    search_fields = ("name",)


@admin.register(AcademicTerm)
class AcademicTermAdmin(AuditedModelAdmin):
    """Institucional: sem filtro por programa, o calendário é único (ADR-007 dec. 4)."""

    list_display = ("__str__", "starts_on", "ends_on", "is_active")
    list_filter = ("is_active", "year")
