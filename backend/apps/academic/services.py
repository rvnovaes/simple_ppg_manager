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
from apps.programs.models import CollectiveProject, Program, ResearchLine

from .models import Teacher


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
