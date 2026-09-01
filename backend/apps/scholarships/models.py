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

    A leitura dos campos de nota (`committee_score`, `candidate_score`,
    `subtotal`, `fully_reviewed`) lê os `BaremeEntry` da inscrição.
    `final_score()` — a nota da comissão mais o bônus da FUMP — entra com
    o algoritmo de classificação.
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

    # -- notas -------------------------------------------------------------
    #
    # Três leituras da mesma tabela de lançamentos, e a sutileza é sempre a
    # mesma: **o teto é do item, aplicado sobre a soma dos lançamentos
    # daquele item** (ver o comentário de `BaremeItem.raw_score`). Somar os
    # lançamentos já limitados daria a resposta certa nos casos fáceis e a
    # errada exatamente onde importa.

    def committee_score(self) -> Decimal:
        """A nota do barema segundo a comissão.

        Lançamento ainda não avaliado (`committee_score` nulo) conta
        **zero**: a lista pode ser calculada a qualquer momento, e quem
        avisa que ela ainda não está madura é `fully_reviewed()`, não um
        total que se recusa a existir.

        Sem o bônus da FUMP — ele entra em `final_score()`, com o resto do
        algoritmo de classificação.
        """
        return self._somar_por_item("committee_score")

    def candidate_score(self) -> Decimal:
        """O mesmo cálculo sobre o que o candidato lançou.

        É a coluna "Candidato" do cabeçalho da tela de análise: a comissão
        precisa ver, lado a lado, o que foi pedido e o que foi concedido.
        """
        return self._somar_por_item("candidate_score")

    def subtotal(self, section: str) -> Decimal:
        """A nota da comissão restrita a uma seção do barema.

        Existe para os critérios III e IV do desempate (item 3.3): maior
        subtotal em Formação Acadêmica, depois em Produção Bibliográfica.
        """
        return self._somar_por_item("committee_score", section=section)

    def _somar_por_item(self, campo: str, *, section: str | None = None) -> Decimal:
        """Agrupa os lançamentos por item, limita cada grupo e soma.

        Inscrição ainda não salva não tem lançamento — e o gerente reverso
        nem existe nela.
        """
        if self.pk is None:
            return Decimal("0.00")
        lancamentos = self.bareme_entries.select_related("item")
        if section is not None:
            lancamentos = lancamentos.filter(item__section=section)
        totais: dict[int, Decimal] = {}
        itens: dict[int, BaremeItem] = {}
        for lancamento in lancamentos:
            valor = getattr(lancamento, campo)
            totais[lancamento.item_id] = totais.get(
                lancamento.item_id, Decimal("0.00")
            ) + (valor if valor is not None else Decimal("0.00"))
            itens[lancamento.item_id] = lancamento.item
        return sum(
            (itens[item_id].apply_cap(total) for item_id, total in totais.items()),
            Decimal("0.00"),
        )

    def fully_reviewed(self) -> bool:
        """Todos os lançamentos já têm nota da comissão.

        É o "Todos itens analisados" do legado, e é **derivado**: não há
        botão de "concluí a análise" para alguém esquecer de apertar ou
        apertar cedo demais. Inscrição sem lançamento nenhum é vacuamente
        analisada — não há o que avaliar nela.
        """
        if self.pk is None:
            return True
        return not self.bareme_entries.filter(committee_score__isnull=True).exists()

    # -- documentos --------------------------------------------------------

    def pending_docs(self) -> list[str]:
        """Os "Sim" do questionário que ainda estão sem comprovante.

        É o `Sim - Não enviado` do export do legado: a comissão precisa
        ver, item a item, o que o candidato afirmou e não provou — sem
        isso a análise vira conferência manual de anexo contra
        questionário.

        Devolve os `ApplicationDocumentKind` na ordem de declaração do
        enum, que é a ordem do questionário na tela. Inscrição ainda não
        salva não tem anexo nenhum, e por isso deve tudo o que afirmou.
        """
        exigidos = [
            kind
            for kind, campo in RESPOSTA_QUE_EXIGE_DOCUMENTO.items()
            if getattr(self, campo)
        ]
        if self.pk is None:
            return exigidos
        enviados = set(self.documents.values_list("kind", flat=True))
        return [kind for kind in exigidos if kind not in enviados]


# ---------------------------------------------------------------------------
# ApplicationDocument (o comprovante de cada "Sim" do questionário)
# ---------------------------------------------------------------------------

