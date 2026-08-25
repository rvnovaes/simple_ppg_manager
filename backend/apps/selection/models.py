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

import hashlib
import json
import secrets
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.academic.models import (
    EXTENSOES_DE_DOCUMENTO,
    TAMANHO_MAXIMO_DO_DOCUMENTO,
)
from apps.core.exceptions import DomainError, InvalidStateTransition, NotAllowed

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

    @classmethod
    def validate_notice_upload(cls, *, filename: str, size: int) -> None:
        """Formato e tamanho do PDF do edital.

        Só PDF, e não a lista de `EXTENSOES_DE_DOCUMENTO`: o anexo do
        candidato é foto de celular com frequência, mas o edital é o
        documento oficial que o programa publica — foto de edital não é
        edital. O limite de tamanho é o mesmo do resto do projeto.
        """
        if not filename or not filename.lower().endswith(".pdf"):
            raise DomainError(
                "O arquivo do edital precisa ser um PDF.",
                code="invalid_notice_file",
            )
        if size > TAMANHO_MAXIMO_DO_DOCUMENTO:
            limite = TAMANHO_MAXIMO_DO_DOCUMENTO // (1024 * 1024)
            raise DomainError(
                f"O arquivo do edital tem no máximo {limite} MB.",
                code="invalid_notice_file",
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

        Usa o template **corrente** do edital; o lote já disparado
        renderiza pelas cópias que guardou (`Convocation.render_for`).
        """
        return renderizar_convocacao(
            subject=self.convocation_subject,
            body=self.convocation_body,
            application=application,
            stage=stage,
            process_title=self.title,
        )


def renderizar_convocacao(
    *,
    subject: str,
    body: str,
    application: Any,
    stage: "SelectionStage",
    process_title: str,
) -> tuple[str, str]:
    """Assunto e corpo do e-mail de convocação para uma inscrição × etapa.

    `application` é duck typing de propósito: precisa só de `full_name` e
    `protocol`. Placeholder desconhecido fica literal no texto
    (`_PlaceholderTolerante`) — erro de digitação no template não derruba
    o envio do lote inteiro.
    """
    valores = _PlaceholderTolerante(
        nome=application.full_name,
        protocolo=application.protocol,
        etapa=stage.name,
        data_hora=_formatar_data_hora(stage.session_at),
        local=stage.location,
        edital=process_title,
    )
    return (subject.format_map(valores), body.format_map(valores))


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


# ---------------------------------------------------------------------------
# Vacancy (vaga)
# ---------------------------------------------------------------------------


class Vacancy(models.Model):
    """Linha da grade de vagas de um edital: nível × alvo × categoria de cota.

    `quantity` zero é permitido de propósito: a realocação
    (`VacancyReallocation`) pode esvaziar uma linha, e a linha zerada é o
    histórico de que ali havia vaga — apagar perderia o rastro.

    O alvo (projeto coletivo OU linha de pesquisa) é XOR pela
    `CheckConstraint`; a amarração ao tipo do edital é
    `process.ensure_target`, no `clean()`.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_vacancies",
        verbose_name="programa",
    )
    process = models.ForeignKey(
        SelectionProcess,
        on_delete=models.PROTECT,
        related_name="vacancies",
        verbose_name="edital",
    )
    level = models.CharField("nível", max_length=20, choices=SelectionLevel)
    project = models.ForeignKey(
        "programs.CollectiveProject",
        on_delete=models.PROTECT,
        related_name="selection_vacancies",
        null=True,
        blank=True,
        verbose_name="projeto coletivo",
    )
    research_line = models.ForeignKey(
        "programs.ResearchLine",
        on_delete=models.PROTECT,
        related_name="selection_vacancies",
        null=True,
        blank=True,
        verbose_name="linha de pesquisa",
    )
    quota_category = models.CharField(
        "categoria de cota", max_length=20, choices=QuotaCategory
    )
    quantity = models.PositiveSmallIntegerField("quantidade")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "vaga"
        verbose_name_plural = "vagas"
        ordering = ["process", "level", "project", "research_line", "quota_category"]
        constraints = [
            xor_de_alvo("vacancy"),
            # `nulls_distinct=False`: sem isso o Postgres trata cada NULL
            # como valor distinto e duas vagas do mesmo projeto (linha
            # nula) passariam pela unique.
            models.UniqueConstraint(
                fields=[
                    "process",
                    "level",
                    "project",
                    "research_line",
                    "quota_category",
                ],
                nulls_distinct=False,
                name="unique_vaga_por_edital_nivel_alvo_e_cota",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.get_level_display()} — {self.project or self.research_line} — "
            f"{self.get_quota_category_display()}: {self.quantity}"
        )

    def target_key(self) -> tuple[str, int | None, int | None]:
        """Chave de agrupamento da classificação: mesmo nível e mesmo alvo
        disputam as mesmas vagas, cota a cota."""
        return (self.level, self.project_id, self.research_line_id)

    def clean(self) -> None:
        """Alvo compatível com o tipo do edital, cota permitida nele e uma
        linha por (edital, nível, alvo, cota) — espelho da UniqueConstraint,
        contando NULL como igual a NULL."""
        super().clean()
        if self.process_id is None:
            return
        self.process.ensure_target(self.project, self.research_line)
        if self.quota_category:
            self.process.ensure_quota_category(self.quota_category)
        duplicatas = Vacancy.objects.filter(
            process_id=self.process_id,
            level=self.level,
            project_id=self.project_id,
            research_line_id=self.research_line_id,
            quota_category=self.quota_category,
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Já existe vaga para este nível, este alvo e esta categoria "
                "de cota neste edital.",
                code="duplicate_vacancy",
            )


# ---------------------------------------------------------------------------
# Board (banca)
# ---------------------------------------------------------------------------


class BoardQuerySet(models.QuerySet["Board"]):
    def for_process(self, process: Any) -> "BoardQuerySet":
        return self.filter(process=process)

    def with_teacher(self, teacher: Any) -> "BoardQuerySet":
        """Bancas em que o professor ocupa qualquer um dos quatro papéis.

        É o único lugar em que o `Q()` de quatro ramos é escrito — quem
        precisar de "as bancas do professor" (rota `boards/mine`, checagem
        de `board_in_use`) chama daqui.
        """
        return self.filter(
            models.Q(president=teacher)
            | models.Q(member_1=teacher)
            | models.Q(member_2=teacher)
            | models.Q(alternate=teacher)
        )


