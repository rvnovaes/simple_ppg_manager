"""Vida acadêmica do programa: quem ensina e quem estuda.

O app depende de `programs` (linha de pesquisa, projeto coletivo, período
letivo) e de `people` (a pessoa por trás do vínculo). A dependência é
sempre nesta direção — `programs` e `people` não conhecem `academic`.
"""

from datetime import date, datetime

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


class IsolatedEnrollmentCycleQuerySet(models.QuerySet):
    def for_program(self, program) -> "IsolatedEnrollmentCycleQuerySet":
        return self.filter(program=program)

    def active(self) -> "IsolatedEnrollmentCycleQuerySet":
        return self.filter(is_active=True)


class IsolatedEnrollmentCycle(models.Model):
    """Edital de matrícula em disciplina isolada de um semestre.

    O ciclo é o calendário do edital transformado em dado: enquanto as
    datas moram aqui, é o sistema que recusa a inscrição fora do prazo, e
    não a secretaria conferindo à mão. Um ciclo por período letivo por
    programa — o edital é único no semestre.

    A FK `program` é direta mesmo sendo alcançável por navegação
    (ADR-007 dec. 5): sem ela `apps.core.audit.record()` grava AuditLog
    com `program=None` e o rastro perde a chave de tenant. `term` não tem
    programa para comparar — período letivo é institucional (ADR-007
    dec. 4).
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="isolated_cycles",
        verbose_name="programa",
    )
    term = models.ForeignKey(
        "programs.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="isolated_cycles",
        verbose_name="período letivo",
    )
    submission_opens_at = models.DateTimeField("inscrições abrem em")
    submission_closes_at = models.DateTimeField("inscrições encerram em")
    # Data, e não instante: o edital publica o resultado num dia, sem hora.
    result_published_on = models.DateField("resultado publicado em")
    appeal_opens_at = models.DateTimeField("recursos abrem em")
    appeal_closes_at = models.DateTimeField("recursos encerram em")
    final_result_on = models.DateField("resultado final em")
    payment_closes_at = models.DateTimeField("pagamento encerra em")
    is_active = models.BooleanField("ativo", default=True)

    objects = IsolatedEnrollmentCycleQuerySet.as_manager()

    class Meta:
        verbose_name = "ciclo de matrícula em isolada"
        verbose_name_plural = "ciclos de matrícula em isolada"
        ordering = ["-term__year", "-term__half"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "term"],
                name="unique_ciclo_isolada_por_programa_e_periodo",
            ),
        ]

    def __str__(self) -> str:
        return f"Isoladas {self.term}"

    def clean(self) -> None:
        """As datas do edital só fazem sentido em ordem.

        Uma janela de recurso que abre antes das inscrições fecharem, ou um
        prazo de pagamento anterior ao resultado, deixaria `submit()` e
        `appeal()` (US-004) aceitando e recusando pelas razões erradas pelo
        resto do semestre. O erro é do formulário da secretaria, então é
        400 (`DomainError`) e não 409.

        `<=` entre fechamento e abertura da fase seguinte porque encadear
        as duas no mesmo instante é legítimo; `<` dentro de cada janela
        porque janela de duração zero não aceita ninguém.
        """
        super().clean()
        campos = (
            self.submission_opens_at,
            self.submission_closes_at,
            self.appeal_opens_at,
            self.appeal_closes_at,
            self.payment_closes_at,
        )
        if any(campo is None for campo in campos):
            # Obrigatoriedade é cobrança do schema Ninja e do NOT NULL.
            return
        if not (
            self.submission_opens_at
            < self.submission_closes_at
            <= self.appeal_opens_at
            < self.appeal_closes_at
            <= self.payment_closes_at
        ):
            raise DomainError(
                "As datas do ciclo precisam estar em ordem: abertura e "
                "encerramento das inscrições, janela de recurso e prazo de "
                "pagamento.",
                code="invalid_cycle_dates",
            )

    def submission_open(self, at: datetime) -> bool:
        """A janela de inscrição inclui a abertura e exclui o fechamento —
        quem chega no instante exato do prazo chegou tarde.
        """
        return self.submission_opens_at <= at < self.submission_closes_at

    def appeal_open(self, at: datetime) -> bool:
        return self.appeal_opens_at <= at < self.appeal_closes_at


class DisciplineOfferingQuerySet(models.QuerySet):
    def for_program(self, program) -> "DisciplineOfferingQuerySet":
        return self.filter(program=program)

    def for_cycle(self, cycle: IsolatedEnrollmentCycle) -> "DisciplineOfferingQuerySet":
        return self.filter(cycle=cycle)


class DisciplineOffering(models.Model):
    """Disciplina oferecida às isoladas num ciclo, com vagas e responsável.

    A oferta é a disciplina do catálogo recortada por um semestre: o mesmo
    `Discipline` reaparece a cada ciclo com outro número de vagas e, às
    vezes, outro docente. Uma oferta por disciplina por ciclo — repetir a
    disciplina no mesmo edital dividiria as vagas em duas contagens que
    ninguém consegue somar.

    `teacher` é obrigatório porque a classificação dos candidatos
    (US-011) é ato dele: sem responsável definido a oferta trava o fluxo,
    e é melhor travar no cadastro do que na hora do deferimento.

    A FK `program` é direta mesmo sendo alcançável por `cycle`
    (ADR-007 dec. 5): sem ela `apps.core.audit.record()` grava AuditLog
    com `program=None`.
    """

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="offerings",
        verbose_name="programa",
    )
    cycle = models.ForeignKey(
        IsolatedEnrollmentCycle,
        on_delete=models.PROTECT,
        related_name="offerings",
        verbose_name="ciclo",
    )
    discipline = models.ForeignKey(
        "programs.Discipline",
        on_delete=models.PROTECT,
        related_name="offerings",
        verbose_name="disciplina",
    )
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,
        related_name="offerings",
        verbose_name="docente responsável",
    )
    seats = models.PositiveSmallIntegerField("vagas")

    objects = DisciplineOfferingQuerySet.as_manager()

    class Meta:
        verbose_name = "oferta de disciplina"
        verbose_name_plural = "ofertas de disciplina"
        ordering = ["discipline__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["cycle", "discipline"],
                name="unique_oferta_por_ciclo_e_disciplina",
            ),
        ]
        permissions = [
            # Classificar é ato do docente responsável e nada mais: quem
            # ordena os candidatos não precisa poder editar a oferta, e
            # quem edita a oferta (secretaria) não classifica ninguém.
            ("rank_disciplineoffering", "Pode classificar candidatos da oferta"),
        ]

    def __str__(self) -> str:
        return f"{self.discipline} ({self.cycle})"

    def seats_taken(self) -> int:
        """Vagas já comprometidas nesta oferta.

        Conta o deferido e o matriculado: deferir é o ato que reserva a
        vaga, e a matrícula é o mesmo candidato um passo adiante — contar
        só DEFERRED faria a vaga reaparecer no instante em que a
        secretaria efetiva a matrícula (US-014), e a oferta aceitaria mais
        gente do que tem lugar.

        Inscrito NÃO conta: a vaga é da decisão da secretaria, não da
        intenção do candidato — senão a fila de inscritos esgotaria as
        vagas antes de alguém ser julgado. Cancelado devolve a vaga, que é
        exatamente para isso que `cancel()` existe (US-004).
        """
        return self.items.filter(
            request__status__in=(
                IsolatedRequestStatus.DEFERRED,
                IsolatedRequestStatus.ENROLLED,
            )
        ).count()

    def seats_available(self) -> int:
        """Nunca negativo: `seats` reduzido depois de deferimentos deixaria
        a conta abaixo de zero, e vaga negativa não significa nada para
        quem lê a tela.
        """
        return max(self.seats - self.seats_taken(), 0)

    def candidates(self) -> "models.QuerySet[IsolatedEnrollmentItem]":
        """Quem disputa esta oferta, na ordem em que o docente decidiu.

        Só o inscrito: rascunho ainda não é candidatura, e deferido,
        recusado ou cancelado já passou pela secretaria — classificar
        depois da decisão mudaria o corte de vagas por baixo dela.

        Sem posição vem por último (`nulls_last`), não primeiro: a lista
        classificada é a resposta do docente e tem de ficar no topo
        quando ele reabre a tela. Empate de "sem posição" desempata pelo
        nome, para a ordem não variar entre duas leituras.
        """
        if self.pk is None:
            return IsolatedEnrollmentItem.objects.none()
        return (
            self.items.filter(request__status=IsolatedRequestStatus.SUBMITTED)
            .select_related("request__person")
            .order_by(
                models.F("rank").asc(nulls_last=True), "request__person__full_name"
            )
        )

    def needs_ranking(self) -> bool:
        """Ainda falta classificar alguém aqui.

        É o marcador da lista do docente (`?mine=true`): oferta sem
        inscrito nenhum não "falta classificar" — não há o que ordenar —,
        e oferta com todo mundo posicionado já foi respondida.
        """
        if self.pk is None:
            return False
        return self.items.filter(
            request__status=IsolatedRequestStatus.SUBMITTED, rank__isnull=True
        ).exists()

    def rank_items(self, item_ids: list[int]) -> list["IsolatedEnrollmentItem"]:
        """Posição 1..N na ordem recebida, SEM salvar.

        Devolve os itens já com o `rank` em memória; quem persiste é o
        router, no mesmo `transaction.atomic()` do AuditLog — igual às
        transições de estado do requerimento.

        Item que não é candidato desta oferta é `item_not_in_offering`
        (400): a lista que o docente devolve é a MESMA que ele recebeu de
        `candidates()`, então id de fora é erro de chamada, não escolha.
        """
        candidatos = {item.pk: item for item in self.candidates()}
        if any(item_id not in candidatos for item_id in item_ids):
            raise DomainError(
                "A classificação só aceita candidatos inscritos nesta oferta.",
                code="item_not_in_offering",
            )
        ordenados = []
        for posicao, item_id in enumerate(item_ids, start=1):
            item = candidatos[item_id]
            item.rank = posicao
            ordenados.append(item)
        return ordenados

    def clean(self) -> None:
        """Ciclo, disciplina e docente têm de ser todos do mesmo programa.

        Cada um deles carrega a própria FK de programa, então nada impede
        no banco montar uma oferta que mistura tenants — e a mistura só
        apareceria lá na frente, com candidato inscrito em disciplina de
        outro programa. É invariante, não detalhe de formulário.
        """
        super().clean()
        outros = []
        for campo in ("cycle", "discipline", "teacher"):
            try:
                relacionado = getattr(self, campo)
            except ObjectDoesNotExist:
                # Obrigatoriedade é cobrança do schema Ninja e do NOT NULL.
                continue
            outros.append(relacionado.program_id)
        if self.program_id is None or not outros:
            return
        if any(program_id != self.program_id for program_id in outros):
            raise DomainError(
                "O ciclo, a disciplina e o docente da oferta precisam ser do "
                "mesmo programa.",
                code="program_mismatch",
            )


# Limite do edital: até duas disciplinas por candidato por semestre. Mora
# no módulo, e não dentro do model, porque a borda (schema Ninja e tela)
# precisa do mesmo número para impedir a terceira antes de submeter.
MAX_ISOLATED_ITEMS = 2


class IsolatedRequestStatus(models.TextChoices):
    """Situação do requerimento de isolada, no vocabulário do edital.

    Mora fora do model, com nome único, porque o gerador de OpenAPI batiza
    o schema do enum com o `__name__` da classe: dois `Status` aninhados
    colidem e o último registrado sobrescreve o outro, silenciosamente.
    `IsolatedEnrollmentRequest.Status` continua valendo pelo alias.
    """

    DRAFT = "draft", "Rascunho"
    SUBMITTED = "submitted", "Inscrito"
    DEFERRED = "deferred", "Deferido"
    REJECTED = "rejected", "Indeferido"
    CANCELLED = "cancelled", "Cancelado"
    ENROLLED = "enrolled", "Matriculado"


class IsolatedPaymentStatus(models.TextChoices):
    """Situação da taxa (GRU) do requerimento.

    Separada do `status` porque as duas caminham em ritmos diferentes: o
    deferimento é decisão da secretaria, o pagamento é ato do candidato, e
    é a combinação das duas que libera a matrícula (US-004 `enroll()`).
    Fora do model pelo mesmo motivo de colisão de nome no OpenAPI.
    """

    PENDING = "pending", "Pendente"
    PAID = "paid", "Pago"
    EXEMPT = "exempt", "Isento"


class IsolatedEnrollmentRequestQuerySet(models.QuerySet):
    def for_program(self, program) -> "IsolatedEnrollmentRequestQuerySet":
        return self.filter(program=program)

    def for_cycle(
        self, cycle: IsolatedEnrollmentCycle
    ) -> "IsolatedEnrollmentRequestQuerySet":
        return self.filter(cycle=cycle)

    def visible_to(self, user, program) -> "IsolatedEnrollmentRequestQuerySet":
        """O que esta sessão pode ler — sempre depois de `for_program`.

        `view_isolatedenrollmentrequest` é permissão de papel: ela diz que
        a pessoa acompanha requerimento, não QUAIS requerimentos. O recorte
        é aqui, como em `EnrollmentAdjustmentRequestQuerySet.visible_to`.

        Secretaria e Coordenação (e o superusuário, que opera a plataforma)
        veem o edital inteiro. Todo o resto vê a união do que é seu como
        candidato e do que chega a ele como docente responsável por uma
        oferta — união, e não dois ramos, porque nada impede que o docente
        também se inscreva numa isolada de outro programa... e, no mesmo
        programa, que a mesma pessoa acumule os dois papéis.
        """
        if (
            user.is_superuser
            or user.groups.filter(name__in=PAPEIS_COM_VISAO_DO_PROGRAMA).exists()
        ):
            return self
        pessoas = Person.objects.active().filter(user=user, program=program)
        # `distinct` porque o lado do docente atravessa `items` (um-para-
        # muitos): requerimento com duas disciplinas do mesmo docente
        # apareceria duas vezes sem ele.
        return self.filter(
            models.Q(person__in=pessoas)
            | models.Q(items__offering__teacher__person__in=pessoas)
        ).distinct()


class IsolatedEnrollmentRequest(models.Model):
    """Requerimento de uma pessoa para cursar isoladas num ciclo.

    Um requerimento por pessoa por ciclo: a inscrição carrega até duas
    disciplinas (`items`, US-005), e não duas inscrições. É o que mantém
    documentação e taxa únicas — o edital cobra uma GRU por candidato, não
    uma por disciplina.

    `person` e não `student`: quem se inscreve ainda não é aluno. O
    `Student` com `modality=ISOLATED` só nasce na efetivação (US-014).

    A FK `program` é direta mesmo sendo alcançável por `cycle`
    (ADR-007 dec. 5): sem ela `apps.core.audit.record()` grava AuditLog
    com `program=None` e o rastro perde a chave de tenant.
    """

    Status = IsolatedRequestStatus
    PaymentStatus = IsolatedPaymentStatus

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="isolated_requests",
        verbose_name="programa",
    )
    cycle = models.ForeignKey(
        IsolatedEnrollmentCycle,
        on_delete=models.PROTECT,
        related_name="requests",
        verbose_name="ciclo",
    )
    person = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="isolated_requests",
        verbose_name="candidato",
    )
    status = models.CharField(
        "situação",
        max_length=20,
        choices=Status,
        default=Status.DRAFT,
    )
    payment_status = models.CharField(
        "situação do pagamento",
        max_length=20,
        choices=PaymentStatus,
        default=PaymentStatus.PENDING,
    )
    # Servidor da UFMG é isento da taxa, mas em troca precisa juntar
    # contracheque e autorização da chefia (US-006).
    is_ufmg_staff = models.BooleanField("é servidor da UFMG", default=False)
    # Link da GRU, gravado pela secretaria no deferimento (US-012). O
    # sistema não emite a guia; ela vem do sistema de arrecadação da UFMG.
    gru_url = models.URLField("link da GRU", blank=True)
    decision_note = models.TextField("motivo da decisão", blank=True)
    # Vazio enquanto não decidido; carimbado por defer()/reject() (US-004).
    decided_at = models.DateTimeField("decidido em", null=True, blank=True)
    appeal_note = models.TextField("razões do recurso", blank=True)
    appealed_at = models.DateTimeField("recurso interposto em", null=True, blank=True)
    # Vazio enquanto Rascunho; carimbado por submit() (US-004).
    submitted_at = models.DateTimeField("inscrito em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = IsolatedEnrollmentRequestQuerySet.as_manager()

    class Meta:
        verbose_name = "requerimento de isolada"
        verbose_name_plural = "requerimentos de isolada"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cycle", "person"],
                name="unique_requerimento_isolada_por_ciclo_e_pessoa",
            ),
        ]

    def __str__(self) -> str:
        return f"Requerimento de {self.person} em {self.cycle}"

    def clean(self) -> None:
        """A FK `program` é direta (ADR-007 dec. 5) e por isso pode divergir
        da do ciclo e da pessoa. Divergir significa AuditLog com a chave de
        tenant errada — é invariante, não detalhe de formulário.
        """
        super().clean()
        outros = []
        for campo in ("cycle", "person"):
            try:
                relacionado = getattr(self, campo)
            except ObjectDoesNotExist:
                # Obrigatoriedade é cobrança do schema Ninja e do NOT NULL.
                continue
            outros.append(relacionado.program_id)
        if self.program_id is None or not outros:
            return
        if any(program_id != self.program_id for program_id in outros):
            raise DomainError(
                "O ciclo e o candidato do requerimento precisam ser do mesmo programa.",
                code="program_mismatch",
            )

    def submit(self, *, at: datetime) -> None:
        """Inscreve o candidato: Rascunho vira Inscrito.

        `at` vem por parâmetro, e não de `timezone.now()` aqui dentro,
        porque a janela é do edital e o teste precisa poder escolher o
        instante sem congelar o relógio — mesmo motivo de
        `IsolatedEnrollmentCycle.submission_open()`.

        A contagem de itens é validação de método, e não constraint de
        banco: ela depende de contar linhas relacionadas, coisa que
        `CheckConstraint` não faz. Vem depois da checagem de estado e de
        janela de propósito — as duas primeiras não tocam o banco, então
        o erro barato sai antes da consulta.

        A documentação obrigatória é a última cobrança, e não a primeira,
        pelo mesmo motivo: ela consulta os anexos.
        """
        self._exigir_status(
            self.Status.DRAFT,
            "Só um requerimento em rascunho pode ser inscrito.",
        )
        if not self.cycle.submission_open(at):
            raise DomainError(
                "As inscrições deste ciclo não estão abertas.",
                code="submission_window_closed",
            )
        if not 1 <= self.items.count() <= MAX_ISOLATED_ITEMS:
            raise DomainError(
                "A inscrição precisa ter uma ou duas disciplinas.",
                code="invalid_item_count",
            )
        if self.missing_documents():
            raise DomainError(
                "A inscrição só pode ser enviada com toda a documentação "
                "obrigatória anexada.",
                code="missing_documents",
            )
        self.status = self.Status.SUBMITTED
        self.submitted_at = at

    def ensure_editable(self) -> None:
        """Só o rascunho aceita mudança de disciplina ou de vínculo.

        Depois de inscrito, o requerimento é a peça que o docente
        classifica e a secretaria julga: trocar as disciplinas ali dentro
        mudaria a fila das vagas debaixo de quem já foi ordenado. Quem
        errou a escolha cancela e o edital decide se cabe nova inscrição.
        """
        self._exigir_status(
            self.Status.DRAFT,
            "Só um requerimento em rascunho pode ser alterado.",
        )

    def ensure_document_upload_allowed(self, kind: str) -> None:
        """Quando cada tipo de anexo ainda pode ser enviado.

        A documentação da inscrição acompanha `ensure_editable()`: depois
        de inscrito, trocar a identidade ou o diploma mudaria a peça que o
        docente classifica e a secretaria julga.

        O comprovante da GRU é o oposto e por isso tem regra própria: ele
        não existe no rascunho — a guia só é emitida no deferimento —, e
        exigi-lo no mesmo estado dos outros fecharia a porta do pagamento
        (US-013).
        """
        if kind == RequestDocumentKind.PAYMENT_RECEIPT:
            self._exigir_status(
                self.Status.DEFERRED,
                "O comprovante da GRU só é anexado depois do deferimento.",
            )
            return
        self._exigir_status(
            self.Status.DRAFT,
            "A documentação só é anexada enquanto o requerimento é rascunho.",
        )

    def required_document_kinds(self) -> list[str]:
        """Tipos de documento que este requerimento precisa ter anexados.

        Servidor da UFMG junta contracheque e autorização da chefia: é o
        que sustenta a isenção da taxa (`defer()`) e a liberação do
        horário. O comprovante da GRU fica de fora de propósito — ele só
        existe depois do deferimento, quando a secretaria emite a guia.
        """
        obrigatorios = [
            RequestDocumentKind.IDENTITY,
            RequestDocumentKind.DIPLOMA,
            RequestDocumentKind.LATTES,
            RequestDocumentKind.ADDRESS,
        ]
        if self.is_ufmg_staff:
            obrigatorios += [
                RequestDocumentKind.PAYSLIP,
                RequestDocumentKind.SUPERVISOR_AUTH,
            ]
        return [str(kind) for kind in obrigatorios]

    def missing_documents(self) -> list[str]:
        """Os tipos obrigatórios que ainda faltam anexar, na ordem do edital.

        Requerimento sem pk não tem anexo nenhum por definição, e o
        acessor reverso levantaria `ValueError` nele — a saída antecipada
        mantém o invariante testável em memória, sem banco.
        """
        exigidos = self.required_document_kinds()
        if self.pk is None:
            return exigidos
        anexados = set(self.documents.values_list("kind", flat=True))
        return [kind for kind in exigidos if kind not in anexados]

    def defer(self, *, note: str = "") -> None:
        """Defere o requerimento.

        A nota é opcional: quem defere não deve satisfação; quem indefere,
        sim. Servidor da UFMG nasce isento aqui — a isenção é consequência
        automática do vínculo declarado, e não uma segunda decisão da
        secretaria que ela poderia esquecer de tomar.
        """
        self._exigir_status(
            self.Status.SUBMITTED,
            "Só um requerimento inscrito pode ser deferido.",
        )
        self.status = self.Status.DEFERRED
        self.decision_note = note
        self.decided_at = timezone.now()
        if self.is_ufmg_staff:
            self.payment_status = self.PaymentStatus.EXEMPT

    def reject(self, *, note: str) -> None:
        """Indefere o requerimento, com motivo obrigatório.

        O motivo é o que o candidato lê na tela dele e o que ele contesta
        no recurso; indeferir sem motivo é uma porta fechada sem
        explicação e um recurso impossível de escrever.
        """
        self._exigir_status(
            self.Status.SUBMITTED,
            "Só um requerimento inscrito pode ser indeferido.",
        )
        if not note.strip():
            raise DomainError(
                "Indeferir exige um motivo.",
                code="rejection_requires_note",
            )
        self.status = self.Status.REJECTED
        self.decision_note = note
        self.decided_at = timezone.now()

    def cancel(self, *, note: str = "") -> None:
        """Cancela o requerimento e, com ele, devolve a vaga.

        É a única saída de um deferido que não pagou: não existe
        expiração automática no projeto (nada roda sozinho), então a vaga
        só volta para a fila quando a secretaria cancela explicitamente.
        Cancelar um inscrito é a desistência do candidato antes da
        decisão.
        """
        if self.status not in (self.Status.SUBMITTED, self.Status.DEFERRED):
            raise InvalidStateTransition(
                "Só um requerimento inscrito ou deferido pode ser cancelado."
            )
        self.status = self.Status.CANCELLED
        self.decision_note = note
        self.decided_at = timezone.now()

    def appeal(self, *, note: str, at: datetime) -> None:
        """Interpõe recurso contra o indeferimento.

        Não mexe no `status` de propósito: o recurso é pedido de
        rejulgamento, não deferimento automático. O requerimento continua
        Indeferido até a secretaria decidir de novo — e é o `appealed_at`
        que a coloca na fila de rejulgamento.
        """
        self._exigir_status(
            self.Status.REJECTED,
            "Só cabe recurso de requerimento indeferido.",
        )
        if not self.cycle.appeal_open(at):
            raise DomainError(
                "A janela de recurso deste ciclo não está aberta.",
                code="appeal_window_closed",
            )
        if not note.strip():
            raise DomainError(
                "O recurso exige as razões do pedido.",
                code="appeal_requires_note",
            )
        self.appeal_note = note
        self.appealed_at = at

    def enroll(self) -> None:
        """Efetiva a matrícula: Deferido vira Matriculado.

        Deferimento e pagamento são atos de pessoas diferentes e é a
        combinação dos dois que libera a matrícula. Isento passa sem
        comprovante nenhum — é o servidor da UFMG, que já pagou com o
        contracheque que anexou.
        """
        self._exigir_status(
            self.Status.DEFERRED,
            "Só um requerimento deferido pode virar matrícula.",
        )
        if self.payment_status not in (
            self.PaymentStatus.PAID,
            self.PaymentStatus.EXEMPT,
        ):
            raise DomainError(
                "A taxa do requerimento ainda não foi paga.",
                code="payment_required",
            )
        self.status = self.Status.ENROLLED

    def _exigir_status(self, esperado: str, mensagem: str) -> None:
        """Transição a partir do estado errado é 409, no padrão de
        `Person.archive()`: erro do chamador, não no-op silencioso.
        """
        if self.status != esperado:
            raise InvalidStateTransition(mensagem)


class IsolatedEnrollmentItem(models.Model):
    """Uma disciplina pedida dentro de um requerimento de isolada.

    O requerimento é único por pessoa por ciclo e carrega de uma a duas
    disciplinas (`MAX_ISOLATED_ITEMS`, cobrado em
    `IsolatedEnrollmentRequest.submit()`): documentação e taxa são do
    candidato, a escolha é por disciplina.

    `rank` é a posição que o docente responsável atribui na oferta
    (US-011) e nasce nulo — antes de ele classificar, ninguém tem
    posição, e é essa ausência que a secretaria vê como "oferta ainda não
    classificada" no deferimento (US-012). Nulo não é zero nem último.

    Sem FK `program` direta, ao contrário do resto (ADR-007 dec. 5): o
    item não é alvo de AuditLog próprio — quem é auditado é o
    requerimento, que já carrega o tenant. O `on_delete=CASCADE` para
    `request` diz o mesmo: item não existe sem o requerimento dele.
    """

    request = models.ForeignKey(
        IsolatedEnrollmentRequest,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="requerimento",
    )
    offering = models.ForeignKey(
        DisciplineOffering,
        on_delete=models.PROTECT,
        related_name="items",
        verbose_name="oferta",
    )
    rank = models.PositiveSmallIntegerField("classificação", null=True, blank=True)

    class Meta:
        verbose_name = "item do requerimento de isolada"
        verbose_name_plural = "itens do requerimento de isolada"
        ordering = ["offering__discipline__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "offering"],
                name="unique_item_por_requerimento_e_oferta",
            ),
            # Duas pessoas na mesma posição da mesma oferta tornam o corte
            # das vagas indecidível. A condição deixa de fora o rank nulo:
            # antes da classificação todo mundo empata em "sem posição", e
            # isso é o estado normal, não uma violação.
            models.UniqueConstraint(
                fields=["offering", "rank"],
                condition=models.Q(rank__isnull=False),
                name="unique_classificacao_por_oferta",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.offering} em {self.request}"

    def clean(self) -> None:
        """O item só pode apontar para uma oferta do mesmo ciclo.

        Nada no banco impede montar um requerimento de 2026/1 com uma
        oferta de 2026/2 — e a mistura só apareceria no deferimento, com
        a vaga sendo descontada do edital errado.
        """
        super().clean()
        try:
            requerimento = self.request
            oferta = self.offering
        except ObjectDoesNotExist:
            # Obrigatoriedade é cobrança do schema Ninja e do NOT NULL.
            return
        if requerimento.cycle_id != oferta.cycle_id:
            raise DomainError(
                "A disciplina escolhida precisa ser uma oferta do mesmo ciclo "
                "do requerimento.",
                code="cycle_mismatch",
            )


def caminho_do_documento(instance: "RequestDocument", filename: str) -> str:
    """Onde o anexo é gravado dentro do MEDIA_ROOT.

    Particionado por ciclo e por requerimento porque a operação do
    edital é por lote: a secretaria arquiva, copia ou apaga um semestre
    inteiro, e um diretório plano com milhares de arquivos torna isso
    manual. Função de módulo, e não lambda, porque a migração precisa
    conseguir serializar a referência.
    """
    return (
        f"isoladas/ciclo-{instance.request.cycle_id}/"
        f"requerimento-{instance.request_id}/{filename}"
    )


# O que o edital aceita como anexo. PDF é o formato do diploma e do
# Lattes; imagem entra porque comprovante de endereço e identidade quase
# sempre chegam como foto de celular. Nada além disso: documento de
# candidato é lido pela secretaria, não executado.
EXTENSOES_DE_DOCUMENTO = (".pdf", ".jpg", ".jpeg", ".png")
# 10 MB por arquivo — foto de celular cabe com folga e PDF digitalizado
# também; acima disso é digitalização mal configurada, não documento.
TAMANHO_MAXIMO_DO_DOCUMENTO = 10 * 1024 * 1024


class RequestDocumentQuerySet(models.QuerySet):
    def for_program(self, program) -> "RequestDocumentQuerySet":
        """O anexo não tem FK `program` (ele mora no requerimento), então
        o escopo de tenant atravessa a FK — mas continua obrigatório e
        continua sendo o primeiro filtro de toda busca.
        """
        return self.filter(request__program=program)


class RequestDocumentKind(models.TextChoices):
    """Os documentos que o edital cobra do candidato.

    Classe de módulo com nome único: dois enums aninhados de mesmo nome
    colidem no gerador de OpenAPI e o último registrado sobrescreve o
    outro, sem erro no backend.
    """

    IDENTITY = "identity", "Identidade e CPF"
    DIPLOMA = "diploma", "Diploma de graduação ou certidão de conclusão"
    LATTES = "lattes", "Currículo Lattes em PDF"
    ADDRESS = "address", "Comprovante de endereço"
    PAYSLIP = "payslip", "Contracheque de servidor da UFMG"
    SUPERVISOR_AUTH = "supervisor_auth", "Autorização da chefia"
    PAYMENT_RECEIPT = "payment_receipt", "Comprovante de pagamento da GRU"


class RequestDocument(models.Model):
    """Um documento anexado a um requerimento de isolada.

    Um por tipo (`UniqueConstraint`): reenviar o comprovante de endereço
    é substituir o anterior, não empilhar duas versões e deixar a
    secretaria adivinhar qual vale.

    Sem FK `program` direta, como `IsolatedEnrollmentItem` e pelo mesmo
    motivo (ADR-007 dec. 5): o anexo não é alvo de AuditLog próprio —
    quem é auditado é o requerimento, que carrega o tenant — e o
    `on_delete=CASCADE` diz que ele não existe fora dele.
    """

    Kind = RequestDocumentKind

    request = models.ForeignKey(
        IsolatedEnrollmentRequest,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="requerimento",
    )
    kind = models.CharField("tipo", max_length=20, choices=Kind)
    file = models.FileField("arquivo", upload_to=caminho_do_documento)
    uploaded_at = models.DateTimeField("anexado em", auto_now_add=True)

    objects = RequestDocumentQuerySet.as_manager()

    class Meta:
        verbose_name = "documento do requerimento"
        verbose_name_plural = "documentos do requerimento"
        ordering = ["kind"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "kind"],
                name="unique_documento_por_requerimento_e_tipo",
            ),
        ]
        permissions = [
            # Baixar o anexo é mais do que ver o requerimento: são dados
            # pessoais do candidato (documento de identidade,
            # contracheque). Quem lista a fila não precisa disso.
            ("download_requestdocument", "Pode baixar documento do requerimento"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} de {self.request}"

    @classmethod
    def validate_upload(cls, *, filename: str, size: int) -> None:
        """Formato e tamanho do que chega — invariante, não detalhe da borda.

        Fica no model, e não num validador de campo, porque o arquivo que
        interessa validar é o que a requisição traz: `FileField.validators`
        só roda em `full_clean()` e não vê o tamanho do upload. Método de
        classe porque a checagem antecede a instância — recusar antes de
        gravar é o ponto.

        Um único `code="invalid_document"` para os dois casos: a tela
        mostra a mensagem, e distinguir extensão de tamanho no `code` só
        multiplicaria contrato.
        """
        if not filename or not filename.lower().endswith(EXTENSOES_DE_DOCUMENTO):
            aceitas = ", ".join(EXTENSOES_DE_DOCUMENTO)
            raise DomainError(
                f"O documento precisa ser um arquivo {aceitas}.",
                code="invalid_document",
            )
        if size > TAMANHO_MAXIMO_DO_DOCUMENTO:
            limite = TAMANHO_MAXIMO_DO_DOCUMENTO // (1024 * 1024)
            raise DomainError(
                f"O documento tem no máximo {limite} MB.",
                code="invalid_document",
            )
