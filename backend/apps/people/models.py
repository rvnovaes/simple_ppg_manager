"""Pessoa — entidade de domínio.

Este model é o exemplo de referência do padrão do projeto (ADR-002):
a regra que protege o invariante mora em método do próprio model, e o teste
dela instancia o objeto em memória, sem banco e sem mock.
"""

from django.conf import settings
from django.db import models

from apps.core.exceptions import InvalidStateTransition


class PersonQuerySet(models.QuerySet):
    def active(self) -> "PersonQuerySet":
        return self.filter(status=Person.Status.ACTIVE)

    def for_program(self, program) -> "PersonQuerySet":
        return self.filter(program=program)


class Person(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        ARCHIVED = "archived", "Arquivada"

    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="people",
        verbose_name="programa",
    )
    # A conta de acesso da pessoa. É FK e não OneToOne de propósito: o User
    # é global e a Person pertence a um programa, então quem atua em dois
    # programas tem UM usuário e DUAS pessoas.
    #
    # Opcional porque nem todo cadastro tem acesso ao sistema (egresso,
    # registro histórico, pessoa que nunca vai logar). Sem esta FK o
    # vínculo existiria só por coincidência de e-mail e quebraria em
    # silêncio a cada edição.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="people",
        null=True,
        blank=True,
        verbose_name="conta de acesso",
    )
    full_name = models.CharField("nome completo", max_length=200)
    primary_email = models.EmailField("e-mail principal")
    phone_number = models.CharField("telefone", max_length=30, blank=True)
    status = models.CharField(
        "situação",
        max_length=20,
        choices=Status,
        default=Status.ACTIVE,
    )
    # Carimbos técnicos, nunca dado de negócio (Seção 8 do CLAUDE.md).
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PersonQuerySet.as_manager()

    class Meta:
        verbose_name = "pessoa"
        verbose_name_plural = "pessoas"
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "primary_email"],
                name="unique_email_por_programa",
            ),
            # Uma conta não pode aparecer duas vezes no mesmo programa.
            # Entre programas pode, e é justamente o caso multi-tenant.
            models.UniqueConstraint(
                fields=["program", "user"],
                name="unique_conta_por_programa",
            ),
        ]

    def __str__(self) -> str:
        return self.full_name

    def archive(self) -> None:
        """Arquiva a pessoa.

        Invariante: arquivar só faz sentido a partir de ACTIVE. Chamar duas
        vezes é erro do chamador, não no-op silencioso.
        """
        if self.status == self.Status.ARCHIVED:
            raise InvalidStateTransition("Pessoa já está arquivada.")
        self.status = self.Status.ARCHIVED
