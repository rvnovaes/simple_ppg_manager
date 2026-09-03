"""Borda HTTP do app academic.

Padrão de toda rota: require_perm na primeira linha, current_program logo
depois, chamada ao model/service, schema de saída explícito. Zero regra de
negócio aqui.
"""

from pathlib import Path

from django.db import transaction
from django.http import FileResponse, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from ninja import File, Form, Router, Status, UploadedFile
from ninja.decorators import decorate_view
from ninja.pagination import paginate

from apps.core import audit
from apps.core.exceptions import DomainError, NotAllowed
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

from .models import (
    AccessProfile,
    AdjustmentStatus,
    DisciplineOffering,
    EnrollmentAdjustmentRequest,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
    IsolatedRequestStatus,
    RequestDocument,
    RequestDocumentKind,
    Student,
    Teacher,
)
from .schemas import (
    AccessSignupIn,
    AccessSignupOut,
    DisciplineOfferingIn,
    DisciplineOfferingOut,
    DisciplineOfferingPatch,
    EnrollmentAdjustmentApproveIn,
    EnrollmentAdjustmentRejectIn,
    EnrollmentAdjustmentRequestIn,
    EnrollmentAdjustmentRequestOut,
    IsolatedCancelIn,
    IsolatedCandidateOut,
    IsolatedCycleCloseOut,
    IsolatedCycleIn,
    IsolatedCycleOut,
    IsolatedCyclePatch,
    IsolatedDeferIn,
    IsolatedEnrollIn,
    IsolatedItemIn,
    IsolatedRankIn,
    IsolatedRejectIn,
    IsolatedRequestIn,
    IsolatedRequestOut,
    IsolatedRequestPatch,
    RequestDocumentOut,
    StudentIn,
    StudentOut,
    StudentPatch,
    TeacherDeaccreditIn,
    TeacherIn,
    TeacherOut,
    TeacherPatch,
)
from .services import (
    JANELA_DE_SIGNUP_EM_SEGUNDOS,
    LIMITE_DE_SIGNUP_POR_IP,
    ciclo_com_inscricao_aberta,
    close_isolated_cycle,
    conferir_programa,
    create_enrollment_adjustment,
    create_isolated_request,
    create_student,
    create_teacher,
    enroll_isolated_request,
    programa_que_aceita_autocadastro,
    signup_access_request,
)

router = Router(tags=["academic"])
# Segundo router do arquivo, montado noutro prefixo (/access/), como
# accounts/router.py faz com `router` e `users_router`. O autocadastro não
# é assunto de vida acadêmica: quem chama ainda não tem vínculo nenhum, e
# a única rota pública de escrita do projeto merece prefixo próprio.
access_router = Router(tags=["access"])


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


@router.get("/teachers/{int:teacher_id}/", response=TeacherOut)
def get_teacher(request: HttpRequest, teacher_id: int):
    """Um professor pelo id, para a tela de detalhes.

    O escopo entra na busca: professor de outro programa simplesmente não
    existe para esta requisição (404, nunca 403 — 403 revelaria que o id
    existe).
    """
    require_perm(request, "academic.view_teacher")
    return get_object_or_404(
        Teacher.objects.for_program(current_program(request)).select_related(
            "person", "person__user"
        ),
        pk=teacher_id,
    )


@router.post("/teachers/{int:teacher_id}/deaccredit", response=TeacherOut)
def deaccredit_teacher(
    request: HttpRequest, teacher_id: int, payload: TeacherDeaccreditIn
):
    """Descredencia o professor — o "excluir" da tela.

    Não apaga: o professor descredenciado continua sendo quem orientou os
    alunos dele. A permissão é `change_teacher`, e não `delete_teacher`,
    porque é exatamente o que a operação é — uma alteração de estado.
    """
    require_perm(request, "academic.change_teacher")
    teacher = get_object_or_404(
        Teacher.objects.for_program(current_program(request)).select_related(
            "person", "person__user"
        ),
        pk=teacher_id,
    )
    with transaction.atomic():
        # A regra mora no model; aqui só persistimos e auditamos.
        teacher.deaccredit(on=payload.on or timezone.localdate())
        teacher.save(update_fields=["accredited_until", "updated_at"])
        audit.record(
            "academic.teacher.deaccredit",
            request=request,
            target=teacher,
            accredited_until=str(teacher.accredited_until),
        )
    return teacher


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


@router.get("/students/{int:student_id}/", response=StudentOut)
def get_student(request: HttpRequest, student_id: int):
    """Um aluno pelo id, para a tela de detalhes. Escopo na busca, como
    em `get_teacher`."""
    require_perm(request, "academic.view_student")
    return get_object_or_404(
        Student.objects.for_program(current_program(request)).select_related(
            "person", "person__user", "project", "advisor__person", "term"
        ),
        pk=student_id,
    )


