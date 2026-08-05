"""Borda HTTP do app programs.

Programa em si é só leitura: criar programa é ato raro e administrativo,
feito no Admin. A estrutura interna do programa (linha de pesquisa,
projeto coletivo) é escrita por aqui, pela secretaria.

Padrão de toda rota: require_perm na primeira linha, current_program logo
depois, chamada ao model, schema de saída explícito. Zero regra de
negócio aqui.
"""

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Status
from ninja.pagination import paginate

from apps.core import audit
from apps.core.permissions import require_perm
from apps.core.tenancy import current_program

from .models import Program, ResearchLine
from .schemas import ProgramOut, ResearchLineIn, ResearchLineOut, ResearchLinePatch

router = Router(tags=["programs"])


@router.get("/", response=list[ProgramOut])
def list_programs(request: HttpRequest):
    require_perm(request, "programs.view_program")
    return Program.objects.active()


@router.get("/research-lines/", response=list[ResearchLineOut])
@paginate
def list_research_lines(request: HttpRequest):
    require_perm(request, "programs.view_researchline")
    return ResearchLine.objects.for_program(current_program(request))


@router.post("/research-lines/", response={201: ResearchLineOut})
def create_research_line(request: HttpRequest, payload: ResearchLineIn):
    require_perm(request, "programs.add_researchline")
    program = current_program(request)
    research_line = ResearchLine(program=program, **payload.model_dump())
    with transaction.atomic():
        # A regra mora no model; aqui só persistimos e auditamos.
        research_line.clean()
        research_line.save()
        audit.record(
            "programs.research_line.create",
            request=request,
            target=research_line,
            name=research_line.name,
        )
    return Status(201, research_line)


@router.patch("/research-lines/{int:research_line_id}/", response=ResearchLineOut)
def update_research_line(
    request: HttpRequest, research_line_id: int, payload: ResearchLinePatch
):
    require_perm(request, "programs.change_researchline")
    program = current_program(request)
    # O escopo entra na busca, não num if depois: linha de outro programa
    # simplesmente não existe para esta requisição.
    research_line = get_object_or_404(
        ResearchLine.objects.for_program(program), pk=research_line_id
    )
    campos = payload.model_dump(exclude_unset=True, exclude_none=True)
    for campo, valor in campos.items():
        setattr(research_line, campo, valor)
    with transaction.atomic():
        research_line.clean()
        # update_fields=[] faria o Django pular o save; sem campo nenhum no
        # corpo, gravamos tudo (que é o mesmo estado já carregado).
        research_line.save(update_fields=list(campos) or None)
        audit.record(
            "programs.research_line.update",
            request=request,
            target=research_line,
            fields=sorted(campos),
        )
    return research_line
