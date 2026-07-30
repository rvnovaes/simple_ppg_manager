"""Borda HTTP do app programs.

Só leitura: criar programa é ato raro e administrativo, feito no Admin.
"""

from django.http import HttpRequest
from ninja import Router

from apps.core.permissions import require_perm

from .models import Program
from .schemas import ProgramOut

router = Router(tags=["programs"])


@router.get("/", response=list[ProgramOut])
def list_programs(request: HttpRequest):
    require_perm(request, "programs.view_program")
    return Program.objects.active()