@router.post("/students/{int:student_id}/exclude", response=StudentOut)
def exclude_student(request: HttpRequest, student_id: int):
    """Encerra o vínculo do aluno — o "excluir" da tela.

    Não apaga: o histórico é o que sustenta acerto de matrícula já
    decidido. Permissão `change_student` pelo mesmo motivo do professor —
    é alteração de situação, não remoção.
    """
    require_perm(request, "academic.change_student")
    student = get_object_or_404(
        Student.objects.for_program(current_program(request)).select_related(
            "person", "person__user", "project", "advisor__person", "term"
        ),
        pk=student_id,
    )
    status_anterior = student.status
    with transaction.atomic():
        # A regra mora no model; aqui só persistimos e auditamos.
        student.exclude_from_program()
        student.save(update_fields=["status", "updated_at"])
        audit.record(
            "academic.student.exclude",
            request=request,
            target=student,
            status_anterior=status_anterior,
            status_novo=student.status,
        )
    return student


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


@router.get("/isolated/cycles/", response=list[IsolatedCycleOut])
def list_isolated_cycles(request: HttpRequest):
    """Os editais do programa, do semestre mais recente para o mais antigo.

    Sem paginação e sem filtro: é um edital por semestre, e a tela da
    secretaria precisa da lista inteira para escolher qual analisar.

    Só Secretaria e Coordenação chegam aqui (`academic.0011`). O candidato
    não lê o edital como entidade — o que ele precisa saber do calendário
    viaja dentro do requerimento dele.
    """
    require_perm(request, "academic.view_isolatedenrollmentcycle")
    program: Program = current_program(request)
    return IsolatedEnrollmentCycle.objects.for_program(program).select_related("term")


@router.post("/isolated/cycles/", response={201: IsolatedCycleOut})
def create_isolated_cycle(request: HttpRequest, payload: IsolatedCycleIn):
    """A secretaria abre o edital do semestre.

    O período letivo é institucional (ADR-007 dec. 4), então a busca dele
    não passa por `for_program` — o calendário 2026/1 é o mesmo para todos
    os programas. O tenant do ciclo continua vindo de `current_program`.
    """
    require_perm(request, "academic.add_isolatedenrollmentcycle")
    program: Program = current_program(request)
    campos = payload.model_dump()
    periodo = get_object_or_404(AcademicTerm, pk=campos.pop("term_id"))
    ciclo = IsolatedEnrollmentCycle(program=program, term=periodo, **campos)
    with transaction.atomic():
        ciclo.clean()
        ciclo.save()
        audit.record(
            "academic.isolated_cycle.create",
            request=request,
            target=ciclo,
            term_id=ciclo.term_id,
        )
    return Status(201, ciclo)


@router.patch("/isolated/cycles/{int:cycle_id}/", response=IsolatedCycleOut)
def update_isolated_cycle(
    request: HttpRequest, cycle_id: int, payload: IsolatedCyclePatch
):
    """Correção do calendário do edital.

    Prorrogar prazo é rotina de secretaria e por isso é tela, não Admin
    (ADR-006). `is_active` não é editável aqui pela razão declarada em
    `IsolatedCycleIn`.
    """
    require_perm(request, "academic.change_isolatedenrollmentcycle")
    program: Program = current_program(request)
    ciclo = get_object_or_404(
        IsolatedEnrollmentCycle.objects.for_program(program), pk=cycle_id
    )
    campos = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "term_id" in campos:
        # Existência do período é 404 aqui também: id inválido não pode
        # virar IntegrityError na hora do save.
        get_object_or_404(AcademicTerm, pk=campos["term_id"])
    for campo, valor in campos.items():
        setattr(ciclo, campo, valor)
    with transaction.atomic():
        ciclo.clean()
        ciclo.save(update_fields=list(campos) or None)
        audit.record(
            "academic.isolated_cycle.update",
            request=request,
            target=ciclo,
            fields=sorted(campos),
        )
    return ciclo


