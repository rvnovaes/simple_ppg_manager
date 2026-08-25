"""Models do processo seletivo de mestrado e doutorado.

App próprio, separado de `academic` (plano, decisão P1): edital, etapas,
vagas, bancas, inscrição pública, notas, atas e convocações entram aqui,
story a story, cada uma com a sua migration.

Convenções válidas para todos os models deste app (não repetidas por model):

- FK `program` direta com `PROTECT` (ADR-007), exceto filhos de agregado
  (`SelectionStage` e afins), que chegam ao programa pelo pai.
- `clean()` levanta `DomainError(code=...)` cobrindo a duplicata de cada
  `UniqueConstraint` — `.save()` não roda `clean()`, e sem o espelho a
  violação vira `IntegrityError` → 500 (armadilha 5 do plano).
- Transições de estado **não salvam**; `InvalidStateTransition` = 409.
- Todos os `TextChoices` no nível do módulo, com nome único: o gerador de
  OpenAPI batiza o schema pelo `__name__` da classe, e enums aninhados
  colidem (precedente: `AdjustmentStatus` em `apps/academic/models.py`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import models
from django.utils import timezone

from apps.core.exceptions import DomainError, InvalidStateTransition

# ---------------------------------------------------------------------------
# Enums de módulo
# ---------------------------------------------------------------------------


class SelectionKind(models.TextChoices):
    """Tipo do edital.

    O Regular chaveia por projeto coletivo; o Suplementar (ações
    afirmativas) chaveia por linha de pesquisa (decisão P4 do plano).
    """

    REGULAR = "regular", "Regular"
    SUPPLEMENTARY = "supplementary", "Suplementar"


class SelectionProcessStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    PUBLISHED = "published", "Publicado"
    CLOSED = "closed", "Encerrado"


class SelectionLevel(models.TextChoices):
    """Mesmos valores de `Student.Level` — a conversão em aluno copia direto."""

    MASTERS = "masters", "Mestrado"
    DOCTORATE = "doctorate", "Doutorado"


class QuotaCategory(models.TextChoices):
    OPEN = "open", "Ampla concorrência"
    RACIAL = "racial", "Cota racial"
    DISABILITY = "disability", "Pessoa com deficiência"
    QUILOMBOLA = "quilombola", "Quilombola"
    TRANS = "trans", "Pessoa trans"
    INDIGENOUS = "indigenous", "Indígena"


class ApplicationStatus(models.TextChoices):
    SUBMITTED = "submitted", "Inscrita"
    HOMOLOGATED = "homologated", "Homologada"
    REJECTED = "rejected", "Indeferida"
    ELIMINATED = "eliminated", "Eliminada"
    APPROVED = "approved", "Aprovada"
    ENROLLED = "enrolled", "Matriculada"


class RankingOutcome(models.TextChoices):
    CLASSIFIED_OPEN = "classified_open", "Classificado (ampla concorrência)"
    CLASSIFIED_QUOTA = "classified_quota", "Classificado (cota)"
    NOT_CLASSIFIED = "not_classified", "Não classificado"


class ApplicationDocumentKind(models.TextChoices):
    IDENTITY = "identity", "Documento de identidade"
    DIPLOMA = "diploma", "Diploma"
    LATTES = "lattes", "Currículo Lattes"
    EXPANDED_ABSTRACT = "expanded_abstract", "Resumo expandido"
    MEMORIAL = "memorial", "Memorial"
    PAYMENT_RECEIPT = "payment_receipt", "Comprovante de pagamento"
    QUOTA_PROOF = "quota_proof", "Comprovação da cota"


class RecordStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    AWAITING_SIGNATURES = "awaiting_signatures", "Aguardando assinaturas"
    SIGNED = "signed", "Assinada"
    SUPERSEDED = "superseded", "Substituída"


class SignatureMethod(models.TextChoices):
    LOGIN = "login", "Login"
    TOKEN = "token", "Token por e-mail"


class ReallocationKind(models.TextChoices):
    LEVEL_TRANSFER = "level_transfer", "Transferência entre níveis"
    NOTICE_RECTIFICATION = "notice_rectification", "Retificação do edital"


class EmailDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    SENT = "sent", "Enviado"
    FAILED = "failed", "Falhou"


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Quais categorias de cota cada tipo de edital aceita. O Regular tem ampla
# concorrência e cota racial; o Suplementar é só ações afirmativas.
CATEGORIAS_POR_TIPO: dict[str, frozenset[str]] = {
    SelectionKind.REGULAR: frozenset({QuotaCategory.OPEN, QuotaCategory.RACIAL}),
    SelectionKind.SUPPLEMENTARY: frozenset(
        {
            QuotaCategory.DISABILITY,
            QuotaCategory.QUILOMBOLA,
            QuotaCategory.TRANS,
            QuotaCategory.INDIGENOUS,
        }
    ),
}
NOTA_DE_CORTE = Decimal("70.00")
NOTA_MAXIMA = Decimal("100.00")

# Placeholders que o template de convocação do edital pode usar. Quem
# renderiza é `SelectionProcess.render_convocation`; a lista existe para a
# tela mostrar ao usuário o que está disponível.
PLACEHOLDERS_DE_CONVOCACAO = (
    "nome",
    "protocolo",
    "etapa",
    "data_hora",
    "local",
    "edital",
)


# ---------------------------------------------------------------------------
# Helpers de módulo
# ---------------------------------------------------------------------------


def xor_de_alvo(nome: str) -> models.CheckConstraint:
    """Exatamente um alvo: projeto coletivo OU linha de pesquisa.

    Vaga, banca, inscrição e ata carregam `project`/`research_line`
    nuláveis (decisão P4); esta constraint é o que impede a linha sem alvo
    nenhum ou com os dois. Helper de módulo, sem mixin/abstract, porque o
    projeto não cria camada para o que cabe numa função.
    A amarração ao tipo do edital (Regular exige projeto, Suplementar
    exige linha) mora em outra tabela e por isso é
    `SelectionProcess.ensure_target`, chamada no `clean()` de cada um.
    """
    return models.CheckConstraint(
        condition=models.Q(project__isnull=False, research_line__isnull=True)
        | models.Q(project__isnull=True, research_line__isnull=False),
        name=f"{nome}_exactly_one_target",
    )


def caminho_do_edital(instance: "SelectionProcess", filename: str) -> str:
    """Onde o PDF do edital é gravado dentro do MEDIA_ROOT.

    Particionado por edital, no mesmo prefixo `selecao/edital-{id}/` que os
    anexos de inscrição e as atas vão usar — arquivar um processo seletivo
    inteiro é copiar um diretório. Função de módulo, e não lambda, porque a
    migração precisa serializar a referência.
    """
    return f"selecao/edital-{instance.pk}/{filename}"


class _PlaceholderTolerante(dict[str, Any]):
    """Mapping para `str.format_map` que deixa placeholder desconhecido literal.

    A secretaria escreve `{nome}` e `{local}` no template; se digitar
    `{sala}` por engano, o e-mail sai com `{sala}` visível em vez de o
    envio inteiro do lote falhar com `KeyError`.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