class Board(models.Model):
    """Banca examinadora de um nível × alvo de um edital.

    Três titulares (presidente e dois membros) e um suplente. Quem assina
    a ata são os titulares; se um deles estiver impedido, o suplente
    assina no lugar (`expected_signers`). Uma banca por (edital, nível,
    alvo).

    As FKs para `Teacher` são PROTECT: descredenciar é preencher
    `accredited_until`, e a banca da qual o professor participou é
    histórico.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_boards",
        verbose_name="programa",
    )
    process = models.ForeignKey(
        SelectionProcess,
        on_delete=models.PROTECT,
        related_name="boards",
        verbose_name="edital",
    )
    level = models.CharField("nível", max_length=20, choices=SelectionLevel)
    project = models.ForeignKey(
        "programs.CollectiveProject",
        on_delete=models.PROTECT,
        related_name="selection_boards",
        null=True,
        blank=True,
        verbose_name="projeto coletivo",
    )
    research_line = models.ForeignKey(
        "programs.ResearchLine",
        on_delete=models.PROTECT,
        related_name="selection_boards",
        null=True,
        blank=True,
        verbose_name="linha de pesquisa",
    )
    president = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="selection_boards_as_president",
        verbose_name="presidente",
    )
    member_1 = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="selection_boards_as_member_1",
        verbose_name="membro 1",
    )
    member_2 = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="selection_boards_as_member_2",
        verbose_name="membro 2",
    )
    alternate = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="selection_boards_as_alternate",
        verbose_name="suplente",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BoardQuerySet.as_manager()

    # Nome do campo → rótulo, na ordem em que aparecem na ata.
    PAPEIS = ("president", "member_1", "member_2", "alternate")

    class Meta:
        verbose_name = "banca"
        verbose_name_plural = "bancas"
        ordering = ["process", "level", "project", "research_line"]
        constraints = [
            xor_de_alvo("board"),
            models.UniqueConstraint(
                fields=["process", "level", "project", "research_line"],
                nulls_distinct=False,
                name="unique_banca_por_edital_nivel_e_alvo",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Banca {self.get_level_display()} — {self.project or self.research_line}"
        )

    # -- composição -------------------------------------------------------

    def titular_members(self) -> list[Any]:
        return [self.president, self.member_1, self.member_2]

    def _members(self) -> list[Any]:
        return [*self.titular_members(), self.alternate]

    def is_member(self, teacher: Any) -> bool:
        """Titular ou suplente."""
        return teacher.pk in {m.pk for m in self._members()}

    def expected_signers(self, replaced_member: Any | None = None) -> list[Any]:
        """Quem precisa assinar a ata: os três titulares, ou — com um
        titular impedido — os outros dois mais o suplente, na posição do
        impedido. Suplente ou estranho como `replaced_member` é erro."""
        titulares = self.titular_members()
        if replaced_member is None:
            return titulares
        posicoes = [m.pk for m in titulares]
        if replaced_member.pk not in posicoes:
            raise DomainError(
                "Só um membro titular pode ser substituído pelo suplente.",
                code="not_a_titular_member",
            )
        titulares[posicoes.index(replaced_member.pk)] = self.alternate
        return titulares

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """Alvo compatível com o tipo do edital; quatro professores
        distintos, todos do programa da banca e credenciados; uma banca por
        (edital, nível, alvo) — espelho da UniqueConstraint, com NULL igual
        a NULL."""
        super().clean()
        membros = [
            m for m in (getattr(self, papel, None) for papel in self.PAPEIS) if m
        ]
        if len({m.pk for m in membros}) != len(membros):
            raise DomainError(
                "Um professor não pode ocupar dois lugares na mesma banca.",
                code="duplicate_board_member",
            )
        for membro in membros:
            if membro.program_id != self.program_id:
                raise DomainError(
                    "Todos os membros da banca precisam ser professores "
                    "deste programa.",
                    code="teacher_from_other_program",
                )
            if not membro.is_accredited:
                raise DomainError(
                    "Professor descredenciado não pode compor banca.",
                    code="teacher_not_accredited",
                )
        if self.process_id is None:
            return
        self.process.ensure_target(self.project, self.research_line)
        duplicatas = Board.objects.filter(
            process_id=self.process_id,
            level=self.level,
            project_id=self.project_id,
            research_line_id=self.research_line_id,
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Já existe banca para este nível e este alvo neste edital.",
                code="duplicate_board",
            )


# ---------------------------------------------------------------------------
# Application (inscrição)
# ---------------------------------------------------------------------------


def cpf_valido(cpf: str) -> bool:
    """Onze dígitos e os dois verificadores do mod-11 conferindo.

    Sequências repetidas (`11111111111`) passam no mod-11 e por isso são
    barradas à parte — é o CPF "de teste" que todo formulário público
    recebe. Não consulta a Receita: a validação diz que o número é bem
    formado, não que pertence ao candidato.
    """
    if len(cpf) != 11 or not cpf.isdigit() or cpf == cpf[0] * 11:
        return False
    digitos = [int(d) for d in cpf]
    for posicao in (9, 10):
        soma = sum(
            d * peso
            for d, peso in zip(
                digitos[:posicao], range(posicao + 1, 1, -1), strict=True
            )
        )
        esperado = (soma * 10 % 11) % 10
        if digitos[posicao] != esperado:
            return False
    return True


def gerar_protocolo(process: SelectionProcess) -> str:
    """`PS{ano}{R|S}-{8 hex maiúsculos}` — é o que o candidato anota e
    digita na consulta pública. `secrets` porque o protocolo é o único
    segredo entre o candidato e a inscrição dele; a unicidade é da coluna,
    e quem gera tenta de novo na colisão (32 bits: rara, não impossível).
    """
    letra = "R" if process.kind == SelectionKind.REGULAR else "S"
    return f"PS{process.year}{letra}-{secrets.token_hex(4).upper()}"


DESFECHOS_CLASSIFICADOS = frozenset(
    {RankingOutcome.CLASSIFIED_OPEN, RankingOutcome.CLASSIFIED_QUOTA}
)


class ApplicationQuerySet(models.QuerySet["Application"]):
    def for_program(self, program: Any) -> "ApplicationQuerySet":
        return self.filter(program=program)

    def for_process(self, process: Any) -> "ApplicationQuerySet":
        return self.filter(process=process)

    def alive(self) -> "ApplicationQuerySet":
        """Quem ainda disputa: homologada e não eliminada nem aprovada.

        Promoção entre etapas não muda o status (deriva da ata assinada),
        então "viva" é exatamente `homologated`.
        """
        return self.filter(status=ApplicationStatus.HOMOLOGATED)

    def approved(self) -> "ApplicationQuerySet":
        return self.filter(status=ApplicationStatus.APPROVED)

    def for_target(
        self, level: str, project: Any, research_line: Any
    ) -> "ApplicationQuerySet":
        """Mesmo nível e mesmo alvo — a unidade da banca, da ata e da
        classificação. Um dos dois alvos é sempre `None` (XOR)."""
        return self.filter(level=level, project=project, research_line=research_line)

    def convocable_for(self, stage: "SelectionStage") -> "ApplicationQuerySet":
        """Quem pode ser convocado para a etapa: as inscrições vivas do
        edital. Versão simples — `f4-convocacoes-api` refina para exigir
        aprovação na etapa anterior."""
        return self.for_process(stage.process_id).alive()


class Application(models.Model):
    """Inscrição de um candidato em um edital, para um nível × alvo × cota.

    Nasce pelo formulário público (`submit_application`), sem usuário:
    o candidato não tem conta e o protocolo é a chave dele. Mesmo CPF
    pode se inscrever no Regular e no Suplementar do mesmo ano — a unique
    é por edital.

    As transições não salvam (`InvalidStateTransition` = 409); o instante
    da decisão vem de fora, como em `SelectionProcess.publish(at)`.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_applications",
        verbose_name="programa",
    )
    process = models.ForeignKey(
        SelectionProcess,
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name="edital",
    )
    protocol = models.CharField("protocolo", max_length=20, unique=True)
    full_name = models.CharField("nome completo", max_length=200)
    email = models.EmailField("e-mail")
    cpf = models.CharField("CPF", max_length=11)
    birth_date = models.DateField("data de nascimento")
    phone_number = models.CharField("telefone", max_length=30, blank=True)
    level = models.CharField("nível", max_length=20, choices=SelectionLevel)
    project = models.ForeignKey(
        "programs.CollectiveProject",
        on_delete=models.PROTECT,
        related_name="selection_applications",
        null=True,
        blank=True,
        verbose_name="projeto coletivo",
    )
    research_line = models.ForeignKey(
        "programs.ResearchLine",
        on_delete=models.PROTECT,
        related_name="selection_applications",
        null=True,
        blank=True,
        verbose_name="linha de pesquisa",
    )
    quota_category = models.CharField(
        "categoria de cota", max_length=20, choices=QuotaCategory
    )
    status = models.CharField(
        "situação",
        max_length=20,
        choices=ApplicationStatus,
        default=ApplicationStatus.SUBMITTED,
    )
    decision_note = models.TextField("nota da decisão", blank=True)
    decided_at = models.DateTimeField("decidida em", null=True, blank=True)
    eliminated_at_stage = models.ForeignKey(
        SelectionStage,
        on_delete=models.PROTECT,
        related_name="eliminated_applications",
        null=True,
        blank=True,
        verbose_name="eliminada na etapa",
    )
    final_score = models.DecimalField(
        "nota final", max_digits=5, decimal_places=2, null=True, blank=True
    )
    final_rank = models.PositiveIntegerField("classificação", null=True, blank=True)
    final_outcome = models.CharField(
        "resultado", max_length=20, choices=RankingOutcome, blank=True
    )
    ranked_at = models.DateTimeField("classificada em", null=True, blank=True)
    student = models.OneToOneField(
        "academic.Student",
        on_delete=models.PROTECT,
        related_name="selection_application",
        null=True,
        blank=True,
        verbose_name="aluno",
    )
    submitted_at = models.DateTimeField("inscrita em")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ApplicationQuerySet.as_manager()

    class Meta:
        verbose_name = "inscrição"
        verbose_name_plural = "inscrições"
        ordering = ["process", "full_name"]
        constraints = [
            xor_de_alvo("application"),
            models.UniqueConstraint(
                fields=["process", "cpf"],
                name="unique_inscricao_por_edital_e_cpf",
            ),
            models.CheckConstraint(
                condition=models.Q(final_score__isnull=True)
                | models.Q(final_score__gte=0, final_score__lte=100),
                name="application_final_score_range",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=ApplicationStatus.ELIMINATED)
                | models.Q(eliminated_at_stage__isnull=False),
                name="application_eliminated_requires_stage",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=ApplicationStatus.ENROLLED)
                | models.Q(student__isnull=False),
                name="application_enrolled_requires_student",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.protocol} — {self.full_name}"

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """CPF bem formado, nascimento no passado, alvo e cota compatíveis
        com o edital e um CPF por edital (espelho da UniqueConstraint)."""
        super().clean()
        if not cpf_valido(self.cpf or ""):
            raise DomainError("O CPF informado não é válido.", code="invalid_cpf")
        if self.birth_date is not None and self.birth_date >= date.today():
            raise DomainError(
                "A data de nascimento precisa estar no passado.",
                code="invalid_birth_date",
            )
        if self.process_id is None:
            return
        self.process.ensure_target(self.project, self.research_line)
        if self.quota_category:
            self.process.ensure_quota_category(self.quota_category)
        duplicatas = Application.objects.filter(
            process_id=self.process_id, cpf=self.cpf
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Já existe inscrição com este CPF neste edital.",
                code="duplicate_application",
            )

    # -- documentos -------------------------------------------------------

    def required_document_kinds(self) -> list[str]:
        """Os documentos que esta inscrição precisa ter, na ordem da tela.

        Depende do tipo do edital (resumo expandido no Regular, memorial no
        Suplementar) e da cota (comprovação fora da ampla concorrência).
        """
        exigidos = [
            ApplicationDocumentKind.IDENTITY,
            ApplicationDocumentKind.DIPLOMA,
            ApplicationDocumentKind.LATTES,
            ApplicationDocumentKind.PAYMENT_RECEIPT,
        ]
        if self.process.kind == SelectionKind.REGULAR:
            exigidos.append(ApplicationDocumentKind.EXPANDED_ABSTRACT)
        else:
            exigidos.append(ApplicationDocumentKind.MEMORIAL)
        if self.quota_category != QuotaCategory.OPEN:
            exigidos.append(ApplicationDocumentKind.QUOTA_PROOF)
        return [str(k) for k in exigidos]

    def missing_documents(self, present: Iterable[str] | None = None) -> list[str]:
        """Exigidos que faltam. `present` permite checar o lote do POST
        antes de gravar qualquer arquivo; sem ele, consulta os anexos."""
        if present is None:
            present = self.documents.values_list("kind", flat=True)
        existentes = set(present)
        return [k for k in self.required_document_kinds() if k not in existentes]

    # -- estado -----------------------------------------------------------

    def _exigir_status(self, *esperados: str) -> None:
        if self.status not in esperados:
            rotulos = " ou ".join(ApplicationStatus(e).label.lower() for e in esperados)
            raise InvalidStateTransition(
                f"A inscrição precisa estar {rotulos}; está "
                f"{self.get_status_display().lower()}.",
                code=f"application_not_{esperados[0]}",
            )

    def homologate(self, at: datetime, note: str = "") -> None:
        self._exigir_status(ApplicationStatus.SUBMITTED)
        self.status = ApplicationStatus.HOMOLOGATED
        self.decision_note = note
        self.decided_at = at

    def reject(self, at: datetime, note: str) -> None:
        self._exigir_status(ApplicationStatus.SUBMITTED)
        if not note.strip():
            raise DomainError(
                "Indeferir exige uma justificativa.", code="rejection_requires_note"
            )
        self.status = ApplicationStatus.REJECTED
        self.decision_note = note
        self.decided_at = at

    def eliminate(self, stage: SelectionStage) -> None:
        """Sistema, ao fechar a etapa: faltou ou ficou abaixo do corte."""
        self._exigir_status(ApplicationStatus.HOMOLOGATED)
        if stage.process_id != self.process_id:
            raise DomainError(
                "A etapa não pertence ao edital desta inscrição.",
                code="stage_mismatch",
            )
        self.status = ApplicationStatus.ELIMINATED
        self.eliminated_at_stage = stage

    def approve(self, score: Decimal) -> None:
        """Sistema, ao fechar a última etapa com nota no corte ou acima."""
        self._exigir_status(ApplicationStatus.HOMOLOGATED)
        if not Decimal(0) <= score <= NOTA_MAXIMA:
            raise DomainError(
                f"A nota final fica entre 0 e {NOTA_MAXIMA}.", code="invalid_score"
            )
        self.status = ApplicationStatus.APPROVED
        self.final_score = score

    def reinstate(self) -> None:
        """Eliminada volta a viva. Fase 2: só a retificação de ata chama."""
        self._exigir_status(ApplicationStatus.ELIMINATED)
        self.status = ApplicationStatus.HOMOLOGATED
        self.eliminated_at_stage = None

    def enroll(self, student: Any) -> None:
        """Aprovada e classificada vira aluno (`convert_to_student`)."""
        self._exigir_status(ApplicationStatus.APPROVED)
        if self.final_outcome not in DESFECHOS_CLASSIFICADOS:
            raise InvalidStateTransition(
                "Só uma inscrição classificada pode ser convertida em aluno.",
                code="not_classified",
            )
        self.status = ApplicationStatus.ENROLLED
        self.student = student


