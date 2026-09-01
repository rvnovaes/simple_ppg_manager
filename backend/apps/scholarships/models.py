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

from apps.core.exceptions import DomainError, InvalidStateTransition, NotAllowed

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


# ---------------------------------------------------------------------------
# BaremeItem (a linha do barema de uma edição, por nível)
# ---------------------------------------------------------------------------


class BaremeItemQuerySet(models.QuerySet["BaremeItem"]):
    def for_program(self, program: Any) -> "BaremeItemQuerySet":
        """Chega ao programa pelo pai — este model não tem FK `program`."""
        return self.filter(edition__program=program)

    def for_edition(self, edition: Any) -> "BaremeItemQuerySet":
        return self.filter(edition=edition)

    def for_level(self, level: str) -> "BaremeItemQuerySet":
        """O barema é por (edição, nível): mestrado e doutorado são listas
        independentes, com códigos e pontos próprios."""
        return self.filter(level=level)


class BaremeItem(models.Model):
    """Uma linha pontuável do barema de uma edição, para um nível.

    O barema é por **(edição, nível)**: mestrado e doutorado têm itens
    independentes, com códigos, pontuação e limites próprios. `code` é o
    número que o edital publica ("1.3") e é o que o candidato enxerga na
    tela de lançamento.

    `points_per_unit` é quanto vale **uma** unidade de `unit` (um semestre,
    um mês, uma hora, uma unidade), e `cap` é o limite do item.

    Congelamento: quem guarda a escrita é `ScholarshipEdition.bareme_editable()`
    — item só nasce, muda ou some com a edição em rascunho. `open_submissions()`
    congela, porque a partir dali o candidato lança contra os pontos que leu.
    """

    edition = models.ForeignKey(
        ScholarshipEdition,
        on_delete=models.CASCADE,
        related_name="bareme_items",
        verbose_name="edição",
    )
    level = models.CharField("nível", max_length=20, choices=ScholarshipLevel)
    section = models.CharField("seção", max_length=20, choices=BaremeSection)
    code = models.CharField("código", max_length=10)
    text = models.TextField("descrição")
    unit = models.CharField("unidade", max_length=20, choices=BaremeUnit)
    points_per_unit = models.DecimalField(
        "pontos por unidade", max_digits=6, decimal_places=2
    )
    cap = models.DecimalField("limite do item", max_digits=7, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BaremeItemQuerySet.as_manager()

    class Meta:
        verbose_name = "item do barema"
        verbose_name_plural = "itens do barema"
        ordering = ["edition", "level", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["edition", "level", "code"],
                name="unique_item_do_barema_por_edicao_e_nivel",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.text[:60]}"

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """Um código por (edição, nível).

        Espelho da `UniqueConstraint`, como nos demais models deste app.
        """
        super().clean()
        if self.edition_id is None or not self.code or not self.level:
            return
        duplicatas = BaremeItem.objects.filter(
            edition_id=self.edition_id, level=self.level, code=self.code
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                f"O item {self.code} já existe no barema deste nível nesta edição.",
                code="duplicate_bareme_item",
            )

    # -- aritmética --------------------------------------------------------
    #
    # SÃO DUAS FUNÇÕES SEPARADAS DE PROPÓSITO, E ESSE É O PONTO SUTIL DO
    # BAREMA: `raw_score` pontua UM lançamento, e `apply_cap` corta a SOMA
    # dos lançamentos daquele item. O teto é do item, não do lançamento —
    # dois lançamentos de 3,00 no item 1.8 somam 6,00 contra o limite de
    # 18,00, e nenhum dos dois é cortado sozinho. Aplicar o teto dentro de
    # `raw_score` daria a mesma resposta nos casos fáceis (um lançamento só)
    # e a errada exatamente no caso que importa.

    def raw_score(self, quantity: Decimal) -> Decimal:
        """Pontuação bruta de **um** lançamento, sem teto."""
        return quantity * self.points_per_unit

    def apply_cap(self, total: Decimal) -> Decimal:
        """Corta pelo limite do item a **soma** dos lançamentos dele."""
        return min(total, self.cap)


# ---------------------------------------------------------------------------
# ScholarshipApplication (a inscrição do discente na edição)
# ---------------------------------------------------------------------------

# Níveis da FUMP lançados pela Secretaria. O resultado da FUMP chega à
# Comissão fora do sistema (Q9); aqui ele é só transcrito. Zero é "sem
# nível" e não pontua — ver `BONUS_FUMP`, que por isso não tem a chave 0.
NIVEIS_DA_FUMP: list[tuple[int, str]] = [
    (0, "Sem nível"),
    (1, "Nível 1"),
    (2, "Nível 2"),
]


class ScholarshipApplicationQuerySet(models.QuerySet["ScholarshipApplication"]):
    def for_program(self, program: Any) -> "ScholarshipApplicationQuerySet":
        return self.filter(program=program)

    def for_edition(self, edition: Any) -> "ScholarshipApplicationQuerySet":
        return self.filter(edition=edition)

    def for_level(self, level: str) -> "ScholarshipApplicationQuerySet":
        """A classificação corre por nível: mestrado e doutorado são duas
        listas independentes, com barema e faixas próprios."""
        return self.filter(level=level)

    def for_student(self, student: Any) -> "ScholarshipApplicationQuerySet":
        return self.filter(student=student)


class ScholarshipApplication(models.Model):
    """A inscrição de um discente na edição anual do edital de bolsas.

    Uma por (edição, aluno). O `level` é **copiado do `Student` no ato** e
    congelado: o barema, a nota e a fila são por nível, e um aluno que
    passa de mestrado a doutorado no meio da edição não pode migrar de
    lista depois que a comissão já pontuou.

    O **questionário é fixo em código** (decisão B7 do plano), e não uma
    tabela de perguntas cadastráveis: cada campo aqui é um inciso do
    edital, com efeito próprio na derivação da faixa. Mudar a norma é
    mudar o código — e a migração que vem junto é o registro de quando a
    pergunta mudou. Uma tabela genérica trocaria isso por um formulário
    editável cujo efeito na classificação ninguém consegue ler.

    `has_paid_activity` é a **chave** do questionário: falso joga o
    candidato no bloco 2.1, verdadeiro no bloco 2.4. Os demais booleanos
    escolhem o inciso dentro do bloco (a derivação completa é da
    `classify()` da edição).

    A leitura dos campos de nota (`committee_score`, `final_score`,
    `subtotal`, `fully_reviewed`) depende de `BaremeEntry`, e a de
    `pending_docs` depende de `ApplicationDocument`: entram com esses
    models, nas stories seguintes.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="scholarship_applications",
        verbose_name="programa",
    )
    edition = models.ForeignKey(
        ScholarshipEdition,
        on_delete=models.CASCADE,
        related_name="applications",
        verbose_name="edição",
    )
    student = models.ForeignKey(
        "academic.Student",
        on_delete=models.PROTECT,
        related_name="scholarship_applications",
        verbose_name="discente",
    )
    level = models.CharField(
        "nível",
        max_length=20,
        choices=ScholarshipLevel,
        help_text=(
            "Copiado do vínculo do discente no ato da inscrição e congelado: "
            "mudança posterior no Student não move a inscrição de lista."
        ),
    )
    submitted_at = models.DateTimeField("inscrito em", null=True, blank=True)

    # -- questionário (fixo em código, decisão B7) -------------------------
    has_paid_activity = models.BooleanField(
        "exerce atividade remunerada",
        default=False,
        help_text="A chave do questionário: falso vai ao bloco 2.1, verdadeiro ao 2.4.",
    )
    affirmative_action = models.BooleanField(
        "ingressou por ação afirmativa", default=False
    )
    socioeconomic_vulnerability = models.BooleanField(
        "vulnerabilidade socioeconômica", default=False
    )
    cadastro_unico = models.BooleanField(
        "inscrito no CadÚnico",
        default=False,
        help_text=(
            "ASSUNÇÃO A CONFIRMAR NO MERGE: o CadÚnico é o critério II do "
            "desempate (item 3.3 do edital) mas não aparece no questionário "
            "da spec. Sem este campo o critério é letra morta, por isso ele "
            "entra aqui, junto do bloco de vulnerabilidade."
        ),
    )
    substitute_teacher = models.BooleanField("professor substituto", default=False)
    basic_education_or_collective_health = models.BooleanField(
        "atua na educação básica ou em saúde coletiva", default=False
    )
    public_service = models.BooleanField("vínculo com o serviço público", default=False)
    private_service = models.BooleanField(
        "vínculo com o serviço privado", default=False
    )
    other_non_public_scholarship = models.BooleanField(
        "recebe outra bolsa não pública", default=False
    )

    # -- o que a atividade remunerada carrega ------------------------------
    #
    # Obrigatórios quando `has_paid_activity` (`clean()` → `income_required`):
    # são eles que ordenam as faixas 2.4-V (menor rendimento) e
    # 2.4-VI/VII/VIII (menor rendimento, depois menor carga horária).
    monthly_income = models.DecimalField(
        "rendimento mensal", max_digits=10, decimal_places=2, null=True, blank=True
    )
    weekly_hours = models.PositiveSmallIntegerField(
        "carga horária semanal", null=True, blank=True
    )

    # -- lançado pela Secretaria -------------------------------------------
    fump_level = models.PositiveSmallIntegerField(
        "nível da FUMP",
        choices=NIVEIS_DA_FUMP,
        default=0,
        help_text=(
            "Transcrito do resultado que a FUMP manda à Comissão fora do "
            "sistema. Vale duas vezes: bônus na nota final e 1º critério de "
            "desempate."
        ),
    )

    # -- sobrescrita de faixa (decisão B6) ---------------------------------
    #
    # A válvula da secretaria: 2.4-I e 2.4-II não têm pergunta no
    # questionário e só chegam por aqui, junto de todo caso omisso.
    band_override = models.CharField(  # noqa: DJ001
        "faixa sobrescrita",
        max_length=20,
        choices=PriorityBand,
        null=True,
        blank=True,
        help_text="Nulo é o normal: a faixa sai do questionário.",
    )
    band_override_reason = models.TextField("justificativa da sobrescrita", blank=True)

    # -- snapshot da publicação (decisão B10) ------------------------------
    #
    # Tudo nulo até publicar. Depois de publicado, é ESTE o resultado que a
    # tela e o PDF mostram — recalcular na leitura faria a lista publicada
    # mudar debaixo de quem já a leu.
    published_band = models.CharField(  # noqa: DJ001
        "faixa publicada", max_length=20, choices=PriorityBand, null=True, blank=True
    )
    published_score = models.DecimalField(
        "nota publicada", max_digits=7, decimal_places=2, null=True, blank=True
    )
    published_position = models.PositiveIntegerField(
        "classificação publicada", null=True, blank=True
    )
    draw_order = models.PositiveIntegerField(
        "ordem do sorteio",
        null=True,
        blank=True,
        help_text="Preenchida só em quem o sorteio de desempate precisou ordenar.",
    )
    published_at = models.DateTimeField("publicado em", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScholarshipApplicationQuerySet.as_manager()

    class Meta:
        verbose_name = "inscrição no edital de bolsas"
        verbose_name_plural = "inscrições no edital de bolsas"
        ordering = ["edition", "level", "student"]
        constraints = [
            models.UniqueConstraint(
                fields=["edition", "student"],
                name="unique_inscricao_de_bolsa_por_edicao_e_discente",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.edition}"

    # -- construção --------------------------------------------------------

    @classmethod
    def for_student(
        cls, *, edition: ScholarshipEdition, student: Any, **campos: Any
    ) -> "ScholarshipApplication":
        """Instância **não salva**, com `program` e `level` já copiados.

        O nível é congelado aqui, e não em `save()`, porque este é o único
        momento em que copiar faz sentido: uma inscrição que lesse o nível
        do `Student` a cada acesso mudaria de lista sozinha no dia em que o
        aluno passasse de mestrado a doutorado.

        Isolada e eletiva não têm nível (`Student.level` é nulo nelas) e
        por isso não se inscrevem: sem nível não há barema contra o qual
        pontuar.
        """
        if not student.level:
            raise DomainError(
                "Só discente com nível de vínculo (mestrado ou doutorado) "
                "pode se inscrever no edital de bolsas.",
                code="student_without_level",
            )
        return cls(
            program=edition.program,
            edition=edition,
            student=student,
            level=student.level,
            **campos,
        )

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """Uma inscrição por (edição, discente), coerente com o questionário.

        As três regras, nesta ordem: o discente e a edição são do mesmo
        programa; a atividade remunerada declarada vem com rendimento e
        carga horária (são eles que ordenam as faixas 2.4-V e
        2.4-VI/VII/VIII — sem eles a fila não existe); e a sobrescrita de
        faixa vem com justificativa, porque ela é o ato discricionário do
        módulo e sem motivo escrito não há o que revisar.
        """
        super().clean()
        self._validar_programa()
        self._validar_atividade_remunerada()
        self._validar_sobrescrita_de_faixa()
        self._validar_duplicata()

    def _validar_programa(self) -> None:
        if self.program_id is None or self.edition_id is None:
            return
        if self.edition.program_id != self.program_id:
            raise DomainError(
                "A inscrição precisa ser da mesma edição do programa do discente.",
                code="program_mismatch",
            )
        if self.student_id is not None and self.student.program_id != self.program_id:
            raise DomainError(
                "O discente precisa ser do mesmo programa da edição.",
                code="program_mismatch",
            )

    def _validar_atividade_remunerada(self) -> None:
        if not self.has_paid_activity:
            return
        if self.monthly_income is None or self.weekly_hours is None:
            raise DomainError(
                "Quem declara atividade remunerada precisa informar o "
                "rendimento mensal e a carga horária semanal.",
                code="income_required",
            )

    def _validar_sobrescrita_de_faixa(self) -> None:
        if self.band_override and not self.band_override_reason.strip():
            raise DomainError(
                "A sobrescrita da faixa de prioridade exige justificativa.",
                code="override_reason_required",
            )

    def _validar_duplicata(self) -> None:
        """Espelho da `UniqueConstraint`, como nos demais models do app."""
        if self.edition_id is None or self.student_id is None:
            return
        duplicatas = ScholarshipApplication.objects.filter(
            edition_id=self.edition_id, student_id=self.student_id
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Este discente já tem inscrição nesta edição do edital de bolsas.",
                code="duplicate_application",
            )

    # -- guardas -----------------------------------------------------------

    def ensure_editable(self, user: Any) -> None:
        """Só na janela aberta, e só pelo próprio aluno.

        Vale para alterar o questionário, lançar no barema, anexar
        comprovante **e excluir a própria inscrição**: enquanto as
        inscrições estão abertas o candidato desfaz o que fez; fechada a
        janela, a inscrição é a peça que a comissão pontua e some da mão
        dele.

        Duas exceções diferentes de propósito: o estado errado é 409
        (a janela pode reabrir para todo mundo), a pessoa errada é 403.
        A secretaria não passa por aqui — o que ela mexe em inscrição
        alheia tem rota e permissão próprias (`set_fump_level`,
        `override_band`), justamente para não virar "editar como se fosse
        o aluno".
        """
        if not self.edition.submission_open():
            raise InvalidStateTransition(
                "A inscrição só pode ser alterada com as inscrições abertas.",
                code="submissions_closed",
            )
        if not self._user_is_owner(user):
            raise NotAllowed(
                "Só o próprio discente pode alterar a sua inscrição.",
                code="not_application_owner",
            )

    def _user_is_owner(self, user: Any) -> bool:
        if user is None or not getattr(user, "pk", None):
            return False
        pessoa = getattr(self.student, "person", None)
        return pessoa is not None and pessoa.user_id == user.pk

    # -- derivação ---------------------------------------------------------

    def band(self) -> str | None:
        """A faixa de prioridade: a sobrescrita, quando existe.

        A sobrescrita da secretaria vence sempre — é a válvula do B6, e
        também o único caminho para 2.4-I e 2.4-II, que não têm pergunta
        no questionário.

        Sem sobrescrita, a faixa é **derivada do questionário**, e essa
        derivação mora na `classify()` da edição, com o resto do
        algoritmo. Até ela existir, este método devolve `None` para quem
        não tem override — "ainda não derivada", nunca "residual": tratar
        a ausência como residual poria candidato do bloco 2.1 no fim da
        fila sem que ninguém percebesse.
        """
        return self.band_override or None
