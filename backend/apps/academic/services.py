"""Operações do app academic que cruzam mais de um model.

`create_teacher` existe aqui porque escreve em Person, User, Group, Teacher
e AuditLog na mesma transação (ADR-002). Operação que toca um model só
continua sendo chamada direto do router — não crie service "por simetria".

Quem escreve aqui chama `clean()` antes de `save()`: o Django não executa
`clean()` em `.save()`/`.create()`, só em formulário — sem essa chamada o
invariante de programa de Teacher e Student nunca roda no caminho real.
"""

from collections.abc import Sequence
from typing import Any

from django.db import transaction
from django.http import HttpRequest

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
