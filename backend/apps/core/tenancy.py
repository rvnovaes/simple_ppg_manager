"""Programa corrente da requisição — helper único do projeto.

Mesmo espírito de `require_perm`: a rota chama explicitamente, ninguém
resolve tenant por middleware mágico. "Todos os alunos do programa"
significa a mesma coisa em qualquer rota porque todas passam por aqui.

Resolução, nesta ordem:

1. As Person ativas do usuário da sessão são o vínculo que vale.
2. Exatamente uma: o programa dela, sem precisar de nada na requisição.
3. Mais de uma (quem atua em dois programas tem um User e duas Person):
   a requisição precisa dizer qual, via `program_id`, e o vínculo é
   conferido.
4. Nenhuma: só o superusuário passa, e ainda assim informando
   `program_id` — é o caso do sysadmin operando a plataforma.
"""

from django.http import HttpRequest

from apps.people.models import Person
from apps.programs.models import Program

from .exceptions import DomainError, NoProgramInContext, NotAuthenticated


def current_program(request: HttpRequest, *, program_id: int | None = None) -> Program:
    """Devolve o Program a que esta requisição pertence.

    `program_id` pode vir do parâmetro (quando a rota já o declara) ou da
    query string; o argumento explícito ganha. Levanta NoProgramInContext
    (403) quando não há vínculo e DomainError `program_required` (400)
    quando o vínculo é ambíguo.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise NotAuthenticated("Autenticação necessária.")

    if program_id is None:
        program_id = _program_id_da_query(request)

    vinculos = set(
        Person.objects.active().filter(user=user).values_list("program_id", flat=True)
    )

    if not vinculos:
        if program_id is None or not user.is_superuser:
            raise NoProgramInContext("Usuário sem vínculo ativo em nenhum programa.")
        return _buscar(program_id)

    if len(vinculos) > 1 and program_id is None:
        raise DomainError(
            "Usuário atua em mais de um programa: informe program_id.",
            code="program_required",
        )

    if program_id is None:
        return _buscar(next(iter(vinculos)))

    if program_id not in vinculos:
        raise NoProgramInContext("Usuário sem vínculo ativo neste programa.")
    return _buscar(program_id)


def _buscar(program_id: int) -> Program:
    try:
        return Program.objects.get(pk=program_id)
    except Program.DoesNotExist:
        raise NoProgramInContext("Programa inexistente.") from None


def _program_id_da_query(request: HttpRequest) -> int | None:
    bruto = request.GET.get("program_id")
    if bruto is None:
        return None
    try:
        return int(bruto)
    except ValueError:
        raise DomainError(
            "program_id inválido.",
            code="program_required",
        ) from None
