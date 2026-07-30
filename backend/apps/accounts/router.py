"""Borda de autenticação. Sessão do Django, sem JWT (ADR-003)."""

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from ninja import Router
from ninja.decorators import decorate_view

from apps.core import audit
from apps.core.exceptions import DomainError

from .schemas import LoginIn, UserOut

router = Router(tags=["auth"])


def _user_out(user) -> dict:
    pessoas = user.people.select_related("program").all()
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.get_full_name(),
        "is_staff": user.is_staff,
        "permissions": sorted(user.get_all_permissions()),
        "people": [
            {
                "id": p.id,
                "program_id": p.program_id,
                "program_acronym": p.program.acronym,
                "full_name": p.full_name,
                "status": p.status,
            }
            for p in pessoas
        ],
    }


class InvalidCredentials(DomainError):
    status_code = 401
    code = "invalid_credentials"


@router.get("/csrf", auth=None, response={200: dict})
def issue_csrf(request: HttpRequest):
    # público: precisa ser alcançável antes do login — é esta chamada que
    # planta o cookie csrftoken que o client usa em toda escrita.
    return {"detail": get_token(request)}


@router.post("/login", auth=None, response={200: UserOut})
@decorate_view(csrf_protect)
def do_login(request: HttpRequest, payload: LoginIn):
    # público: é o endpoint que cria a sessão, então não pode exigir sessão.
    # auth=None desliga junto a checagem de CSRF que o SessionAuth faria, por
    # isso o csrf_protect explícito — sem ele o endpoint fica aberto a login
    # CSRF (atacante autentica a vítima na conta dele).
    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None:
        raise InvalidCredentials("Usuário ou senha inválidos.")

    with transaction.atomic():
        login(request, user)
        audit.record("auth.login", request=request, username=user.username)

    return _user_out(user)


@router.post("/logout", response={200: dict})
def do_logout(request: HttpRequest):
    # Sem require_perm: qualquer usuário autenticado pode encerrar a própria
    # sessão. A autenticação já é exigida pelo auth padrão da API.
    with transaction.atomic():
        audit.record("auth.logout", request=request, username=request.user.username)
        logout(request)
    return {"detail": "Sessão encerrada."}


@router.get("/me", response={200: UserOut})
def me(request: HttpRequest):
    # Sem require_perm: devolve apenas os dados do próprio usuário da sessão.
    return _user_out(request.user)
