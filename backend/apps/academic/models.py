"""Vida acadêmica do programa: quem ensina e quem estuda.

O app depende de `programs` (linha de pesquisa, projeto coletivo, período
letivo) e de `people` (a pessoa por trás do vínculo). A dependência é
sempre nesta direção — `programs` e `people` não conhecem `academic`.
"""

from datetime import date

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone

from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.people.models import Person


def _somar_anos(dia: date, anos: int) -> date:
    """Mesma data, `anos` anos depois.

    24 e 48 meses são 2 e 4 anos exatos, então isto resolve o prazo sem
    trazer python-dateutil para o pyproject.toml. 29/02 em ano seguinte
    não bissexto cai em 28/02 — é o único caso que `replace` recusa.
    """
    try:
        return dia.replace(year=dia.year + anos)
    except ValueError:
        return dia.replace(year=dia.year + anos, day=28)


class TeacherQuerySet(models.QuerySet):
    def for_program(self, program) -> "TeacherQuerySet":
        return self.filter(program=program)


class Teacher(models.Model):
    """Professor credenciado no programa.

    `person` é OneToOne, ao contrário de `Student.person` que é FK
    (ADR-007 dec. 2): nada indica que uma pessoa tenha dois vínculos
    docentes simultâneos no mesmo programa. Quem atua em dois programas
    tem duas `Person` — e portanto dois `Teacher`, um por programa.

    Descredenciar é preencher `accredited_until`, não apagar o registro:
    o professor descredenciado continua sendo quem orientou os alunos
    dele.
    """

    class Category(models.TextChoices):
        PERMANENT = "permanent", "Permanente"
        COLLABORATOR = "collaborator", "Colaborador"
        VISITING = "visiting", "Visitante"

    class AcademicDegree(models.TextChoices):
        DOCTORATE = "doctorate", "Doutor"
        POSTDOCTORATE = "postdoctorate", "Pós-doutor"
        HABILITATION = "habilitation", "Livre-docente"

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="teachers",
        verbose_name="programa",
    )
    person = models.OneToOneField(
        "people.Person",
        on_delete=models.PROTECT,
        related_name="teacher_profile",
        verbose_name="pessoa",
    )
    # Categoria CAPES: é o que entra no relatório do programa, não um
    # rótulo interno.
    category = models.CharField(
        "categoria CAPES",
        max_length=20,
        choices=Category,
    )
    accredited_since = models.DateField("credenciado desde")
    # Vazio = credenciamento vigente. Preenchido = descredenciado naquela
    # data, e o histórico continua legível.
    accredited_until = models.DateField(
        "credenciado até",
        null=True,
        blank=True,
    )
    academic_degree = models.CharField(
        "titulação",
        max_length=20,
        choices=AcademicDegree,
    )
    lattes_url = models.URLField("currículo Lattes", blank=True)
    home_institution = models.CharField(
        "instituição de origem",
        max_length=200,
        blank=True,
    )
    research_lines = models.ManyToManyField(
        "programs.ResearchLine",
        related_name="teachers",
        blank=True,
        verbose_name="linhas de pesquisa",
    )
    projects = models.ManyToManyField(
        "programs.CollectiveProject",
        related_name="teachers",
        blank=True,
        verbose_name="projetos coletivos",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TeacherQuerySet.as_manager()

    class Meta:
        verbose_name = "professor"
        verbose_name_plural = "professores"
        ordering = ["person__full_name"]

    def __str__(self) -> str:
        return str(self.person)

    def clean(self) -> None:
        """A FK `program` é direta (ADR-007 dec. 5) e por isso pode
        divergir de `person.program`. Divergir significa AuditLog com a
        chave de tenant errada — é invariante, não detalhe de formulário.
        """
        super().clean()
        try:
            person = self.person
        except ObjectDoesNotExist:
            # Sem pessoa ainda: quem cobra a obrigatoriedade é o schema
            # Ninja (borda) e o NOT NULL da coluna, não este invariante.
            return
        if self.program_id != person.program_id:
            raise DomainError(
                "O programa do professor precisa ser o mesmo da pessoa.",
                code="program_mismatch",
            )


class StudentQuerySet(models.QuerySet):
    def for_program(self, program) -> "StudentQuerySet":
        return self.filter(program=program)

    def active(self) -> "StudentQuerySet":
        return self.filter(status=Student.Status.ACTIVE)

    def regular(self) -> "StudentQuerySet":
        return self.filter(modality=Student.Modality.REGULAR)


class Student(models.Model):
    """Vínculo de aluno com o programa.

    Duas decisões do ADR-007 moldam este model:

    1. `modality` (Regular/Isolada/Eletiva) e `status` (Ativo/Trancado/
       Excluído) são campos SEPARADOS. Um campo só forçaria "Isolada" e
       "Trancado" a disputarem o mesmo espaço, e a pergunta "quantos
       regulares ativos?" viraria string matching.
    2. `person` é FK, não OneToOne: a mesma pessoa cursa uma isolada em
       2026/1, outra em 2026/2 e depois entra como regular. São vínculos
       distintos, cada um com sua situação.

    Os campos de grau (nível, projeto, orientador, datas) só fazem sentido
    para o regular; a isolada e a eletiva duram um semestre e por isso
    carregam `term`. As CheckConstraint abaixo é que garantem isso — não
    há caminho de escrita que as contorne, ao contrário de `clean()`.
    """

    class Modality(models.TextChoices):
        REGULAR = "regular", "Regular"
        ISOLATED = "isolated", "Isolada"
        ELECTIVE = "elective", "Eletiva"

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        LEAVE = "leave", "Trancado"
        EXCLUDED = "excluded", "Excluído"

    class Level(models.TextChoices):
        MASTERS = "masters", "Mestrado"
        DOCTORATE = "doctorate", "Doutorado"

    # Prazo regimental por nível, em anos. Mestrado 24 meses, doutorado 48.
    PRAZO_EM_ANOS = {Level.MASTERS: 2, Level.DOCTORATE: 4}

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="students",
        verbose_name="programa",
    )
    person = models.ForeignKey(
        "people.Person",
        on_delete=models.PROTECT,
        related_name="student_records",
        verbose_name="pessoa",
    )
    # Vazio enquanto a matrícula não sai (isolada e eletiva só recebem
    # número quando viram vínculo formal, se virarem).
    registration_number = models.CharField(
        "matrícula",
        max_length=30,
        null=True,
        blank=True,
        unique=True,
    )
    modality = models.CharField(
        "modalidade",
        max_length=20,
        choices=Modality,
        default=Modality.REGULAR,
    )
    status = models.CharField(
        "situação",
        max_length=20,
        choices=Status,
        default=Status.ACTIVE,
    )
    # Campos de grau: obrigatórios para o regular pela CheckConstraint,
    # proibidos para isolada/eletiva. No banco todos aceitam NULL.
    # noqa DJ001: string vazia não serve aqui. A CheckConstraint fala em
    # `level__isnull`, e "regular exige nível" precisa distinguir ausente de
    # preenchido — com "" o banco aceitaria um regular sem nível.
    level = models.CharField(  # noqa: DJ001
        "nível",
        max_length=20,
        choices=Level,
        null=True,
        blank=True,
    )
    project = models.ForeignKey(
        "programs.CollectiveProject",
        on_delete=models.PROTECT,
        related_name="students",
        null=True,
        blank=True,
        verbose_name="projeto coletivo",
    )
    advisor = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,
        related_name="advisees",
        null=True,
        blank=True,
        verbose_name="orientador",
    )
    admission_date = models.DateField("data de ingresso", null=True, blank=True)
    deadline = models.DateField("prazo de conclusão", null=True, blank=True)
    defense_date = models.DateField("data da defesa", null=True, blank=True)
    # Período letivo do vínculo — obrigatório para isolada e eletiva, que
    # existem dentro de um semestre. AcademicTerm é institucional e não
    # tem programa (ADR-007 dec. 4).
    term = models.ForeignKey(
        "programs.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="students",
        null=True,
        blank=True,
        verbose_name="período letivo",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StudentQuerySet.as_manager()

    class Meta:
        verbose_name = "aluno"
        verbose_name_plural = "alunos"
        ordering = ["person__full_name"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(modality="regular")
                | models.Q(
                    level__isnull=False,
                    project__isnull=False,
                    admission_date__isnull=False,
                    deadline__isnull=False,
                ),
                name="student_regular_requires_degree_fields",
            ),
            models.CheckConstraint(
                condition=~models.Q(modality__in=["isolated", "elective"])
                | models.Q(
                    term__isnull=False,
                    level__isnull=True,
                    project__isnull=True,
                    advisor__isnull=True,
                    admission_date__isnull=True,
                    deadline__isnull=True,
                    defense_date__isnull=True,
                ),
                name="student_non_regular_requires_term",
            ),
            # Trancar não se aplica a isolada nem eletiva: elas duram um
            # semestre e terminam em Excluído.
            models.CheckConstraint(
                condition=~models.Q(status="leave") | models.Q(modality="regular"),
                name="student_leave_only_when_regular",
            ),
        ]

    def __str__(self) -> str:
        return str(self.person)

    def default_deadline(self) -> date | None:
        """Prazo regimental a partir do ingresso: 2 anos no mestrado, 4 no
        doutorado. Devolve None quando falta ingresso ou nível — quem cobra
        a obrigatoriedade é a CheckConstraint.
        """
        if not self.admission_date or not self.level:
            return None
        return _somar_anos(
            self.admission_date, self.PRAZO_EM_ANOS[self.Level(self.level)]
        )

    def save(self, *args, **kwargs) -> None:
        """Preenche o prazo do regular quando ele não veio.

        É default, não invariante: depois de criado o campo é livremente
        editável (prorrogação é rotina do programa).
        """
        if self.modality == self.Modality.REGULAR and self.deadline is None:
            self.deadline = self.default_deadline()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """As FKs `program` são diretas (ADR-007 dec. 5) e por isso podem
        divergir das do que elas apontam. Divergir significa AuditLog com a
        chave de tenant errada — é invariante, não detalhe de formulário.

        `term` fica de fora de propósito: período letivo é institucional e
        não tem programa para comparar.
        """
        super().clean()
        try:
            person = self.person
        except ObjectDoesNotExist:
            # Sem pessoa ainda: quem cobra a obrigatoriedade é o schema
            # Ninja (borda) e o NOT NULL da coluna, não este invariante.
            return
        if self.program_id != person.program_id:
            raise DomainError(
                "O programa do aluno precisa ser o mesmo da pessoa.",
                code="program_mismatch",
            )
        # FK anulável devolve None sem ir ao banco quando o _id é None.
        project = self.project
        if project is not None and project.program_id != self.program_id:
            raise DomainError(
                "O projeto coletivo precisa ser do mesmo programa do aluno.",
                code="program_mismatch",
            )
        advisor = self.advisor
        if advisor is not None and advisor.program_id != self.program_id:
            raise DomainError(
                "O orientador precisa ser do mesmo programa do aluno.",
                code="program_mismatch",
            )
        # Por último: o erro de tenant é o mais grave e por isso fala
        # primeiro.
        self._conferir_modalidade()

    def ensure_can_request_adjustment(self) -> None:
        """Invariante de quem pode abrir acerto de matrícula.

        A ordem importa: a modalidade vem primeiro porque a isolada e a
        eletiva nem podem ter orientador (CheckConstraint
        `student_non_regular_requires_term`) — checar o orientador antes
        devolveria `advisor_required` para quem nunca poderia ter um.

        Sem orientador a solicitação nasceria presa: só o orientador
        decide, então ninguém a tiraria de Aberta. É 409, não 400 — o
        payload está certo, o estado do vínculo é que não permite.
        """
        if self.modality != self.Modality.REGULAR:
            raise InvalidStateTransition(
                "Só o aluno regular abre acerto de matrícula.",
                code="regular_students_only",
            )
        if self.advisor_id is None:
            raise InvalidStateTransition(
                "Aluno sem orientador não tem quem decida o acerto.",
                code="advisor_required",
            )

    def _conferir_modalidade(self) -> None:
        """Mesma coerência das CheckConstraint, no caminho do domínio.

        A constraint continua sendo a garantia final; aqui ela vira erro de
        negócio (400) em vez de IntegrityError (500) para quem edita pela
        API — o PATCH pode deixar o vínculo incoerente sem tocar na
        modalidade, por exemplo trancando uma isolada.

        `deadline` fica de fora: `save()` calcula o do regular quando ele
        não veio, e neste ponto ele ainda pode estar vazio.
        """
        if self.modality == self.Modality.REGULAR:
            if not (self.level and self.project_id and self.admission_date):
                raise DomainError(
                    "Aluno regular exige nível, projeto e data de ingresso.",
                    code="incomplete_regular",
                )
            return

        if self.term_id is None:
            raise DomainError(
                "Aluno de isolada ou eletiva exige período letivo.",
                code="term_required",
            )
        if any(
            (
                self.level,
                self.project_id,
                self.advisor_id,
                self.admission_date,
                self.deadline,
                self.defense_date,
            )
        ):
            raise DomainError(
                "Aluno de isolada ou eletiva não tem campos de grau.",
                code="degree_fields_not_allowed",
            )
        if self.status == self.Status.LEAVE:
            raise DomainError(
                "Trancamento só se aplica ao aluno regular.",
                code="leave_not_allowed",
            )


