"""Contrato HTTP do app people.

Schemas explícitos de entrada e saída. Serializar o model direto faria o
contrato da API mudar por acidente quando uma coluna mudasse.
"""

from datetime import datetime

from ninja import Schema
from pydantic import EmailStr


class PersonIn(Schema):
    program_id: int
    full_name: str
    primary_email: EmailStr
    phone_number: str = ""


class PersonOut(Schema):
    id: int
    program_id: int
    # Nulo quando a pessoa não tem conta de acesso (egresso, registro
    # histórico, quem nunca vai logar).
    user_id: int | None
    full_name: str
    primary_email: str
    phone_number: str
    status: str
    created_at: datetime
