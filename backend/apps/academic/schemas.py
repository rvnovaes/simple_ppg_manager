"""Contrato HTTP do app academic.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md). Serializar o
model direto faria o contrato mudar por acidente quando uma coluna mudasse
— vale também para a `Person` embutida em `TeacherOut`, que aparece aqui
reduzida ao que a tela precisa mostrar.
"""

import datetime
from pathlib import Path

from django.utils import timezone
from ninja import Schema
from pydantic import EmailStr, HttpUrl, model_validator

from apps.people.models import Person

from .models import (
    MAX_ISOLATED_ITEMS,
    AccessProfile,
    AccessRequest,
    DisciplineOffering,
    EnrollmentAdjustmentItem,
    EnrollmentAdjustmentRequest,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
    RequestDocument,
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


class TeacherDeaccreditIn(Schema):
    """Data do descredenciamento. Vazia significa hoje.

    Existe como corpo, e não como parâmetro na URL, porque descredenciar
    com data retroativa é rotina: a portaria sai depois do fato.
    """

    on: datetime.date | None = None


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
    # Nomes resolvidos ao lado dos ids: sem eles toda tela que mostra um
    # aluno teria de buscar professores, projetos e períodos só para
    # traduzir três números.
    advisor_name: str | None
    project_name: str | None
    term_label: str | None
    created_at: datetime.datetime

    @staticmethod
    def resolve_advisor_name(obj: Student) -> str | None:
        # `advisor` é FK anulável: o mypy não deduz do `advisor_id` que ela
        # está preenchida, então a checagem é no próprio objeto.
        return obj.advisor.person.full_name if obj.advisor else None

    @staticmethod
    def resolve_project_name(obj: Student) -> str | None:
        return obj.project.name if obj.project else None

    @staticmethod
    def resolve_term_label(obj: Student) -> str | None:
        # str(AcademicTerm) é o rótulo canônico "2026/1" (ADR-007 dec. 4);
        # ninguém remonta essa string por conta própria.
        return str(obj.term) if obj.term else None


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


class DisciplineOfferingIn(Schema):
    """Uma disciplina posta no edital, com responsável e vagas.

    Sem `program_id`: o tenant é o da requisição. `cycle_id` viaja porque
    a secretaria monta o edital do semestre que ela escolheu na tela — e
    não necessariamente o que está com inscrição aberta agora.
    """

    cycle_id: int
    discipline_id: int
    teacher_id: int
    seats: int


class DisciplineOfferingPatch(Schema):
    """Atualização parcial: o ciclo não muda.

    Trocar a oferta de edital reescreveria a história de quem já se
    inscreveu nela; o caminho é apagar (quebra-vidro no Admin) e cadastrar
    de novo no ciclo certo.
    """

    discipline_id: int | None = None
    teacher_id: int | None = None
    seats: int | None = None


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
    # Marcador da lista do docente (`?mine=true`): ele precisa ver de
    # relance onde ainda falta responder. Calculado no servidor pela mesma
    # razão de `seats_available` — a tela não conta inscritos sem posição.
    needs_ranking: bool

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

    @staticmethod
    def resolve_needs_ranking(obj: DisciplineOffering) -> bool:
        return obj.needs_ranking()


class IsolatedCandidateOut(Schema):
    """Um inscrito na oferta, como o docente responsável o vê.

    Só o necessário para ordenar: nome, quando se inscreveu e a posição
    atual. Documentação e situação de pagamento são da análise da
    secretaria (US-012) e não entram aqui — o docente classifica por
    mérito, não por pendência administrativa.
    """

    item_id: int
    request_id: int
    person_id: int
    person_name: str
    rank: int | None
    submitted_at: datetime.datetime | None

    @staticmethod
    def resolve_item_id(obj: IsolatedEnrollmentItem) -> int:
        return obj.pk

    @staticmethod
    def resolve_person_id(obj: IsolatedEnrollmentItem) -> int:
        return obj.request.person_id

    @staticmethod
    def resolve_person_name(obj: IsolatedEnrollmentItem) -> str:
        return obj.request.person.full_name

    @staticmethod
    def resolve_submitted_at(obj: IsolatedEnrollmentItem) -> datetime.datetime | None:
        return obj.request.submitted_at


class IsolatedRankIn(Schema):
    """A ordem escolhida pelo docente, do primeiro ao último.

    A posição não viaja no corpo: ela É o índice da lista, e mandar
    `rank` explícito abriria a porta para buraco (1, 2, 4) e empate.
    Lista vazia zera a classificação da oferta — é como o docente
    recomeça, igual ao `items: []` do rascunho do candidato.
    """

    item_ids: list[int] = []

    @model_validator(mode="after")
    def sem_repeticao(self) -> "IsolatedRankIn":
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("O mesmo candidato aparece duas vezes na ordem.")
        return self


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


class IsolatedDeferIn(Schema):
    """Deferimento: a nota é opcional, o link da GRU é o que vem junto.

    O sistema não emite a guia — ela vem do sistema de arrecadação da
    UFMG e a secretaria cola o link aqui, no mesmo ato em que defere.
    `HttpUrl` cobra a forma na borda (422); o servidor da UFMG é isento e
    para ele o campo fica vazio.
    """

    note: str = ""
    gru_url: HttpUrl | None = None


class IsolatedRejectIn(Schema):
    """Indeferimento: o motivo é o que o candidato contesta no recurso.

    A obrigatoriedade real é do model (`reject` levanta
    `rejection_requires_note`): aqui o campo é exigido na borda, mas
    string em branco só é barrada lá, com `code` estável.
    """

    note: str


class IsolatedCancelIn(Schema):
    """Cancelamento: a nota é opcional porque o cancelamento tem dois
    motivos legítimos e só um deles é decisão da secretaria — o candidato
    que desistiu e o deferido que não pagou a GRU no prazo.
    """

    note: str = ""


class IsolatedEnrollIn(Schema):
    """Efetivação: só a matrícula, digitada pela secretaria.

    O número vem do sistema da UFMG — este sistema não o emite, apenas o
    guarda. Como em `IsolatedRejectIn`, o campo é exigido aqui e a string
    em branco é barrada no service, com `code` estável; a unicidade é do
    banco e sai pelo mesmo caminho.
    """

    registration_number: str


class IsolatedCycleIn(Schema):
    """O calendário do edital, digitado pela secretaria.

    Sem `program_id`: o programa é o da requisição (`current_program`).
    `is_active` não entra — o ciclo nasce ativo e só sai do ar pelo
    encerramento, que é ato explícito com contagem de vínculos fechados
    (`POST /isolated/cycles/{id}/close`). Um `is_active=false` no
    formulário desligaria o edital sem excluir aluno nenhum.
    """

    term_id: int
    submission_opens_at: datetime.datetime
    submission_closes_at: datetime.datetime
    result_published_on: datetime.date
    appeal_opens_at: datetime.datetime
    appeal_closes_at: datetime.datetime
    final_result_on: datetime.date
    payment_closes_at: datetime.datetime


class IsolatedCyclePatch(Schema):
    """Atualização parcial: só os campos presentes no corpo são aplicados."""

    term_id: int | None = None
    submission_opens_at: datetime.datetime | None = None
    submission_closes_at: datetime.datetime | None = None
    result_published_on: datetime.date | None = None
    appeal_opens_at: datetime.datetime | None = None
    appeal_closes_at: datetime.datetime | None = None
    final_result_on: datetime.date | None = None
    payment_closes_at: datetime.datetime | None = None


class IsolatedCycleOut(Schema):
    """O edital do semestre, como a secretaria e a coordenação o veem.

    O calendário inteiro viaja porque a tela de análise (US-019) precisa
    dizer em que fase o edital está — e `submission_open` vem resolvido do
    servidor pela mesma razão de `IsolatedRequestOut`: comparar a data no
    navegador deixaria a fase depender do relógio de quem acessa.
    """

    id: int
    program_id: int
    term_id: int
    # Rótulo canônico '2026/1', igual ao de `AcademicTermOut`: nenhuma
    # tela remonta a string do semestre por conta própria (ADR-007 dec. 4).
    term_label: str
    submission_opens_at: datetime.datetime
    submission_closes_at: datetime.datetime
    result_published_on: datetime.date
    appeal_opens_at: datetime.datetime
    appeal_closes_at: datetime.datetime
    final_result_on: datetime.date
    payment_closes_at: datetime.datetime
    is_active: bool
    submission_open: bool
    # Quantos alunos o encerramento excluiria agora: a confirmação da
    # secretaria precisa do número ANTES de executar, e a tela não conta
    # vínculo por conta própria (Seção 12).
    students_to_exclude: int

    @staticmethod
    def resolve_students_to_exclude(obj: IsolatedEnrollmentCycle) -> int:
        return obj.students_to_exclude()

    @staticmethod
    def resolve_term_label(obj: IsolatedEnrollmentCycle) -> str:
        return str(obj.term)

    @staticmethod
    def resolve_submission_open(obj: IsolatedEnrollmentCycle) -> bool:
        return obj.submission_open(timezone.now())


class IsolatedCycleCloseOut(Schema):
    """Recibo do encerramento do edital.

    A contagem volta para a tela porque encerrar é irreversível pelo
    caminho normal: a secretaria precisa ver quantos vínculos a ação
    fechou, e é o mesmo número que ficou no AuditLog.
    """

    cycle_id: int
    is_active: bool
    students_excluded: int


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
    # As janelas do edital viajam com o requerimento porque o Candidato não
    # tem permissão sobre o ciclo (`academic.0011`) e a tela de
    # acompanhamento precisa mostrar o prazo antes de oferecer o controle.
    appeal_opens_at: datetime.datetime
    appeal_closes_at: datetime.datetime
    payment_closes_at: datetime.datetime
    # Aberto AGORA, decidido pelo relógio do servidor: comparar a data no
    # navegador deixaria o prazo depender do relógio de quem acessa.
    appeal_open: bool
    payment_open: bool

    @staticmethod
    def resolve_person_name(obj: IsolatedEnrollmentRequest) -> str:
        return obj.person.full_name

    @staticmethod
    def resolve_appeal_opens_at(obj: IsolatedEnrollmentRequest) -> datetime.datetime:
        return obj.cycle.appeal_opens_at

    @staticmethod
    def resolve_appeal_closes_at(obj: IsolatedEnrollmentRequest) -> datetime.datetime:
        return obj.cycle.appeal_closes_at

    @staticmethod
    def resolve_payment_closes_at(obj: IsolatedEnrollmentRequest) -> datetime.datetime:
        return obj.cycle.payment_closes_at

    @staticmethod
    def resolve_appeal_open(obj: IsolatedEnrollmentRequest) -> bool:
        return obj.cycle.appeal_open(timezone.now())

    @staticmethod
    def resolve_payment_open(obj: IsolatedEnrollmentRequest) -> bool:
        return obj.cycle.payment_open(timezone.now())

    @staticmethod
    def resolve_items(obj: IsolatedEnrollmentRequest) -> list[IsolatedEnrollmentItem]:
        return list(obj.items.all())

    @staticmethod
    def resolve_missing_documents(obj: IsolatedEnrollmentRequest) -> list[str]:
        return obj.missing_documents()


class RequestDocumentOut(Schema):
    """Um anexo, sem o caminho do arquivo.

    Nem `file` nem `file.url` entram aqui de propósito: MEDIA é servido
    pelo Nginx sem passar pelo Django, então publicar a URL entregaria a
    identidade do candidato a quem descobrisse o endereço — e sem
    AuditLog. O único caminho para o conteúdo é o endpoint de download,
    que checa posse ou permissão e registra o acesso.
    """

    id: int
    kind: str
    kind_label: str
    filename: str
    size: int
    uploaded_at: datetime.datetime

    @staticmethod
    def resolve_kind_label(obj: RequestDocument) -> str:
        return obj.get_kind_display()

    @staticmethod
    def resolve_filename(obj: RequestDocument) -> str:
        """Só o nome, sem o caminho: o diretório é detalhe do storage e
        expõe o id do ciclo e do requerimento sem necessidade.
        """
        return Path(obj.file.name or "").name

    @staticmethod
    def resolve_size(obj: RequestDocument) -> int:
        """Arquivo sumido do storage vale 0, e não erro 500: a listagem da
        secretaria precisa continuar mostrando que o anexo existe para ela
        poder pedir o reenvio.
        """
        try:
            return obj.file.size
        except (FileNotFoundError, ValueError):
            return 0


class AccessSignupIn(Schema):
    """Autocadastro de quem ainda não tem acesso ao programa.

    `program_id` é OBRIGATÓRIO e continua não sendo escolha livre: ele só
    vale para programa com `accepts_self_signup` ligado, e é a lista
    pública (`GET /api/v1/programs/public`) que alimenta o campo na tela.
    A trava mudou de lugar — saiu do edital aberto e virou interruptor do
    programa —, não sumiu.

    Os quatro campos de docente são declaração da própria pessoa; a
    secretaria confere na aprovação. Categoria e titulação são cobrados
    aqui na borda porque no model são só CheckConstraint: sem este
    validador, docente sem eles viraria IntegrityError (500) em vez de 422.
    """

    program_id: int
    profile: AccessProfile
    full_name: str
    email: EmailStr
    phone_number: str = ""
    password: str
    # Só o docente preenche; o service zera estes campos nos demais perfis.
    teacher_category: Teacher.Category | None = None
    academic_degree: Teacher.AcademicDegree | None = None
    home_institution: str = ""
    lattes_url: str = ""

    @model_validator(mode="after")
    def campos_do_perfil(self) -> "AccessSignupIn":
        if self.profile != AccessProfile.TEACHER:
            return self
        faltando = [
            campo
            for campo in ("teacher_category", "academic_degree")
            if getattr(self, campo) is None
        ]
        if faltando:
            raise ValueError("Docente exige " + ", ".join(sorted(faltando)) + ".")
        if (
            self.teacher_category == Teacher.Category.EXTERNAL
            and not self.home_institution.strip()
        ):
            raise ValueError("Colaborador externo exige home_institution.")
        return self


class AccessSignupOut(Schema):
    """Resposta do autocadastro, que varia por PERFIL — nunca por conta.

    E-mail inédito e e-mail já cadastrado respondem exatamente a mesma
    coisa, senão a rota vira um oráculo de quem tem conta neste programa.
    O que muda é o perfil declarado: o candidato já pode entrar, enquanto
    docente e discente esperam o deferimento da secretaria, e é isso que
    `requires_confirmation` diz à tela.
    """

    detail: str
    requires_confirmation: bool


class AccessStatusOut(Schema):
    """Estado do próprio cadastro, para a tela de espera.

    É o único schema do app lido por quem ainda não tem permissão
    nenhuma, e por isso carrega tudo que a tela precisa mostrar sem uma
    segunda chamada: quem não é pendente não consegue ler `/programs/` nem
    `/people/` para completar a informação.

    Os rótulos viajam prontos (`profile_label`, `status_label`) pelo mesmo
    motivo de `RequestDocumentOut.kind_label`: traduzir choice no front
    duplicaria a tabela de valores em outro idioma de programação.
    """

    id: int
    program_id: int
    # A pessoa pode ter se cadastrado em mais de um programa; a tela diz de
    # qual solicitação está falando.
    program_name: str
    profile: str
    profile_label: str
    status: str
    status_label: str
    # O motivo da recusa é o texto que a pessoa lê na tela dela.
    decision_note: str
    decided_at: datetime.datetime | None
    created_at: datetime.datetime

    @staticmethod
    def resolve_program_name(obj: AccessRequest) -> str:
        return obj.program.name

    @staticmethod
    def resolve_profile_label(obj: AccessRequest) -> str:
        return obj.get_profile_display()

    @staticmethod
    def resolve_status_label(obj: AccessRequest) -> str:
        return obj.get_status_display()


class AccessRequestOut(Schema):
    """Uma solicitação na fila da secretaria.

    Carrega o DECLARADO pela pessoa (perfil, categoria, titulação,
    instituição, Lattes) porque é isso que a secretaria confere antes de
    confirmar — sem estes campos a tela faria uma segunda chamada por
    linha só para saber o que está julgando.

    Sem rótulo pronto, ao contrário de `AccessStatusOut`: a fila é lida
    por quem tem permissão e já carrega `lib/acesso.ts`, que traduz as
    choices uma vez para as três telas do módulo.
    """

    id: int
    program_id: int
    person_id: int
    # Nome e e-mail viajam juntos pela razão de `IsolatedRequestOut`: a
    # fila lista muitos pedidos e não deve buscar cada pessoa.
    person_name: str
    person_email: str
    person_phone_number: str
    profile: str
    teacher_category: str
    academic_degree: str
    home_institution: str
    lattes_url: str
    status: str
    decision_note: str
    decided_at: datetime.datetime | None
    created_at: datetime.datetime

    @staticmethod
    def resolve_person_name(obj: AccessRequest) -> str:
        return obj.person.full_name

    @staticmethod
    def resolve_person_email(obj: AccessRequest) -> str:
        return obj.person.primary_email

    @staticmethod
    def resolve_person_phone_number(obj: AccessRequest) -> str:
        return obj.person.phone_number


class AccessApproveIn(Schema):
    """O que a SECRETARIA informa ao confirmar o cadastro.

    Todos os campos são opcionais na borda de propósito: quais deles são
    exigidos depende do `profile` da solicitação, que está no banco e não
    no corpo. Quem cobra é o domínio, com `code` estável —
    `accredited_since_required` no service para o docente e
    `incomplete_regular` no `Student.clean()` para o discente. Repetir a
    regra aqui criaria uma segunda verdade sobre o mesmo invariante.

    O que a pessoa declarou (categoria, titulação, instituição, Lattes)
    NÃO entra aqui: sai de `solicitacao.campos_do_professor()`.

    `deadline` também não: o `Student.save()` calcula o prazo regimental a
    partir do nível e do ingresso.
    """

    # Docente: a data do credenciamento é decisão de quem aprova.
    accredited_since: datetime.date | None = None
    # Discente regular: nível, projeto e ingresso são obrigatórios no
    # model; o orientador pode entrar depois.
    level: Student.Level | None = None
    project_id: int | None = None
    advisor_id: int | None = None
    admission_date: datetime.date | None = None


class AccessRejectIn(Schema):
    """Recusa: o motivo é o texto que a pessoa lê na tela de espera.

    Como em `IsolatedRejectIn`, a obrigatoriedade real é do model
    (`AccessRequest.reject` levanta `rejection_requires_note`): aqui o
    campo é exigido na borda, mas string em branco só é barrada lá, com
    `code` estável.
    """

    note: str