@router.get("/isolated/offerings/", response=list[DisciplineOfferingOut])
def list_isolated_offerings(
    request: HttpRequest, mine: bool = False, cycle_id: int | None = None
):
    """As disciplinas do edital aberto, com o saldo de vagas.

    Sem paginação: um edital oferece dezenas de disciplinas, não milhares,
    e a tela do candidato precisa da lista inteira para ele escolher duas.
    Fora da janela de inscrição a resposta é `no_open_cycle` (400) — a
    mesma que o auto-registro dá, e a mesma mensagem que a tela exibe.

    `?mine=true` é a lista do docente e NÃO passa pelo ciclo aberto de
    propósito: ele classifica depois que a inscrição fecha, e amarrar a
    janela aqui deixaria a tela dele vazia justamente quando ela importa.
    O recorte então é o ciclo ativo, e `needs_ranking` diz onde falta
    resposta.

    `?cycle_id=` é a lista da secretaria e também ignora a janela: ela
    analisa depois que a inscrição fecha, e é justamente aí que precisa
    das vagas restantes e de saber onde falta classificação. Escolher o
    ciclo livremente exige `view_isolatedenrollmentcycle` — sem essa
    trava, o candidato leria o edital de qualquer semestre a qualquer
    hora, driblando a janela que a rota impõe a ele.
    """
    require_perm(request, "academic.view_disciplineoffering")
    program: Program = current_program(request)
    # `seats_available()` e `needs_ranking()` fazem um COUNT por oferta e
    # não aproveitam prefetch (são `filter` sobre o acessor reverso). São
    # dezenas de consultas curtas num edital, não milhares — se um dia
    # doer, o caminho é anotar o COUNT no queryset, e não espalhar a regra
    # das vagas nem a da classificação na tela.
    ofertas = DisciplineOffering.objects.for_program(program).select_related(
        "discipline", "teacher__person"
    )
    if mine:
        # A posse sai da sessão, nunca de um `teacher_id` do chamador —
        # senão qualquer docente lê a fila de qualquer outro.
        pessoas = Person.objects.active().filter(user=request.user, program=program)
        return ofertas.filter(
            teacher__person__in=pessoas, cycle__is_active=True
        ).order_by("cycle__term__year", "cycle__term__half", "discipline__code")
    if cycle_id is not None:
        require_perm(request, "academic.view_isolatedenrollmentcycle")
        # O escopo entra na busca: ciclo de outro programa vira 404, nunca
        # 403 — o padrão de tenant do projeto.
        ciclo = get_object_or_404(
            IsolatedEnrollmentCycle.objects.for_program(program), pk=cycle_id
        )
        return ofertas.for_cycle(ciclo).order_by("discipline__code")
    ciclo = ciclo_com_inscricao_aberta(program=program, at=timezone.now())
    return ofertas.for_cycle(ciclo)


@router.post("/isolated/offerings/", response={201: DisciplineOfferingOut})
def create_isolated_offering(request: HttpRequest, payload: DisciplineOfferingIn):
    """A secretaria põe uma disciplina no edital, com responsável e vagas.

    Ciclo, disciplina e docente são buscados já escopados pelo programa:
    referência de outro tenant vira 404, e não o `program_mismatch` do
    model — este fica como rede de segurança para quem escrever pelo
    Admin.
    """
    require_perm(request, "academic.add_disciplineoffering")
    program: Program = current_program(request)
    ciclo = get_object_or_404(
        IsolatedEnrollmentCycle.objects.for_program(program), pk=payload.cycle_id
    )
    oferta = DisciplineOffering(
        program=program,
        cycle=ciclo,
        discipline=get_object_or_404(
            Discipline.objects.for_program(program), pk=payload.discipline_id
        ),
        teacher=get_object_or_404(
            Teacher.objects.for_program(program), pk=payload.teacher_id
        ),
        seats=payload.seats,
    )
    with transaction.atomic():
        oferta.clean()
        oferta.save()
        audit.record(
            "academic.discipline_offering.create",
            request=request,
            target=oferta,
            cycle_id=oferta.cycle_id,
            discipline_id=oferta.discipline_id,
            seats=oferta.seats,
        )
    return Status(201, oferta)


@router.patch("/isolated/offerings/{int:offering_id}/", response=DisciplineOfferingOut)
def update_isolated_offering(
    request: HttpRequest, offering_id: int, payload: DisciplineOfferingPatch
):
    """Troca de responsável, de disciplina ou do número de vagas."""
    require_perm(request, "academic.change_disciplineoffering")
    program: Program = current_program(request)
    oferta = get_object_or_404(
        DisciplineOffering.objects.for_program(program).select_related(
            "discipline", "teacher__person"
        ),
        pk=offering_id,
    )
    campos = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "discipline_id" in campos:
        oferta.discipline = get_object_or_404(
            Discipline.objects.for_program(program), pk=campos["discipline_id"]
        )
    if "teacher_id" in campos:
        oferta.teacher = get_object_or_404(
            Teacher.objects.for_program(program), pk=campos["teacher_id"]
        )
    if "seats" in campos:
        oferta.seats = campos["seats"]
    with transaction.atomic():
        oferta.clean()
        oferta.save(update_fields=list(campos) or None)
        audit.record(
            "academic.discipline_offering.update",
            request=request,
            target=oferta,
            fields=sorted(campos),
        )
    return oferta


def _ofertas(
    ciclo: IsolatedEnrollmentCycle, itens: list[IsolatedItemIn]
) -> list[DisciplineOffering]:
    """Resolve as escolhas em ofertas DO CICLO ABERTO.

    O escopo entra na busca: oferta de outro ciclo ou de outro programa
    não existe para esta requisição (404, nunca 403). É o que impede o
    `cycle_mismatch` de `IsolatedEnrollmentItem.clean()` de chegar ao
    banco pelo caminho normal.
    """
    return [
        get_object_or_404(
            DisciplineOffering.objects.for_cycle(ciclo), pk=item.offering_id
        )
        for item in itens
    ]


def _pessoa_da_sessao(
    request: HttpRequest, program: Program, person_id: int | None
) -> Person:
    """A pessoa de quem está pedindo — nunca a do payload.

    Aceitar `person_id` do corpo sem conferir seria deixar qualquer
    candidato se inscrever em nome de outro. O campo só serve para a tela
    ser explícita: se não for uma Person desta sessão, é 403.
    """
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    if person_id is not None:
        pessoa = pessoas.filter(pk=person_id).first()
        if pessoa is None:
            raise NotAllowed("A inscrição é sempre em nome do próprio candidato.")
        return pessoa
    pessoa = pessoas.first()
    if pessoa is None:
        raise NotAllowed("Sua conta não tem cadastro neste programa.")
    return pessoa


