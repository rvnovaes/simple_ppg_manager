from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import Teacher


@admin.register(Teacher)
class TeacherAdmin(AuditedModelAdmin):
    """Quebra-vidro: a rotina da secretaria é a tela Svelte (ADR-006)."""

    list_display = (
        "person",
        "category",
        "academic_degree",
        "accredited_since",
        "accredited_until",
        "program",
    )
    list_filter = ("program", "category", "academic_degree")
    search_fields = ("person__full_name", "person__primary_email")
    list_select_related = ("person", "program")
    # Sem isto o Admin renderiza um <select> com todas as pessoas do banco.
    raw_id_fields = ("person",)
    filter_horizontal = ("research_lines", "projects")
    readonly_fields = ("created_at", "updated_at")
