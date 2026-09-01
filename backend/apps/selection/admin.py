"""Admin do processo seletivo — quebra-vidro, como nos demais apps (ADR-006).

A rotina de quem opera o edital é a tela Svelte; o que se faz aqui é ler e
corrigir dado que o sistema errou. Por isso todo `ModelAdmin` herda de
`AuditedModelAdmin`: escrita por aqui desvia do model e é justamente onde o
rastro mais importa.

O que é `readonly_fields` não é enfeite — é o que o domínio calcula e a
correção manual invalidaria em silêncio: `content_hash` e `pdf` da ata (o
hash cobre o cabeçalho e as linhas; editá-lo à mão quebraria a verificação
das assinaturas já dadas), o `token_hash` e os carimbos do token de
assinatura (o texto do token nunca é guardado), o `protocol` da inscrição e
os carimbos técnicos.
"""

from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import (
    Application,
    ApplicationDocument,
    Board,
    Convocation,
    ConvocationEmail,
    ExaminationRecord,
    RecordSignature,
    SelectionProcess,
    SelectionStage,
    StageScore,
    Vacancy,
    VacancyReallocation,
)

QUEBRA_VIDRO = "Quebra-vidro: a rotina do edital é a tela Svelte (ADR-006)."

CARIMBOS = ("created_at", "updated_at")


class StageInline(admin.TabularInline):
    model = SelectionStage
    extra = 0
    fields = ("order", "name", "session_at", "location", "tiebreak_rank")
    show_change_link = True


@admin.register(SelectionProcess)
class SelectionProcessAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = (
        "title",
        "kind",
        "year",
        "status",
        "submission_opens_at",
        "submission_closes_at",
        "program",
    )
    list_filter = ("program", "kind", "status", "year")
    search_fields = ("title",)
    list_select_related = ("program",)
    date_hierarchy = "submission_opens_at"
    readonly_fields = ("published_at", "closed_at", *CARIMBOS)
    inlines = [StageInline]


@admin.register(SelectionStage)
class SelectionStageAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = ("process", "order", "name", "session_at", "tiebreak_rank")
    list_filter = ("process__program", "process")
    search_fields = ("name", "process__title")
    list_select_related = ("process",)
    raw_id_fields = ("process",)
    readonly_fields = CARIMBOS


@admin.register(Vacancy)
class VacancyAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = (
        "process",
        "level",
        "project",
        "research_line",
        "quota_category",
        "quantity",
        "program",
    )
    list_filter = ("program", "process", "level", "quota_category")
    search_fields = ("process__title", "project__name", "research_line__name")
    list_select_related = ("program", "process", "project", "research_line")
    raw_id_fields = ("process", "project", "research_line")
    readonly_fields = CARIMBOS


@admin.register(Board)
class BoardAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = (
        "process",
        "level",
        "project",
        "research_line",
        "president",
        "member_1",
        "member_2",
        "alternate",
    )
    list_filter = ("program", "process", "level")
    search_fields = (
        "process__title",
        "president__person__full_name",
        "member_1__person__full_name",
        "member_2__person__full_name",
        "alternate__person__full_name",
    )
    list_select_related = (
        "program",
        "process",
        "project",
        "research_line",
        "president__person",
        "member_1__person",
        "member_2__person",
        "alternate__person",
    )
    # Sem isto o Admin renderiza quatro <select> com todos os professores.
    raw_id_fields = (
        "process",
        "project",
        "research_line",
        "president",
        "member_1",
        "member_2",
        "alternate",
    )
    readonly_fields = CARIMBOS


class ApplicationDocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0
    fields = ("kind", "file", "uploaded_at")
    readonly_fields = ("uploaded_at",)


@admin.register(Application)
class ApplicationAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = (
        "protocol",
        "full_name",
        "process",
        "level",
        "quota_category",
        "status",
        "final_rank",
        "final_outcome",
    )
    list_filter = ("program", "process", "status", "level", "quota_category")
    search_fields = ("protocol", "full_name", "email", "cpf")
    list_select_related = ("program", "process")
    date_hierarchy = "submitted_at"
    raw_id_fields = (
        "process",
        "project",
        "research_line",
        "eliminated_at_stage",
        "student",
    )
    # `protocol` é gerado por `gerar_protocolo`: reescrevê-lo à mão quebraria
    # o comprovante que o candidato já recebeu.
    readonly_fields = ("protocol", "ranked_at", *CARIMBOS)
    inlines = [ApplicationDocumentInline]


