"""Borda HTTP do app people.

Padrão de toda rota: require_perm na primeira linha, chamada ao
model/service, schema de saída explícito. Zero regra de negócio aqui.
"""

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Status
from ninja.pagination import paginate

from apps.core import audit
from apps.core.permissions import require_perm
from apps.core.tenancy import current_program
from apps.programs.models import Program

from .models import Person
from .schemas import PersonIn, PersonOut
from .services import create_person_with_user

router = Router(tags=["people"])


@router.get("/", response=list[PersonOut])
@paginate
def list_people(request: HttpRequest, email: str | None = None):
    require_perm(request, "people.view_person")
    # O escopo é o programa da requisição, nunca um filtro que o chamador
    # escolhe: program_id como filtro livre deixava vazar pessoa de outro
    # tenant para quem simplesmente omitisse o parâmetro.
    pessoas = Person.objects.for_program(current_program(request))
    if email is not None:
        # A tela procura por aqui antes de tentar criar uma pessoa nova:
        # sem isso ela bate na UniqueConstraint (program, primary_email) e
        # o usuário vê um erro em vez do cadastro que já existe.
        pessoas = pessoas.filter(primary_email__iexact=email)
    return pessoas


@router.post("/", response={201: PersonOut})
def create_person(request: HttpRequest, payload: PersonIn):
    require_perm(request, "people.add_person")
    program = get_object_or_404(Program, pk=payload.program_id)
    person = create_person_with_user(
        program=program,
        full_name=payload.full_name,
        email=payload.primary_email,
        phone_number=payload.phone_number,
        request=request,
    )
    return Status(201, person)


@router.post("/{int:person_id}/archive", response=PersonOut)
def archive_person(request: HttpRequest, person_id: int):
    require_perm(request, "people.change_person")
    person = get_object_or_404(Person, pk=person_id)
    with transaction.atomic():
        # A regra mora no model; aqui só persistimos e auditamos.
        person.archive()
        person.save(update_fields=["status", "updated_at"])
        audit.record("people.archive", request=request, target=person)
    return person
