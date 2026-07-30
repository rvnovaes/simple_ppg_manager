from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Somente leitura: auditoria editável não é auditoria."""

    list_display = (
        "created_at",
        "event",
        "actor",
        "program",
        "target_type",
        "target_id",
    )
    list_filter = ("event", "program")
    search_fields = ("event", "target_id", "actor__username")
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
