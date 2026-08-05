"""Vida acadêmica do programa: quem ensina e quem estuda.

O app depende de `programs` (linha de pesquisa, projeto coletivo, período
letivo) e de `people` (a pessoa por trás do vínculo). A dependência é
sempre nesta direção — `programs` e `people` não conhecem `academic`.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from apps.core.exceptions import DomainError


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
