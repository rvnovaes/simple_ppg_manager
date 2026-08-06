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
    MAX_ISOLATED_ITEMS,
    DisciplineOffering,
    EnrollmentAdjustmentItem,
    EnrollmentAdjustmentRequest,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
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


class EnrollmentAdjustmentApproveIn(Schema):
    """Aprovação: a nota é opcional — quem aprova não deve satisfação."""

    note: str = ""


class EnrollmentAdjustmentRejectIn(Schema):
    """Recusa: o motivo é o que o aluno lê para saber o que corrigir.

    A obrigatoriedade real é do model (`reject` levanta
    `rejection_requires_note`): aqui o campo é exigido na borda, mas
    string em branco só é barrada lá, com `code` estável.
    """

    note: str


class EnrollmentAdjustmentRequestOut(Schema):
    id: int
    program_id: int
    student_id: int
    # O nome vem junto pelo mesmo motivo do código da disciplina: a tela da
    # secretaria lista acerto de vários alunos e não deve buscar cada um.
    student_name: str
    # Quem decide o acerto. Nulo só no aluno sem orientador, que hoje nem
    # consegue abrir solicitação (advisor_required) — mas o vínculo pode ser
    # desfeito depois, e a tela da secretaria não deve quebrar por isso.
    advisor_name: str | None
    term_id: int
    status: str
    justification: str
    decision_note: str
    decided_at: datetime.datetime | None
    created_at: datetime.datetime
    items: list[EnrollmentAdjustmentItemOut]

    @staticmethod
    def resolve_student_name(obj: EnrollmentAdjustmentRequest) -> str:
        return obj.student.person.full_name

    @staticmethod
    def resolve_advisor_name(obj: EnrollmentAdjustmentRequest) -> str | None:
        advisor = obj.student.advisor
        return advisor.person.full_name if advisor is not None else None

    @staticmethod
    def resolve_items(
        obj: EnrollmentAdjustmentRequest,
    ) -> list[EnrollmentAdjustmentItem]:
        return list(obj.items.all())


class DisciplineOfferingOut(Schema):
    """Uma disciplina oferecida no edital, como o candidato a vê.

    `seats_available` vem calculado do servidor: a tela não tem como
    somar deferidos e matriculados, e deixar a conta para ela seria
    espalhar a regra das vagas (Seção 12).
    """

    id: int
    program_id: int
    cycle_id: int
    discipline_id: int
    # Código e nome viajam junto para a tela não precisar de uma segunda
    # chamada ao catálogo por oferta.
    discipline_code: str
    discipline_name: str
    teacher_id: int
    teacher_name: str
    seats: int
    seats_available: int

    @staticmethod
    def resolve_discipline_code(obj: DisciplineOffering) -> str:
        return obj.discipline.code

    @staticmethod
    def resolve_discipline_name(obj: DisciplineOffering) -> str:
        return obj.discipline.name

    @staticmethod
    def resolve_teacher_name(obj: DisciplineOffering) -> str:
        return obj.teacher.person.full_name

    @staticmethod
    def resolve_seats_available(obj: DisciplineOffering) -> int:
        return obj.seats_available()


class IsolatedItemIn(Schema):
    """Uma disciplina escolhida pelo candidato, pela oferta do ciclo."""

    offering_id: int


class IsolatedItemOut(Schema):
    id: int
    offering_id: int
    discipline_code: str
    discipline_name: str
    # Nulo até o docente classificar (US-011). Nulo não é zero nem último.
    rank: int | None

    @staticmethod
    def resolve_discipline_code(obj: IsolatedEnrollmentItem) -> str:
        return obj.offering.discipline.code

    @staticmethod
    def resolve_discipline_name(obj: IsolatedEnrollmentItem) -> str:
        return obj.offering.discipline.name


