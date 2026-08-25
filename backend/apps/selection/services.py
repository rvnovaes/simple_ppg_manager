"""Operações do app selection que cruzam mais de um model.

`publish_process` está aqui, e não no router, porque publicar não é gravar
um campo: é conferir etapas, vagas e template — três models — antes de
mudar o estado do edital, tudo na mesma transação (ADR-002).

Quem escreve aqui chama `clean()` antes de `save()`: o Django não executa
`clean()` em `.save()`/`.create()`, e sem essa chamada o invariante do
model nunca roda no caminho real.
"""

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.core import audit
from apps.core.exceptions import DomainError

from .models import SelectionProcess


@transaction.atomic
def publish_process(
    *, process: SelectionProcess, request: HttpRequest | None = None
) -> SelectionProcess:
    """Publica o edital, depois de conferir que ele está completo.

    Publicar abre a inscrição pública: a partir daqui o conteúdo do edital
    congela (`ensure_editable`) e o candidato se inscreve contra ele. Um
    edital sem etapa não tem como ser avaliado, um sem vaga não tem como
    ser classificado e um sem template de convocação não tem como chamar
    ninguém para a prova — as três faltas são o mesmo erro para a tela,
    `process_incomplete`, com a lista do que falta na mensagem.
    """
    faltando = []
    if not process.stages.exists():
        faltando.append("pelo menos uma etapa")
    if not process.vacancies.exists():
        faltando.append("pelo menos uma vaga")
    if not (process.convocation_subject and process.convocation_body):
        faltando.append("o template de convocação")
    if faltando:
        raise DomainError(
            "O edital não pode ser publicado sem " + ", ".join(faltando) + ".",
            code="process_incomplete",
        )

    process.publish(at=timezone.now())
    process.clean()
    process.save(update_fields=["status", "published_at", "updated_at"])
    audit.record(
        "selection.process.publish",
        request=request,
        target=process,
        year=process.year,
        kind=process.kind,
        published_at=str(process.published_at),
    )
    return process
