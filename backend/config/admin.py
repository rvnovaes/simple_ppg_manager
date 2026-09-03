"""Admin da plataforma — restrito a sysadmin (ADR-006).

A restrição mora aqui, e não num combinado de equipe: `has_permission` é o
que o Django consulta antes de deixar qualquer requisição entrar no Admin.
"""

from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.http import HttpRequest


class SysadminAdminSite(AdminSite):
    site_header = "PPGM — operação da plataforma"
    site_title = "PPGM"
    index_title = "Operação da plataforma"

    def has_permission(self, request: HttpRequest) -> bool:
        """Só superusuário entra.

        O padrão do Django aceita qualquer `is_staff`. Aqui não: papel de
        domínio (Secretaria, Coordenação) é Group e nunca abre esta porta.
        Usuário de negócio é servido pelo front — ver ADR-006.
        """
        user = request.user
        return user.is_active and user.is_superuser


class PPGDAdminConfig(AdminConfig):
    """Faz o Django usar o SysadminAdminSite como `admin.site` padrão.

    Registrado em INSTALLED_APPS no lugar de "django.contrib.admin", que é
    a forma documentada de trocar o site padrão sem quebrar o autodiscover
    dos `admin.py` de cada app.
    """

    default_site = "config.admin.SysadminAdminSite"
