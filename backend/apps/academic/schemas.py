"""Contrato HTTP do app academic.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md). Serializar o
model direto faria o contrato mudar por acidente quando uma coluna mudasse
— vale também para a `Person` embutida em `TeacherOut`, que aparece aqui
reduzida ao que a tela precisa mostrar.
"""

import datetime

from ninja import Schema
from pydantic import EmailStr, model_validator

from apps.people.models import Person

from .models import (
    EnrollmentAdjustmentItem,
    EnrollmentAdjustmentRequest,
    Student,
    Teacher,
)


class PersonBrief(Schema):
    """Pessoa por trás do vínculo, no mínimo que a tela exibe."""

    id: int
    full_name: str
    primary_email: str
    phone_number: str
    # Nulo quando a pessoa não tem conta de acesso.
    user_id: int | None
    # A tela da Secretaria só oferece "definir senha inicial" enquanto a
    # conta não tiver senha (US-007). Sem este campo ela teria de adivinhar
    # — ou pior, oferecer a ação para quem já usa o sistema.
    needs_initial_password: bool

    @staticmethod
    def resolve_needs_initial_password(obj: Person) -> bool:
        user = obj.user
        return user is not None and not user.has_usable_password()


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


# Campos que só existem no vínculo regular: a isolada e a eletiva duram um
# semestre e por isso a CheckConstraint student_non_regular_requires_term
# exige que todos venham nulos. Aqui eles são recusados na borda, com 422,
# em vez de virarem IntegrityError 500 lá no INSERT.
CAMPOS_DE_GRAU = (
    "level",
    "project_id",
    "advisor_id",
    "admission_date",
    "deadline",
    "defense_date",
)


class StudentIn(Schema):
    """Criação de aluno.

    Como em `TeacherIn`, o payload traz OU `person_id` OU os dados de uma
    pessoa nova. Os campos exigidos dependem da modalidade — é a mesma
    regra das CheckConstraint de `Student`, cobrada aqui na borda.
    """

    person_id: int | None = None
    full_name: str | None = None
    primary_email: EmailStr | None = None
    phone_number: str = ""

    modality: Student.Modality
    status: Student.Status = Student.Status.ACTIVE
    registration_number: str | None = None
    level: Student.Level | None = None
    project_id: int | None = None
    advisor_id: int | None = None
    admission_date: datetime.date | None = None
    # Opcional mesmo no regular: sem ele o model calcula o prazo
    # regimental a partir do ingresso (24 meses no mestrado, 48 no
    # doutorado).
    deadline: datetime.date | None = None
    defense_date: datetime.date | None = None
    term_id: int | None = None

    @model_validator(mode="after")
    def pessoa_existente_ou_nova(self) -> "StudentIn":
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

    @model_validator(mode="after")
    def campos_da_modalidade(self) -> "StudentIn":
        if self.modality == Student.Modality.REGULAR:
            faltando = [
                campo
                for campo in ("level", "project_id", "admission_date")
                if getattr(self, campo) is None
            ]
            if faltando:
                raise ValueError(
                    "Aluno regular exige " + ", ".join(sorted(faltando)) + "."
                )
            return self

        if self.term_id is None:
            raise ValueError("Aluno de isolada ou eletiva exige term_id.")
        sobrando = [
            campo for campo in CAMPOS_DE_GRAU if getattr(self, campo) is not None
        ]
        if sobrando:
            raise ValueError(
                "Aluno de isolada ou eletiva não aceita "
                + ", ".join(sorted(sobrando))
                + "."
            )
        if self.status == Student.Status.LEAVE:
            raise ValueError("Trancamento só se aplica ao aluno regular.")
        return self


class StudentPatch(Schema):
    """Atualização parcial: só os campos presentes no corpo são aplicados.

    A pessoa e a modalidade ficam de fora. Trocar a pessoa apagaria o
    histórico do vínculo; trocar a modalidade transformaria uma isolada em
    regular por edição de campo, quando o que existe no domínio é um
    vínculo novo.
    """

    status: Student.Status | None = None
    registration_number: str | None = None
    level: Student.Level | None = None
    project_id: int | None = None
    advisor_id: int | None = None
    admission_date: datetime.date | None = None
    deadline: datetime.date | None = None
    defense_date: datetime.date | None = None
    term_id: int | None = None


class StudentOut(Schema):
    id: int
    program_id: int
    person: PersonBrief
    registration_number: str | None
    # Modalidade e situação são campos separados (ADR-007 dec. 1): a tela
    # nunca precisa quebrar string para saber se o regular está trancado.
    modality: str
    status: str
    level: str | None
    project_id: int | None
    advisor_id: int | None
    admission_date: datetime.date | None
    deadline: datetime.date | None
    defense_date: datetime.date | None
    term_id: int | None
    created_at: datetime.datetime


class EnrollmentAdjustmentItemIn(Schema):
    """Uma mudança pedida: incluir ou excluir uma disciplina."""

    discipline_id: int
    action: EnrollmentAdjustmentItem.Action


class EnrollmentAdjustmentItemOut(Schema):
    id: int
    discipline_id: int
    # O código e o nome vêm junto para a tela do aluno e a da secretaria
    # não precisarem de uma segunda chamada ao catálogo por item.
    discipline_code: str
    discipline_name: str
    action: str

    @staticmethod
    def resolve_discipline_code(obj: EnrollmentAdjustmentItem) -> str:
        return obj.discipline.code

    @staticmethod
    def resolve_discipline_name(obj: EnrollmentAdjustmentItem) -> str:
        return obj.discipline.name


class EnrollmentAdjustmentRequestIn(Schema):
    """Abertura de um acerto de matrícula.

    Sem `program_id`: o programa é o da requisição (current_program).
    `student_id` é opcional e existe só para a tela ser explícita — o
    aluno vem sempre da sessão, e informar o de outra pessoa é 403.
    """

    student_id: int | None = None
    term_id: int
    justification: str = ""
    items: list[EnrollmentAdjustmentItemIn]

    @model_validator(mode="after")
    def itens_validos(self) -> "EnrollmentAdjustmentRequestIn":
        """Lista vazia e item repetido são 422 na borda.

        A repetição já é barrada pela UniqueConstraint
        `unique_item_por_solicitacao`, mas lá viraria IntegrityError 500 —
        aqui vira erro de validação com a lista do que veio duplicado.
        """
        if not self.items:
            raise ValueError("Informe ao menos uma disciplina.")
        pares = [(item.discipline_id, item.action) for item in self.items]
        if len(set(pares)) != len(pares):
            raise ValueError("A mesma disciplina aparece duas vezes com a mesma ação.")
        return self


class EnrollmentAdjustmentRequestOut(Schema):
    id: int
    program_id: int
    student_id: int
    term_id: int
    status: str
    justification: str
    decision_note: str
    decided_at: datetime.datetime | None
    created_at: datetime.datetime
    items: list[EnrollmentAdjustmentItemOut]

    @staticmethod
    def resolve_items(
        obj: EnrollmentAdjustmentRequest,
    ) -> list[EnrollmentAdjustmentItem]:
        return list(obj.items.all())