def _meu_requerimento(
    request: HttpRequest, program: Program, request_id: int
) -> IsolatedEnrollmentRequest:
    """O requerimento desta sessão — só o do próprio candidato.

    `change_isolatedenrollmentrequest` é permissão de papel: ela diz que a
    pessoa mexe no requerimento dela, não em QUALQUER um. Vale inclusive
    para a Secretaria, que julga (US-012) mas não escolhe disciplina por
    ninguém.
    """
    requerimento = get_object_or_404(
        IsolatedEnrollmentRequest.objects.for_program(program).select_related(
            "person", "cycle"
        ),
        pk=request_id,
    )
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    if not pessoas.filter(pk=requerimento.person_id).exists():
        raise NotAllowed("Só o próprio candidato altera o requerimento dele.")
    return requerimento


@router.get("/isolated/requests/", response=list[IsolatedRequestOut])
@paginate
def list_isolated_requests(
    request: HttpRequest,
    cycle_id: int | None = None,
    status: IsolatedRequestStatus | None = None,
):
    require_perm(request, "academic.view_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimentos = (
        # Duas camadas, nesta ordem: o tenant primeiro (não é opcional) e o
        # papel depois. `visible_to` é quem recorta o candidato e o docente
        # de secretaria/coordenação — ver o método no model.
        IsolatedEnrollmentRequest.objects.for_program(program)
        .visible_to(request.user, program)
        # `cycle` entra porque `IsolatedRequestOut` publica as janelas do
        # edital: sem ele a fila da secretaria faria uma consulta por linha.
        .select_related("person", "cycle")
        .prefetch_related("items__offering__discipline")
    )
    if cycle_id is not None:
        # Filtro de conveniência da tela. Não é escopo de tenant — esse já
        # foi aplicado acima e não é opcional.
        requerimentos = requerimentos.filter(cycle_id=cycle_id)
    if status is not None:
        # A fila da secretaria é uma situação por vez: os inscritos para
        # julgar, os deferidos para conferir pagamento. Valor fora do enum
        # é 422 na borda, de graça.
        requerimentos = requerimentos.filter(status=status)
    return requerimentos


@router.post("/isolated/requests/", response={201: IsolatedRequestOut})
def create_isolated_request_endpoint(request: HttpRequest, payload: IsolatedRequestIn):
    require_perm(request, "academic.add_isolatedenrollmentrequest")
    program: Program = current_program(request)
    pessoa = _pessoa_da_sessao(request, program, payload.person_id)
    ciclo = ciclo_com_inscricao_aberta(program=program, at=timezone.now())
    requerimento = create_isolated_request(
        program=program,
        cycle=ciclo,
        person=pessoa,
        is_ufmg_staff=payload.is_ufmg_staff,
        ofertas=_ofertas(ciclo, payload.items),
        request=request,
    )
    return Status(201, requerimento)


@router.patch("/isolated/requests/{int:request_id}/", response=IsolatedRequestOut)
def update_isolated_request(
    request: HttpRequest, request_id: int, payload: IsolatedRequestPatch
):
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _meu_requerimento(request, program, request_id)
    # A regra mora no model: fora do rascunho é InvalidStateTransition
    # (409) e o handler central converte, sem try/except aqui (Seção 8).
    requerimento.ensure_editable()

    campos = payload.model_dump(exclude_unset=True, exclude_none=True)
    itens = campos.pop("items", None)
    with transaction.atomic():
        if "is_ufmg_staff" in campos:
            requerimento.is_ufmg_staff = campos["is_ufmg_staff"]
            requerimento.save(update_fields=["is_ufmg_staff"])
        if itens is not None:
            ofertas = _ofertas(requerimento.cycle, payload.items or [])
            # Substituição, e não acréscimo: a lista do corpo é a escolha
            # final do candidato, e apagar antes de inserir dispensa
            # calcular a diferença.
            requerimento.items.all().delete()
            IsolatedEnrollmentItem.objects.bulk_create(
                [
                    IsolatedEnrollmentItem(request=requerimento, offering=oferta)
                    for oferta in ofertas
                ]
            )
        audit.record(
            "academic.isolated.update",
            request=request,
            target=requerimento,
            fields=sorted([*campos, *(["items"] if itens is not None else [])]),
        )
    return requerimento


@router.post("/isolated/requests/{int:request_id}/submit", response=IsolatedRequestOut)
def submit_isolated_request(request: HttpRequest, request_id: int):
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _meu_requerimento(request, program, request_id)
    with transaction.atomic():
        # Janela, contagem de disciplinas e documentação faltante são
        # cobrança do model e voltam como 4xx do handler central.
        requerimento.submit(at=timezone.now())
        requerimento.save(update_fields=["status", "submitted_at"])
        audit.record(
            "academic.isolated.submit",
            request=request,
            target=requerimento,
            person_id=requerimento.person_id,
            cycle_id=requerimento.cycle_id,
        )
    return requerimento


