"""Programa de pós-graduação — a chave de tenant do sistema — e a
estrutura acadêmica que pertence a ele (linha de pesquisa, projeto
coletivo).

O sistema nasce para o PPGD, mas todo dado de negócio carrega a FK de
programa desde a primeira migração (Seção 1 do CLAUDE.md). Adicionar a
chave depois, com dados em produção, é caro; adicionar agora é de graça.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from apps.core.exceptions import DomainError


class ProgramQuerySet(models.QuerySet):
    def active(self) -> "ProgramQuerySet":
        return self.filter(is_active=True)


class Program(models.Model):
    name = models.CharField("nome", max_length=200)
    acronym = models.CharField("sigla", max_length=20, unique=True)
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProgramQuerySet.as_manager()

    class Meta:
        verbose_name = "programa"
        verbose_name_plural = "programas"
        ordering = ["acronym"]

    def __str__(self) -> str:
        return self.acronym


class ResearchLineQuerySet(models.QuerySet):
    def active(self) -> "ResearchLineQuerySet":
        return self.filter(is_active=True)

    def for_program(self, program: Program) -> "ResearchLineQuerySet":
        return self.filter(program=program)


class ResearchLine(models.Model):
    """Linha de pesquisa do programa.

    Agrupa projetos coletivos e é a referência que professores e alunos
    citam. Desativar (is_active=False) em vez de apagar: linha antiga
    continua sendo a linha de quem se vinculou a ela.
    """

    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="research_lines",
        verbose_name="programa",
    )
    name = models.CharField("nome", max_length=200)
    is_active = models.BooleanField("ativa", default=True)

    objects = ResearchLineQuerySet.as_manager()

    class Meta:
        verbose_name = "linha de pesquisa"
        verbose_name_plural = "linhas de pesquisa"
        ordering = ["name"]
        constraints = [
            # Nome é único dentro do programa, não globalmente: dois
            # programas podem ter linhas homônimas.
            models.UniqueConstraint(
                fields=["program", "name"],
                name="unique_linha_por_programa",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        """Nome duplicado no mesmo programa já é barrado pela constraint do
        banco; validar aqui é o que faz a violação chegar como 400 com code
        estável em vez de IntegrityError virando 500.
        """
        super().clean()
        if not self.name or self.program_id is None:
            # Campo obrigatório ausente é cobrança do schema Ninja e do NOT
            # NULL da coluna, não deste invariante.
            return
        duplicatas = ResearchLine.objects.filter(
            program_id=self.program_id, name=self.name
        )
        if self.pk is not None:
            duplicatas = duplicatas.exclude(pk=self.pk)
        if duplicatas.exists():
            raise DomainError(
                "Já existe uma linha de pesquisa com este nome neste programa.",
                code="duplicate_name",
            )


class CollectiveProjectQuerySet(models.QuerySet):
    def active(self) -> "CollectiveProjectQuerySet":
        return self.filter(is_active=True)

    def for_program(self, program: Program) -> "CollectiveProjectQuerySet":
        return self.filter(program=program)


class CollectiveProject(models.Model):
    """Projeto coletivo de uma linha de pesquisa.

    Uma linha tem vários projetos; o projeto é a unidade que professores e
    alunos citam no vínculo.
    """

    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="collective_projects",
        verbose_name="programa",
    )
    research_line = models.ForeignKey(
        ResearchLine,
        on_delete=models.PROTECT,
        related_name="projects",
        verbose_name="linha de pesquisa",
    )
    name = models.CharField("nome", max_length=200)
    is_active = models.BooleanField("ativo", default=True)

    objects = CollectiveProjectQuerySet.as_manager()

    class Meta:
        verbose_name = "projeto coletivo"
        verbose_name_plural = "projetos coletivos"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        """A FK program é direta (ADR-007 dec. 5) e por isso pode divergir
        de research_line.program. Divergir significa AuditLog com a chave de
        tenant errada — é invariante, não detalhe de formulário.
        """
        super().clean()
        try:
            research_line = self.research_line
        except ObjectDoesNotExist:
            # Sem linha ainda: quem cobra a obrigatoriedade é o schema Ninja
            # (borda) e o NOT NULL da coluna, não este invariante.
            return
        if self.program_id != research_line.program_id:
            raise DomainError(
                "O programa do projeto precisa ser o mesmo da linha de pesquisa.",
                code="program_mismatch",
            )


class AcademicTermQuerySet(models.QuerySet):
    def active(self) -> "AcademicTermQuerySet":
        return self.filter(is_active=True)


class AcademicTerm(models.Model):
    """Período letivo — entidade INSTITUCIONAL, sem FK de programa.

    Única exceção à regra de FK `program` direta (ADR-007 dec. 4): o
    calendário 2026/1 é o da UFMG inteira. Por programa haveria "PPGD
    2026/1" e "PPGA 2026/1" divergentes, com datas que deveriam ser as
    mesmas. O AuditLog das escritas aqui grava `program=None` — está
    correto, o período não pertence a programa nenhum.
    """

    class Half(models.IntegerChoices):
        FIRST = 1, "1º semestre"
        SECOND = 2, "2º semestre"

    year = models.PositiveSmallIntegerField("ano")
    half = models.PositiveSmallIntegerField("semestre", choices=Half)
    starts_on = models.DateField("início")
    ends_on = models.DateField("fim")
    is_active = models.BooleanField("ativo", default=True)

    objects = AcademicTermQuerySet.as_manager()

    class Meta:
        verbose_name = "período letivo"
        verbose_name_plural = "períodos letivos"
        ordering = ["-year", "-half"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "half"],
                name="unique_periodo_por_ano_e_semestre",
            ),
        ]

    def __str__(self) -> str:
        """Rótulo canônico: '2026/1'. É a única forma de escrever um
        semestre no sistema (ADR-007 dec. 4) — tela, relatório e log usam
        este formato, ninguém remonta a string por conta própria.
        """
        return f"{self.year}/{self.half}"

    def clean(self) -> None:
        super().clean()
        if self.starts_on and self.ends_on and self.ends_on <= self.starts_on:
            raise DomainError(
                "O fim do período letivo precisa ser posterior ao início.",
                code="invalid_term_range",
            )