@admin.register(ApplicationDocument)
class ApplicationDocumentAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = ("application", "kind", "file", "uploaded_at")
    list_filter = ("kind", "application__process")
    search_fields = ("application__protocol", "application__full_name")
    list_select_related = ("application",)
    raw_id_fields = ("application",)
    readonly_fields = ("uploaded_at",)


@admin.register(StageScore)
class StageScoreAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = ("application", "stage", "score", "absent", "entered_by")
    list_filter = ("program", "stage__process", "absent")
    search_fields = ("application__protocol", "application__full_name")
    list_select_related = ("program", "application", "stage", "entered_by")
    raw_id_fields = ("application", "stage", "entered_by")
    readonly_fields = ("entered_at",)


class RecordSignatureInline(admin.TabularInline):
    model = RecordSignature
    extra = 0
    fields = ("signer", "method", "signed_at", "signed_hash", "token_expires_at")
    readonly_fields = ("signed_at", "signed_hash", "token_expires_at")
    raw_id_fields = ("signer",)


@admin.register(ExaminationRecord)
class ExaminationRecordAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = (
        "process",
        "stage",
        "level",
        "project",
        "research_line",
        "version",
        "status",
        "frozen_at",
        "signed_at",
    )
    list_filter = ("program", "process", "status", "level")
    search_fields = ("process__title", "stage__name")
    list_select_related = ("program", "process", "stage", "board")
    raw_id_fields = (
        "process",
        "stage",
        "project",
        "research_line",
        "board",
        "replaced_member",
        "supersedes",
    )
    # Hash e PDF são derivados do conteúdo congelado: editá-los aqui
    # invalidaria as assinaturas já dadas sem que ninguém percebesse.
    readonly_fields = (
        "content_hash",
        "pdf",
        "frozen_at",
        "signed_at",
        *CARIMBOS,
    )
    inlines = [RecordSignatureInline]


@admin.register(RecordSignature)
class RecordSignatureAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = ("record", "signer", "method", "signed_at", "token_sent_at")
    list_filter = ("method", "record__process")
    search_fields = ("signer__person__full_name", "record__process__title")
    list_select_related = ("record", "signer__person", "signed_by_user")
    raw_id_fields = ("record", "signer", "signed_by_user")
    # Do token só existe o hash; os carimbos são prova de emissão, envio e
    # uso, e nenhum deles se corrige digitando.
    readonly_fields = (
        "signed_hash",
        "token_hash",
        "token_expires_at",
        "token_sent_at",
        "token_used_at",
        *CARIMBOS,
    )


@admin.register(VacancyReallocation)
class VacancyReallocationAdmin(AuditedModelAdmin):
    """Registro imutável: `save()` recusa update, então aqui só se cria e lê."""

    list_display = (
        "process",
        "kind",
        "from_vacancy",
        "to_vacancy",
        "quantity",
        "decided_on",
    )
    list_filter = ("program", "process", "kind")
    search_fields = ("process__title", "reason", "decided_by_note")
    list_select_related = ("program", "process", "from_vacancy", "to_vacancy")
    raw_id_fields = ("process", "from_vacancy", "to_vacancy")
    readonly_fields = ("created_at",)


class ConvocationEmailInline(admin.TabularInline):
    model = ConvocationEmail
    extra = 0
    fields = ("application", "to_email", "status", "attempts", "sent_at", "error")
    readonly_fields = ("attempts", "sent_at")
    raw_id_fields = ("application",)


@admin.register(Convocation)
class ConvocationAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = ("process", "stage", "subject", "sent_by", "created_at")
    list_filter = ("program", "process")
    search_fields = ("subject", "process__title")
    list_select_related = ("program", "process", "stage", "sent_by")
    raw_id_fields = ("process", "stage", "sent_by")
    readonly_fields = ("created_at",)
    inlines = [ConvocationEmailInline]


@admin.register(ConvocationEmail)
class ConvocationEmailAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = (
        "convocation",
        "application",
        "to_email",
        "status",
        "attempts",
        "sent_at",
    )
    list_filter = ("status", "convocation__process")
    search_fields = ("to_email", "application__protocol", "application__full_name")
    list_select_related = ("convocation", "application")
    raw_id_fields = ("convocation", "application")
    readonly_fields = ("attempts", "sent_at", *CARIMBOS)
