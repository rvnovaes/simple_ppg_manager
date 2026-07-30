"""Checagem de permissão — helper único do projeto.

Regra de review (Seção 5 do CLAUDE.md): toda rota chama require_perm na
primeira linha. Rota sem checagem só passa marcada com `# público` e
justificativa.
"""

from django.http import HttpRequest

from .exceptions import NotAllowed, NotAuthenticated


def require_perm(request: HttpRequest, perm: str) -> None:
    """Garante que o usuário da sessão tem `perm` ("app_label.codename").

    Levanta NotAuthenticated (401) se não há sessão, NotAllowed (403) se há
    sessão mas falta a permissão. O handler central traduz para HTTP.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise NotAuthenticated("Autenticação necessária.")
    if not user.has_perm(perm):
        raise NotAllowed(f"Permissão necessária: {perm}.")
