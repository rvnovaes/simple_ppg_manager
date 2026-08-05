"""Borda HTTP do app academic.

Padrão de toda rota: require_perm na primeira linha, current_program logo
depois, chamada ao model/service, schema de saída explícito. Zero regra de
negócio aqui.
"""

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from ninja import Router, Status
from ninja.decorators import decorate_view
from ninja.pagination import paginate

from apps.core import audit
from apps.core.exceptions import NotAllowed
from apps.core.permissions import require_perm
from apps.core.ratelimit import enforce_rate_limit
from apps.core.tenancy import current_program
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Discipline,
    Program,
    ResearchLine,
)

from .models import AdjustmentStatus, EnrollmentAdjustmentRequest, Student, Teacher
from .schemas import (
    EnrollmentAdjustmentApproveIn,
    EnrollmentAdjustmentRejectIn,
    EnrollmentAdjustmentRequestIn,
    EnrollmentAdjustmentRequestOut,
    IsolatedSignupIn,
    IsolatedSignupOut,
    StudentIn,
    StudentOut,
    StudentPatch,
    TeacherIn,
    TeacherOut,
    TeacherPatch,
)
from .services import (
    JANELA_DE_SIGNUP_EM_SEGUNDOS,
    LIMITE_DE_SIGNUP_POR_IP,
    conferir_programa,
    create_enrollment_adjustment,
    create_student,
    create_teacher,
    programa_com_inscricao_aberta,
    signup_isolated_candidate,
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


@router.get("/students/me", response=list[StudentOut])
def list_my_students(request: HttpRequest):
    """Os vínculos de aluno da própria sessão — nunca os dos outros.

    Existe para a tela do acerto: ela precisa saber, antes de o formulário
    ser preenchido, se o aluno tem orientador e qual vínculo é regular. Sem
    isso o único jeito de descobrir seria levar o 409 `advisor_required`
    depois de tudo digitado.

    A permissão é a de abrir acerto, e não `academic.view_student`: essa
    daria de quebra a listagem inteira do programa, que o discente não pode
    ler. Lista curta (uma pessoa tem um ou dois vínculos), sem paginação.
    """
    require_perm(request, "academic.add_enrollmentadjustmentrequest")
    program: Program = current_program(request)
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    return (
        Student.objects.for_program(program)
        .filter(person__in=pessoas)
        .select_related("person", "person__user")
    )


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


@router.get("/enrollment-requests/", response=list[EnrollmentAdjustmentRequestOut])
@paginate
def list_enrollment_requests(
    request: HttpRequest,
    status: AdjustmentStatus | None = None,
    term_id: int | None = None,
):
    require_perm(request, "academic.view_enrollmentadjustmentrequest")
    program: Program = current_program(request)
    solicitacoes = (
        # Duas camadas, nesta ordem: o tenant primeiro (não é opcional) e o
        # papel depois. `visible_to` é quem recorta aluno/orientador de
        # secretaria/coordenação — ver o método no model.
        EnrollmentAdjustmentRequest.objects.for_program(program)
        .visible_to(request.user, program)
        # Sem o prefetch são duas consultas por solicitação: uma pelos
        # itens, outra pela disciplina de cada item.
        .select_related("student__person", "student__advisor__person")
        .prefetch_related("items__discipline")
    )
    # Filtros de conveniência da tela. Nenhum deles é escopo — esse já foi
    # aplicado acima e não é opcional.
    filtros = {"status": status, "term_id": term_id}
    return solicitacoes.filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )


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


