"""Usuário do sistema.

Subclasse vazia de AbstractUser de propósito: continua sendo o auth nativo
do Django (ADR-003), mas trocar AUTH_USER_MODEL depois de existirem dados é
uma migração cara. Criar agora custa zero.

O usuário é GLOBAL — não pertence a um programa. Quem tem chave de programa
são os dados de negócio (Person) e a auditoria. Papel por programa, se um
dia for necessário, entra como model de vínculo com ADR próprio.
"""

from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    class Meta(AbstractUser.Meta):
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.get_full_name() or self.username
