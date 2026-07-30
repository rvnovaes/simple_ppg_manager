"""Operações do app people que cruzam mais de um model.

Este arquivo só existe porque create_person_with_user escreve em três
models e precisa ser atômico (ADR-002). Operação que toca um model só é
chamada direto do router — não crie service "por simetria".
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpRequest

from apps.core import audit
from apps.programs.models import Program

from .models import Person

User = get_user_model()


@transaction.atomic
def create_person_with_user(
    *,
    program: Program,
    full_name: str,
    email: str,
    phone_number: str = "",
    request: HttpRequest | None = None,
) -> Person:
    """Cria a pessoa, garante uma conta de acesso e audita — tudo ou nada.

    A conta nasce sem senha utilizável: o acesso é liberado quando alguém
    define a senha (fluxo de convite fica para um módulo futuro).
    """
    # A conta vem primeiro: a Person nasce já apontando para ela, em vez de
    # ficarem ligadas só por coincidência de e-mail.
    user, created = User.objects.get_or_create(
        username=email,
        defaults={"email": email, "first_name": full_name[:150]},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])

    person = Person.objects.create(
        program=program,
        user=user,
        full_name=full_name,
        primary_email=email,
        phone_number=phone_number,
    )

    audit.record(
        "people.create",
        request=request,
        target=person,
        full_name=full_name,
        email=email,
        user_created=created,
    )
    return person
