"""Schemas da borda de autenticação.

Nunca serializar o model User direto: o contrato da API não pode mudar
porque uma coluna mudou (Seção 3 do CLAUDE.md).
"""

from ninja import Schema


class LoginIn(Schema):
    username: str
    password: str


class SetInitialPasswordIn(Schema):
    password: str


class DetailOut(Schema):
    """Resposta de operação que não devolve entidade."""

    detail: str


class PersonRefOut(Schema):
    """A pessoa do domínio, por programa, ligada à conta logada."""

    id: int
    program_id: int
    program_acronym: str
    full_name: str
    status: str


class UserOut(Schema):
    id: int
    username: str
    email: str
    full_name: str
    is_staff: bool
    permissions: list[str]
    # Papel de domínio é Group (Seção 5). Vem junto porque há tela cujo
    # público não se distingue por permissão: Secretaria, Coordenação,
    # Docente e Discente têm todos `view_enrollmentadjustmentrequest`, e o
    # que muda entre eles é o papel — o mesmo critério que o backend usa em
    # `EnrollmentAdjustmentRequestQuerySet.visible_to`.
    groups: list[str]
    # Sem isto o front sabe QUEM logou, mas não sabe QUAL pessoa do domínio
    # é essa conta — nem em quais programas ela atua. Lista porque o User é
    # global e a Person é por programa.
    people: list[PersonRefOut]
