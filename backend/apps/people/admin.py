from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import Person


@admin.register(Person)
class PersonAdmin(AuditedModelAdmin):
    """Correção excepcional de dados por sysadmin (ADR-006).

    NÃO é a tela da secretaria: essa é `/pessoas` no front. Editar aqui
    desvia das regras do model — daí a auditoria obrigatória.
    """

    list_display = (
        "full_name",
        "primary_email",
        "user",
        "phone_number",
        "program",
        "status",
    )
    list_filter = ("program", "status")
    search_fields = ("full_name", "primary_email", "user__username")
    list_select_related = ("program", "user")
    # Sem isto o Admin renderiza um <select> com todos os usuários do banco.
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
