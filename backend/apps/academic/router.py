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
from apps.core.exceptions import NotAllowed
from apps.core.permissions import require_perm
from apps.core.tenancy import current_program
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Discipline,
    Program,
    ResearchLine,
)

from .models import Student, Teacher
from .schemas import (
    EnrollmentAdjustmentRequestIn,
    EnrollmentAdjustmentRequestOut,
    StudentIn,
    StudentOut,
    StudentPatch,
    TeacherIn,
    TeacherOut,
    TeacherPatch,
)
from .services import (
    conferir_programa,
    create_enrollment_adjustment,
    create_student,
    create_teacher,
)

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
        # person__user por causa de needs_initial_password: sem isto a
        # listagem faz uma consulta por professor.
        "person",
        "person__user",
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
        Teacher.objects.for_program(program).select_related("person", "person__user"),
        pk=teacher_id,
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


def _projeto(program: Program, project_id: int | None) -> CollectiveProject | None:
    if project_id is None:
        return None
    return get_object_or_404(
        CollectiveProject.objects.for_program(program), pk=project_id
    )


def _orientador(program: Program, advisor_id: int | None) -> Teacher | None:
    if advisor_id is None:
        return None
    return get_object_or_404(Teacher.objects.for_program(program), pk=advisor_id)


def _periodo(term_id: int | None) -> AcademicTerm | None:
    """Período letivo é institucional (ADR-007 dec. 4): não tem programa
    para escopar, então a busca é global.
    """
    if term_id is None:
        return None
    return get_object_or_404(AcademicTerm, pk=term_id)


@router.get("/students/", response=list[StudentOut])
@paginate
def list_students(
    request: HttpRequest,
    modality: Student.Modality | None = None,
    status: Student.Status | None = None,
    level: Student.Level | None = None,
    term_id: int | None = None,
    advisor_id: int | None = None,
):
    require_perm(request, "academic.view_student")
    alunos = Student.objects.for_program(current_program(request)).select_related(
        "person",
        "person__user",
    )
    # Filtros de conveniência da tela. Nenhum deles é escopo de tenant —
    # esse já foi aplicado acima e não é opcional.
    filtros = {
        "modality": modality,
        "status": status,
        "level": level,
        "term_id": term_id,
        "advisor_id": advisor_id,
    }
    return alunos.filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )


@router.post("/students/", response={201: StudentOut})
def create_student_endpoint(request: HttpRequest, payload: StudentIn):
    require_perm(request, "academic.add_student")
    program: Program = current_program(request)
    dados = payload.model_dump()
    person_id = dados.pop("person_id")
    full_name = dados.pop("full_name")
    primary_email = dados.pop("primary_email")
    phone_number = dados.pop("phone_number")

    person = None
    dados_da_pessoa = None
    if person_id is not None:
        # O escopo entra na busca: pessoa de outro programa simplesmente
        # não existe para esta requisição (404, nunca 403).
        person = get_object_or_404(Person.objects.for_program(program), pk=person_id)
    else:
        dados_da_pessoa = {
            "full_name": full_name,
            "email": primary_email,
            "phone_number": phone_number,
        }

    # As FKs viram objeto aqui: id inexistente vira 404, e não
    # IntegrityError 500 lá na frente.
    dados["project"] = _projeto(program, dados.pop("project_id"))
    dados["advisor"] = _orientador(program, dados.pop("advisor_id"))
    dados["term"] = _periodo(dados.pop("term_id"))

    student = create_student(
        program=program,
        person=person,
        dados_da_pessoa=dados_da_pessoa,
        campos=dados,
        request=request,
    )
    return Status(201, student)


@router.patch("/students/{int:student_id}/", response=StudentOut)
def update_student(request: HttpRequest, student_id: int, payload: StudentPatch):
    require_perm(request, "academic.change_student")
    program = current_program(request)
    student = get_object_or_404(
        Student.objects.for_program(program).select_related("person"), pk=student_id
    )
    campos = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "project_id" in campos:
        campos["project"] = _projeto(program, campos.pop("project_id"))
    if "advisor_id" in campos:
        campos["advisor"] = _orientador(program, campos.pop("advisor_id"))
    if "term_id" in campos:
        campos["term"] = _periodo(campos.pop("term_id"))

    # A situação anterior entra na auditoria: "quem trancou este aluno e
    # em que situação ele estava" é a pergunta que a secretaria faz.
    status_anterior = student.status
    for campo, valor in campos.items():
        setattr(student, campo, valor)
    with transaction.atomic():
        student.clean()
        student.save()
        extra = {}
        if "status" in campos and campos["status"] != status_anterior:
            extra = {"status_anterior": status_anterior, "status_novo": student.status}
        audit.record(
            "academic.student.update",
            request=request,
            target=student,
            fields=sorted(campos),
            **extra,
        )
    return student


def _aluno_da_sessao(
    request: HttpRequest, program: Program, student_id: int | None
) -> Student:
    """O vínculo de aluno de quem está pedindo — nunca o do payload.

    Aceitar `student_id` do corpo sem conferir seria deixar qualquer
    discente abrir pedido em nome de outro. O `student_id` só serve para a
    tela ser explícita: se não for um vínculo desta sessão, é 403.

    Quando ele não vem, o vínculo regular ganha do não regular. O `first()`
    solto no fim é de propósito: quem só tem isolada recebe o 409
    `regular_students_only`, que explica o problema, em vez de um 403 que
    diria "você não é aluno".
    """
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    meus = Student.objects.for_program(program).filter(person__in=pessoas)
    if student_id is not None:
        aluno = meus.filter(pk=student_id).first()
        if aluno is None:
            raise NotAllowed("O acerto de matrícula é sempre em nome do próprio aluno.")
        return aluno
    aluno = meus.regular().first() or meus.first()
    if aluno is None:
        raise NotAllowed("Sua conta não tem vínculo de aluno neste programa.")
    return aluno


@router.post("/enrollment-requests/", response={201: EnrollmentAdjustmentRequestOut})
def create_enrollment_request(
    request: HttpRequest, payload: EnrollmentAdjustmentRequestIn
):
    require_perm(request, "academic.add_enrollmentadjustmentrequest")
    program: Program = current_program(request)
    student = _aluno_da_sessao(request, program, payload.student_id)
    # Período letivo é institucional (ADR-007 dec. 4): busca global.
    term = get_object_or_404(AcademicTerm, pk=payload.term_id)
    # O escopo entra na busca: disciplina de outro programa não existe para
    # esta requisição (404, nunca 403).
    itens = [
        (
            get_object_or_404(
                Discipline.objects.for_program(program), pk=item.discipline_id
            ),
            item.action,
        )
        for item in payload.items
    ]
    solicitacao = create_enrollment_adjustment(
        program=program,
        student=student,
        term=term,
        justification=payload.justification,
        itens=itens,
        request=request,
    )
    return Status(201, solicitacao)