# Qual booleano do questionário cobra qual comprovante. A chave é o valor
# do `ApplicationDocumentKind`, o valor é o nome do campo na inscrição —
# são iguais de propósito, e este mapa existe para que a igualdade seja
# uma **decisão escrita** e não uma coincidência de nomes que a próxima
# renomeação quebra em silêncio.
#
# `has_paid_activity` não está aqui: ele é a chave que joga o candidato do
# bloco 2.1 para o 2.4, e quem comprova são os incisos abaixo dele.
# `cadastro_unico` também não: é critério de desempate, não de faixa, e o
# edital não pede anexo para ele.
RESPOSTA_QUE_EXIGE_DOCUMENTO: dict[str, str] = {
    ApplicationDocumentKind.AFFIRMATIVE_ACTION: "affirmative_action",
    ApplicationDocumentKind.SOCIOECONOMIC_VULNERABILITY: (
        "socioeconomic_vulnerability"
    ),
    ApplicationDocumentKind.SUBSTITUTE_TEACHER: "substitute_teacher",
    ApplicationDocumentKind.BASIC_EDUCATION_OR_COLLECTIVE_HEALTH: (
        "basic_education_or_collective_health"
    ),
    ApplicationDocumentKind.PUBLIC_SERVICE: "public_service",
    ApplicationDocumentKind.PRIVATE_SERVICE: "private_service",
    ApplicationDocumentKind.OTHER_NON_PUBLIC_SCHOLARSHIP: (
        "other_non_public_scholarship"
    ),
}


def caminho_do_documento_da_inscricao(
    instance: "ApplicationDocument", filename: str
) -> str:
    """Onde o comprovante do questionário é gravado dentro do MEDIA_ROOT.

    Particionado por edição e por inscrição pelo mesmo motivo do anexo das
    isoladas (`caminho_do_documento`, `apps/academic/models.py`): a
    operação do edital é por lote, e um diretório plano com milhares de
    arquivos torna manual o que deveria ser um `cp` de diretório.

    O subdiretório `questionario/` separa estes comprovantes dos do
    barema, que virão na mesma inscrição — dois conjuntos com regras de
    acesso diferentes não devem se misturar no disco.

    Função de módulo, e não lambda, porque a migração precisa conseguir
    serializar a referência.
    """
    return (
        f"bolsas/edicao-{instance.application.edition_id}/"
        f"inscricao-{instance.application_id}/questionario/{filename}"
    )


# O que o edital aceita como comprovante do questionário. Mesmo conjunto
# do anexo das isoladas: PDF é o formato da certidão e da declaração;
# imagem entra porque comprovante de endereço e identidade quase sempre
# chegam como foto de celular. Nada além disso — documento de candidato é
# lido pela secretaria, não executado.
#
# O comprovante do **barema** é mais estrito (só PDF, plano Seção 2): lá o
# anexo é certificado, não foto. São duas constantes de propósito.
EXTENSOES_DO_DOCUMENTO_DA_INSCRICAO = (".pdf", ".jpg", ".jpeg", ".png")
# 10 MB por arquivo — foto de celular cabe com folga e PDF digitalizado
# também; acima disso é digitalização mal configurada, não documento.
TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO = 10 * 1024 * 1024


class ApplicationDocumentQuerySet(models.QuerySet["ApplicationDocument"]):
    def for_program(self, program: Any) -> "ApplicationDocumentQuerySet":
        """Filho de agregado: o escopo de tenant atravessa a FK do pai, mas
        continua obrigatório e continua sendo o primeiro filtro de toda
        busca."""
        return self.filter(application__program=program)

    def for_application(self, application: Any) -> "ApplicationDocumentQuerySet":
        return self.filter(application=application)


