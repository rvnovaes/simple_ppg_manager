"""Contrato HTTP do app programs.

Schemas explícitos de entrada e saída. Serializar o model direto faria o
contrato da API mudar por acidente quando uma coluna mudasse.
"""

from ninja import Schema


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
