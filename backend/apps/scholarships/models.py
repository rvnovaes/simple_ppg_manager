"""Models da concessão de bolsas do PPGD.

App próprio (plano `bolsas.md`): edição anual do edital, comissão, barema,
inscrição do discente, análise, classificação em faixas de prioridade,
recurso e publicação entram aqui, story a story, cada uma com a sua
migration.

Convenções válidas para todos os models deste app (não repetidas por
model):

- FK `program` direta com `PROTECT` (ADR-007), exceto filhos de agregado
  (`BaremeItem`, `CommitteeMember`, `BaremeEntry`, `ApplicationDocument`,
  `ItemReview`, `ScholarshipAppeal`), que chegam ao programa pelo pai —
  mesmo recorte de `RequestDocument` (`apps/academic/models.py`).
- `clean()` levanta `DomainError(code=...)` cobrindo `program_mismatch` e
  a duplicata de cada `UniqueConstraint` — `.save()` não roda `clean()`, e
  sem o espelho a violação vira `IntegrityError` → 500.
- QuerySet com `for_program()` como **primeiro** filtro de toda busca.
- Transições de estado **não salvam**: quem persiste é o router/service, no
  mesmo `transaction.atomic()` do `AuditLog`. `InvalidStateTransition` = 409.
- Todos os `TextChoices` no **nível do módulo**, com nome único: o gerador de
  OpenAPI batiza o schema pelo `__name__` da classe, e enums aninhados de
  nome repetido colidem — o último registrado sobrescreve o outro, sem erro
  no backend (precedente comentado em `apps/academic/models.py`).

Nada abre ou fecha por relógio: as datas do cronograma do edital são
informação, e toda mudança de estado é ato manual da secretaria — mesmo
corte das isoladas.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import models

from apps.core.exceptions import DomainError, InvalidStateTransition

# ---------------------------------------------------------------------------
# Enums de módulo
# ---------------------------------------------------------------------------


class ScholarshipEditionStatus(models.TextChoices):
    """Estados da edição anual, sempre para frente (não há volta ao rascunho).

    Correção de rumo é quebra-vidro no Admin, não transição.
    """

    DRAFT = "draft", "Rascunho"
    SUBMISSIONS_OPEN = "submissions_open", "Inscrições abertas"
    UNDER_REVIEW = "under_review", "Em análise"
    PRELIMINARY_RESULT = "preliminary_result", "Resultado preliminar"
    APPEALS_UNDER_REVIEW = "appeals_under_review", "Recursos em análise"
    FINAL_RESULT = "final_result", "Resultado final"


class ScholarshipLevel(models.TextChoices):
    """Nível do vínculo a que a bolsa se refere.

    Mesmos valores de `Student.Level` (`apps/academic/models.py`) — a
    inscrição copia o nível do aluno no ato e o congela. Enum próprio (e não
    reuso do aninhado) porque enum de módulo é a regra deste app.
    """

    MASTERS = "masters", "Mestrado"
    DOCTORATE = "doctorate", "Doutorado"


class BaremeSection(models.TextChoices):
    """As seis seções (I..VI) do barema do edital."""

    FORMATION = "formation", "I - Formação Acadêmica"
    BIBLIOGRAPHIC = "bibliographic", "II - Produção Bibliográfica"
    EVENTS = "events", "III - Participação em Eventos"
    PROFESSIONAL = "professional", "IV - Atividade Profissional"
    BOARDS = "boards", "V - Participação em Bancas"
    OTHER_TITLES = "other_titles", "VI - Outros Títulos"


class BaremeUnit(models.TextChoices):
    """Unidade em que o item do barema mede a quantidade lançada."""

    SEMESTER = "semester", "Semestre"
    MONTH = "month", "Mês"
    HOUR = "hour", "Hora"
    UNIT = "unit", "Unidade"


class PriorityBand(models.TextChoices):
    """As dez faixas de prioridade, nomeadas pelo inciso do edital.

    `B24_I` e `B24_II` só existem por sobrescrita da secretaria: não há
    pergunta no questionário que as derive. A residual é a décima e recebe
    quem não se encaixa em nenhum inciso.
    """

    B21_I = "b21_i", "2.1-I"
    B21_II = "b21_ii", "2.1-II"
    B24_I = "b24_i", "2.4-I"
    B24_II = "b24_ii", "2.4-II"
    B24_III = "b24_iii", "2.4-III"
    B24_IV = "b24_iv", "2.4-IV"
    B24_V = "b24_v", "2.4-V"
    B24_VI_VII_VIII = "b24_vi_vii_viii", "2.4-VI/VII/VIII"
    B24_IX = "b24_ix", "2.4-IX"
    RESIDUAL = "residual", "Residual"


class AppealOutcome(models.TextChoices):
    """Resultado do julgamento do recurso."""

    GRANTED = "granted", "Deferido"
    PARTIALLY_GRANTED = "partially_granted", "Parcialmente deferido"
    DENIED = "denied", "Indeferido"


class ApplicationDocumentKind(models.TextChoices):
    """Um tipo por resposta "Sim" do questionário que exige comprovante.

    São sete: `has_paid_activity` é a chave que joga o candidato do bloco
    2.1 para o 2.4 e não pede documento próprio — quem comprova são os
    incisos abaixo dela.
    """

    AFFIRMATIVE_ACTION = "affirmative_action", "Ação afirmativa"
    SOCIOECONOMIC_VULNERABILITY = (
        "socioeconomic_vulnerability",
        "Vulnerabilidade socioeconômica",
    )
    SUBSTITUTE_TEACHER = "substitute_teacher", "Professor substituto"
    BASIC_EDUCATION_OR_COLLECTIVE_HEALTH = (
        "basic_education_or_collective_health",
        "Educação básica ou saúde coletiva",
    )
    PUBLIC_SERVICE = "public_service", "Serviço público"
    PRIVATE_SERVICE = "private_service", "Serviço privado"
    OTHER_NON_PUBLIC_SCHOLARSHIP = (
        "other_non_public_scholarship",
        "Outra bolsa não pública",
    )


# ---------------------------------------------------------------------------
# Constantes de módulo
# ---------------------------------------------------------------------------

# Ordem canônica em que as faixas são publicadas. O rótulo "Ordem de
# prioridade: N" é **derivado da posição nesta lista** — não é campo. A
# residual é sempre a última.
ORDEM_DAS_FAIXAS: list[str] = [
    PriorityBand.B21_I,
    PriorityBand.B21_II,
    PriorityBand.B24_I,
    PriorityBand.B24_II,
    PriorityBand.B24_III,
    PriorityBand.B24_IV,
    PriorityBand.B24_V,
    PriorityBand.B24_VI_VII_VIII,
    PriorityBand.B24_IX,
    PriorityBand.RESIDUAL,
]

# Bônus somado à nota da comissão conforme o nível da FUMP (item 3.2 do
# edital). Nível 0 é "sem nível" e não pontua — por isso fica fora do dict,
# que é consultado com `.get(fump_level, Decimal("0.00"))`.
BONUS_FUMP: dict[int, Decimal] = {1: Decimal("15.00"), 2: Decimal("9.00")}

# Regra de ordenação dentro de cada faixa. Faixa ausente ordena só por
# nota (decrescente); as duas listadas ordenam antes pela remuneração —
# menor rendimento primeiro — e a 2.4-VI/VII/VIII ainda pela menor carga
# horária. É dado, não código: o cabeçalho do PDF publica esta mesma regra.
ORDENACAO_DA_FAIXA: dict[str, tuple[str, ...]] = {
    PriorityBand.B24_V: ("income", "score"),
    PriorityBand.B24_VI_VII_VIII: ("income", "hours", "score"),
}


# ---------------------------------------------------------------------------
# Caminhos de upload
# ---------------------------------------------------------------------------


def caminho_do_edital_de_bolsas(instance: "ScholarshipEdition", filename: str) -> str:
    """Onde o PDF do edital de bolsas é gravado dentro do MEDIA_ROOT.

    Particionado por edição, no prefixo `bolsas/edicao-{id}/` que os
    comprovantes do barema e os anexos da inscrição também vão usar —
    arquivar uma edição inteira é copiar um diretório. Função de módulo, e
    não lambda, porque a migração precisa serializar a referência.
    """
    return f"bolsas/edicao-{instance.pk}/{filename}"


# ---------------------------------------------------------------------------
# ScholarshipEdition (a edição anual do edital)
# ---------------------------------------------------------------------------


class ScholarshipEditionQuerySet(models.QuerySet["ScholarshipEdition"]):
    def for_program(self, program: Any) -> "ScholarshipEditionQuerySet":
        return self.filter(program=program)


class ScholarshipEdition(models.Model):
    """Edição anual do edital de concessão de bolsas de um programa.

    `year` é o ano da concessão, não o ano em que o edital foi assinado.
    Uma edição por (programa, ano).

    As cinco datas do cronograma são **informação publicada**, não gatilho:
    nada abre, fecha ou publica por relógio. Quem move a edição de um
    estado para o outro é sempre a secretaria, pela tela — mesmo corte das
    disciplinas isoladas. Por isso as transições não recebem "agora" para
    comparar com prazo; só para carimbar o instante da publicação.

    O caminho é de mão única: `draft` → `submissions_open` → `under_review`
    → `preliminary_result` → `appeals_under_review` → `final_result`.
    Corrigir rumo (voltar um passo) é quebra-vidro no Admin, e auditado —
    não existe transição de volta.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="scholarship_editions",
        verbose_name="programa",
    )
    year = models.PositiveIntegerField("ano da concessão")
    title = models.CharField("título", max_length=200)
    status = models.CharField(
        "situação",
        max_length=30,
        choices=ScholarshipEditionStatus,
        default=ScholarshipEditionStatus.DRAFT,
    )
    notice_file = models.FileField(
        "arquivo do edital", upload_to=caminho_do_edital_de_bolsas, blank=True
    )
    # -- cronograma publicado (informação, nunca gatilho) ------------------
    submission_starts_on = models.DateField(
        "inscrições começam em", null=True, blank=True
    )
    submission_ends_on = models.DateField(
        "inscrições encerram em", null=True, blank=True
    )
    preliminary_result_on = models.DateField(
        "resultado preliminar em", null=True, blank=True
    )
    appeal_ends_on = models.DateField("recursos encerram em", null=True, blank=True)
    final_result_on = models.DateField("resultado final em", null=True, blank=True)
    # -- publicação --------------------------------------------------------
    draw_seed = models.BigIntegerField(
        "semente do sorteio",
        null=True,
        blank=True,
        help_text=(
            "Gerada na publicação do preliminar e reusada no final: o "
            "sorteio de desempate precisa ser reprodutível."
        ),
    )
    published_preliminary_at = models.DateTimeField(
        "preliminar publicado em", null=True, blank=True
    )
    published_final_at = models.DateTimeField(
        "final publicado em", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScholarshipEditionQuerySet.as_manager()

    class Meta:
        verbose_name = "edição do edital de bolsas"
        verbose_name_plural = "edições do edital de bolsas"
        ordering = ["-year"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "year"],
                name="unique_edicao_de_bolsas_por_programa_e_ano",
            ),
        ]

    def __str__(self) -> str:
        return self.title or f"Bolsas {self.year}"

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """Uma edição por (programa, ano).

        Espelho da `UniqueConstraint`: `.save()` não roda `clean()`, e sem
        este espelho a violação chegaria ao router como `IntegrityError`
        → 500 em vez de 400 com código.
        """
        super().clean()
        if self.program_id is None or self.year is None:
            # Obrigatoriedade é cobrança do schema Ninja e do NOT NULL.
            return
        duplicatas = ScholarshipEdition.objects.filter(
            program_id=self.program_id, year=self.year
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Já existe uma edição do edital de bolsas para este ano "
                "neste programa.",
                code="duplicate_edition",
            )

    # -- guardas de leitura -------------------------------------------------

    def bareme_editable(self) -> bool:
        """O barema só muda em rascunho.

        `open_submissions()` congela: a partir dali o candidato lança
        contra os itens que leu, e mexer no ponto por unidade mudaria nota
        já dada.
        """
        return self.status == ScholarshipEditionStatus.DRAFT

    def submission_open(self) -> bool:
        """Estado, não relógio: a data do cronograma é informação."""
        return self.status == ScholarshipEditionStatus.SUBMISSIONS_OPEN

    def committee_can_review(self) -> bool:
        """A comissão lança nota em `under_review` **e** em
        `appeals_under_review`.

        O segundo estado não é sobra: o recurso deferido reabre o
        lançamento do item atacado, e é a comissão que o refaz antes do
        resultado final.
        """
        return self.status in {
            ScholarshipEditionStatus.UNDER_REVIEW,
            ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
        }

    def appeal_open(self) -> bool:
        """Fase de recurso: o discente interpõe e a comissão julga.

        É `appeals_under_review`, o estado que `open_appeals()` abre — o
        mesmo que `ScholarshipAppeal.judge()` vai exigir. Publicado o
        preliminar, a secretaria ainda precisa abrir a fase; enquanto não
        abrir, ninguém recorre.
        """
        return self.status == ScholarshipEditionStatus.APPEALS_UNDER_REVIEW

    def results_visible_to_student(self) -> bool:
        """A partir do preliminar publicado o candidato vê o resultado."""
        return self.status in {
            ScholarshipEditionStatus.PRELIMINARY_RESULT,
            ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
            ScholarshipEditionStatus.FINAL_RESULT,
        }

    # -- transições --------------------------------------------------------
    #
    # Nenhuma salva: quem persiste é o router/service, no mesmo
    # `transaction.atomic()` do `AuditLog`.

    def _ensure_status(self, esperado: str, mensagem: str, code: str) -> None:
        if self.status != esperado:
            raise InvalidStateTransition(mensagem, code=code)

    def open_submissions(self) -> None:
        """Abre as inscrições e **congela o barema**."""
        self._ensure_status(
            ScholarshipEditionStatus.DRAFT,
            "Só uma edição em rascunho pode abrir inscrições.",
            "edition_not_draft",
        )
        self.status = ScholarshipEditionStatus.SUBMISSIONS_OPEN

    def start_review(self) -> None:
        """Encerra as inscrições e entrega a fila para a comissão."""
        self._ensure_status(
            ScholarshipEditionStatus.SUBMISSIONS_OPEN,
            "Só uma edição com inscrições abertas pode entrar em análise.",
            "edition_not_submissions_open",
        )
        self.status = ScholarshipEditionStatus.UNDER_REVIEW

    def publish_preliminary(self, at: datetime) -> None:
        self._ensure_status(
            ScholarshipEditionStatus.UNDER_REVIEW,
            "Só uma edição em análise pode publicar o resultado preliminar.",
            "edition_not_under_review",
        )
        self.status = ScholarshipEditionStatus.PRELIMINARY_RESULT
        self.published_preliminary_at = at

    def open_appeals(self) -> None:
        self._ensure_status(
            ScholarshipEditionStatus.PRELIMINARY_RESULT,
            "Só uma edição com resultado preliminar publicado pode abrir "
            "a fase de recursos.",
            "edition_not_preliminary_result",
        )
        self.status = ScholarshipEditionStatus.APPEALS_UNDER_REVIEW

    def publish_final(self, at: datetime) -> None:
        self._ensure_status(
            ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
            "Só uma edição com os recursos em análise pode publicar o resultado final.",
            "edition_not_appeals_under_review",
        )
        self.status = ScholarshipEditionStatus.FINAL_RESULT
        self.published_final_at = at