class ApplicationDocument(models.Model):
    """O comprovante de uma resposta "Sim" do questionário da inscrição.

    Um por tipo (`UniqueConstraint`): reenviar o comprovante de ação
    afirmativa é **substituir** o anterior, não empilhar duas versões e
    deixar a comissão adivinhar qual vale. Quem substitui é
    `replace_for()`.

    Sem FK `program` direta, como `RequestDocument` e pelo mesmo motivo
    (ADR-007 dec. 5): o anexo não é alvo de `AuditLog` próprio — quem é
    auditado é a inscrição, que carrega o tenant — e o `CASCADE` diz que
    ele não existe fora dela.
    """

    Kind = ApplicationDocumentKind

    application = models.ForeignKey(
        ScholarshipApplication,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="inscrição",
    )
    kind = models.CharField("tipo", max_length=40, choices=Kind)
    file = models.FileField("arquivo", upload_to=caminho_do_documento_da_inscricao)
    uploaded_at = models.DateTimeField("anexado em", auto_now_add=True)

    objects = ApplicationDocumentQuerySet.as_manager()

    class Meta:
        verbose_name = "documento da inscrição de bolsa"
        verbose_name_plural = "documentos da inscrição de bolsa"
        ordering = ["kind"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "kind"],
                name="unique_documento_por_inscricao_de_bolsa_e_tipo",
            ),
        ]
        permissions = [
            # Baixar o anexo é mais do que ver a inscrição: são dados
            # pessoais do candidato (laudo, contracheque, declaração de
            # vulnerabilidade). Quem lista a fila não precisa disso.
            ("download_applicationdocument", "Pode baixar documento da inscrição"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} de {self.application}"

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        super().clean()
        self._validar_duplicata()

    def _validar_duplicata(self) -> None:
        """Espelho da `UniqueConstraint`, como nos demais models do app."""
        if self.application_id is None or not self.kind:
            return
        duplicatas = ApplicationDocument.objects.filter(
            application_id=self.application_id, kind=self.kind
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Esta inscrição já tem um documento deste tipo; "
                "reenviar substitui o anterior.",
                code="duplicate_application_document",
            )

    @classmethod
    def validate_upload(cls, *, filename: str, size: int) -> None:
        """Formato e tamanho do que chega — invariante, não detalhe da borda.

        Mesmo contrato de `RequestDocument.validate_upload`
        (`apps/academic/models.py`), inclusive no `code` único: fica no
        model, e não num validador de campo, porque o arquivo que
        interessa validar é o que a requisição traz — `FileField.validators`
        só roda em `full_clean()` e não vê o tamanho do upload. Método de
        classe porque a checagem antecede a instância: recusar antes de
        gravar é o ponto.
        """
        if not filename or not filename.lower().endswith(
            EXTENSOES_DO_DOCUMENTO_DA_INSCRICAO
        ):
            aceitas = ", ".join(EXTENSOES_DO_DOCUMENTO_DA_INSCRICAO)
            raise DomainError(
                f"O documento precisa ser um arquivo {aceitas}.",
                code="invalid_document",
            )
        if size > TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO:
            limite = TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO // (1024 * 1024)
            raise DomainError(
                f"O documento tem no máximo {limite} MB.",
                code="invalid_document",
            )

    # -- substituição ------------------------------------------------------

    @classmethod
    def replace_for(
        cls, *, application: "ScholarshipApplication", kind: str, file: Any
    ) -> tuple["ApplicationDocument", bool]:
        """Grava o anexo daquele tipo, apagando a versão anterior se houver.

        Substitui apagando a linha, e não editando o `file`: `uploaded_at`
        é `auto_now_add` e ficaria com a data do envio errado se o
        registro fosse reaproveitado.

        A remoção do arquivo do storage é explícita porque o `delete()` do
        model não a faz — sem ela cada reenvio deixaria um órfão no
        MEDIA_ROOT. E vem antes de qualquer escrita que possa falhar, já
        que o storage não participa do rollback da transação.

        Devolve `(documento, substituiu)`: o segundo item é o que o router
        usa para escolher entre 201 e 200 e para descrever o `AuditLog`.
        """
        anterior = cls.objects.filter(application=application, kind=kind).first()
        if anterior is not None:
            anterior.file.delete(save=False)
            anterior.delete()
        documento = cls.objects.create(application=application, kind=kind, file=file)
        return documento, anterior is not None


# ---------------------------------------------------------------------------
# BaremeEntry (o lançamento do candidato em uma linha do barema)
# ---------------------------------------------------------------------------


def caminho_do_comprovante(instance: "BaremeEntry", filename: str) -> str:
    """Onde o comprovante de um lançamento do barema é gravado.

    Mesmo particionamento por edição e por inscrição do comprovante do
    questionário (`caminho_do_documento_da_inscricao`), e pelo mesmo
    motivo: a operação do edital é por lote. Sem o subdiretório
    `questionario/`, porque este é o outro conjunto — dois grupos de
    anexo com regras de acesso diferentes não se misturam no disco.

    Função de módulo, e não lambda, porque a migração precisa conseguir
    serializar a referência.
    """
    return (
        f"bolsas/edicao-{instance.application.edition_id}/"
        f"inscricao-{instance.application_id}/{filename}"
    )


# O comprovante do barema é **mais estrito** que o do questionário
# (`EXTENSOES_DO_DOCUMENTO_DA_INSCRICAO`, que aceita imagem): aqui o anexo
# é certificado, declaração de orientador, publicação — documento emitido,
# não foto de celular. São duas constantes de propósito.
EXTENSOES_DO_COMPROVANTE_DO_BAREMA = (".pdf",)
TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA = 10 * 1024 * 1024


class BaremeEntryQuerySet(models.QuerySet["BaremeEntry"]):
    def for_program(self, program: Any) -> "BaremeEntryQuerySet":
        """Filho de agregado: chega ao programa pela inscrição, e continua
        sendo o primeiro filtro de toda busca."""
        return self.filter(application__program=program)

    def for_application(self, application: Any) -> "BaremeEntryQuerySet":
        return self.filter(application=application)

    def for_item(self, item: Any) -> "BaremeEntryQuerySet":
        return self.filter(item=item)

    def pending_review(self) -> "BaremeEntryQuerySet":
        """Os lançamentos que a comissão ainda não pontuou."""
        return self.filter(committee_score__isnull=True)


class BaremeEntry(models.Model):
    """Um lançamento do candidato em uma linha do barema.

    Duas notas convivem na mesma linha, e essa é a peça central da análise:
    `candidate_score` é o que o candidato pediu (gravado como
    `item.raw_score(quantity)`, sem teto — o teto é do item e se aplica à
    soma, em `ScholarshipApplication.committee_score()`), e
    `committee_score` é o que a comissão concedeu. Nulo em
    `committee_score` significa **não avaliado**, e não zero: zerar é uma
    decisão da comissão, e ela vem com observação obrigatória.

    O comprovante é **obrigatório** (Q11): sem ele o lançamento não
    existe. A consequência prática é que a comissão nunca recebe item
    vazio para zerar — o que chega para análise já veio provado.

    Vários lançamentos no mesmo item são normais e não são duplicata: dois
    semestres de docência são duas linhas, e é a soma delas que enfrenta o
    `cap` do item. Por isso não há `UniqueConstraint` aqui.
    """

    application = models.ForeignKey(
        ScholarshipApplication,
        on_delete=models.CASCADE,
        related_name="bareme_entries",
        verbose_name="inscrição",
    )
    item = models.ForeignKey(
        BaremeItem,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="item do barema",
    )
    description = models.TextField(
        "descrição",
        help_text="O que o candidato lançou: título do artigo, nome da disciplina.",
    )
    quantity = models.DecimalField(
        "quantidade",
        max_digits=6,
        decimal_places=2,
        help_text=(
            "Decimal, e não inteiro: o barema mede semestres, meses e horas, "
            "e meio semestre é lançamento legítimo."
        ),
    )
    candidate_score = models.DecimalField(
        "pontuação do candidato",
        max_digits=7,
        decimal_places=2,
        help_text="Gravada como item.raw_score(quantity) — sem teto, que é do item.",
    )
    committee_score = models.DecimalField(
        "pontuação da comissão",
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Nulo é NÃO AVALIADO; zero é a comissão tendo negado o ponto.",
    )
    committee_note = models.TextField(
        "observação da comissão",
        blank=True,
        help_text="Obrigatória quando a nota da comissão diverge da do candidato.",
    )
    reviewed_at = models.DateTimeField("avaliado em", null=True, blank=True)
    proof = models.FileField(
        "comprovante", upload_to=caminho_do_comprovante, max_length=255
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BaremeEntryQuerySet.as_manager()

    class Meta:
        verbose_name = "lançamento do barema"
        verbose_name_plural = "lançamentos do barema"
        ordering = ["application", "item", "pk"]
        permissions = [
            # Avaliar **não** é `change`: o candidato tem `change` sobre o
            # próprio lançamento (enquanto as inscrições estão abertas) e
            # não pode encostar na nota da comissão. Uma permissão só para
            # as duas coisas juntaria os dois papéis num verbo.
            ("review_baremeentry", "Pode avaliar lançamento do barema"),
        ]

    def __str__(self) -> str:
        return f"{self.item.code} — {self.description[:40]}"

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        """As três regras do lançamento.

        Não há espelho de `UniqueConstraint` aqui (o model não tem
        nenhuma): repetir o item é o caso normal.
        """
        super().clean()
        self._validar_item()
        self._validar_quantidade()
        self._validar_observacao()

    def _validar_item(self) -> None:
        """O item precisa ser da mesma edição **e do mesmo nível**.

        O nível importa tanto quanto a edição: o barema é por (edição,
        nível), e o código "1.3" do mestrado é outro item, com outros
        pontos, que não o "1.3" do doutorado. Sem esta checagem um
        candidato de mestrado pontuaria pela tabela do doutorado.
        """
        if self.application_id is None or self.item_id is None:
            return
        if (
            self.item.edition_id != self.application.edition_id
            or self.item.level != self.application.level
        ):
            raise DomainError(
                "O item do barema precisa ser da mesma edição e do mesmo "
                "nível da inscrição.",
                code="bareme_item_mismatch",
            )

    def _validar_quantidade(self) -> None:
        if self.quantity is None or self.quantity <= 0:
            raise DomainError(
                "A quantidade lançada precisa ser maior que zero.",
                code="invalid_quantity",
            )

    def _validar_observacao(self) -> None:
        """Divergência sem justificativa não passa (decisão B9).

        A observação é o que o recurso ataca: um lançamento cortado sem
        motivo escrito deixa o candidato recorrendo contra um número, e a
        comissão julgando o recurso sem lembrar por que cortou.
        """
        if self.committee_score is None:
            return
        if (
            self.committee_score != self.candidate_score
            and not self.committee_note.strip()
        ):
            raise DomainError(
                "Quando a nota da comissão diverge da do candidato, a "
                "observação é obrigatória.",
                code="note_required",
            )

    @classmethod
    def validate_upload(cls, *, filename: str, size: int) -> None:
        """Só PDF, 10 MB — mesmo contrato de `validate_upload` dos demais
        anexos (`RequestDocument`, `ApplicationDocument`), inclusive no
        `code` único, e no motivo de morar no model: `FileField.validators`
        só roda em `full_clean()` e não vê o tamanho do upload."""
        if not filename or not filename.lower().endswith(
            EXTENSOES_DO_COMPROVANTE_DO_BAREMA
        ):
            aceitas = ", ".join(EXTENSOES_DO_COMPROVANTE_DO_BAREMA)
            raise DomainError(
                f"O comprovante do barema precisa ser um arquivo {aceitas}.",
                code="invalid_document",
            )
        if size > TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA:
            limite = TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA // (1024 * 1024)
            raise DomainError(
                f"O comprovante do barema tem no máximo {limite} MB.",
                code="invalid_document",
            )


# ---------------------------------------------------------------------------
# ItemReview (a observação da comissão por item do barema)
# ---------------------------------------------------------------------------


class ItemReviewQuerySet(models.QuerySet["ItemReview"]):
    def for_program(self, program: Any) -> "ItemReviewQuerySet":
        return self.filter(application__program=program)

    def for_application(self, application: Any) -> "ItemReviewQuerySet":
        return self.filter(application=application)


class ItemReview(models.Model):
    """A observação da comissão sobre um **item do barema** da inscrição.

    É a segunda observação do legado, e não a mesma de
    `BaremeEntry.committee_note`: aquela explica **um lançamento**
    ("este certificado não cobre o semestre inteiro"), esta comenta o
    item como um todo ("a produção bibliográfica declarada foi
    reclassificada em bloco"). Uma por (inscrição, item).
    """

    application = models.ForeignKey(
        ScholarshipApplication,
        on_delete=models.CASCADE,
        related_name="item_reviews",
        verbose_name="inscrição",
    )
    item = models.ForeignKey(
        BaremeItem,
        on_delete=models.PROTECT,
        related_name="reviews",
        verbose_name="item do barema",
    )
    note = models.TextField("observação")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ItemReviewQuerySet.as_manager()

    class Meta:
        verbose_name = "observação por item do barema"
        verbose_name_plural = "observações por item do barema"
        ordering = ["application", "item"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "item"],
                name="unique_observacao_por_inscricao_e_item_do_barema",
            ),
        ]

    def __str__(self) -> str:
        return f"Observação em {self.item.code} de {self.application}"

    # -- invariantes -------------------------------------------------------

    def clean(self) -> None:
        super().clean()
        self._validar_item()
        self._validar_duplicata()

    def _validar_item(self) -> None:
        """Mesma checagem do lançamento, e pelo mesmo motivo: comentar o
        "1.3" do doutorado numa inscrição de mestrado é comentar outro
        item."""
        if self.application_id is None or self.item_id is None:
            return
        if (
            self.item.edition_id != self.application.edition_id
            or self.item.level != self.application.level
        ):
            raise DomainError(
                "O item do barema precisa ser da mesma edição e do mesmo "
                "nível da inscrição.",
                code="bareme_item_mismatch",
            )

    def _validar_duplicata(self) -> None:
        """Espelho da `UniqueConstraint`, como nos demais models do app."""
        if self.application_id is None or self.item_id is None:
            return
        duplicatas = ItemReview.objects.filter(
            application_id=self.application_id, item_id=self.item_id
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Esta inscrição já tem observação neste item do barema.",
                code="duplicate_item_review",
            )