# ---------------------------------------------------------------------------
# ApplicationDocument (anexo da inscrição)
# ---------------------------------------------------------------------------


def caminho_do_documento_de_inscricao(
    instance: "ApplicationDocument", filename: str
) -> str:
    """`selecao/edital-{id}/inscricao-{id}/{filename}` — mesmo prefixo do
    PDF do edital e das atas (ver `caminho_do_edital`)."""
    return (
        f"selecao/edital-{instance.application.process_id}/"
        f"inscricao-{instance.application_id}/{filename}"
    )


class ApplicationDocument(models.Model):
    """Um documento anexado à inscrição, um por tipo.

    Sem FK `program` (filho de agregado, como `RequestDocument` em
    `academic`): quem é auditado é a inscrição. A permissão custom
    `download_applicationdocument` separa "ver a lista" de "abrir o
    arquivo" — a segunda expõe dado pessoal do candidato.
    """

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="inscrição",
    )
    kind = models.CharField("tipo", max_length=20, choices=ApplicationDocumentKind)
    file = models.FileField("arquivo", upload_to=caminho_do_documento_de_inscricao)
    uploaded_at = models.DateTimeField("anexado em", auto_now_add=True)

    class Meta:
        verbose_name = "documento da inscrição"
        verbose_name_plural = "documentos da inscrição"
        ordering = ["application", "kind"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "kind"],
                name="unique_documento_por_inscricao_e_tipo",
            ),
        ]
        permissions = [
            ("download_applicationdocument", "Pode baixar documento da inscrição"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.application_id}"

    @classmethod
    def validate_upload(cls, *, filename: str, size: int) -> None:
        """Formato e tamanho do que chega, com as mesmas constantes de
        `academic.RequestDocument` (uma fonte para o que o programa aceita
        como anexo). Método de classe: recusa antes de existir instância."""
        if not filename or not filename.lower().endswith(EXTENSOES_DE_DOCUMENTO):
            aceitas = ", ".join(EXTENSOES_DE_DOCUMENTO)
            raise DomainError(
                f"O documento precisa ser um arquivo {aceitas}.",
                code="invalid_document",
            )
        if size > TAMANHO_MAXIMO_DO_DOCUMENTO:
            limite = TAMANHO_MAXIMO_DO_DOCUMENTO // (1024 * 1024)
            raise DomainError(
                f"O documento tem no máximo {limite} MB.", code="invalid_document"
            )

    def clean(self) -> None:
        """Um documento por tipo na inscrição (espelho da UniqueConstraint)."""
        super().clean()
        if self.application_id is None:
            return
        duplicatas = ApplicationDocument.objects.filter(
            application_id=self.application_id, kind=self.kind
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "A inscrição já tem um documento deste tipo.",
                code="duplicate_document",
            )


# ---------------------------------------------------------------------------
# StageScore (nota de uma etapa)
# ---------------------------------------------------------------------------


class StageScoreQuerySet(models.QuerySet["StageScore"]):
    def for_stage(self, stage: Any) -> "StageScoreQuerySet":
        return self.filter(stage=stage)

    def for_target(
        self, level: str, project: Any, research_line: Any
    ) -> "StageScoreQuerySet":
        """Notas das inscrições de um nível × alvo — o recorte da ata."""
        return self.filter(
            application__level=level,
            application__project=project,
            application__research_line=research_line,
        )


class StageScore(models.Model):
    """Nota de uma inscrição em uma etapa — rascunho até a ata assinar.

    Três situações, e a diferença importa para a ata:

    - linha com `score`: o candidato foi avaliado;
    - linha com `absent=True`: faltou (elimina);
    - **sem linha**: não avaliado, porque foi eliminado antes ou porque a
      etapa ainda não chegou.

    `absent` e `score` são XOR (constraint e `clean()`); a nota vale de 0 a
    100 e o corte é `NOTA_DE_CORTE`. Enquanto a ata corrente da (etapa ×
    nível × alvo) está em rascunho a banca pode reescrever a linha; com
    ela congelada ou assinada a nota é só leitura (`record_frozen`, na
    rota — o model não conhece a ata).
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_stage_scores",
        verbose_name="programa",
    )
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="scores",
        verbose_name="inscrição",
    )
    stage = models.ForeignKey(
        SelectionStage,
        on_delete=models.PROTECT,
        related_name="scores",
        verbose_name="etapa",
    )
    score = models.DecimalField(
        "nota", max_digits=5, decimal_places=2, null=True, blank=True
    )
    absent = models.BooleanField("ausente", default=False)
    entered_by = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="selection_scores_entered",
        null=True,
        blank=True,
        verbose_name="lançada por",
    )
    # Carimbo técnico da última escrita da linha; o instante de negócio
    # que conta é o `frozen_at`/`signed_at` da ata.
    entered_at = models.DateTimeField("lançada em", auto_now=True)

    objects = StageScoreQuerySet.as_manager()

    class Meta:
        verbose_name = "nota da etapa"
        verbose_name_plural = "notas da etapa"
        ordering = ["stage", "application"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "stage"],
                name="unique_nota_por_inscricao_e_etapa",
            ),
            models.CheckConstraint(
                condition=models.Q(absent=True, score__isnull=True)
                | models.Q(absent=False, score__isnull=False),
                name="stagescore_absent_xor_score",
            ),
            models.CheckConstraint(
                condition=models.Q(score__isnull=True)
                | models.Q(score__gte=0, score__lte=100),
                name="stagescore_score_range",
            ),
        ]

    def __str__(self) -> str:
        nota = "ausente" if self.absent else str(self.score)
        return f"{self.application_id} × {self.stage_id}: {nota}"

    @property
    def passed(self) -> bool:
        """No corte ou acima; ausente nunca passa."""
        return (
            not self.absent and self.score is not None and self.score >= NOTA_DE_CORTE
        )

    def as_record_row(self) -> dict[str, Any]:
        """A linha desta nota no `content` da ata.

        `score` vai como texto (`"85.50"`) porque JSON não tem `Decimal` e
        `float` mudaria o hash entre gravações (armadilha 7 do plano).
        """
        inscricao = self.application
        return {
            "application_id": inscricao.pk,
            "protocol": inscricao.protocol,
            "full_name": inscricao.full_name,
            "quota_category": str(inscricao.quota_category),
            "score": None if self.score is None else str(self.score),
            "absent": self.absent,
            "passed": self.passed,
        }

    def clean(self) -> None:
        """XOR entre ausência e nota, nota no intervalo, etapa do mesmo
        edital da inscrição e uma linha por (inscrição, etapa) — espelho
        da UniqueConstraint."""
        super().clean()
        if self.absent == (self.score is not None):
            raise DomainError(
                "Informe a nota ou marque ausência — um dos dois, nunca ambos.",
                code="absent_xor_score",
            )
        if self.score is not None and not Decimal(0) <= self.score <= NOTA_MAXIMA:
            raise DomainError(
                f"A nota fica entre 0 e {NOTA_MAXIMA}.", code="invalid_score"
            )
        if self.application_id is None or self.stage_id is None:
            return
        if self.stage.process_id != self.application.process_id:
            raise DomainError(
                "A etapa não pertence ao edital desta inscrição.",
                code="stage_mismatch",
            )
        duplicatas = StageScore.objects.filter(
            application_id=self.application_id, stage_id=self.stage_id
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Esta inscrição já tem nota nesta etapa.", code="duplicate_score"
            )


# ---------------------------------------------------------------------------
# ExaminationRecord (ata)
# ---------------------------------------------------------------------------


def caminho_da_ata(instance: "ExaminationRecord", filename: str) -> str:
    """`selecao/edital-{id}/atas/ata-{id}-v{version}.pdf` — o nome vem da
    própria ata, não do upload: o PDF é gerado pelo sistema."""
    return (
        f"selecao/edital-{instance.process_id}/atas/"
        f"ata-{instance.pk}-v{instance.version}.pdf"
    )


def hash_canonico(documento: Any) -> str:
    """SHA-256 da serialização canônica de um JSON (armadilha 9 do plano).

    `sort_keys` + separadores sem espaço + `ensure_ascii=False`: o mesmo
    dicionário produz sempre os mesmos bytes, independentemente da ordem
    de inserção ou de quem serializou.
    """
    texto = json.dumps(
        documento, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


class ExaminationRecordQuerySet(models.QuerySet["ExaminationRecord"]):
    def for_program(self, program: Any) -> "ExaminationRecordQuerySet":
        return self.filter(program=program)

    def for_process(self, process: Any) -> "ExaminationRecordQuerySet":
        return self.filter(process=process)

    def current(self) -> "ExaminationRecordQuerySet":
        """Atas vigentes: tudo que não foi substituído por versão nova."""
        return self.exclude(status=RecordStatus.SUPERSEDED)

    def for_key(
        self, stage: Any, level: str, project: Any, research_line: Any
    ) -> "ExaminationRecordQuerySet":
        """Todas as versões da ata de uma (etapa × nível × alvo)."""
        return self.filter(
            stage=stage, level=level, project=project, research_line=research_line
        )


class ExaminationRecord(models.Model):
    """Ata de uma etapa para um nível × alvo, versionável.

    O `content` é a fotografia das notas no instante do congelamento —
    lista de linhas ordenada por nome, uma por inscrição viva do alvo.
    O `content_hash` é o que cada assinatura confere: se a ata mudar
    entre congelar e assinar, a assinatura recusa (`record_changed`).

    Versão: retificação (fase 2) cria a versão `n+1` apontando para a
    anterior em `supersedes`; quando a nova fica assinada, a anterior
    vira `superseded`. Há sempre no máximo **uma ata corrente** (não
    substituída) por chave — invariante do `clean()`.

    As transições não salvam, como nos demais models do app.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_records",
        verbose_name="programa",
    )
    process = models.ForeignKey(
        SelectionProcess,
        on_delete=models.PROTECT,
        related_name="records",
        verbose_name="edital",
    )
    stage = models.ForeignKey(
        SelectionStage,
        on_delete=models.PROTECT,
        related_name="records",
        verbose_name="etapa",
    )
    level = models.CharField("nível", max_length=20, choices=SelectionLevel)
    project = models.ForeignKey(
        "programs.CollectiveProject",
        on_delete=models.PROTECT,
        related_name="selection_records",
        null=True,
        blank=True,
        verbose_name="projeto coletivo",
    )
    research_line = models.ForeignKey(
        "programs.ResearchLine",
        on_delete=models.PROTECT,
        related_name="selection_records",
        null=True,
        blank=True,
        verbose_name="linha de pesquisa",
    )
    board = models.ForeignKey(
        Board,
        on_delete=models.PROTECT,
        related_name="records",
        verbose_name="banca",
    )
    replaced_member = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="selection_records_replaced_in",
        null=True,
        blank=True,
        verbose_name="titular impedido",
    )
    version = models.PositiveSmallIntegerField("versão", default=1)
    supersedes = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="superseded_by",
        null=True,
        blank=True,
        verbose_name="substitui a versão",
    )
    rectification_reason = models.TextField("motivo da retificação", blank=True)
    status = models.CharField(
        "situação",
        max_length=20,
        choices=RecordStatus,
        default=RecordStatus.DRAFT,
    )
    content = models.JSONField("conteúdo", default=list, blank=True)
    content_hash = models.CharField("hash do conteúdo", max_length=64, blank=True)
    pdf = models.FileField("PDF", upload_to=caminho_da_ata, blank=True)
    frozen_at = models.DateTimeField("congelada em", null=True, blank=True)
    signed_at = models.DateTimeField("assinada em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ExaminationRecordQuerySet.as_manager()

    class Meta:
        verbose_name = "ata de exame"
        verbose_name_plural = "atas de exame"
        ordering = ["process", "stage", "level", "project", "research_line", "version"]
        constraints = [
            xor_de_alvo("examinationrecord"),
            models.UniqueConstraint(
                fields=[
                    "process",
                    "stage",
                    "level",
                    "project",
                    "research_line",
                    "version",
                ],
                nulls_distinct=False,
                name="unique_ata_por_edital_etapa_nivel_alvo_e_versao",
            ),
            # version = 1 ⇔ supersedes IS NULL
            models.CheckConstraint(
                condition=models.Q(version=1, supersedes__isnull=True)
                | models.Q(version__gt=1, supersedes__isnull=False),
                name="examinationrecord_version_matches_supersedes",
            ),
        ]
        permissions = [
            ("sign_examinationrecord", "Pode assinar ata de exame"),
        ]

    def __str__(self) -> str:
        return f"Ata {self.stage_id} — {self.get_level_display()} v{self.version}"

    # -- leitura ----------------------------------------------------------

    @property
    def is_current(self) -> bool:
        return self.status != RecordStatus.SUPERSEDED

    @property
    def is_draft(self) -> bool:
        return self.status == RecordStatus.DRAFT

    @property
    def is_frozen(self) -> bool:
        """Congelada ou assinada: as notas por trás dela são só leitura."""
        return self.status in (RecordStatus.AWAITING_SIGNATURES, RecordStatus.SIGNED)

    def expected_signers(self) -> list[Any]:
        """Quem assina: delega à banca, com o titular impedido trocado
        pelo suplente."""
        return self.board.expected_signers(self.replaced_member)

    # -- hash -------------------------------------------------------------

    def canonical_document(self) -> dict[str, Any]:
        """Cabeçalho (ids e versão) + conteúdo: é isto que é hasheado.

        O cabeçalho entra para que o mesmo conteúdo em outra etapa, outra
        banca ou outra versão produza hash diferente — assinatura não é
        reaproveitável entre atas.
        """
        return {
            "process_id": self.process_id,
            "stage_id": self.stage_id,
            "board_id": self.board_id,
            "level": str(self.level),
            "project_id": self.project_id,
            "research_line_id": self.research_line_id,
            "replaced_member_id": self.replaced_member_id,
            "version": self.version,
            "content": self.content,
        }

    def compute_hash(self) -> str:
        return hash_canonico(self.canonical_document())

    def verify_hash(self) -> bool:
        """O conteúdo gravado ainda corresponde ao hash que foi assinado?"""
        return bool(self.content_hash) and self.compute_hash() == self.content_hash

    @staticmethod
    def normalize_content(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ordena por nome (e protocolo, no empate) e força `score` a texto.

        Chamado por `freeze`, para que o hash não dependa da ordem em que
        as notas saíram do banco nem do tipo com que a nota chegou.
        """
        normalizadas = []
        for row in rows:
            score = row.get("score")
            normalizadas.append(
                {**row, "score": None if score is None else str(Decimal(str(score)))}
            )
        return sorted(normalizadas, key=lambda r: (r["full_name"], r["protocol"]))

    # -- estado -----------------------------------------------------------

    def _exigir_status(self, esperado: str) -> None:
        if self.status != esperado:
            raise InvalidStateTransition(
                f"A ata precisa estar {RecordStatus(esperado).label.lower()}; "
                f"está {self.get_status_display().lower()}.",
                code=f"record_not_{esperado}",
            )

    def freeze(self, content: Iterable[dict[str, Any]], at: datetime) -> None:
        """Rascunho → aguardando assinaturas, com conteúdo e hash fixados.

        Ata sem candidato não existe: a etapa sem ninguém vivo no alvo
        não tem o que assinar.
        """
        self._exigir_status(RecordStatus.DRAFT)
        linhas = self.normalize_content(content)
        if not linhas:
            raise DomainError(
                "Não há candidato vivo neste nível e alvo para compor a ata.",
                code="no_candidates",
            )
        self.content = linhas
        self.content_hash = self.compute_hash()
        self.frozen_at = at
        self.status = RecordStatus.AWAITING_SIGNATURES

    def reopen(self) -> None:
        """Aguardando assinaturas → rascunho. Quem garante que não há
        assinatura dada (e apaga as pendentes) é o service."""
        self._exigir_status(RecordStatus.AWAITING_SIGNATURES)
        self.status = RecordStatus.DRAFT
        self.content_hash = ""
        self.frozen_at = None

    def mark_signed(self, at: datetime) -> None:
        """Sistema, na última assinatura."""
        self._exigir_status(RecordStatus.AWAITING_SIGNATURES)
        self.status = RecordStatus.SIGNED
        self.signed_at = at

    def supersede(self) -> None:
        """Sistema, quando a versão seguinte fica assinada."""
        self._exigir_status(RecordStatus.SIGNED)
        self.status = RecordStatus.SUPERSEDED

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """Alvo compatível com o edital e igual ao da banca; etapa do
        edital; versão coerente com `supersedes`; titular impedido é
        titular da banca; uma ata corrente por chave e uma versão por
        chave (espelhos da UniqueConstraint, NULL igual a NULL)."""
        super().clean()
        if (self.version == 1) != (self.supersedes_id is None):
            raise DomainError(
                "A primeira versão não substitui ninguém; as seguintes "
                "precisam apontar a versão anterior.",
                code="invalid_version",
            )
        anterior = getattr(self, "supersedes", None)
        if anterior is not None and anterior.version + 1 != self.version:
            raise DomainError(
                "A versão nova é a seguinte à que ela substitui.",
                code="invalid_version",
            )
        if self.process_id is None:
            return
        self.process.ensure_target(self.project, self.research_line)
        if self.stage_id is not None and self.stage.process_id != self.process_id:
            raise DomainError(
                "A etapa não pertence a este edital.", code="stage_mismatch"
            )
        banca = getattr(self, "board", None)
        if banca is not None:
            if (banca.level, banca.project_id, banca.research_line_id) != (
                self.level,
                self.project_id,
                self.research_line_id,
            ):
                raise DomainError(
                    "A banca não é a deste nível e alvo.", code="board_mismatch"
                )
            impedido = getattr(self, "replaced_member", None)
            if impedido is not None:
                banca.expected_signers(impedido)  # → not_a_titular_member
        mesma_chave = ExaminationRecord.objects.for_key(
            self.stage_id, self.level, self.project_id, self.research_line_id
        ).filter(process_id=self.process_id)
        if self.pk is not None:
            mesma_chave = mesma_chave.exclude(pk=self.pk)
        if self.is_current and mesma_chave.current().exists():
            raise DomainError(
                "Já existe ata vigente para esta etapa, nível e alvo.",
                code="record_already_exists",
            )
        if mesma_chave.filter(version=self.version).exists():
            raise DomainError(
                "Já existe esta versão da ata para esta etapa, nível e alvo.",
                code="duplicate_record",
            )


# ---------------------------------------------------------------------------
# RecordSignature (assinatura da ata)
# ---------------------------------------------------------------------------

VALIDADE_DO_TOKEN = timedelta(days=7)


def hash_do_token(raw: str) -> str:
    """Só o SHA-256 do token vai para o banco: quem lê a tabela não
    consegue assinar por ninguém."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RecordSignatureQuerySet(models.QuerySet["RecordSignature"]):
    def pending(self) -> "RecordSignatureQuerySet":
        return self.filter(signed_at__isnull=True)

    def by_token(self, raw: str) -> "RecordSignatureQuerySet":
        """Assinatura dona do token em texto — a rota pública nunca vê o
        hash, e o banco nunca vê o texto."""
        return self.filter(method=SignatureMethod.TOKEN, token_hash=hash_do_token(raw))


class RecordSignature(models.Model):
    """Assinatura de um signatário em uma ata congelada.

    Nasce pendente (`signed_at` nulo) no congelamento, uma por
    `expected_signers`. Professor do programa assina logado
    (`method=login`); o externo, que não tem conta, assina por token
    recebido por e-mail (`method=token`) — o método é decidido pela
    categoria do signatário, não escolhido.

    `signed_hash` guarda o hash que o signatário viu: é a prova de que
    todos assinaram o mesmo conteúdo.
    """

    record = models.ForeignKey(
        ExaminationRecord,
        on_delete=models.PROTECT,
        related_name="signatures",
        verbose_name="ata",
    )
    signer = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="selection_signatures",
        verbose_name="signatário",
    )
    method = models.CharField("método", max_length=20, choices=SignatureMethod)
    signed_at = models.DateTimeField("assinada em", null=True, blank=True)
    signed_hash = models.CharField("hash assinado", max_length=64, blank=True)
    signed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="selection_signatures",
        null=True,
        blank=True,
        verbose_name="conta que assinou",
    )
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    token_hash = models.CharField("hash do token", max_length=64, blank=True)
    token_expires_at = models.DateTimeField("token expira em", null=True, blank=True)
    token_sent_at = models.DateTimeField("token enviado em", null=True, blank=True)
    token_used_at = models.DateTimeField("token usado em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RecordSignatureQuerySet.as_manager()

    class Meta:
        verbose_name = "assinatura da ata"
        verbose_name_plural = "assinaturas da ata"
        ordering = ["record", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "signer"],
                name="unique_assinatura_por_ata_e_signatario",
            ),
            models.CheckConstraint(
                condition=models.Q(method=SignatureMethod.TOKEN)
                | models.Q(token_hash=""),
                name="recordsignature_token_only_for_token_method",
            ),
        ]

    def __str__(self) -> str:
        situacao = "assinada" if self.is_signed else "pendente"
        return f"Assinatura {self.signer_id} na ata {self.record_id} ({situacao})"

    # -- construção -------------------------------------------------------

    @staticmethod
    def method_for(signer: Any) -> str:
        """Externo assina por token; todo o resto, logado."""
        if signer.category == signer.Category.EXTERNAL:
            return SignatureMethod.TOKEN
        return SignatureMethod.LOGIN

    @classmethod
    def for_signer(cls, record: ExaminationRecord, signer: Any) -> "RecordSignature":
        """Assinatura pendente com o método certo para o signatário."""
        return cls(record=record, signer=signer, method=cls.method_for(signer))

    # -- leitura ----------------------------------------------------------

    @property
    def is_signed(self) -> bool:
        return self.signed_at is not None

    @property
    def uses_token(self) -> bool:
        return self.method == SignatureMethod.TOKEN

    def token_valid_at(self, at: datetime) -> bool:
        """Há token emitido, não usado e dentro do prazo?"""
        return (
            bool(self.token_hash)
            and self.token_used_at is None
            and self.token_expires_at is not None
            and at < self.token_expires_at
        )

    # -- assinatura -------------------------------------------------------

    def _exigir_pendente(self) -> None:
        if self.is_signed:
            raise InvalidStateTransition(
                "Este signatário já assinou a ata.", code="already_signed"
            )

    def sign(
        self,
        at: datetime,
        content_hash: str,
        user: Any | None = None,
        ip: str | None = None,
    ) -> None:
        """Registra a assinatura sobre o hash que o signatário viu.

        Recusa se a ata não está aguardando assinaturas, se o hash visto
        não é o corrente ou se o conteúdo gravado deixou de bater com o
        hash — qualquer um dos três significa que quem assina não está
        assinando o que acha (`record_changed`).
        """
        self._exigir_pendente()
        ata = self.record
        if ata.status != RecordStatus.AWAITING_SIGNATURES:
            raise InvalidStateTransition(
                "A ata não está aguardando assinaturas.",
                code="record_not_awaiting_signatures",
            )
        if content_hash != ata.content_hash or not ata.verify_hash():
            raise InvalidStateTransition(
                "O conteúdo da ata mudou desde que foi apresentado; "
                "confira a versão atual antes de assinar.",
                code="record_changed",
            )
        self.signed_at = at
        self.signed_hash = content_hash
        self.signed_by_user = user
        self.ip_address = ip

    def ensure_can_sign_by_login(self, user: Any) -> None:
        """Só o próprio signatário, logado, e só quando o método é login."""
        if not self.uses_token and self._user_is_signer(user):
            return
        raise NotAllowed(
            "Só o próprio signatário, autenticado, pode assinar esta ata.",
            code="not_the_signer",
        )

    def _user_is_signer(self, user: Any) -> bool:
        if user is None or not getattr(user, "pk", None):
            return False
        pessoa = getattr(self.signer, "person", None)
        return pessoa is not None and pessoa.user_id == user.pk

    # -- token ------------------------------------------------------------

    def issue_token(self, at: datetime, ttl: timedelta = VALIDADE_DO_TOKEN) -> str:
        """Emite (ou reemite, invalidando o anterior) o token do externo.

        Devolve o texto **uma única vez** — é o que vai no e-mail; no
        banco fica só o hash. `token_sent_at` é do service, depois que o
        e-mail de fato saiu.
        """
        if not self.uses_token:
            raise DomainError(
                "Este signatário assina logado, não por token.",
                code="token_not_applicable",
            )
        self._exigir_pendente()
        raw = secrets.token_urlsafe(32)
        self.token_hash = hash_do_token(raw)
        self.token_expires_at = at + ttl
        self.token_sent_at = None
        self.token_used_at = None
        return raw

    def consume_token(self, at: datetime) -> None:
        """Marca o token como usado; a assinatura em si é `sign()`, na
        mesma transação."""
        if not self.uses_token or not self.token_hash:
            raise DomainError(
                "Não há token emitido para esta assinatura.",
                code="token_not_applicable",
            )
        if self.token_used_at is not None:
            raise InvalidStateTransition(
                "Este token já foi usado.", code="token_already_used"
            )
        if self.token_expires_at is None or at >= self.token_expires_at:
            raise InvalidStateTransition(
                "Este token expirou; peça à secretaria um novo.",
                code="token_expired",
            )
        self.token_used_at = at

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """Método coerente com a categoria do signatário, signatário
        esperado pela ata e um por ata (espelho da UniqueConstraint)."""
        super().clean()
        signatario = getattr(self, "signer", None)
        if signatario is not None and self.method != self.method_for(signatario):
            raise DomainError(
                "O método de assinatura é decidido pela categoria do "
                "signatário: externo assina por token, os demais logados.",
                code="signature_method_mismatch",
            )
        if not self.uses_token and self.token_hash:
            raise DomainError(
                "Assinatura por login não carrega token.",
                code="token_not_applicable",
            )
        ata = getattr(self, "record", None)
        if ata is None or signatario is None:
            return
        if signatario.pk not in {s.pk for s in ata.expected_signers()}:
            raise DomainError(
                "Este professor não é signatário desta ata.",
                code="signer_not_expected",
            )
        if self.record_id is None:
            return
        duplicatas = RecordSignature.objects.filter(
            record_id=self.record_id, signer_id=self.signer_id
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Este signatário já consta na ata.", code="duplicate_signature"
            )


