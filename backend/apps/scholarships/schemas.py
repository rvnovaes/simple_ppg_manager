"""Contrato HTTP do app scholarships.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md); nenhum model
é serializado direto. Preenchido pelas stories de API.
"""

import datetime
import decimal
from pathlib import Path

from ninja import Field, Schema

from .models import (
    AppealOutcome,
    AppealState,
    ApplicationDocument,
    ApplicationDocumentKind,
    BaremeEntry,
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    CommitteeMember,
    ItemReview,
    PriorityBand,
    ScholarshipAppeal,
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


# ---------------------------------------------------------------------------
# Recurso contra o resultado preliminar
# ---------------------------------------------------------------------------
#
# Declarado **antes** da inscrição porque `ScholarshipApplicationOut` o
# embute: a tela do candidato precisa, na mesma resposta, do recurso que
# ele já interpôs e do bool que diz se ainda dá para interpor. Duas
# chamadas para isso deixariam a tela desenhar o botão de recorrer para
# quem já recorreu, no intervalo entre elas.


class ScholarshipAppealIn(Schema):
    """As razões do candidato — **um campo, e sem anexo**.

    A ausência do anexo é do edital, não do esquecimento: o item 1.3 veta
    a postagem de documento fora do prazo de inscrição, e o recurso ataca
    a pontuação com argumento sobre o que já foi entregue. Ver a docstring
    de `ScholarshipAppeal`.
    """

    text: str


class ScholarshipAppealJudgeIn(Schema):
    """O julgamento da comissão: resultado e fundamentação.

    A fundamentação vazia é recusada pelo `judge()` do model
    (`appeal_reasoning_required`) e não aqui — decisão sem fundamentação é
    o que o próprio candidato recorreria, e isso é regra do domínio.
    """

    outcome: AppealOutcome
    reasoning: str


class ScholarshipAppealOut(Schema):
    """O recurso como as duas telas o leem: a do candidato e a da comissão.

    `outcome_label` viaja resolvido porque o rótulo ("Parcialmente
    deferido") é do edital, e montá-lo no front seria a segunda cópia da
    tabela de resultados.
    """

    id: int
    application_id: int
    text: str
    submitted_at: datetime.datetime
    outcome: AppealOutcome | None
    outcome_label: str | None
    reasoning: str
    decided_at: datetime.datetime | None
    judged: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_outcome_label(obj: ScholarshipAppeal) -> str | None:
        return obj.get_outcome_display() if obj.outcome else None

    @staticmethod
    def resolve_judged(obj: ScholarshipAppeal) -> bool:
        return obj.judged()


# ---------------------------------------------------------------------------
# Inscrição do discente (saída)
# ---------------------------------------------------------------------------


class ScholarshipApplicationOut(Schema):
    """A inscrição como a tela do discente e a da comissão a veem.

    As derivações viajam resolvidas, e nenhuma delas é recalculável no
    front: `submission_open` (a janela, que decide se a tela desenha os
    botões de edição), `pending_docs` (o "Sim - Não enviado" do legado),
    `band` (a faixa efetiva) e o par do recurso — `can_appeal` (o botão de
    recorrer) e `appeal` (o que já foi interposto e como foi julgado).

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
    can_appeal: bool
    appeal: ScholarshipAppealOut | None
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
    def resolve_can_appeal(obj: ScholarshipApplication) -> bool:
        """O bool que desenha o botão de recorrer; quem cobra é
        `ensure_appealable`."""
        return obj.can_appeal()

    @staticmethod
    def resolve_appeal(obj: ScholarshipApplication) -> "ScholarshipAppeal | None":
        return obj.submitted_appeal()

    @staticmethod
    def resolve_documents(obj: ScholarshipApplication) -> list[ApplicationDocument]:
        return list(obj.documents.all())

    @staticmethod
    def resolve_pending_docs(obj: ScholarshipApplication) -> list[dict]:
        rotulos = dict(ApplicationDocumentKind.choices)
        return [
            {"kind": kind, "kind_label": rotulos[kind]} for kind in obj.pending_docs()
        ]


# ---------------------------------------------------------------------------
# Lançamentos do barema
# ---------------------------------------------------------------------------


class BaremeEntryIn(Schema):
    """O que o candidato digita ao lançar uma linha do barema.

    **Três campos, e só três.** Não há `candidate_score` aqui de
    propósito: a nota do candidato é *calculada* pelo servidor como
    `item.raw_score(quantity)`, e aceitá-la do corpo deixaria o candidato
    escolher a própria pontuação. Também não há `committee_score` nem
    `committee_note` — a nota da comissão tem rota e permissão próprias
    (`review_baremeentry`, f13), e é assim que "a comissão não mexe no que
    o aluno digitou, e o aluno não mexe no que a comissão decidiu" vira
    código, e não combinado.

    Viaja como **multipart** junto com o comprovante (`Form(...)` no
    router): sem comprovante o lançamento não existe (Q11), então não há
    caminho de criar vazio e anexar depois.
    """

    item_id: int
    description: str
    quantity: decimal.Decimal


class BaremeEntryPatch(Schema):
    """Retificação do lançamento: só os campos presentes são aplicados.

    JSON, ao contrário do `BaremeEntryIn` — o comprovante tem rota
    própria porque o Django não parseia multipart em PATCH. Os campos da
    comissão continuam de fora, pela mesma razão do `In`.
    """

    item_id: int | None = None
    description: str | None = None
    quantity: decimal.Decimal | None = None


class BaremeEntryOut(Schema):
    """O lançamento como a tela do candidato e a da comissão o veem.

    Os dados do item viajam resolvidos (`item_code`, `item_text`,
    `item_section`) porque as duas telas agrupam os lançamentos por seção
    do barema e o texto da linha é do edital, não do front.

    O comprovante sai como nome e tamanho, nunca como caminho ou URL —
    mesmo motivo de `ApplicationDocumentOut`: o MEDIA é servido pelo Nginx
    sem passar pelo Django, e o único caminho para o conteúdo é a rota de
    download, que audita o acesso.
    """

    id: int
    application_id: int
    item_id: int
    item_code: str
    item_text: str
    item_section: BaremeSection
    item_section_label: str
    item_unit: BaremeUnit
    item_unit_label: str
    description: str
    quantity: decimal.Decimal
    candidate_score: decimal.Decimal
    committee_score: decimal.Decimal | None
    committee_note: str
    reviewed_at: datetime.datetime | None
    proof_filename: str
    proof_size: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_item_code(obj: BaremeEntry) -> str:
        return obj.item.code

    @staticmethod
    def resolve_item_text(obj: BaremeEntry) -> str:
        return obj.item.text

    @staticmethod
    def resolve_item_section(obj: BaremeEntry) -> str:
        return obj.item.section

    @staticmethod
    def resolve_item_section_label(obj: BaremeEntry) -> str:
        return obj.item.get_section_display()

    @staticmethod
    def resolve_item_unit(obj: BaremeEntry) -> str:
        return obj.item.unit

    @staticmethod
    def resolve_item_unit_label(obj: BaremeEntry) -> str:
        return obj.item.get_unit_display()

    @staticmethod
    def resolve_proof_filename(obj: BaremeEntry) -> str:
        return Path(obj.proof.name or "").name

    @staticmethod
    def resolve_proof_size(obj: BaremeEntry) -> int:
        """Arquivo sumido do storage vale 0, e não erro 500 — mesma
        decisão de `ApplicationDocumentOut.resolve_size`: a comissão
        precisa continuar vendo o lançamento para poder pedir o reenvio."""
        try:
            return obj.proof.size
        except (FileNotFoundError, ValueError):
            return 0


# ---------------------------------------------------------------------------
# Análise da comissão
# ---------------------------------------------------------------------------


class BaremeEntryReviewIn(Schema):
    """A avaliação da comissão sobre um lançamento — **dois campos**.

    Não há `description`, `quantity`, `item_id` nem `candidate_score`
    aqui, e a ausência é o ponto: a comissão pontua o que o candidato
    lançou e não reescreve o que ele lançou. Campo extra no corpo é
    ignorado pelo pydantic, sem erro — o teste que prova isso manda o
    campo e confere o gravado.

    `committee_note` tem default vazio porque nota igual à do candidato
    não precisa de justificativa; a divergência sem observação é recusada
    pelo `clean()` do lançamento (`note_required`), que é onde a regra
    mora desde o model.
    """

    committee_score: decimal.Decimal
    committee_note: str = ""


class ItemReviewIn(Schema):
    """A observação da comissão sobre um item inteiro do barema.

    Outra coisa que `committee_note`: aquela explica **um lançamento**,
    esta comenta o item como um todo. Uma por (inscrição, item) — por isso
    a rota é `PUT`, e reenviar sobrescreve em vez de empilhar.
    """

    item_id: int
    note: str


class ItemReviewOut(Schema):
    id: int
    application_id: int
    item_id: int
    item_code: str
    item_text: str
    item_section: BaremeSection
    note: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_item_code(obj: ItemReview) -> str:
        return obj.item.code

    @staticmethod
    def resolve_item_text(obj: ItemReview) -> str:
        return obj.item.text

    @staticmethod
    def resolve_item_section(obj: ItemReview) -> str:
        return obj.item.section


class ScholarshipApplicationQueueOut(Schema):
    """Uma linha da fila de trabalho da comissão.

    É um schema próprio, e não o `ScholarshipApplicationOut`: a fila
    responde a outras perguntas (quanto o candidato pediu, quanto a
    comissão já concedeu, sobrou item a analisar, recorreu) e não precisa
    do questionário inteiro em cada linha — quem quer o questionário abre
    a inscrição.

    As três leituras de nota (`candidate_score`, `committee_score`,
    `fully_reviewed`) são derivadas dos lançamentos a cada resposta: não
    há campo denormalizado a manter em dia, e o teto do item é aplicado
    sobre a soma dos lançamentos daquele item (ver
    `BaremeItem.raw_score`). É por isso que a fila é paginada.
    """

    id: int
    student_id: int
    student_name: str
    level: ScholarshipLevel
    level_label: str
    research_line: str | None
    advisor_name: str | None
    admission_year: int | None
    submitted_at: datetime.datetime | None
    fump_level: int
    band: PriorityBand | None
    candidate_score: decimal.Decimal
    committee_score: decimal.Decimal
    fully_reviewed: bool
    appeal_state: AppealState
    appeal_outcome: AppealOutcome | None
    pending_docs: list[PendingDocumentOut]
    updated_at: datetime.datetime

    @staticmethod
    def resolve_student_name(obj: ScholarshipApplication) -> str:
        return obj.student.person.full_name

    @staticmethod
    def resolve_level_label(obj: ScholarshipApplication) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_research_line(obj: ScholarshipApplication) -> str | None:
        """A linha de pesquisa chega pelo projeto coletivo do vínculo — é
        um dos filtros da fila, e a tela precisa exibir o que filtrou."""
        projeto = obj.student.project
        return projeto.research_line.name if projeto is not None else None

    @staticmethod
    def resolve_advisor_name(obj: ScholarshipApplication) -> str | None:
        orientador = obj.student.advisor
        return orientador.person.full_name if orientador is not None else None

    @staticmethod
    def resolve_admission_year(obj: ScholarshipApplication) -> int | None:
        ingresso = obj.student.admission_date
        return ingresso.year if ingresso is not None else None

    @staticmethod
    def resolve_band(obj: ScholarshipApplication) -> str | None:
        return obj.band()

    @staticmethod
    def resolve_candidate_score(obj: ScholarshipApplication) -> decimal.Decimal:
        return obj.candidate_score()

    @staticmethod
    def resolve_committee_score(obj: ScholarshipApplication) -> decimal.Decimal:
        return obj.committee_score()

    @staticmethod
    def resolve_fully_reviewed(obj: ScholarshipApplication) -> bool:
        return obj.fully_reviewed()

    @staticmethod
    def resolve_appeal_state(obj: ScholarshipApplication) -> str:
        return obj.appeal_state()

    @staticmethod
    def resolve_appeal_outcome(obj: ScholarshipApplication) -> str | None:
        recurso = obj.submitted_appeal()
        return recurso.outcome if recurso is not None else None

    @staticmethod
    def resolve_pending_docs(obj: ScholarshipApplication) -> list[dict]:
        rotulos = dict(ApplicationDocumentKind.choices)
        return [
            {"kind": kind, "kind_label": rotulos[kind]} for kind in obj.pending_docs()
        ]


# ---------------------------------------------------------------------------
# Lançamentos da Secretaria na inscrição alheia
# ---------------------------------------------------------------------------


class FumpLevelIn(Schema):
    """O nível da FUMP transcrito pela Secretaria — **um campo**.

    O resultado da FUMP chega à Comissão fora do sistema (Q9); aqui ele é
    só transcrito, e vale duas vezes: bônus na nota final (`BONUS_FUMP`) e
    1º critério de desempate. Os limites são os de `NIVEIS_DA_FUMP` (0 é
    "sem nível"), conferidos aqui para que valor fora do domínio pare na
    borda, com 422, em vez de virar linha gravada que ninguém entende.
    """

    fump_level: int = Field(..., ge=0, le=2)


class BandOverrideIn(Schema):
    """A sobrescrita da faixa de prioridade, com a justificativa.

    A válvula da decisão B6: 2.4-I e 2.4-II não têm pergunta no
    questionário e só chegam por aqui, junto de todo caso omisso.

    `band_override` nulo **limpa** a sobrescrita e devolve a inscrição à
    faixa derivada do questionário. A justificativa continua aceita nesse
    caso (desfazer também é ato discricionário e merece motivo escrito),
    mas só é *exigida* quando há faixa — quem cobra é o `clean()` do
    model (`override_reason_required`), que é onde a regra mora.
    """

    band_override: PriorityBand | None = None
    band_override_reason: str = ""
