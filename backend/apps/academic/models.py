"""Vida acadêmica do programa: quem ensina e quem estuda.

O app depende de `programs` (linha de pesquisa, projeto coletivo, período
letivo) e de `people` (a pessoa por trás do vínculo). A dependência é
sempre nesta direção — `programs` e `people` não conhecem `academic`.
"""

from datetime import date

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from apps.core.exceptions import DomainError


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
