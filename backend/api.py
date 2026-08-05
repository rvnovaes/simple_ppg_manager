"""NinjaAPI raiz: versão, autenticação padrão e tradução de erros.

Montada em /api/v1/ por config/urls.py.
"""

from django.http import HttpRequest
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError
from ninja.security import django_auth

from apps.academic.router import router as academic_router
from apps.accounts.router import router as accounts_router
from apps.accounts.router import users_router as accounts_users_router
from apps.core.exceptions import DomainError
from apps.people.router import router as people_router
from apps.programs.router import router as programs_router

api = NinjaAPI(
    title="PPGD Manager API",
    version="1.0.0",
    description="API interna do sistema de gestão do PPGD.",
    # Sessão do Django é o padrão de toda rota (ADR-003). Rotas públicas
    # declaram auth=None explicitamente e justificam com `# público`.
    #
    # O CSRF vem junto: django_auth é um SessionAuth (APIKeyCookie) que já
    # roda a checagem de CSRF em toda escrita. Nas rotas com auth=None a
    # checagem precisa ser pedida à mão — ver @decorate_view(csrf_protect)
    # no login.
    auth=django_auth,
)


@api.exception_handler(DomainError)
def on_domain_error(request: HttpRequest, exc: DomainError):
    """Todo erro de negócio vira 4xx com corpo padronizado.

    É por causa deste handler que os routers não fazem try/except.
    """
    return api.create_response(
        request,
        {"detail": exc.detail, "code": exc.code},
        status=exc.status_code,
    )


@api.exception_handler(AuthenticationError)
def on_authentication_error(request: HttpRequest, exc: AuthenticationError):
    """Sessão ausente ou inválida — mesmo formato de corpo dos demais erros."""
    return api.create_response(
        request,
        {"detail": "Autenticação necessária.", "code": "not_authenticated"},
        status=401,
    )


@api.exception_handler(ValidationError)
def on_validation_error(request: HttpRequest, exc: ValidationError):
    """Payload fora do schema. `errors` traz o detalhe campo a campo."""
    return api.create_response(
        request,
        {
            "detail": "Dados inválidos.",
            "code": "validation_error",
            "errors": exc.errors,
        },
        status=422,
    )


api.add_router("/auth/", accounts_router)
api.add_router("/accounts/", accounts_users_router)
api.add_router("/programs/", programs_router)
api.add_router("/people/", people_router)
api.add_router("/academic/", academic_router)