# Papéis que acompanham o fluxo do programa inteiro. Aluno e orientador
# enxergam só o que é deles, e por isso não estão aqui: quem não é
# Secretaria nem Coordenação cai no escopo do próprio vínculo.
PAPEIS_COM_VISAO_DO_PROGRAMA = ("Secretaria", "Coordenação")


class EnrollmentAdjustmentRequestQuerySet(models.QuerySet):
    def for_program(self, program) -> "EnrollmentAdjustmentRequestQuerySet":
        return self.filter(program=program)

    def open(self) -> "EnrollmentAdjustmentRequestQuerySet":
        return self.filter(status=EnrollmentAdjustmentRequest.Status.OPEN)

    def visible_to(self, user, program) -> "EnrollmentAdjustmentRequestQuerySet":
        """O que esta sessão pode ler — sempre depois de `for_program`.

        `view_enrollmentadjustmentrequest` é permissão de papel: os quatro
        papéis a têm, mas ela diz que a pessoa acompanha acerto, não QUAIS
        acertos. O recorte é aqui.

        Secretaria e Coordenação (e o superusuário, que opera a
        plataforma) veem o programa inteiro. Todo o resto vê a união do
        que é seu como aluno e do que é seu como orientador — união, e não
        dois ramos, porque nada impede que o mesmo User tenha os dois
        vínculos.
        """
        if (
            user.is_superuser
            or user.groups.filter(name__in=PAPEIS_COM_VISAO_DO_PROGRAMA).exists()
        ):
            return self
        pessoas = Person.objects.active().filter(user=user, program=program)
        # Sem duplicata a corrigir: os dois lados do OU são FK direta
        # (uma solicitação tem um aluno, que tem uma pessoa e um
        # orientador), então o join não multiplica linha.
        return self.filter(
            models.Q(student__person__in=pessoas)
            | models.Q(student__advisor__person__in=pessoas)
        )


