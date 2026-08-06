"""Pessoa — entidade de domínio.

Este model é o exemplo de referência do padrão do projeto (ADR-002):
a regra que protege o invariante mora em método do próprio model, e o teste
dela instancia o objeto em memória, sem banco e sem mock.
"""

from django.conf import settings
from django.db import models

from apps.core.exceptions import InvalidStateTransition

# Papéis que respondem pela operação do programa. É a definição de
# "administrativo" na listagem de pessoas: quem trabalha na secretaria ou
# na coordenação e não é, necessariamente, professor nem aluno.
PAPEIS_ADMINISTRATIVOS = ("Secretaria", "Coordenação")


class PersonQuerySet(models.QuerySet):
    def active(self) -> "PersonQuerySet":
        return self.filter(status=Person.Status.ACTIVE)

    def for_program(self, program) -> "PersonQuerySet":
        return self.filter(program=program)

    # Os quatro recortes abaixo NÃO são exclusivos entre si, e é o ponto:
    # o coordenador que também dá aula é pessoa uma só e aparece tanto em
    # `teachers()` quanto em `staff()`. Quem tem um recorte por vínculo
    # cai na tentação de transformar "tipo de pessoa" num campo — e aí a
    # primeira pessoa que acumula papéis não cabe em lugar nenhum.

    def teachers(self) -> "PersonQuerySet":
        """Quem tem vínculo docente. `teacher_profile` é OneToOne, então
        não há duplicata a remover.
        """
        return self.filter(teacher_profile__isnull=False)

    def students(self) -> "PersonQuerySet":
        """Quem tem (ou teve) vínculo de aluno, em qualquer modalidade.

        `distinct` porque `student_records` é um-para-muitos: quem cursou
        duas isoladas e depois entrou como regular tem três vínculos e
        apareceria três vezes.
        """
        return self.filter(student_records__isnull=False).distinct()

    def candidates(self) -> "PersonQuerySet":
        """Quem se inscreveu em disciplina isolada, em qualquer estado.

        Inclui quem já virou aluno: o requerimento não deixa de existir
        quando a matrícula sai, e sumir da lista de candidatos apagaria o
        histórico do edital para a secretaria.
        """
        return self.filter(isolated_requests__isnull=False).distinct()

    def staff(self) -> "PersonQuerySet":
        """Quem responde pela operação do programa.

        Sai do Group do usuário (ADR-003), e não de um campo em Person:
        papel é permissão, e duplicá-lo aqui criaria duas verdades que
        divergem na primeira troca de função. Pessoa sem conta não é
        administrativo — o vínculo administrativo É o acesso.
        """
        return self.filter(user__groups__name__in=PAPEIS_ADMINISTRATIVOS).distinct()


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