@router.get(
    "/isolated/requests/{int:request_id}/documents",
    response=list[RequestDocumentOut],
)
def list_isolated_documents(request: HttpRequest, request_id: int):
    """O que já foi anexado — nome, tipo, tamanho e data, sem o arquivo.

    Escopo por papel igual ao da fila (`visible_to`): o candidato vê os
    próprios anexos, o docente vê os de quem se inscreveu na oferta dele,
    secretaria e coordenação veem todos. Quem enxerga a lista não
    necessariamente baixa o conteúdo — isso é a rota de download.
    """
    require_perm(request, "academic.view_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = get_object_or_404(
        IsolatedEnrollmentRequest.objects.for_program(program).visible_to(
            request.user, program
        ),
        pk=request_id,
    )
    return requerimento.documents.all()


def _substituir_documento(
    requerimento: IsolatedEnrollmentRequest,
    kind: str,
    file: UploadedFile,
) -> tuple[RequestDocument, bool]:
    """Grava o anexo daquele tipo, apagando a versão anterior se houver.

    Substituir apagando a linha, e não editando o `file`: `uploaded_at` é
    `auto_now_add` e ficaria com a data do envio errado se o registro
    fosse reaproveitado.

    A remoção do arquivo do storage é explícita porque `delete()` do model
    não a faz — sem ela cada reenvio deixaria um órfão no MEDIA_ROOT. E
    vem antes de qualquer escrita que possa falhar, já que o storage não
    participa do rollback da transação.
    """
    anterior = RequestDocument.objects.filter(request=requerimento, kind=kind).first()
    if anterior is not None:
        anterior.file.delete(save=False)
        anterior.delete()
    documento = RequestDocument.objects.create(
        request=requerimento, kind=kind, file=file
    )
    return documento, anterior is not None


@router.post(
    "/isolated/requests/{int:request_id}/documents",
    response={201: RequestDocumentOut},
)
def upload_isolated_document(
    request: HttpRequest,
    request_id: int,
    kind: RequestDocumentKind = Form(...),
    file: UploadedFile = File(...),
):
    """Anexa (ou substitui) o documento de um tipo.

    A permissão é a de montar o requerimento — anexar é parte de montar —,
    e `_meu_requerimento` garante que é o próprio: nem a Secretaria anexa
    documento no lugar do candidato, pelo mesmo motivo de US-009.

    Substituir, e não empilhar: um tipo tem uma versão
    (`unique_documento_por_requerimento_e_tipo`), e o reenvio é a correção
    de quem mandou a página errada.
    """
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _meu_requerimento(request, program, request_id)
    # As duas cobranças são do model e voltam como 4xx do handler central:
    # estado errado é 409, arquivo recusado é 400 com code invalid_document.
    requerimento.ensure_document_upload_allowed(kind)
    RequestDocument.validate_upload(filename=file.name or "", size=file.size or 0)

    with transaction.atomic():
        documento, substituiu = _substituir_documento(requerimento, kind, file)
        audit.record(
            "academic.isolated.document_upload",
            request=request,
            target=requerimento,
            document_id=documento.pk,
            kind=str(kind),
            filename=file.name,
            replaced=substituiu,
        )
    return Status(201, documento)


@router.get("/isolated/documents/{int:document_id}/download")
def download_isolated_document(request: HttpRequest, document_id: int):
    """Entrega o arquivo — pelo Django, nunca por URL direta do MEDIA.

    Duas portas, e só duas: a Secretaria pela permissão
    `download_requestdocument`, e o próprio candidato por posse. Docente e
    Coordenação enxergam o requerimento e mesmo assim levam 403 aqui —
    identidade e contracheque não são insumo de classificação.

    A permissão ampla é checada só depois da posse porque ela é a exceção,
    e não a regra: o dono do documento não precisa de permissão de
    secretaria para ler o que ele mesmo enviou.
    """
    require_perm(request, "academic.view_isolatedenrollmentrequest")
    program: Program = current_program(request)
    documento = get_object_or_404(
        RequestDocument.objects.for_program(program).select_related("request"),
        pk=document_id,
    )
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    if not pessoas.filter(pk=documento.request.person_id).exists():
        require_perm(request, "academic.download_requestdocument")

    with transaction.atomic():
        # Auditar leitura é exceção no projeto e aqui é obrigatório: é o
        # acesso ao documento de identidade de outra pessoa.
        audit.record(
            "academic.isolated.document_download",
            request=request,
            target=documento.request,
            document_id=documento.pk,
            kind=documento.kind,
        )
    return FileResponse(
        documento.file.open("rb"),
        as_attachment=True,
        filename=Path(documento.file.name).name,
    )


