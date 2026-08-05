"""Contrato HTTP do app programs.

Schemas explícitos de entrada e saída. Serializar o model direto faria o
contrato da API mudar por acidente quando uma coluna mudasse.
"""

import datetime

from ninja import Schema

from .models import AcademicTerm


class ProgramOut(Schema):
    id: int
    name: str
    acronym: str
    is_active: bool


class ResearchLineIn(Schema):
    # Sem program_id: o programa da linha é o da requisição
    # (current_program), nunca o que o chamador escolher no corpo.
    name: str
    is_active: bool = True


class ResearchLinePatch(Schema):
    """Atualização parcial: só os campos presentes no corpo são aplicados."""

    name: str | None = None
    is_active: bool | None = None


class ResearchLineOut(Schema):
    id: int
    program_id: int
    name: str
    is_active: bool


class CollectiveProjectIn(Schema):
    # Sem program_id, pelo mesmo motivo de ResearchLineIn. A linha de
    # pesquisa, essa sim, o chamador escolhe — mas só entre as do próprio
    # programa (o invariante mora em CollectiveProject.clean).
    research_line_id: int
    name: str
    is_active: bool = True


class CollectiveProjectPatch(Schema):
    """Atualização parcial: só os campos presentes no corpo são aplicados."""

    research_line_id: int | None = None
    name: str | None = None
    is_active: bool | None = None


class CollectiveProjectOut(Schema):
    id: int
    program_id: int
    research_line_id: int
    name: str
    is_active: bool


class DisciplineIn(Schema):
    # Sem program_id, pelo mesmo motivo de ResearchLineIn: o programa da
    # disciplina é o da requisição (current_program).
    code: str
    name: str
    is_active: bool = True


class DisciplinePatch(Schema):
    """Atualização parcial: só os campos presentes no corpo são aplicados."""

    code: str | None = None
    name: str | None = None
    is_active: bool | None = None


class DisciplineOut(Schema):
    id: int
    program_id: int
    code: str
    name: str
    is_active: bool


class AcademicTermIn(Schema):
    # Sem program_id, e não por omissão: período letivo é institucional
    # (ADR-007 dec. 4), não pertence a programa nenhum.
    # half tipado com a IntegerChoices do model para que semestre 3 seja
    # 422 na borda, e não uma linha inválida no banco.
    year: int
    half: AcademicTerm.Half
    starts_on: datetime.date
    ends_on: datetime.date
    is_active: bool = True


class AcademicTermPatch(Schema):
    """Atualização parcial: só os campos presentes no corpo são aplicados."""

    year: int | None = None
    half: AcademicTerm.Half | None = None
    starts_on: datetime.date | None = None
    ends_on: datetime.date | None = None
    is_active: bool | None = None


class AcademicTermOut(Schema):
    id: int
    year: int
    half: int
    starts_on: datetime.date
    ends_on: datetime.date
    is_active: bool
    # Rótulo canônico '2026/1'. Vai no contrato para que nenhuma tela
    # remonte a string por conta própria (ADR-007 dec. 4).
    label: str

    @staticmethod
    def resolve_label(obj: AcademicTerm) -> str:
        return str(obj)