def _itens_validos(itens: list[IsolatedItemIn]) -> list[IsolatedItemIn]:
    """Repetição e excesso são 422 na borda.

    A repetição já é barrada pela UniqueConstraint
    `unique_item_por_requerimento_e_oferta` e o excesso por `submit()`,
    mas o primeiro viraria IntegrityError 500 e o segundo só apareceria
    na hora de enviar, depois de o candidato ter escolhido três.
    """
    ids = [item.offering_id for item in itens]
    if len(set(ids)) != len(ids):
        raise ValueError("A mesma disciplina aparece duas vezes.")
    if len(ids) > MAX_ISOLATED_ITEMS:
        raise ValueError(f"Escolha no máximo {MAX_ISOLATED_ITEMS} disciplinas.")
    return itens


class IsolatedRequestIn(Schema):
    """Abertura do requerimento de isolada, sempre em rascunho.

    Sem `program_id` nem `cycle_id`: o programa é o da requisição
    (`current_program`) e o ciclo é o que está com inscrição aberta —
    escolher o ciclo livremente seria inscrever-se em edital encerrado.
    `person_id` é opcional e existe só para a tela ser explícita; a
    pessoa vem sempre da sessão, e informar a de outra é 403.

    A lista de disciplinas pode vir vazia: rascunho é rascunho, e é
    `submit()` que exige de uma a duas.
    """

    person_id: int | None = None
    is_ufmg_staff: bool = False
    items: list[IsolatedItemIn] = []

    @model_validator(mode="after")
    def itens_validos(self) -> "IsolatedRequestIn":
        _itens_validos(self.items)
        return self


class IsolatedRequestPatch(Schema):
    """Alteração do rascunho: só o que o candidato escolheu.

    Situação, pagamento e decisão não estão aqui de propósito — cada um
    deles é um ato de outra pessoa, com endpoint próprio (US-011 a
    US-014). `items` ausente mantém as disciplinas; `items: []` apaga
    todas, que é o jeito de o candidato recomeçar a escolha.
    """

    is_ufmg_staff: bool | None = None
    items: list[IsolatedItemIn] | None = None

    @model_validator(mode="after")
    def itens_validos(self) -> "IsolatedRequestPatch":
        if self.items is not None:
            _itens_validos(self.items)
        return self


class IsolatedRequestOut(Schema):
    id: int
    program_id: int
    cycle_id: int
    person_id: int
    # O nome vem junto pela mesma razão do código da disciplina: a fila da
    # secretaria lista muitos candidatos e não deve buscar cada um.
    person_name: str
    status: str
    payment_status: str
    is_ufmg_staff: bool
    gru_url: str
    decision_note: str
    decided_at: datetime.datetime | None
    appeal_note: str
    appealed_at: datetime.datetime | None
    submitted_at: datetime.datetime | None
    created_at: datetime.datetime
    items: list[IsolatedItemOut]
    # O que ainda falta anexar, na ordem do edital: sem isto a tela do
    # candidato só descobriria a pendência no 400 do envio.
    missing_documents: list[str]

    @staticmethod
    def resolve_person_name(obj: IsolatedEnrollmentRequest) -> str:
        return obj.person.full_name

    @staticmethod
    def resolve_items(obj: IsolatedEnrollmentRequest) -> list[IsolatedEnrollmentItem]:
        return list(obj.items.all())

    @staticmethod
    def resolve_missing_documents(obj: IsolatedEnrollmentRequest) -> list[str]:
        return obj.missing_documents()


class IsolatedSignupIn(Schema):
    """Auto-registro do candidato a disciplina isolada.

    Não tem `program_id` obrigatório pela mesma razão dos demais schemas de
    entrada — o tenant não é escolha livre de quem chama. Aqui não há
    sessão de onde tirá-lo, então ele sai do ciclo com inscrições abertas;
    o campo só existe (opcional) para desempatar quando mais de um programa
    está com edital aberto no mesmo instante.
    """

    full_name: str
    email: EmailStr
    phone_number: str = ""
    password: str
    program_id: int | None = None


class IsolatedSignupOut(Schema):
    """Resposta única do auto-registro.

    Corpo fixo de propósito: e-mail novo e e-mail já cadastrado respondem
    exatamente isto, senão a rota vira um oráculo de quem tem conta.
    """

    detail: str