def _minha_oferta(
    request: HttpRequest, program: Program, offering_id: int
) -> DisciplineOffering:
    """A oferta desta sessão — só a do docente responsável.

    `rank_disciplineoffering` é permissão de papel: ela diz que a pessoa
    classifica candidatos, não QUAIS ofertas. A posse é aqui, como em
    `_meu_requerimento`.

    403 e não 404, ao contrário do escopo de tenant: a oferta é do mesmo
    programa e o docente sabe que ela existe — o que ele não pode é
    ordenar a fila de um colega.
    """
    oferta = get_object_or_404(
        DisciplineOffering.objects.for_program(program).select_related(
            "teacher", "discipline"
        ),
        pk=offering_id,
    )
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    if not pessoas.filter(pk=oferta.teacher.person_id).exists():
        raise NotAllowed(
            "Só o docente responsável classifica os candidatos desta oferta."
        )
    return oferta


@router.get(
    "/isolated/offerings/{int:offering_id}/candidates",
    response=list[IsolatedCandidateOut],
)
def list_offering_candidates(request: HttpRequest, offering_id: int):
    """Quem se inscreveu nesta oferta, na ordem atual da classificação.

    Sem paginação, pela mesma razão da lista de ofertas: a fila de uma
    disciplina isolada tem dezenas de nomes e o docente ordena todos de
    uma vez — meia lista não dá para classificar.
    """
    require_perm(request, "academic.rank_disciplineoffering")
    program: Program = current_program(request)
    oferta = _minha_oferta(request, program, offering_id)
    return oferta.candidates()


@router.post(
    "/isolated/offerings/{int:offering_id}/rank",
    response=list[IsolatedCandidateOut],
)
def rank_offering_candidates(
    request: HttpRequest, offering_id: int, payload: IsolatedRankIn
):
    """Grava a ordem do docente como posição 1..N.

    Substituição, e não acréscimo: a lista do corpo é a classificação
    final daquela oferta, e quem ficou de fora volta a não ter posição.
    """
    require_perm(request, "academic.rank_disciplineoffering")
    program: Program = current_program(request)
    oferta = _minha_oferta(request, program, offering_id)
    # Id de fora da oferta é `item_not_in_offering` (400), cobrado no
    # model e convertido pelo handler central (Seção 8).
    ordenados = oferta.rank_items(payload.item_ids)
    with transaction.atomic():
        # Zerar antes de gravar não é zelo: `unique_classificacao_por_oferta`
        # barraria a troca de posição entre dois candidatos se as escritas
        # fossem incrementais, e a ordem em que elas sairiam do laço
        # decidiria se a operação passa.
        oferta.items.update(rank=None)
        for item in ordenados:
            item.save(update_fields=["rank"])
        audit.record(
            "academic.isolated.rank",
            request=request,
            target=oferta,
            cycle_id=oferta.cycle_id,
            item_ids=[item.pk for item in ordenados],
        )
    return oferta.candidates()


def _requerimento_para_decidir(
    request: HttpRequest, program: Program, request_id: int
) -> IsolatedEnrollmentRequest:
    """O requerimento que esta sessão pode julgar — nunca o próprio.

    `change_isolatedenrollmentrequest` tem duas faces no fluxo da isolada
    (`academic.0011`): é a permissão de quem monta o requerimento e a de
    quem o decide. O que separa os dois papéis é a posse, no espelho
    exato de `_meu_requerimento`: quem julga é quem NÃO é o candidato.
    Sem esta linha, o próprio candidato deferiria a inscrição dele.

    Docente e Coordenação não chegam aqui: os dois só têm `view`.
    """
    requerimento = get_object_or_404(
        IsolatedEnrollmentRequest.objects.for_program(program)
        .select_related("person", "cycle")
        .prefetch_related("items__offering__discipline"),
        pk=request_id,
    )
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    if pessoas.filter(pk=requerimento.person_id).exists():
        raise NotAllowed("Ninguém decide o próprio requerimento.")
    return requerimento


@router.post("/isolated/requests/{int:request_id}/defer", response=IsolatedRequestOut)
def defer_isolated_request(
    request: HttpRequest, request_id: int, payload: IsolatedDeferIn
):
    """Defere o requerimento e, com ele, reserva a vaga.

    O link da GRU entra no mesmo ato: deferir sem dizer como pagar
    deixaria o candidato parado até a secretaria lembrar de voltar aqui.
    Servidor da UFMG nasce isento dentro de `defer()` e para ele o campo
    fica vazio.
    """
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _requerimento_para_decidir(request, program, request_id)
    # As três cobranças são do model e voltam como 4xx do handler central:
    # oferta sem classificação e sem vaga são 400 com code estável, estado
    # errado é 409 (Seção 8).
    requerimento.ensure_deferrable()
    with transaction.atomic():
        requerimento.defer(note=payload.note)
        if payload.gru_url is not None:
            requerimento.gru_url = str(payload.gru_url)
        requerimento.save(
            update_fields=[
                "status",
                "decision_note",
                "decided_at",
                "payment_status",
                "gru_url",
            ]
        )
        audit.record(
            "academic.isolated.defer",
            request=request,
            target=requerimento,
            person_id=requerimento.person_id,
            cycle_id=requerimento.cycle_id,
            payment_status=requerimento.payment_status,
        )
    return requerimento


