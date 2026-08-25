"""Borda HTTP do app selection, montada em /api/v1/selection/.

Padrão de toda rota: require_perm na primeira linha, current_program logo
depois, chamada ao model/service, schema de saída explícito. Zero regra de
negócio aqui.
"""

from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Router, Status, UploadedFile
from ninja.pagination import paginate

from apps.core import audit
from apps.core.permissions import require_perm
from apps.core.tenancy import current_program
from apps.programs.models import Program

from .models import SelectionKind, SelectionProcess, SelectionProcessStatus
from .schemas import SelectionProcessIn, SelectionProcessOut, SelectionProcessPatch
from .services import publish_process

router = Router(tags=["selection"])


def _editais(program: Program):
    """Editais do programa com as contagens que `SelectionProcessOut` expõe.

    As contagens vêm anotadas para a listagem não fazer duas consultas por
    edital; `distinct=True` porque os dois `Count` no mesmo `annotate`
    cruzam etapas com vagas (o join multiplicaria as linhas).
    """
    return SelectionProcess.objects.for_program(program).annotate(
        stage_count=Count("stages", distinct=True),
        vacancy_count=Count("vacancies", distinct=True),
    )


@router.get("/processes/", response=list[SelectionProcessOut])
@paginate
def list_processes(
    request: HttpRequest,
    kind: SelectionKind | None = None,
    status: SelectionProcessStatus | None = None,
    year: int | None = None,
):
    """Os editais do programa, do ano mais recente para o mais antigo."""
    require_perm(request, "selection.view_selectionprocess")
    editais = _editais(current_program(request))
    # Filtros de conveniência da tela. Nenhum deles é escopo de tenant —
    # esse já foi aplicado acima e não é opcional.
    filtros = {"kind": kind, "status": status, "year": year}
    return editais.filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )


@router.post("/processes/", response={201: SelectionProcessOut})
def create_process(request: HttpRequest, payload: SelectionProcessIn):
    """A secretaria abre o edital do ano, em rascunho."""
    require_perm(request, "selection.add_selectionprocess")
    program: Program = current_program(request)
    edital = SelectionProcess(program=program, **payload.model_dump())
    with transaction.atomic():
        edital.clean()
        edital.save()
        audit.record(
            "selection.process.create",
            request=request,
            target=edital,
            kind=edital.kind,
            year=edital.year,
        )
    return Status(201, edital)


def _edital_do_programa(request: HttpRequest, process_id: int) -> SelectionProcess:
    """O edital desta requisição, já escopado.

    O escopo entra na busca: edital de outro programa simplesmente não
    existe aqui (404, nunca 403 — 403 revelaria que o id existe).
    """
    return get_object_or_404(
        SelectionProcess.objects.for_program(current_program(request)), pk=process_id
    )


@router.get("/processes/{int:process_id}/", response=SelectionProcessOut)
def get_process(request: HttpRequest, process_id: int):
    require_perm(request, "selection.view_selectionprocess")
    return get_object_or_404(_editais(current_program(request)), pk=process_id)


@router.patch("/processes/{int:process_id}/", response=SelectionProcessOut)
def update_process(
    request: HttpRequest, process_id: int, payload: SelectionProcessPatch
):
    """Correção do edital — só enquanto ele é rascunho.

    `ensure_editable` é do model e devolve 409 `process_not_editable`:
    depois de publicado o candidato já se inscreveu contra este conteúdo,
    e vaga se corrige por realocação, com ofício da comissão.
    """
    require_perm(request, "selection.change_selectionprocess")
    edital = _edital_do_programa(request, process_id)
    edital.ensure_editable()
    campos = payload.model_dump(exclude_unset=True, exclude_none=True)
    for campo, valor in campos.items():
        setattr(edital, campo, valor)
    with transaction.atomic():
        edital.clean()
        edital.save(update_fields=list(campos) or None)
        audit.record(
            "selection.process.update",
            request=request,
            target=edital,
            fields=sorted(campos),
        )
    return edital


@router.post("/processes/{int:process_id}/publish", response=SelectionProcessOut)
def publish_process_endpoint(request: HttpRequest, process_id: int):
    """Publica o edital: o trabalho (e a cobrança do que falta) está no
    service, porque a conferência atravessa etapas, vagas e template."""
    require_perm(request, "selection.change_selectionprocess")
    edital = _edital_do_programa(request, process_id)
    return publish_process(process=edital, request=request)


@router.post("/processes/{int:process_id}/close", response=SelectionProcessOut)
def close_process(request: HttpRequest, process_id: int):
    """Encerra o edital — ato explícito da secretaria, nada expira por data.

    Toca um model só, então fica no router (Seção 3): a regra de quando dá
    para encerrar é do `close()` do model, que devolve 409
    `process_not_published`.
    """
    require_perm(request, "selection.change_selectionprocess")
    edital = _edital_do_programa(request, process_id)
    with transaction.atomic():
        edital.close(at=timezone.now())
        edital.save(update_fields=["status", "closed_at", "updated_at"])
        audit.record(
            "selection.process.close",
            request=request,
            target=edital,
            closed_at=str(edital.closed_at),
        )
    return edital


@router.post("/processes/{int:process_id}/notice-file", response=SelectionProcessOut)
def upload_notice_file(
    request: HttpRequest, process_id: int, file: UploadedFile = File(...)
):
    """Anexa (ou substitui) o PDF do edital.

    Substituir, e não empilhar: o edital tem um arquivo, e o reenvio é a
    correção de quem subiu a versão errada. A remoção do arquivo anterior é
    explícita porque o storage não participa do rollback da transação — sem
    ela cada reenvio deixaria um órfão no MEDIA_ROOT.

    Vale depois de publicado: o PDF é o documento que o edital publicado
    divulga, e trocá-lo por uma retificação não muda vaga nem etapa.
    """
    require_perm(request, "selection.change_selectionprocess")
    edital = _edital_do_programa(request, process_id)
    SelectionProcess.validate_notice_upload(
        filename=file.name or "", size=file.size or 0
    )

    anterior = edital.notice_file.name
    if anterior:
        edital.notice_file.delete(save=False)
    with transaction.atomic():
        edital.notice_file = file
        edital.save(update_fields=["notice_file", "updated_at"])
        audit.record(
            "selection.process.notice_file",
            request=request,
            target=edital,
            filename=file.name,
            replaced=bool(anterior),
        )
    return edital