class AdjustmentStatus(models.TextChoices):
    """Situação da solicitação de acerto.

    Mora fora do model, com nome único, porque o gerador de OpenAPI batiza
    o schema do enum com o `__name__` da classe: dois `Status` aninhados
    colidem e o último registrado sobrescreve o outro — foi assim que
    `Student.Status` virou `open/approved/rejected` no `schema.d.ts`.
    `EnrollmentAdjustmentRequest.Status` continua valendo pelo alias.
    """

    OPEN = "open", "Aberta"
    APPROVED = "approved", "Aprovada"
    REJECTED = "rejected", "Recusada"


class EnrollmentAdjustmentRequest(models.Model):
    """Pedido de acerto de matrícula de um aluno num período letivo.

    Um pedido só, com vários itens: o aluno junta tudo o que quer incluir
    e excluir em 2026/1 numa decisão única do orientador, em vez de abrir
    um pedido por disciplina. Por isso o estado (`status`, `decided_at`,
    `decision_note`) vive aqui e não no item.

    A FK `program` é direta mesmo sendo alcançável por `student.program`
    (ADR-007 dec. 5): sem ela `apps.core.audit.record()` grava AuditLog
    com `program=None` e o rastro perde a chave de tenant.
    """

    Status = AdjustmentStatus

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="enrollment_adjustments",
        verbose_name="programa",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="enrollment_adjustments",
        verbose_name="aluno",
    )
    # Obrigatória: acerto é sempre relativo a um semestre, e é ela que dá
    # sentido ao filtro da tela da secretaria.
    term = models.ForeignKey(
        "programs.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="enrollment_adjustments",
        verbose_name="período letivo",
    )
    status = models.CharField(
        "situação",
        max_length=20,
        choices=Status,
        default=Status.OPEN,
    )
    justification = models.TextField("justificativa do aluno", blank=True)
    decision_note = models.TextField("motivo da decisão", blank=True)
    # Vazio enquanto Aberta; carimbado por approve()/reject().
    decided_at = models.DateTimeField("decidida em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = EnrollmentAdjustmentRequestQuerySet.as_manager()

    class Meta:
        verbose_name = "solicitação de acerto de matrícula"
        verbose_name_plural = "solicitações de acerto de matrícula"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Acerto de {self.student} em {self.term}"

    def approve(self, *, note: str = "") -> None:
        """Aprova a solicitação.

        Invariante: só se decide o que está Aberto. Decidir de novo é erro
        do chamador, não no-op silencioso. A nota é opcional aqui — quem
        aprova não deve satisfação; quem recusa, sim.
        """
        self._exigir_aberta()
        self.status = self.Status.APPROVED
        self.decision_note = note
        self.decided_at = timezone.now()

    def reject(self, *, note: str) -> None:
        """Recusa a solicitação, com motivo obrigatório.

        O motivo é o que o aluno lê na tela dele para saber o que corrigir;
        recusa sem motivo é uma porta fechada sem explicação.
        """
        self._exigir_aberta()
        if not note.strip():
            raise DomainError(
                "Recusar exige um motivo.",
                code="rejection_requires_note",
            )
        self.status = self.Status.REJECTED
        self.decision_note = note
        self.decided_at = timezone.now()

    def _exigir_aberta(self) -> None:
        if self.status != self.Status.OPEN:
            raise InvalidStateTransition("Esta solicitação de acerto já foi decidida.")

    def clean(self) -> None:
        """A FK `program` é direta (ADR-007 dec. 5) e por isso pode divergir
        da do aluno. Divergir significa AuditLog com a chave de tenant
        errada — é invariante, não detalhe de formulário.

        `term` fica de fora de propósito: período letivo é institucional e
        não tem programa para comparar (ADR-007 dec. 4).
        """
        super().clean()
        try:
            student = self.student
        except ObjectDoesNotExist:
            # Sem aluno ainda: quem cobra a obrigatoriedade é o schema
            # Ninja (borda) e o NOT NULL da coluna, não este invariante.
            return
        if self.program_id != student.program_id:
            raise DomainError(
                "O programa da solicitação precisa ser o mesmo do aluno.",
                code="program_mismatch",
            )


class EnrollmentAdjustmentItem(models.Model):
    """Uma mudança pedida: incluir ou excluir uma disciplina.

    Sem estado próprio — quem é aprovado ou recusado é a solicitação
    inteira. CASCADE porque item órfão não significa nada.
    """

    class Action(models.TextChoices):
        ADD = "add", "Incluir"
        DROP = "drop", "Excluir"

    request = models.ForeignKey(
        EnrollmentAdjustmentRequest,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="solicitação",
    )
    discipline = models.ForeignKey(
        "programs.Discipline",
        on_delete=models.PROTECT,
        related_name="enrollment_adjustment_items",
        verbose_name="disciplina",
    )
    action = models.CharField("ação", max_length=10, choices=Action)

    class Meta:
        verbose_name = "item do acerto de matrícula"
        verbose_name_plural = "itens do acerto de matrícula"
        ordering = ["discipline__code"]
        constraints = [
            # Pedir duas vezes a mesma coisa é ruído; pedir incluir E
            # excluir a mesma disciplina segue possível e é o orientador
            # quem julga.
            models.UniqueConstraint(
                fields=["request", "discipline", "action"],
                name="unique_item_por_solicitacao",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.discipline}"