@router.post("/isolated/requests/{int:request_id}/reject", response=IsolatedRequestOut)
def reject_isolated_request(
    request: HttpRequest, request_id: int, payload: IsolatedRejectIn
):
    """Indefere com motivo obrigatório — é o texto do recurso (US-013)."""
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _requerimento_para_decidir(request, program, request_id)
    with transaction.atomic():
        requerimento.reject(note=payload.note)
        requerimento.save(update_fields=["status", "decision_note", "decided_at"])
        audit.record(
            "academic.isolated.reject",
            request=request,
            target=requerimento,
            person_id=requerimento.person_id,
            cycle_id=requerimento.cycle_id,
            note=requerimento.decision_note,
        )
    return requerimento


@router.post("/isolated/requests/{int:request_id}/cancel", response=IsolatedRequestOut)
def cancel_isolated_request(
    request: HttpRequest, request_id: int, payload: IsolatedCancelIn
):
    """Cancela e devolve a vaga à oferta.

    Não existe expiração automática no projeto — nada roda sozinho —,
    então a vaga do deferido que não pagou só volta para a fila quando a
    secretaria cancela aqui. A devolução é consequência de
    `seats_taken()` parar de contar o cancelado, e não uma escrita à
    parte.
    """
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _requerimento_para_decidir(request, program, request_id)
    with transaction.atomic():
        requerimento.cancel(note=payload.note)
        requerimento.save(update_fields=["status", "decision_note", "decided_at"])
        audit.record(
            "academic.isolated.cancel",
            request=request,
            target=requerimento,
            person_id=requerimento.person_id,
            cycle_id=requerimento.cycle_id,
            note=requerimento.decision_note,
        )
    return requerimento


@router.post("/isolated/requests/{int:request_id}/appeal", response=IsolatedRequestOut)
def appeal_isolated_request(
    request: HttpRequest,
    request_id: int,
    note: str = Form(...),
    kind: RequestDocumentKind | None = Form(None),
    file: UploadedFile | None = File(None),
):
    """Interpõe recurso contra o indeferimento, com o documento que faltou.

    Multipart, e não JSON, por causa do anexo: o motivo mais comum de
    indeferimento é documentação, e recorrer sem poder juntar a página que
    faltou seria pedir clemência em vez de corrigir. O anexo é opcional —
    quem contesta a nota do docente não tem o que anexar.

    Não existe rota de "rejulgar": a secretaria decide de novo pelos
    mesmos `defer`/`reject` da US-012. O recurso não cria entidade nem
    estado novo, ele reabre a decisão — e por isso não derruba a
    classificação do docente nem dispensa a GRU.
    """
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _meu_requerimento(request, program, request_id)
    if (kind is None) != (file is None):
        raise DomainError(
            "O anexo do recurso precisa do tipo e do arquivo juntos.",
            code="incomplete_document",
        )
    if kind is not None:
        # Estado e janela são cobrança de `appeal()`, logo abaixo; aqui só
        # o que é do anexo. Tipo proibido é 400 do model, arquivo recusado
        # é 400 com code invalid_document.
        requerimento.ensure_appeal_document_allowed(kind)
        assert file is not None  # garantido pela checagem de par acima
        RequestDocument.validate_upload(filename=file.name or "", size=file.size or 0)

    with transaction.atomic():
        # Estado errado é 409 e janela fechada é 400 appeal_window_closed,
        # ambos do model e convertidos pelo handler central (Seção 8).
        requerimento.appeal(note=note, at=timezone.now())
        requerimento.save(update_fields=["appeal_note", "appealed_at"])
        documento = None
        if kind is not None and file is not None:
            documento, _ = _substituir_documento(requerimento, kind, file)
        audit.record(
            "academic.isolated.appeal",
            request=request,
            target=requerimento,
            person_id=requerimento.person_id,
            cycle_id=requerimento.cycle_id,
            document_id=documento.pk if documento is not None else None,
            kind=str(kind) if kind is not None else None,
        )
    return requerimento


@router.post(
    "/isolated/requests/{int:request_id}/payment-receipt",
    response=IsolatedRequestOut,
)
def upload_isolated_payment_receipt(
    request: HttpRequest,
    request_id: int,
    file: UploadedFile = File(...),
):
    """Anexa o comprovante da GRU e dá a taxa por paga.

    Sem `kind` no corpo: esta rota tem um tipo só, e recebê-lo de fora
    deixaria o candidato marcar como pago o envio de qualquer papel. É por
    isso que ela existe separada do upload genérico, que exige rascunho.

    Anexar e marcar pago são o mesmo ato porque a conferência é humana e
    posterior: a secretaria vê o comprovante na tela dela (US-019) e
    cancela se não bater (US-012). O que o sistema garante aqui é que
    ninguém fica PAGO sem ter anexado nada.
    """
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _meu_requerimento(request, program, request_id)
    # Estado errado é 409; isento e prazo vencido são 400 com code estável
    # (payment_not_required, payment_window_closed) — tudo do model.
    requerimento.register_payment(at=timezone.now())
    RequestDocument.validate_upload(filename=file.name or "", size=file.size or 0)

    with transaction.atomic():
        documento, substituiu = _substituir_documento(
            requerimento, RequestDocumentKind.PAYMENT_RECEIPT, file
        )
        requerimento.save(update_fields=["payment_status"])
        audit.record(
            "academic.isolated.payment_receipt",
            request=request,
            target=requerimento,
            person_id=requerimento.person_id,
            cycle_id=requerimento.cycle_id,
            document_id=documento.pk,
            filename=file.name,
            replaced=substituiu,
        )
    return requerimento


