"""Contrato HTTP do app scholarships.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md); nenhum model
é serializado direto. Preenchido pelas stories de API.
"""

import datetime
import decimal
from pathlib import Path

from ninja import Schema

from .models import (
    ApplicationDocument,
    ApplicationDocumentKind,
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    CommitteeMember,
    PriorityBand,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

# ---------------------------------------------------------------------------
# Edição do edital de bolsas
# ---------------------------------------------------------------------------


class ScholarshipEditionIn(Schema):
    """Abertura da edição do ano, digitada pela secretaria.

    Sem `program_id`: o programa é o da requisição (`current_program`),
    nunca o que o chamador escolher. Sem `status` também — a edição nasce
    em rascunho e só anda pelas cinco rotas de transição.

    As datas do cronograma são opcionais e todas nulas por padrão: elas são
    **informação publicada**, não gatilho (nada abre ou fecha por relógio),
    e no momento em que a secretaria abre a edição o calendário ainda está
    sendo fechado.
    """

    year: int
    title: str
    submission_starts_on: datetime.date | None = None
    submission_ends_on: datetime.date | None = None
    preliminary_result_on: datetime.date | None = None
    appeal_ends_on: datetime.date | None = None
    final_result_on: datetime.date | None = None


class ScholarshipEditionPatch(Schema):
    """Retificação da edição: só os campos presentes são aplicados.

    Vale em qualquer estado, de propósito. O que a edição publica de
    cronograma é texto informativo, e retificar data divulgada é o caso
    normal do edital — quem trava o que muda nota já dada é
    `bareme_editable()`, no barema, não aqui. O `year` continua defendido
    pelo `clean()` (`duplicate_edition`).
    """

    year: int | None = None
    title: str | None = None
    submission_starts_on: datetime.date | None = None
    submission_ends_on: datetime.date | None = None
    preliminary_result_on: datetime.date | None = None
    appeal_ends_on: datetime.date | None = None
    final_result_on: datetime.date | None = None


class ScholarshipEditionOut(Schema):
    """A edição como a tela da secretaria a vê.

    As cinco guardas de leitura do model viajam resolvidas: é o servidor
    que decide se o barema ainda é editável ou se o resultado já aparece
    para o discente, e a tela só desenha o que elas dizem. Repetir a
    máquina de estados no front seria a segunda porta que o CLAUDE.md
    proíbe.
    """

    id: int
    program_id: int
    year: int
    title: str
    status: ScholarshipEditionStatus
    status_label: str
    submission_starts_on: datetime.date | None
    submission_ends_on: datetime.date | None
    preliminary_result_on: datetime.date | None
    appeal_ends_on: datetime.date | None
    final_result_on: datetime.date | None
    # O PDF do edital é público por natureza (é o documento que convoca os
    # candidatos), então aqui a URL do MEDIA basta — ao contrário do anexo
    # da inscrição, que só sai pelo endpoint de download auditado.
    notice_filename: str
    notice_url: str
    bareme_editable: bool
    submission_open: bool
    committee_can_review: bool
    appeal_open: bool
    results_visible_to_student: bool
    published_preliminary_at: datetime.datetime | None
    published_final_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_status_label(obj: ScholarshipEdition) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_notice_filename(obj: ScholarshipEdition) -> str:
        """Só o nome do arquivo: o diretório é detalhe do storage."""
        return Path(obj.notice_file.name or "").name

    @staticmethod
    def resolve_notice_url(obj: ScholarshipEdition) -> str:
        return obj.notice_file.url if obj.notice_file else ""

    @staticmethod
    def resolve_bareme_editable(obj: ScholarshipEdition) -> bool:
        return obj.bareme_editable()

    @staticmethod
    def resolve_submission_open(obj: ScholarshipEdition) -> bool:
        return obj.submission_open()

    @staticmethod
    def resolve_committee_can_review(obj: ScholarshipEdition) -> bool:
        return obj.committee_can_review()

    @staticmethod
    def resolve_appeal_open(obj: ScholarshipEdition) -> bool:
        return obj.appeal_open()

    @staticmethod
    def resolve_results_visible_to_student(obj: ScholarshipEdition) -> bool:
        return obj.results_visible_to_student()


# ---------------------------------------------------------------------------
# Comissão de Bolsas
# ---------------------------------------------------------------------------


class CommitteeMemberIn(Schema):
    """Designação de um professor na comissão daquele ano.

    Sem `edition_id`: a edição vem da URL, já escopada no programa da
    sessão. `teacher_id` é conferido contra o programa na rota, e o
    `clean()` do model guarda o mesmo invariante para quem escrever fora
    dela.
    """

    teacher_id: int
    appointed_on: datetime.date | None = None
    ordinance: str = ""


class CommitteeMemberOut(Schema):
    """Um membro da comissão, com o nome já resolvido.

    A tela lista a composição do ano e não deve cruzar id de professor com
    nome. Nada aqui é autorização: quem avalia é quem está no Group
    "Comissão de Bolsas" (docstring de `CommitteeMember`).
    """

    id: int
    edition_id: int
    teacher_id: int
    teacher_name: str
    appointed_on: datetime.date | None
    ordinance: str
    created_at: datetime.datetime

    @staticmethod
    def resolve_teacher_name(obj: CommitteeMember) -> str:
        return obj.teacher.person.full_name


# ---------------------------------------------------------------------------
# Barema
# ---------------------------------------------------------------------------


class BaremeItemIn(Schema):
    """Uma linha do barema, digitada pela secretaria com a edição em
    rascunho.

    Sem `edition_id`: a edição vem da URL, já escopada no programa da
    sessão. `level` é obrigatório e não tem default — o barema é por
    (edição, nível), e mestrado e doutorado são listas independentes;
    um default aqui faria item de doutorado nascer em mestrado por
    esquecimento.
    """

    level: ScholarshipLevel
    section: BaremeSection
    code: str
    text: str
    unit: BaremeUnit
    points_per_unit: decimal.Decimal
    cap: decimal.Decimal


class BaremeItemPatch(Schema):
    """Retificação do item: só os campos presentes são aplicados.

    Vale apenas com a edição em rascunho (`ensure_bareme_editable`), como
    o POST e o DELETE. O `code` continua defendido pelo `clean()`
    (`duplicate_bareme_item`).
    """

    level: ScholarshipLevel | None = None
    section: BaremeSection | None = None
    code: str | None = None
    text: str | None = None
    unit: BaremeUnit | None = None
    points_per_unit: decimal.Decimal | None = None
    cap: decimal.Decimal | None = None


class BaremeItemOut(Schema):
    """O item do barema como a tela o mostra.

    Os três rótulos viajam resolvidos porque a tela de lançamento agrupa
    os itens por seção e o nome da seção é do edital, não do front.
    """

    id: int
    edition_id: int
    level: ScholarshipLevel
    level_label: str
    section: BaremeSection
    section_label: str
    code: str
    text: str
    unit: BaremeUnit
    unit_label: str
    points_per_unit: decimal.Decimal
    cap: decimal.Decimal
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_level_label(obj: BaremeItem) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_section_label(obj: BaremeItem) -> str:
        return obj.get_section_display()

    @staticmethod
    def resolve_unit_label(obj: BaremeItem) -> str:
        return obj.get_unit_display()


class BaremeCloneIn(Schema):
    """De onde copiar o barema.

    O destino é a edição da URL — é ela que precisa estar em rascunho. A
    origem é qualquer outra edição do mesmo programa (tipicamente a do ano
    anterior): montar o barema do zero é a parte mais cara de abrir o
    edital, e ele muda pouco de um ano para o outro.
    """

    source_edition_id: int


class BaremeCloneOut(Schema):
    """O resultado da clonagem: quantos itens vieram e o barema completo.

    A tela recarrega a lista sem uma segunda chamada, e `created` é o
    número que a secretaria confere contra o edital do ano anterior.
    """

    source_edition_id: int
    created: int
    items: list[BaremeItemOut]


# ---------------------------------------------------------------------------
# Inscrição do discente
# ---------------------------------------------------------------------------


class ScholarshipApplicationIn(Schema):
    """A inscrição que o discente monta, com o questionário do edital.

    Sem `student_id` e sem `level`: o vínculo é o da sessão e o nível é
    copiado dele no ato (`ScholarshipApplication.for_student`) — aceitar
    qualquer um dos dois do corpo deixaria um candidato se inscrever em
    nome de outro ou escolher a lista em que compete.

    Sem `fump_level`, `band_override` e `band_override_reason` também:
    esses três são da Secretaria, têm permissão própria e rota própria
    (f14). Aqui só o que o candidato declara.

    Os booleanos têm default `False` para que a tela possa mandar apenas
    os "Sim" — o questionário do edital é uma lista de afirmações, e não
    responder é responder "não".
    """

    edition_id: int
    has_paid_activity: bool = False
    affirmative_action: bool = False
    socioeconomic_vulnerability: bool = False
    cadastro_unico: bool = False
    substitute_teacher: bool = False
    basic_education_or_collective_health: bool = False
    public_service: bool = False
    private_service: bool = False
    other_non_public_scholarship: bool = False
    monthly_income: decimal.Decimal | None = None
    weekly_hours: int | None = None


class ScholarshipApplicationPatch(Schema):
    """Retificação do questionário: só os campos presentes são aplicados.

    Vale enquanto a janela está aberta e só para o próprio candidato
    (`ensure_editable`). A coerência entre atividade remunerada,
    rendimento e carga horária continua sendo do `clean()`
    (`income_required`) — e ela é conferida sobre a inscrição **já
    alterada**, não sobre o payload, porque quem desliga
    `has_paid_activity` sem apagar a renda não está errado.
    """

    has_paid_activity: bool | None = None
    affirmative_action: bool | None = None
    socioeconomic_vulnerability: bool | None = None
    cadastro_unico: bool | None = None
    substitute_teacher: bool | None = None
    basic_education_or_collective_health: bool | None = None
    public_service: bool | None = None
    private_service: bool | None = None
    other_non_public_scholarship: bool | None = None
    monthly_income: decimal.Decimal | None = None
    weekly_hours: int | None = None


class ApplicationDocumentOut(Schema):
    """Um comprovante do questionário, sem o caminho do arquivo.

    Nem `file` nem `file.url` entram aqui, pelo mesmo motivo de
    `RequestDocumentOut` (`apps/academic/schemas.py`): o MEDIA é servido
    pelo Nginx sem passar pelo Django, então publicar a URL entregaria o
    laudo e o contracheque do candidato a quem descobrisse o endereço — e
    sem AuditLog. O único caminho para o conteúdo é a rota de download,
    que exige `download_applicationdocument` de quem não é o dono e
    registra o acesso.
    """

    id: int
    kind: ApplicationDocumentKind
    kind_label: str
    filename: str
    size: int
    uploaded_at: datetime.datetime

    @staticmethod
    def resolve_kind_label(obj: ApplicationDocument) -> str:
        return obj.get_kind_display()

    @staticmethod
    def resolve_filename(obj: ApplicationDocument) -> str:
        """Só o nome, sem o caminho: o diretório expõe o id da edição e o
        da inscrição sem necessidade."""
        return Path(obj.file.name or "").name

    @staticmethod
    def resolve_size(obj: ApplicationDocument) -> int:
        """Arquivo sumido do storage vale 0, e não erro 500: a listagem
        precisa continuar mostrando que o anexo existe para a secretaria
        poder pedir o reenvio."""
        try:
            return obj.file.size
        except (FileNotFoundError, ValueError):
            return 0


class PendingDocumentOut(Schema):
    """Um "Sim" do questionário ainda sem comprovante.

    Viaja com o rótulo resolvido porque é isto que a tela desenha na
    lista de pendências, e o nome do inciso é do edital, não do front.
    """

    kind: ApplicationDocumentKind
    kind_label: str


class ScholarshipApplicationOut(Schema):
    """A inscrição como a tela do discente e a da comissão a veem.

    Três derivações viajam resolvidas, e nenhuma delas é recalculável no
    front: `submission_open` (a janela, que decide se a tela desenha os
    botões de edição), `pending_docs` (o "Sim - Não enviado" do legado) e
    `band` (a faixa, hoje só a sobrescrita da secretaria).

    Os campos de snapshot da publicação não estão aqui: eles entram com a
    tela do resultado (f18/f24), e expô-los antes daria à tela de
    inscrição um resultado que ainda não existe.
    """

    id: int
    edition_id: int
    student_id: int
    student_name: str
    level: ScholarshipLevel
    level_label: str
    submitted_at: datetime.datetime | None
    has_paid_activity: bool
    affirmative_action: bool
    socioeconomic_vulnerability: bool
    cadastro_unico: bool
    substitute_teacher: bool
    basic_education_or_collective_health: bool
    public_service: bool
    private_service: bool
    other_non_public_scholarship: bool
    monthly_income: decimal.Decimal | None
    weekly_hours: int | None
    fump_level: int
    band_override: PriorityBand | None
    band_override_reason: str
    band: PriorityBand | None
    submission_open: bool
    documents: list[ApplicationDocumentOut]
    pending_docs: list[PendingDocumentOut]
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_student_name(obj: ScholarshipApplication) -> str:
        return obj.student.person.full_name

    @staticmethod
    def resolve_level_label(obj: ScholarshipApplication) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_band(obj: ScholarshipApplication) -> str | None:
        """`band` é método do model e campo do schema: sem este resolve o
        Ninja serializaria o método ligado."""
        return obj.band()

    @staticmethod
    def resolve_submission_open(obj: ScholarshipApplication) -> bool:
        return obj.edition.submission_open()

    @staticmethod
    def resolve_documents(obj: ScholarshipApplication) -> list[ApplicationDocument]:
        return list(obj.documents.all())

    @staticmethod
    def resolve_pending_docs(obj: ScholarshipApplication) -> list[dict]:
        rotulos = dict(ApplicationDocumentKind.choices)
        return [
            {"kind": kind, "kind_label": rotulos[kind]} for kind in obj.pending_docs()
        ]
