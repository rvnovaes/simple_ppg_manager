from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group

from apps.core.admin import AuditedModelAdmin

from .models import User


@admin.register(User)
class AppUserAdmin(AuditedModelAdmin, UserAdmin):
    """Contas do sistema. Papéis são os Groups nativos.

    Auditado porque é aqui que se concede acesso: mudança de grupo,
    permissão, `is_staff` ou `is_superuser` precisa deixar rastro
    (Seção 3 do CLAUDE.md).
    """

    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "groups")


# O Group vem registrado pelo django.contrib.auth com um admin sem
# auditoria. Trocamos pelo nosso: alterar as permissões de um papel é
# exatamente o "mudar permissão" que a Seção 3 manda auditar.
admin.site.unregister(Group)


@admin.register(Group)
class AuditedGroupAdmin(AuditedModelAdmin, GroupAdmin):
    """Papéis do domínio (Secretaria, Coordenação)."""