@router.post("/isolated/requests/{int:request_id}/enroll", response=IsolatedRequestOut)
def enroll_isolated_request_endpoint(
    request: HttpRequest, request_id: int, payload: IsolatedEnrollIn
):
    """Efetiva a matrícula: o requerimento deferido e pago vira `Student`.

    A matrícula chega digitada porque quem emite o número é o sistema da
    UFMG: a secretaria lança a inscrição lá, recebe o número e o registra
    aqui. Este é o único ato do fluxo que depende de um sistema de fora, e
    por isso não há como o servidor gerá-lo sozinho.

    O trabalho todo está em `services.enroll_isolated_request`: escreve em
    quatro models na mesma transação e não cabe no router (ADR-002).
    """
    require_perm(request, "academic.change_isolatedenrollmentrequest")
    program: Program = current_program(request)
    requerimento = _requerimento_para_decidir(request, program, request_id)
    enroll_isolated_request(
        requerimento=requerimento,
        registration_number=payload.registration_number,
        request=request,
    )
    return requerimento


@router.post("/isolated/cycles/{int:cycle_id}/close", response=IsolatedCycleCloseOut)
def close_isolated_cycle_endpoint(request: HttpRequest, cycle_id: int):
    """Encerra o edital do semestre e exclui os alunos de isolada dele.

    É sempre um ato explícito da secretaria: nada expira sozinho por data.
    Fosse automático, o sistema excluiria vínculo no meio de uma pendência
    (recurso em análise, GRU paga e matrícula não lançada) sem ninguém
    para responder por isso.

    O trabalho está em `services.close_isolated_cycle` — lote numa só
    transação, com um único AuditLog carregando a contagem (ADR-002).
    """
    require_perm(request, "academic.change_isolatedenrollmentcycle")
    program: Program = current_program(request)
    ciclo = get_object_or_404(
        IsolatedEnrollmentCycle.objects.for_program(program), pk=cycle_id
    )
    excluidos = close_isolated_cycle(ciclo=ciclo, request=request)
    return {
        "cycle_id": ciclo.pk,
        "is_active": ciclo.is_active,
        "students_excluded": excluidos,
    }


@access_router.post("/signup", auth=None, response={200: AccessSignupOut})
@decorate_view(csrf_protect)
def access_signup(request: HttpRequest, payload: AccessSignupIn):
    # público: é o único endpoint de escrita sem sessão do projeto, e tem
    # de ser — quem se cadastra ainda não tem acesso ao programa e
    # portanto não tem conta para autenticar. Sem ele, a secretaria
    # digitaria à mão cada docente, discente e candidato, que é
    # exatamente o trabalho que este módulo existe para tirar dela.
    #
    # As três travas que substituem a sessão: só programa com o
    # interruptor `accepts_self_signup` ligado aceita cadastro
    # (programa_que_aceita_autocadastro — `program_id` é obrigatório, mas
    # vem da lista pública e não é escolha livre), limite de tentativas
    # por IP e csrf_protect explícito — auth=None desliga junto a checagem
    # de CSRF que o SessionAuth faria, mesma armadilha do login.
    enforce_rate_limit(
        request,
        scope="access-signup",
        limit=LIMITE_DE_SIGNUP_POR_IP,
        window_seconds=JANELA_DE_SIGNUP_EM_SEGUNDOS,
    )
    program = programa_que_aceita_autocadastro(program_id=payload.program_id)
    signup_access_request(
        program=program,
        profile=payload.profile,
        full_name=payload.full_name,
        email=str(payload.email),
        password=payload.password,
        phone_number=payload.phone_number,
        teacher_category=payload.teacher_category or "",
        academic_degree=payload.academic_degree or "",
        home_institution=payload.home_institution,
        lattes_url=payload.lattes_url,
        request=request,
    )
    # O corpo varia por PERFIL e só por ele: o valor devolvido pelo service
    # (pessoa nova x pessoa que já existia) é ignorado de propósito, senão
    # a rota vira um verificador de contas para qualquer um.
    if payload.profile == AccessProfile.CANDIDATE:
        return {
            "detail": (
                "Cadastro recebido. Use seu e-mail e sua senha para entrar e "
                "concluir a inscrição."
            ),
            "requires_confirmation": False,
        }
    return {
        "detail": (
            "Cadastro recebido. Este cadastro deve ser confirmado pela secretaria."
        ),
        "requires_confirmation": True,
    }