def _solicitacao_para_decidir(
    request: HttpRequest, program: Program, request_id: int
) -> EnrollmentAdjustmentRequest:
    """A solicitação que esta sessão pode decidir — só a do próprio orientando.

    `academic.change_enrollmentadjustmentrequest` é permissão de papel: ela
    diz que docente decide acerto, não QUAL acerto. Sem esta checagem,
    qualquer docente do programa decidiria o orientando de outro.

    O escopo entra na busca (404, nunca 403, para solicitação de outro
    programa). Aluno sem orientador nunca casa com o filtro — o `advisor_id`
    nulo não encontra Teacher nenhum —, então cai no mesmo 403.
    """
    solicitacao = get_object_or_404(
        EnrollmentAdjustmentRequest.objects.for_program(program)
        .select_related("student")
        .prefetch_related("items__discipline"),
        pk=request_id,
    )
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    sou_o_orientador = (
        Teacher.objects.for_program(program)
        .filter(pk=solicitacao.student.advisor_id, person__in=pessoas)
        .exists()
    )
    if not sou_o_orientador:
        raise NotAllowed("Só o orientador do aluno decide este acerto de matrícula.")
    return solicitacao


@router.post(
    "/enrollment-requests/{int:request_id}/approve",
    response=EnrollmentAdjustmentRequestOut,
)
def approve_enrollment_request(
    request: HttpRequest, request_id: int, payload: EnrollmentAdjustmentApproveIn
):
    require_perm(request, "academic.change_enrollmentadjustmentrequest")
    program: Program = current_program(request)
    solicitacao = _solicitacao_para_decidir(request, program, request_id)
    with transaction.atomic():
        # A regra mora no model: decidir de novo levanta
        # InvalidStateTransition (409) e o handler central converte, sem
        # try/except aqui (Seção 8).
        solicitacao.approve(note=payload.note)
        solicitacao.save(update_fields=["status", "decision_note", "decided_at"])
        audit.record(
            "academic.enrollment_adjustment.approve",
            request=request,
            target=solicitacao,
            student_id=solicitacao.student_id,
            note=solicitacao.decision_note,
        )
    return solicitacao


@router.post(
    "/enrollment-requests/{int:request_id}/reject",
    response=EnrollmentAdjustmentRequestOut,
)
def reject_enrollment_request(
    request: HttpRequest, request_id: int, payload: EnrollmentAdjustmentRejectIn
):
    require_perm(request, "academic.change_enrollmentadjustmentrequest")
    program: Program = current_program(request)
    solicitacao = _solicitacao_para_decidir(request, program, request_id)
    with transaction.atomic():
        solicitacao.reject(note=payload.note)
        solicitacao.save(update_fields=["status", "decision_note", "decided_at"])
        audit.record(
            "academic.enrollment_adjustment.reject",
            request=request,
            target=solicitacao,
            student_id=solicitacao.student_id,
            note=solicitacao.decision_note,
        )
    return solicitacao


@router.post("/isolated/signup", auth=None, response={200: IsolatedSignupOut})
@decorate_view(csrf_protect)
def isolated_signup(request: HttpRequest, payload: IsolatedSignupIn):
    # público: é o único endpoint de escrita sem sessão do projeto, e tem
    # de ser — quem se inscreve em disciplina isolada não tem vínculo com a
    # UFMG e portanto não tem conta para autenticar. Sem ele, a secretaria
    # cadastraria à mão cada candidato do edital, que é exatamente o
    # trabalho que este módulo existe para tirar dela.
    #
    # As três travas que substituem a sessão: só funciona enquanto há
    # edital aberto (programa_com_inscricao_aberta), limite de tentativas
    # por IP e csrf_protect explícito — auth=None desliga junto a checagem
    # de CSRF que o SessionAuth faria, mesma armadilha do login.
    enforce_rate_limit(
        request,
        scope="isolated-signup",
        limit=LIMITE_DE_SIGNUP_POR_IP,
        window_seconds=JANELA_DE_SIGNUP_EM_SEGUNDOS,
    )
    program = programa_com_inscricao_aberta(
        at=timezone.now(), program_id=payload.program_id
    )
    signup_isolated_candidate(
        program=program,
        full_name=payload.full_name,
        email=str(payload.email),
        password=payload.password,
        phone_number=payload.phone_number,
        request=request,
    )
    # Corpo idêntico nos dois desfechos: dizer "e-mail já cadastrado" aqui
    # transformaria a rota num verificador de contas para qualquer um.
    return {
        "detail": (
            "Cadastro recebido. Use seu e-mail e sua senha para entrar e "
            "concluir a inscrição."
        )
    }
