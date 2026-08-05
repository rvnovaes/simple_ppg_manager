"""Borda HTTP do app academic.

Padrão de toda rota: require_perm na primeira linha, current_program logo
depois, chamada ao model/service, schema de saída explícito. Zero regra de
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
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine

from .models import Teacher
from .schemas import TeacherIn, TeacherOut, TeacherPatch
from .services import conferir_programa, create_teacher

router = Router(tags=["academic"])


def _linhas(ids: list[int]) -> list[ResearchLine]:
    """Resolve os ids em objetos: id inexistente vira 404 aqui, em vez de
    IntegrityError 500 lá na frente. Linha de outro programa passa e é
    barrada pelo invariante de tenant, com 400 program_mismatch.
    """
    return [get_object_or_404(ResearchLine, pk=pk) for pk in ids]


def _projetos(ids: list[int]) -> list[CollectiveProject]:
    return [get_object_or_404(CollectiveProject, pk=pk) for pk in ids]


@router.get("/teachers/", response=list[TeacherOut])
@paginate
def list_teachers(request: HttpRequest, category: Teacher.Category | None = None):
    require_perm(request, "academic.view_teacher")
    professores = Teacher.objects.for_program(current_program(request)).select_related(
        "person"
    )
    if category is not None:
        # Filtro de conveniência da tela. Não é escopo de tenant — esse já
        # foi aplicado acima e não é opcional.
        professores = professores.filter(category=category)
    return professores


@router.post("/teachers/", response={201: TeacherOut})
def create_teacher_endpoint(request: HttpRequest, payload: TeacherIn):
    require_perm(request, "academic.add_teacher")
    program: Program = current_program(request)
    dados = payload.model_dump()
    person_id = dados.pop("person_id")
    full_name = dados.pop("full_name")
    primary_email = dados.pop("primary_email")
    phone_number = dados.pop("phone_number")
    research_line_ids = dados.pop("research_line_ids")
    project_ids = dados.pop("project_ids")

    person = None
    dados_da_pessoa = None
    if person_id is not None:
        # O escopo entra na busca: pessoa de outro programa simplesmente
        # não existe para esta requisição (404, nunca 403 — 403 revelaria
        # que o id existe).
        person = get_object_or_404(Person.objects.for_program(program), pk=person_id)
    else:
        dados_da_pessoa = {
            "full_name": full_name,
            "email": primary_email,
            "phone_number": phone_number,
        }

    teacher = create_teacher(
        program=program,
        person=person,
        dados_da_pessoa=dados_da_pessoa,
        campos=dados,
        research_lines=_linhas(research_line_ids),
        projects=_projetos(project_ids),
        request=request,
    )
    return Status(201, teacher)


@router.patch("/teachers/{int:teacher_id}/", response=TeacherOut)
def update_teacher(request: HttpRequest, teacher_id: int, payload: TeacherPatch):
    require_perm(request, "academic.change_teacher")
    program = current_program(request)
    teacher = get_object_or_404(
        Teacher.objects.for_program(program).select_related("person"), pk=teacher_id
    )
    campos = payload.model_dump(exclude_unset=True, exclude_none=True)
    research_line_ids = campos.pop("research_line_ids", None)
    project_ids = campos.pop("project_ids", None)
    for campo, valor in campos.items():
        setattr(teacher, campo, valor)
    with transaction.atomic():
        teacher.clean()
        # update_fields=[] faria o Django pular o save; sem campo escalar
        # no corpo, gravamos tudo (que é o mesmo estado já carregado).
        teacher.save(update_fields=list(campos) or None)
        if research_line_ids is not None:
            linhas = _linhas(research_line_ids)
            conferir_programa(linhas, program, "A linha de pesquisa")
            teacher.research_lines.set(linhas)
        if project_ids is not None:
            projetos = _projetos(project_ids)
            conferir_programa(projetos, program, "O projeto coletivo")
            teacher.projects.set(projetos)
        audit.record(
            "academic.teacher.update",
            request=request,
            target=teacher,
            fields=sorted(
                [
                    *campos,
                    *(["research_line_ids"] if research_line_ids is not None else []),
                    *(["project_ids"] if project_ids is not None else []),
                ]
            ),
        )
    return teacher