# ---------------------------------------------------------------------------
# CommitteeMember (a comissão daquele ano)
# ---------------------------------------------------------------------------


class CommitteeMemberQuerySet(models.QuerySet["CommitteeMember"]):
    def for_program(self, program: Any) -> "CommitteeMemberQuerySet":
        """Chega ao programa pelo pai — este model não tem FK `program`."""
        return self.filter(edition__program=program)

    def for_edition(self, edition: Any) -> "CommitteeMemberQuerySet":
        return self.filter(edition=edition)


class CommitteeMember(models.Model):
    """Composição da Comissão de Bolsas de uma edição.

    ESTE MODEL É REGISTRO HISTÓRICO, NÃO AUTORIZAÇÃO. QUEM PODE AVALIAR É
    QUEM ESTÁ NO GROUP "COMISSÃO DE BOLSAS", VERIFICADO POR `require_perm`
    COMO EM TODO O RESTO DO PROJETO. NENHUMA ROTA PODE CONSULTAR
    `CommitteeMember` PARA DECIDIR ACESSO — FAZER ISSO CRIA UM RBAC
    PARALELO AO DO DJANGO, QUE A SEÇÃO 2 DO `CLAUDE.md` PROÍBE.

    O que este registro serve é dizer quem compôs a comissão daquele ano,
    sob qual portaria e desde quando — é o que a ata e o PDF do resultado
    citam.

    `teacher` é PROTECT: descredenciar professor é preencher
    `accredited_until`, e quem compôs a comissão é histórico. Sem FK
    `program`: chega ao programa pela edição, mesmo recorte de
    `RequestDocument` (`apps/academic/models.py`).
    """

    edition = models.ForeignKey(
        ScholarshipEdition,
        on_delete=models.CASCADE,
        related_name="committee_members",
        verbose_name="edição",
    )
    teacher = models.ForeignKey(
        "academic.Teacher",
        on_delete=models.PROTECT,
        related_name="scholarship_committee_memberships",
        verbose_name="professor",
    )
    appointed_on = models.DateField("designado em", null=True, blank=True)
    ordinance = models.CharField("portaria", max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CommitteeMemberQuerySet.as_manager()

    class Meta:
        verbose_name = "membro da comissão de bolsas"
        verbose_name_plural = "membros da comissão de bolsas"
        ordering = ["edition", "teacher"]
        constraints = [
            models.UniqueConstraint(
                fields=["edition", "teacher"],
                name="unique_membro_da_comissao_por_edicao",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.teacher} — {self.edition}"

    def clean(self) -> None:
        """Professor do mesmo programa da edição, uma vez só na comissão."""
        super().clean()
        if self.edition_id is None or self.teacher_id is None:
            return
        if self.teacher.program_id != self.edition.program_id:
            raise DomainError(
                "O membro da comissão precisa ser professor do mesmo "
                "programa da edição.",
                code="program_mismatch",
            )
        duplicatas = CommitteeMember.objects.filter(
            edition_id=self.edition_id, teacher_id=self.teacher_id
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Este professor já compõe a comissão desta edição.",
                code="duplicate_committee_member",
            )
