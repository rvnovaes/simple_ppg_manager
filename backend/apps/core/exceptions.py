"""Exceções de negócio do projeto.

Toda exceção de negócio herda de DomainError. O handler central em api.py
converte para 4xx com corpo {"detail": ..., "code": ...}. Router não faz
try/except de negócio (Seção 8 do CLAUDE.md).
"""


class DomainError(Exception):
    """Base de toda exceção de negócio.

    `code` é o identificador estável que o front pode testar; a mensagem é
    para humanos e pode mudar sem quebrar contrato.
    """

    status_code = 400
    code = "domain_error"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class InvalidStateTransition(DomainError):
    """Operação incompatível com o estado atual do objeto.

    Ex.: arquivar uma pessoa que já está arquivada.
    """

    status_code = 409
    code = "invalid_state_transition"


class NotAllowed(DomainError):
    """Usuário autenticado sem permissão para a operação."""

    status_code = 403
    code = "not_allowed"


class NotAuthenticated(DomainError):
    """Nenhuma sessão válida na requisição."""

    status_code = 401
    code = "not_authenticated"
