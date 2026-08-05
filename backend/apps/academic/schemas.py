"""Contrato HTTP do app academic.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md). Serializar o
model direto faria o contrato mudar por acidente quando uma coluna mudasse
— vale também para a `Person` embutida em `TeacherOut`, que aparece aqui
reduzida ao que a tela precisa mostrar.
"""

import datetime

from ninja import Schema
from pydantic import EmailStr, model_validator

from .models import Teacher


class PersonBrief(Schema):
    """Pessoa por trás do vínculo, no mínimo que a tela exibe."""

    id: int
    full_name: str
    primary_email: str
    phone_number: str


class TeacherIn(Schema):
    """Criação de professor.

    O payload traz OU `person_id` (pessoa que já existe no programa) OU os
    dados de uma pessoa nova — nunca os dois. Sem `program_id`: o programa
    é o da requisição (current_program), nunca o que o chamador escolher.
    """

    person_id: int | None = None
    full_name: str | None = None
    primary_email: EmailStr | None = None
    phone_number: str = ""

    category: Teacher.Category
    accredited_since: datetime.date
    accredited_until: datetime.date | None = None
    academic_degree: Teacher.AcademicDegree
    lattes_url: str = ""
    home_institution: str = ""
    # Vínculos com a estrutura do programa. Vazio é válido: professor
    # recém-credenciado pode ainda não ter linha nem projeto.
    research_line_ids: list[int] = []
    project_ids: list[int] = []

    @model_validator(mode="after")
    def pessoa_existente_ou_nova(self) -> "TeacherIn":
        """Pessoa existente e pessoa nova são exclusivas entre si.

        Aceitar os dois deixaria ambíguo qual nome vale; aceitar nenhum
        criaria professor sem pessoa. Os dois casos são 422 na borda.
        """
        nova = self.full_name is not None or self.primary_email is not None
        if self.person_id is not None and nova:
            raise ValueError(
                "Informe person_id ou os dados de uma pessoa nova, não os dois."
            )
        if self.person_id is None and not nova:
            raise ValueError("Informe person_id ou os dados de uma pessoa nova.")
        if nova and not (self.full_name and self.primary_email):
            raise ValueError("Pessoa nova exige full_name e primary_email.")
        return self


class TeacherPatch(Schema):
    """Atualização parcial: só os campos presentes no corpo são aplicados.

    A pessoa não muda por aqui: trocar a pessoa de um vínculo docente é
    apagar o histórico de quem orientou quem, não editar um campo.
    """

    category: Teacher.Category | None = None
    accredited_since: datetime.date | None = None
    accredited_until: datetime.date | None = None
    academic_degree: Teacher.AcademicDegree | None = None
    lattes_url: str | None = None
    home_institution: str | None = None
    research_line_ids: list[int] | None = None
    project_ids: list[int] | None = None


class TeacherOut(Schema):
    id: int
    program_id: int
    person: PersonBrief
    category: str
    accredited_since: datetime.date
    accredited_until: datetime.date | None
    academic_degree: str
    lattes_url: str
    home_institution: str
    research_line_ids: list[int]
    project_ids: list[int]
    created_at: datetime.datetime

    @staticmethod
    def resolve_research_line_ids(obj: Teacher) -> list[int]:
        return list(obj.research_lines.values_list("id", flat=True))

    @staticmethod
    def resolve_project_ids(obj: Teacher) -> list[int]:
        return list(obj.projects.values_list("id", flat=True))
