from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import IsolatedEnrollmentCycle, Student, Teacher


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


@admin.register(Student)
class StudentAdmin(AuditedModelAdmin):
    """Quebra-vidro: a rotina da secretaria é a tela Svelte (ADR-006)."""

    list_display = (
        "person",
        "registration_number",
        "modality",
        "status",
        "level",
        "term",
        "program",
    )
    list_filter = ("program", "modality", "status", "level", "term")
    search_fields = (
        "person__full_name",
        "person__primary_email",
        "registration_number",
    )
    list_select_related = ("person", "program", "term")
    raw_id_fields = ("person", "project", "advisor", "term")
    readonly_fields = ("created_at", "updated_at")


@admin.register(IsolatedEnrollmentCycle)
class IsolatedEnrollmentCycleAdmin(AuditedModelAdmin):
    """Quebra-vidro: a rotina da secretaria é a tela Svelte (ADR-006)."""

    list_display = (
        "term",
        "submission_opens_at",
        "submission_closes_at",
        "result_published_on",
        "payment_closes_at",
        "is_active",
        "program",
    )
    list_filter = ("program", "is_active", "term")
    list_select_related = ("program", "term")
    raw_id_fields = ("term",)
