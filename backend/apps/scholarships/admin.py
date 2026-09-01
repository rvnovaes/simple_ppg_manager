"""Admin das bolsas — quebra-vidro, como nos demais apps (ADR-006).

A rotina de quem opera o edital de bolsas é a tela Svelte; o que se faz
aqui é ler e corrigir dado que o sistema errou. Todo `ModelAdmin` deste
app herda de `AuditedModelAdmin`. Preenchido pelas stories de model.
"""

from django.contrib import admin

from apps.core.admin import AuditedModelAdmin

from .models import BaremeItem, CommitteeMember, ScholarshipEdition

QUEBRA_VIDRO = "Quebra-vidro: a rotina do edital de bolsas é a tela Svelte (ADR-006)."

CARIMBOS = ("created_at", "updated_at")


class CommitteeMemberInline(admin.TabularInline):
    model = CommitteeMember
    extra = 0
    fields = ("teacher", "appointed_on", "ordinance")
    raw_id_fields = ("teacher",)
    show_change_link = True


@admin.register(ScholarshipEdition)
class ScholarshipEditionAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = ("title", "year", "status", "program")
    list_filter = ("program", "status", "year")
    search_fields = ("title",)
    list_select_related = ("program",)
    # `draw_seed` e os carimbos de publicação são do domínio: o serviço de
    # publicação os grava, e reescrevê-los à mão trocaria o sorteio já
    # publicado por outro.
    readonly_fields = (
        "draw_seed",
        "published_preliminary_at",
        "published_final_at",
        *CARIMBOS,
    )
    inlines = [CommitteeMemberInline]


@admin.register(CommitteeMember)
class CommitteeMemberAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = ("edition", "teacher", "appointed_on", "ordinance")
    list_filter = ("edition__program", "edition")
    search_fields = ("ordinance", "teacher__person__full_name")
    list_select_related = ("edition", "teacher")
    raw_id_fields = ("edition", "teacher")
    readonly_fields = CARIMBOS


@admin.register(BaremeItem)
class BaremeItemAdmin(AuditedModelAdmin):
    __doc__ = QUEBRA_VIDRO

    list_display = (
        "code",
        "level",
        "section",
        "unit",
        "points_per_unit",
        "cap",
        "edition",
    )
    list_filter = ("edition__program", "edition", "level", "section")
    search_fields = ("code", "text")
    list_select_related = ("edition",)
    raw_id_fields = ("edition",)
    readonly_fields = CARIMBOS