# ---------------------------------------------------------------------------
# SelectionProcess (edital)
# ---------------------------------------------------------------------------


class SelectionProcessQuerySet(models.QuerySet["SelectionProcess"]):
    def for_program(self, program: Any) -> "SelectionProcessQuerySet":
        return self.filter(program=program)

    def published(self) -> "SelectionProcessQuerySet":
        return self.filter(status=SelectionProcessStatus.PUBLISHED)

    def open_for_submission(self, at: datetime) -> "SelectionProcessQuerySet":
        """Editais publicados cuja janela de inscrição contém `at`.

        Mesma regra de `submission_open`: inclui a abertura, exclui o
        fechamento.
        """
        return self.published().filter(
            submission_opens_at__lte=at, submission_closes_at__gt=at
        )


class SelectionProcess(models.Model):
    """Edital de um processo seletivo (Regular ou Suplementar) de um ano.

    `year` é o ano do processo seletivo — PS2027 = 2027 — e não o ano em
    que o edital foi publicado. Um edital por (programa, tipo, ano).

    Vagas, etapas e janela só mudam em rascunho (`ensure_editable`): depois
    de publicado, o candidato já se inscreveu contra esse conteúdo. Mudança
    de vaga depois disso é `VacancyReallocation`, com ofício da comissão.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_processes",
        verbose_name="programa",
    )
    kind = models.CharField("tipo", max_length=20, choices=SelectionKind)
    year = models.PositiveIntegerField("ano do processo seletivo")
    title = models.CharField("título", max_length=200)
    status = models.CharField(
        "situação",
        max_length=20,
        choices=SelectionProcessStatus,
        default=SelectionProcessStatus.DRAFT,
    )
    submission_opens_at = models.DateTimeField("inscrições abrem em")
    submission_closes_at = models.DateTimeField("inscrições encerram em")
    notice_file = models.FileField(
        "arquivo do edital", upload_to=caminho_do_edital, blank=True
    )
    convocation_subject = models.CharField(
        "assunto da convocação", max_length=200, blank=True
    )
    convocation_body = models.TextField(
        "corpo da convocação",
        blank=True,
        help_text=(
            "Placeholders: {nome} {protocolo} {etapa} {data_hora} {local} {edital}"
        ),
    )
    published_at = models.DateTimeField("publicado em", null=True, blank=True)
    closed_at = models.DateTimeField("encerrado em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SelectionProcessQuerySet.as_manager()

    class Meta:
        verbose_name = "edital de seleção"
        verbose_name_plural = "editais de seleção"
        ordering = ["-year", "kind"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "kind", "year"],
                name="unique_edital_por_programa_tipo_e_ano",
            ),
        ]

    def __str__(self) -> str:
        return self.title or f"{self.get_kind_display()} {self.year}"

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """Janela de inscrição em ordem e um edital por (programa, tipo, ano).

        `<` estrito: janela de duração zero não aceita ninguém.
        """
        super().clean()
        if (
            self.submission_opens_at is not None
            and self.submission_closes_at is not None
            and not self.submission_opens_at < self.submission_closes_at
        ):
            raise DomainError(
                "As inscrições precisam abrir antes de encerrar.",
                code="invalid_submission_window",
            )
        if self.program_id is None or not self.kind or self.year is None:
            # Obrigatoriedade é cobrança do schema Ninja e do NOT NULL.
            return
        duplicatas = SelectionProcess.objects.filter(
            program_id=self.program_id, kind=self.kind, year=self.year
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Já existe um edital deste tipo para este ano neste programa.",
                code="duplicate_process",
            )

    def allowed_quota_categories(self) -> frozenset[str]:
        return CATEGORIAS_POR_TIPO[self.kind]

    def ensure_quota_category(self, category: str) -> None:
        """A categoria de cota precisa existir no tipo do edital.

        Chamada por `Vacancy.clean()` e por `submit_application`: cota racial
        no Suplementar, ou ampla concorrência fora do Regular, não são
        combinações — são erro de formulário.
        """
        if category not in self.allowed_quota_categories():
            raise DomainError(
                f"A categoria de cota '{category}' não existe no edital "
                f"{self.get_kind_display().lower()}.",
                code="quota_category_not_allowed",
            )

    def ensure_target(self, project: Any, research_line: Any) -> None:
        """Regular chaveia por projeto coletivo; Suplementar por linha.

        O XOR entre os dois é da `CheckConstraint` (`xor_de_alvo`); aqui é
        a amarração ao tipo do edital, que a constraint não alcança porque
        o tipo está em outra tabela. Chamada no `clean()` de vaga, banca,
        inscrição e ata.
        """
        if self.kind == SelectionKind.REGULAR:
            if project is None or research_line is not None:
                raise DomainError(
                    "No edital regular o alvo é um projeto coletivo, "
                    "sem linha de pesquisa.",
                    code="target_mismatch",
                )
        elif research_line is None or project is not None:
            raise DomainError(
                "No edital suplementar o alvo é uma linha de pesquisa, "
                "sem projeto coletivo.",
                code="target_mismatch",
            )

    # -- estado -----------------------------------------------------------

    @property
    def is_draft(self) -> bool:
        return self.status == SelectionProcessStatus.DRAFT

    @property
    def is_published(self) -> bool:
        return self.status == SelectionProcessStatus.PUBLISHED

    def submission_open(self, at: datetime) -> bool:
        """Inclui a abertura e exclui o fechamento — quem chega no instante
        exato do prazo chegou tarde. Só vale para edital publicado.
        """
        return (
            self.is_published
            and self.submission_opens_at <= at < self.submission_closes_at
        )

    def ensure_editable(self) -> None:
        """Vaga, etapa e janela só mudam em rascunho."""
        if not self.is_draft:
            raise InvalidStateTransition(
                "Vagas, etapas e janela só podem mudar com o edital em rascunho.",
                code="process_not_editable",
            )

    def publish(self, at: datetime) -> None:
        if not self.is_draft:
            raise InvalidStateTransition(
                "Só um edital em rascunho pode ser publicado.",
                code="process_not_draft",
            )
        self.status = SelectionProcessStatus.PUBLISHED
        self.published_at = at

    def close(self, at: datetime) -> None:
        if not self.is_published:
            raise InvalidStateTransition(
                "Só um edital publicado pode ser encerrado.",
                code="process_not_published",
            )
        self.status = SelectionProcessStatus.CLOSED
        self.closed_at = at

    # -- convocação -------------------------------------------------------

    def render_convocation(
        self, application: Any, stage: "SelectionStage"
    ) -> tuple[str, str]:
        """Assunto e corpo do e-mail de convocação para uma inscrição × etapa.

        `application` é duck typing de propósito: precisa só de `full_name`
        e `protocol`. Placeholder desconhecido fica literal no texto
        (`_PlaceholderTolerante`) — erro de digitação no template não
        derruba o envio do lote inteiro.
        """
        valores = _PlaceholderTolerante(
            nome=application.full_name,
            protocolo=application.protocol,
            etapa=stage.name,
            data_hora=_formatar_data_hora(stage.session_at),
            local=stage.location,
            edital=self.title,
        )
        return (
            self.convocation_subject.format_map(valores),
            self.convocation_body.format_map(valores),
        )


def _formatar_data_hora(instante: datetime | None) -> str:
    """Data e hora no formato que o candidato lê (dd/mm/aaaa hh:mm), no
    fuso do projeto. Sem sessão marcada, o placeholder sai vazio."""
    if instante is None:
        return ""
    if timezone.is_aware(instante):
        instante = timezone.localtime(instante)
    return instante.strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# SelectionStage (etapa)
# ---------------------------------------------------------------------------


class SelectionStage(models.Model):
    """Etapa de avaliação de um edital, na ordem em que acontece.

    É dado, não código: o Regular tem resumo expandido (desempate 1) →
    prova oral (desempate 2) → entrevista; o Suplementar tem memorial
    (desempate 1) → prova oral (desempate 2) → análise do projeto e
    memorial. `tiebreak_rank` nulo = a etapa não entra no desempate.

    Filho de agregado: chega ao programa por `process.program`.
    """

    process = models.ForeignKey(
        SelectionProcess,
        on_delete=models.CASCADE,
        related_name="stages",
        verbose_name="edital",
    )
    name = models.CharField("nome", max_length=120)
    order = models.PositiveSmallIntegerField("ordem")
    session_at = models.DateTimeField("sessão em", null=True, blank=True)
    location = models.CharField("local", max_length=200, blank=True)
    tiebreak_rank = models.PositiveSmallIntegerField(
        "posição no desempate", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "etapa da seleção"
        verbose_name_plural = "etapas da seleção"
        ordering = ["process", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["process", "order"],
                name="unique_etapa_por_edital_e_ordem",
            ),
            models.UniqueConstraint(
                fields=["process", "name"],
                name="unique_etapa_por_edital_e_nome",
            ),
            models.UniqueConstraint(
                fields=["process", "tiebreak_rank"],
                condition=models.Q(tiebreak_rank__isnull=False),
                name="unique_desempate_por_edital",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order}. {self.name}"

    @property
    def program_id(self) -> int:
        return self.process.program_id

    @property
    def is_first(self) -> bool:
        return not self.process.stages.filter(order__lt=self.order).exists()

    @property
    def is_last(self) -> bool:
        return not self.process.stages.filter(order__gt=self.order).exists()

    def previous(self) -> "SelectionStage | None":
        return (
            self.process.stages.filter(order__lt=self.order).order_by("-order").first()
        )

    def clean(self) -> None:
        """Ordem a partir de 1 e sem repetir ordem, nome ou posição de
        desempate dentro do mesmo edital (espelho das UniqueConstraints)."""
        super().clean()
        if self.order is not None and self.order < 1:
            raise DomainError(
                "A ordem da etapa começa em 1.", code="invalid_stage_order"
            )
        if self.process_id is None:
            return
        outras = SelectionStage.objects.filter(process_id=self.process_id)
        if self.pk is not None:
            outras = outras.exclude(pk=self.pk)
        repetida = models.Q(order=self.order) | models.Q(name=self.name)
        if self.tiebreak_rank is not None:
            repetida |= models.Q(tiebreak_rank=self.tiebreak_rank)
        if outras.filter(repetida).exists():
            raise DomainError(
                "Já existe etapa com esta ordem, este nome ou esta posição "
                "de desempate neste edital.",
                code="duplicate_stage",
            )
