"""Programa de pós-graduação — a chave de tenant do sistema — e a
estrutura acadêmica que pertence a ele (linha de pesquisa).

O sistema nasce para o PPGD, mas todo dado de negócio carrega a FK de
programa desde a primeira migração (Seção 1 do CLAUDE.md). Adicionar a
chave depois, com dados em produção, é caro; adicionar agora é de graça.
"""

from django.db import models


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