# ---------------------------------------------------------------------------
# VacancyReallocation (realocação de vaga)
# ---------------------------------------------------------------------------


class VacancyReallocationQuerySet(models.QuerySet["VacancyReallocation"]):
    def for_program(self, program: Any) -> "VacancyReallocationQuerySet":
        return self.filter(program=program)

    def for_process(self, process: Any) -> "VacancyReallocationQuerySet":
        return self.filter(process=process)


class VacancyReallocation(models.Model):
    """Movimento de vaga de uma linha da grade para outra, por decisão da
    comissão ou por retificação do edital.

    Existe porque a grade de vagas congela na publicação
    (`SelectionProcess.ensure_editable`): depois disso o candidato já se
    inscreveu contra aquele conteúdo, e mudar `Vacancy.quantity` na mão
    apagaria a vaga original sem deixar rastro. Cada realocação é uma
    linha imutável, com o número do ofício ou da ata que a autorizou.

    Duas espécies (`ReallocationKind`):

    - `level_transfer` — sobrou vaga de mestrado e falta de doutorado no
      **mesmo alvo**: mesmo projeto/linha, níveis diferentes.
    - `notice_rectification` — o edital saiu com a grade errada e foi
      retificado: **mesmo nível**, alvo pode mudar.

    Assunção documentada (plano, "Assunções"; o humano confirma no
    merge): a realocação **preserva a categoria de cota** — vaga de cota
    racial não vira ampla concorrência por decisão da comissão.

    Imutável: `save()` recusa alteração. Errou? Registre a realocação
    inversa, que é como a comissão desfaz no mundo real.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_reallocations",
        verbose_name="programa",
    )
    process = models.ForeignKey(
        SelectionProcess,
        on_delete=models.PROTECT,
        related_name="reallocations",
        verbose_name="edital",
    )
    kind = models.CharField("espécie", max_length=30, choices=ReallocationKind)
    from_vacancy = models.ForeignKey(
        Vacancy,
        on_delete=models.PROTECT,
        related_name="reallocations_out",
        verbose_name="vaga de origem",
    )
    to_vacancy = models.ForeignKey(
        Vacancy,
        on_delete=models.PROTECT,
        related_name="reallocations_in",
        verbose_name="vaga de destino",
    )
    quantity = models.PositiveSmallIntegerField("quantidade")
    reason = models.TextField("motivo")
    decided_on = models.DateField("decidida em")
    decided_by_note = models.CharField(
        "ofício ou ata da decisão",
        max_length=200,
        help_text="Número do ofício ou da ata da comissão que autorizou a realocação.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = VacancyReallocationQuerySet.as_manager()

    class Meta:
        verbose_name = "realocação de vaga"
        verbose_name_plural = "realocações de vaga"
        ordering = ["-decided_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="vacancyreallocation_quantity_at_least_one",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_vacancy=models.F("to_vacancy")),
                name="vacancyreallocation_distinct_vacancies",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.quantity} vaga(s) de {self.from_vacancy_id} para "
            f"{self.to_vacancy_id} ({self.get_kind_display()})"
        )

    # -- imutabilidade -----------------------------------------------------

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Linha de histórico não se edita."""
        if not self._state.adding:
            raise InvalidStateTransition(
                "Uma realocação de vaga não pode ser alterada; registre a "
                "realocação inversa.",
                code="reallocation_is_immutable",
            )
        super().save(*args, **kwargs)

    # -- efeito ------------------------------------------------------------

    def apply_to_vacancies(self) -> None:
        """Move a quantidade entre as duas vagas, **sem salvar**.

        Quem salva (e quem trava as linhas com `select_for_update`) é o
        service `reallocate_vacancy`; aqui fica só a aritmética, para que
        ela seja testável em memória. Origem zerada continua existindo:
        `Vacancy.quantity` aceita 0 justamente para guardar o rastro.
        """
        origem, destino = self.from_vacancy, self.to_vacancy
        if self.quantity > origem.quantity:
            raise DomainError(
                "A vaga de origem não tem essa quantidade disponível.",
                code="insufficient_vacancies",
            )
        origem.quantity -= self.quantity
        destino.quantity += self.quantity

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """As duas vagas são do mesmo edital publicado, a cota é
        preservada e o par nível × alvo respeita a espécie."""
        super().clean()
        origem = getattr(self, "from_vacancy", None)
        destino = getattr(self, "to_vacancy", None)
        if origem is None or destino is None:
            return
        self._exigir_mesmo_edital(origem, destino)
        self._exigir_edital_publicado()
        if origem.quota_category != destino.quota_category:
            raise DomainError(
                "A realocação preserva a categoria de cota: origem e destino "
                "precisam ter a mesma.",
                code="quota_category_must_be_preserved",
            )
        self._exigir_alvo_da_especie(origem, destino)
        if self.quantity is not None and self.quantity > origem.quantity:
            raise DomainError(
                "A vaga de origem não tem essa quantidade disponível.",
                code="insufficient_vacancies",
            )

    def _exigir_mesmo_edital(self, origem: Vacancy, destino: Vacancy) -> None:
        editais = {origem.process_id, destino.process_id}
        if self.process_id is not None:
            editais.add(self.process_id)
        if len(editais) > 1:
            raise DomainError(
                "Origem, destino e realocação precisam ser do mesmo edital.",
                code="process_mismatch",
            )

    def _exigir_edital_publicado(self) -> None:
        """Em rascunho a grade ainda é editável — corrigir a vaga é o
        caminho, e a realocação inventaria um ofício que não existe."""
        edital = getattr(self, "process", None)
        if edital is not None and edital.is_draft:
            raise DomainError(
                "Com o edital em rascunho, corrija a grade de vagas em vez "
                "de realocar.",
                code="process_still_draft",
            )

    def _exigir_alvo_da_especie(self, origem: Vacancy, destino: Vacancy) -> None:
        mesmo_alvo = (origem.project_id, origem.research_line_id) == (
            destino.project_id,
            destino.research_line_id,
        )
        if self.kind == ReallocationKind.LEVEL_TRANSFER:
            if not mesmo_alvo or origem.level == destino.level:
                raise DomainError(
                    "A transferência entre níveis é no mesmo alvo, entre "
                    "níveis diferentes.",
                    code="same_target_required",
                )
        elif origem.level != destino.level:
            raise DomainError(
                "A retificação do edital move vagas dentro do mesmo nível.",
                code="same_level_required",
            )


