"""Usuário do sistema.

Subclasse vazia de AbstractUser de propósito: continua sendo o auth nativo
do Django (ADR-003), mas trocar AUTH_USER_MODEL depois de existirem dados é
uma migração cara. Criar agora custa zero.

O usuário é GLOBAL — não pertence a um programa. Quem tem chave de programa
são os dados de negócio (Person) e a auditoria. Papel por programa, se um
dia for necessário, entra como model de vínculo com ADR próprio.
"""

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.core.exceptions import DomainError, InvalidStateTransition


def validar_senha(raw_password: str, user: "User") -> None:
    """Aplica os validadores de senha do Django como erro de negócio.

    Módulo e não método porque o auto-registro do candidato precisa
    validar a senha ANTES de decidir se cria a conta — respondendo o mesmo
    corpo para e-mail novo e e-mail já cadastrado, ele não pode deixar a
    cobrança de força da senha depender desse desvio.
    """
    try:
        validate_password(raw_password, user)
    except ValidationError as exc:
        raise DomainError(" ".join(exc.messages), code="senha_invalida") from exc


class User(AbstractUser):
    class Meta(AbstractUser.Meta):
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    def set_initial_password(self, raw_password: str) -> None:
        """Define a senha do PRIMEIRO acesso — nunca troca uma senha existente.

        A conta nasce com set_unusable_password() (ver
        people.services.create_person_with_user); é este método que a torna
        utilizável. Se já houver senha, quem troca é a própria pessoa: a
        Secretaria não tem poder de assumir uma conta ativa.
        """
        if self.has_usable_password():
            raise InvalidStateTransition(
                "Esta conta já tem senha definida; use a recuperação de senha."
            )
        validar_senha(raw_password, self)
        self.set_password(raw_password)
