"""Operações do app academic que cruzam mais de um model.

`create_teacher` existe aqui porque escreve em Person, User, Group, Teacher
e AuditLog na mesma transação (ADR-002). Operação que toca um model só
continua sendo chamada direto do router — não crie service "por simetria".

Quem escreve aqui chama `clean()` antes de `save()`: o Django não executa
`clean()` em `.save()`/`.create()`, só em formulário — sem essa chamada o
invariante de programa de Teacher e Student nunca roda no caminho real.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from django.db import transaction
from django.http import HttpRequest

from apps.accounts.models import User, validar_senha
from apps.accounts.services import assign_role_group
from apps.core import audit
from apps.core.exceptions import DomainError
from apps.people.models import Person
from apps.people.services import create_person_with_user
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Discipline,
    Program,
    ResearchLine,
)

from .models import (
    EnrollmentAdjustmentItem,
    EnrollmentAdjustmentRequest,
    IsolatedEnrollmentCycle,
    Student,
    Teacher,
)


def conferir_programa(objetos: Sequence[Any], program: Program, rotulo: str) -> None:
    """Vínculo de M2M com objeto de outro programa é o mesmo erro de tenant
    que `Teacher.clean()` cobre nas FKs — mas M2M só é gravável depois do
    save, então a checagem mora aqui.
    """
    if any(objeto.program_id != program.pk for objeto in objetos):
        raise DomainError(
            f"{rotulo} precisa ser do mesmo programa do professor.",
            code="program_mismatch",
        )


@transaction.atomic
def create_teacher(
    *,
    program: Program,
    person: Person | None = None,
    dados_da_pessoa: dict[str, Any] | None = None,
    campos: dict[str, Any],
    research_lines: Sequence[ResearchLine] = (),
    projects: Sequence[CollectiveProject] = (),
    request: HttpRequest | None = None,
) -> Teacher:
    """Cria o professor e garante o acesso dele — tudo ou nada.

    `person` é a pessoa que já existe; `dados_da_pessoa` (full_name, email,
    phone_number) cria uma nova junto com a conta. Exatamente um dos dois
    vem preenchido — a exclusividade é cobrada na borda, por `TeacherIn`.
    """
    if person is None:
        if dados_da_pessoa is None:
            raise DomainError("Informe a pessoa do professor.", code="person_required")
        person = create_person_with_user(
            program=program, request=request, **dados_da_pessoa
        )

    conferir_programa(research_lines, program, "A linha de pesquisa")
    conferir_programa(projects, program, "O projeto coletivo")

    teacher = Teacher(program=program, person=person, **campos)
    # A regra mora no model; aqui só persistimos e auditamos.
    teacher.clean()
    teacher.save()
    teacher.research_lines.set(research_lines)
    teacher.projects.set(projects)

    # Pessoa sem conta (registro histórico) não entra em papel nenhum —
    # não há usuário para receber o acesso.
    if person.user is not None:
        assign_role_group(person.user, group_name="Docente", request=request)

    audit.record(
        "academic.teacher.create",
        request=request,
        target=teacher,
        person_id=person.pk,
        category=teacher.category,
    )
    return teacher


@transaction.atomic
def create_student(
    *,
    program: Program,
    person: Person | None = None,
    dados_da_pessoa: dict[str, Any] | None = None,
    campos: dict[str, Any],
    request: HttpRequest | None = None,
) -> Student:
    """Cria o vínculo de aluno — tudo ou nada.

    Mesma regra de `create_teacher` para a pessoa: `person` já existe,
    `dados_da_pessoa` cria uma nova junto com a conta, e a exclusividade
    entre os dois é cobrada na borda por `StudentIn`.

    Só o regular entra no papel Discente: a isolada e a eletiva duram um
    semestre e não dão acesso ao sistema do programa.
    """
    if person is None:
        if dados_da_pessoa is None:
            raise DomainError("Informe a pessoa do aluno.", code="person_required")
        person = create_person_with_user(
            program=program, request=request, **dados_da_pessoa
        )

    student = Student(program=program, person=person, **campos)
    # A regra mora no model; aqui só persistimos e auditamos.
    student.clean()
    student.save()

    if student.modality == Student.Modality.REGULAR and person.user is not None:
        assign_role_group(person.user, group_name="Discente", request=request)

    audit.record(
        "academic.student.create",
        request=request,
        target=student,
        person_id=person.pk,
        modality=student.modality,
        status=student.status,
    )
    return student


@transaction.atomic
def create_enrollment_adjustment(
    *,
    program: Program,
    student: Student,
    term: AcademicTerm,
    justification: str = "",
    itens: Sequence[tuple[Discipline, str]],
    request: HttpRequest | None = None,
) -> EnrollmentAdjustmentRequest:
    """Abre a solicitação de acerto com todos os seus itens — tudo ou nada.

    Está aqui, e não no router, porque escreve em três models
    (EnrollmentAdjustmentRequest, EnrollmentAdjustmentItem e AuditLog) na
    mesma transação (ADR-002). Solicitação gravada sem os itens seria um
    pedido vazio esperando decisão.

    `itens` são pares (disciplina, ação) já resolvidos e escopados pelo
    router: id inexistente ou de outro programa vira 404 lá, não
    IntegrityError aqui.
    """
    student.ensure_can_request_adjustment()

    solicitacao = EnrollmentAdjustmentRequest(
        program=program,
        student=student,
        term=term,
        justification=justification,
    )
    # A regra mora no model; aqui só persistimos e auditamos.
    solicitacao.clean()
    solicitacao.save()
    EnrollmentAdjustmentItem.objects.bulk_create(
        [
            EnrollmentAdjustmentItem(
                request=solicitacao, discipline=disciplina, action=acao
            )
            for disciplina, acao in itens
        ]
    )

    audit.record(
        "academic.enrollment_adjustment.create",
        request=request,
        target=solicitacao,
        student_id=student.pk,
        term_id=term.pk,
        items=[
            {"discipline_id": disciplina.pk, "action": acao}
            for disciplina, acao in itens
        ],
    )
    return solicitacao


# Uma pessoa de fora da UFMG cria a conta uma vez por edital; cinco
# tentativas por hora sobra para quem errou o formulário e não serve de
# torneira para script.
LIMITE_DE_SIGNUP_POR_IP = 5
JANELA_DE_SIGNUP_EM_SEGUNDOS = 3600


def programa_com_inscricao_aberta(
    *, at: datetime, program_id: int | None = None
) -> Program:
    """Resolve o tenant do auto-registro pelo edital, e não pelo chamador.

    É o substituto de `current_program()` na única rota pública de escrita
    do projeto: sem sessão não há Person de onde tirar o programa, e
    aceitar `program_id` livre faria a rota criar conta em qualquer tenant
    a qualquer momento. Só existe candidato onde existe inscrição aberta.
    """
    abertos = set(
        IsolatedEnrollmentCycle.objects.active()
        .filter(submission_opens_at__lte=at, submission_closes_at__gt=at)
        .values_list("program_id", flat=True)
    )
    if program_id is not None:
        abertos &= {program_id}
    if not abertos:
        raise DomainError(
            "Não há edital de disciplina isolada com inscrições abertas.",
            code="no_open_cycle",
        )
    if len(abertos) > 1:
        raise DomainError(
            "Há mais de um edital aberto: informe program_id.",
            code="program_required",
        )
    return Program.objects.get(pk=next(iter(abertos)))


@transaction.atomic
def signup_isolated_candidate(
    *,
    program: Program,
    full_name: str,
    email: str,
    password: str,
    phone_number: str = "",
    request: HttpRequest | None = None,
) -> bool:
    """Cria a conta do candidato — tudo ou nada.

    Devolve True quando a pessoa nasceu agora e False quando já existia. O
    router ignora o valor de propósito: os dois casos respondem o mesmo
    corpo, senão a rota conta a quem perguntar quais e-mails têm conta.

    Sem confirmação de e-mail: o projeto não tem SMTP, e quem faz o papel
    de porteiro é o deferimento manual da secretaria (US-012).
    """
    # A força da senha é cobrada antes da consulta: se dependesse do
    # desvio, a mensagem de senha fraca denunciaria o e-mail inédito.
    validar_senha(password, User(username=email, first_name=full_name, email=email))

    email = email.strip().lower()
    if Person.objects.filter(program=program, primary_email=email).exists():
        audit.record(
            "academic.isolated.signup",
            request=request,
            program=program,
            email=email,
            created=False,
        )
        return False

    person = create_person_with_user(
        program=program,
        full_name=full_name,
        email=email,
        phone_number=phone_number,
        request=request,
    )
    user = person.user
    # create_person_with_user sempre garante a conta; o None é só o caso de
    # registro histórico, que não passa por aqui.
    assert user is not None

    # Conta que já existe com senha utilizável é de alguém que se cadastrou
    # em outro programa: definir a senha aqui seria tomar a conta dessa
    # pessoa. Ela entra no edital com a senha que já tem.
    if not user.has_usable_password():
        user.set_initial_password(password)
        user.save(update_fields=["password"])

    assign_role_group(user, group_name="Candidato", request=request)

    audit.record(
        "academic.isolated.signup",
        request=request,
        target=person,
        email=email,
        created=True,
    )
    return True
