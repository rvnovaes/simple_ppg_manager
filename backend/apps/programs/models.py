"""Programa de pós-graduação — a chave de tenant do sistema.

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