# ---------------------------------------------------------------------------
# Convocation / ConvocationEmail (convocação de etapa)
# ---------------------------------------------------------------------------


class Convocation(models.Model):
    """Lote de e-mails de convocação de uma etapa, disparado pela secretaria.

    `subject` e `body_template` são **cópias** do template do edital no
    instante do envio: quem editar o edital depois não reescreve o que o
    candidato recebeu. O texto já renderizado por candidato fica em
    `ConvocationEmail`, pelo mesmo motivo.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="selection_convocations",
        verbose_name="programa",
    )
    process = models.ForeignKey(
        SelectionProcess,
        on_delete=models.PROTECT,
        related_name="convocations",
        verbose_name="edital",
    )
    stage = models.ForeignKey(
        SelectionStage,
        on_delete=models.PROTECT,
        related_name="convocations",
        verbose_name="etapa",
    )
    subject = models.CharField("assunto", max_length=200)
    body_template = models.TextField("corpo (template)")
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="selection_convocations",
        null=True,
        blank=True,
        verbose_name="enviada por",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "convocação"
        verbose_name_plural = "convocações"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Convocação da etapa {self.stage_id}"

    @classmethod
    def from_process(
        cls, process: SelectionProcess, stage: SelectionStage, **extra: Any
    ) -> "Convocation":
        """Lote com o template do edital já copiado."""
        return cls(
            program_id=process.program_id,
            process=process,
            stage=stage,
            subject=process.convocation_subject,
            body_template=process.convocation_body,
            **extra,
        )

    def render_for(self, application: Any) -> tuple[str, str]:
        """Assunto e corpo desta convocação para um candidato, a partir
        das cópias do lote — não do template atual do edital."""
        return renderizar_convocacao(
            subject=self.subject,
            body=self.body_template,
            application=application,
            stage=self.stage,
            process_title=self.process.title,
        )

    def email_for(self, application: Any) -> "ConvocationEmail":
        """E-mail pendente, com o texto já renderizado e congelado."""
        assunto, corpo = self.render_for(application)
        return ConvocationEmail(
            convocation=self,
            application=application,
            to_email=application.email,
            rendered_subject=assunto,
            rendered_body=corpo,
        )

    def clean(self) -> None:
        """A etapa é do edital do lote, e o edital tem template."""
        super().clean()
        etapa = getattr(self, "stage", None)
        if (
            etapa is not None
            and self.process_id is not None
            and etapa.process_id != self.process_id
        ):
            raise DomainError(
                "A etapa não pertence ao edital desta convocação.",
                code="stage_mismatch",
            )
        if not (self.subject or "").strip() or not (self.body_template or "").strip():
            raise DomainError(
                "O edital não tem assunto e corpo de convocação preenchidos.",
                code="convocation_template_missing",
            )


class ConvocationEmailQuerySet(models.QuerySet["ConvocationEmail"]):
    def pending(self) -> "ConvocationEmailQuerySet":
        return self.filter(status=EmailDeliveryStatus.PENDING)

    def sent(self) -> "ConvocationEmailQuerySet":
        return self.filter(status=EmailDeliveryStatus.SENT)

    def failed(self) -> "ConvocationEmailQuerySet":
        return self.filter(status=EmailDeliveryStatus.FAILED)

    def to_send(self) -> "ConvocationEmailQuerySet":
        """O que o reenvio pega: pendente ou falhado, nunca o que já saiu
        — reenviar um e-mail entregue é spam para o candidato."""
        return self.exclude(status=EmailDeliveryStatus.SENT)


class ConvocationEmail(models.Model):
    """Um e-mail de convocação para um candidato, com o resultado do envio.

    Filho de agregado (CASCADE em `convocation`): chega ao programa pelo
    lote. Guarda o texto renderizado, o número de tentativas e o erro da
    última falha — sem fila nem agendador (ADR-009), o reenvio é a
    secretaria clicando de novo.
    """

    convocation = models.ForeignKey(
        Convocation,
        on_delete=models.CASCADE,
        related_name="emails",
        verbose_name="convocação",
    )
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="convocation_emails",
        verbose_name="inscrição",
    )
    to_email = models.EmailField("destinatário")
    rendered_subject = models.CharField("assunto enviado", max_length=200)
    rendered_body = models.TextField("corpo enviado")
    status = models.CharField(
        "situação",
        max_length=20,
        choices=EmailDeliveryStatus,
        default=EmailDeliveryStatus.PENDING,
    )
    error = models.TextField("erro", blank=True)
    attempts = models.PositiveSmallIntegerField("tentativas", default=0)
    sent_at = models.DateTimeField("enviado em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConvocationEmailQuerySet.as_manager()

    class Meta:
        verbose_name = "e-mail de convocação"
        verbose_name_plural = "e-mails de convocação"
        ordering = ["convocation", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["convocation", "application"],
                name="unique_email_por_convocacao_e_inscricao",
            ),
            # Carimbo e situação andam juntos: "enviado" sem instante é um
            # envio que ninguém sabe quando aconteceu.
            models.CheckConstraint(
                condition=models.Q(
                    status=EmailDeliveryStatus.SENT, sent_at__isnull=False
                )
                | (
                    ~models.Q(status=EmailDeliveryStatus.SENT)
                    & models.Q(sent_at__isnull=True)
                ),
                name="convocationemail_sent_at_matches_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.to_email} ({self.get_status_display()})"

    @property
    def is_sent(self) -> bool:
        return self.status == EmailDeliveryStatus.SENT

    # -- transições (não salvam) -------------------------------------------

    def _exigir_nao_enviado(self) -> None:
        if self.is_sent:
            raise InvalidStateTransition(
                "Este e-mail já foi enviado.", code="email_already_sent"
            )

    def mark_sent(self, at: datetime) -> None:
        """Envio deu certo: conta a tentativa e limpa o erro anterior."""
        self._exigir_nao_enviado()
        self.attempts += 1
        self.status = EmailDeliveryStatus.SENT
        self.sent_at = at
        self.error = ""

    def mark_failed(self, error: str) -> None:
        """Envio falhou: conta a tentativa e guarda o motivo.

        O service chama isto dentro de um `except` por candidato — uma
        caixa postal inválida não pode derrubar o lote inteiro.
        """
        self._exigir_nao_enviado()
        self.attempts += 1
        self.status = EmailDeliveryStatus.FAILED
        self.error = error

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """A inscrição é do edital do lote e só entra uma vez nele
        (espelho da UniqueConstraint)."""
        super().clean()
        inscricao = getattr(self, "application", None)
        lote = getattr(self, "convocation", None)
        if (
            inscricao is not None
            and lote is not None
            and lote.process_id is not None
            and inscricao.process_id != lote.process_id
        ):
            raise DomainError(
                "A inscrição não pertence ao edital desta convocação.",
                code="application_from_other_process",
            )
        if self.convocation_id is None:
            return
        duplicatas = ConvocationEmail.objects.filter(
            convocation_id=self.convocation_id, application_id=self.application_id
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Esta inscrição já está nesta convocação.",
                code="duplicate_convocation_email",
            )
