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
from apps.programs.models import CollectiveProject, Program, ResearchLine

from .models import (
    QuotaCategory,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionProcessStatus,
    SelectionStage,
    Vacancy,
)
from .schemas import (
    SelectionProcessIn,
    SelectionProcessOut,
    SelectionProcessPatch,
    SelectionStageIn,
    SelectionStageOut,
    SelectionStagePatch,
    VacancyIn,
    VacancyOut,
    VacancyPatch,
)
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


# ---------------------------------------------------------------------------
# Etapas do edital
# ---------------------------------------------------------------------------
#
# Toda escrita daqui para baixo passa por `ensure_editable`: etapa e vaga
# só mudam com o edital em rascunho (409 `process_not_editable`). Depois de
# publicado o candidato já se inscreveu contra esta grade — corrigir vaga
# vira `VacancyReallocation`, com ofício da comissão.


def _etapa_do_edital(edital: SelectionProcess, stage_id: int) -> SelectionStage:
    """A etapa é filha de agregado: buscar dentro do edital já escopado é o
    que garante o tenant, sem um `for_program` próprio."""
    return get_object_or_404(edital.stages, pk=stage_id)


@router.get("/processes/{int:process_id}/stages/", response=list[SelectionStageOut])
def list_stages(request: HttpRequest, process_id: int):
    """As etapas do edital, na ordem em que acontecem.

    Sem paginação de propósito: são três etapas por edital, e a tela monta
    a grade inteira de uma vez.
    """
    require_perm(request, "selection.view_selectionstage")
    edital = _edital_do_programa(request, process_id)
    return edital.stages.all()


@router.post("/processes/{int:process_id}/stages/", response={201: SelectionStageOut})
def create_stage(request: HttpRequest, process_id: int, payload: SelectionStageIn):
    require_perm(request, "selection.add_selectionstage")
    edital = _edital_do_programa(request, process_id)
    edital.ensure_editable()
    etapa = SelectionStage(process=edital, **payload.model_dump())
    with transaction.atomic():
        etapa.clean()
        etapa.save()
        audit.record(
            "selection.stage.create",
            request=request,
            target=etapa,
            program=edital.program,
            process_id=edital.pk,
            order=etapa.order,
        )
    return Status(201, etapa)


@router.patch(
    "/processes/{int:process_id}/stages/{int:stage_id}/",
    response=SelectionStageOut,
)
def update_stage(
    request: HttpRequest,
    process_id: int,
    stage_id: int,
    payload: SelectionStagePatch,
):
    """`exclude_unset` sem `exclude_none`: `session_at` e `tiebreak_rank`
    precisam poder voltar a nulo (desmarcar a sessão, tirar a etapa do
    desempate)."""
    require_perm(request, "selection.change_selectionstage")
    edital = _edital_do_programa(request, process_id)
    edital.ensure_editable()
    etapa = _etapa_do_edital(edital, stage_id)
    campos = payload.model_dump(exclude_unset=True)
    for campo, valor in campos.items():
        setattr(etapa, campo, valor)
    with transaction.atomic():
        etapa.clean()
        etapa.save(update_fields=[*campos, "updated_at"] if campos else None)
        audit.record(
            "selection.stage.update",
            request=request,
            target=etapa,
            program=edital.program,
            fields=sorted(campos),
        )
    return etapa


@router.delete(
    "/processes/{int:process_id}/stages/{int:stage_id}/", response={204: None}
)
def delete_stage(request: HttpRequest, process_id: int, stage_id: int):
    """Único DELETE do app.

    Em rascunho a etapa ainda não tem nota, ata nem convocação pendurada,
    então apagar a linha errada é a correção honesta. Depois de publicado
    nada é apagado — o histórico do edital é o que a seleção prova.

    A auditoria é gravada **antes** do `delete()`: depois dele a instância
    perde o pk e o alvo do registro sairia vazio.

    A permissão exigida é `change_selectionstage`, e não `delete_`: nenhum
    papel de domínio recebe `delete_*` (migration `0006_papeis_da_selecao`,
    com teste guardando), porque apagar dado da seleção é quebra-vidro de
    sysadmin. Tirar uma linha da grade **em rascunho** não é isso — é a
    mesma edição da grade que o PATCH faz, e quem trava o resto é o
    `ensure_editable` logo abaixo.
    """
    require_perm(request, "selection.change_selectionstage")
    edital = _edital_do_programa(request, process_id)
    edital.ensure_editable()
    etapa = _etapa_do_edital(edital, stage_id)
    with transaction.atomic():
        audit.record(
            "selection.stage.delete",
            request=request,
            target=etapa,
            program=edital.program,
            name=etapa.name,
            order=etapa.order,
        )
        etapa.delete()
    return Status(204, None)


# ---------------------------------------------------------------------------
# Grade de vagas
# ---------------------------------------------------------------------------


def _alvo(program: Program, project_id: int | None, research_line_id: int | None):
    """Projeto e linha da vaga, ambos escopados no programa da sessão.

    Id de outro programa é 404, não 403: responder 403 confirmaria que o id
    existe em algum lugar.
    """
    projeto = (
        None
        if project_id is None
        else get_object_or_404(
            CollectiveProject.objects.for_program(program), pk=project_id
        )
    )
    linha = (
        None
        if research_line_id is None
        else get_object_or_404(
            ResearchLine.objects.for_program(program), pk=research_line_id
        )
    )
    return projeto, linha


def _vagas(edital: SelectionProcess):
    return edital.vacancies.select_related("project", "research_line")


@router.get("/processes/{int:process_id}/vacancies/", response=list[VacancyOut])
def list_vacancies(
    request: HttpRequest,
    process_id: int,
    level: SelectionLevel | None = None,
    quota_category: QuotaCategory | None = None,
):
    """A grade de vagas do edital. Sem paginação: é a grade inteira que a
    tela soma para dizer quantas vagas o edital oferece."""
    require_perm(request, "selection.view_vacancy")
    edital = _edital_do_programa(request, process_id)
    filtros = {"level": level, "quota_category": quota_category}
    return _vagas(edital).filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )


@router.post("/processes/{int:process_id}/vacancies/", response={201: VacancyOut})
def create_vacancy(request: HttpRequest, process_id: int, payload: VacancyIn):
    require_perm(request, "selection.add_vacancy")
    program: Program = current_program(request)
    edital = _edital_do_programa(request, process_id)
    edital.ensure_editable()
    dados = payload.model_dump()
    projeto, linha = _alvo(
        program, dados.pop("project_id"), dados.pop("research_line_id")
    )
    vaga = Vacancy(
        program=program,
        process=edital,
        project=projeto,
        research_line=linha,
        **dados,
    )
    with transaction.atomic():
        vaga.clean()
        vaga.save()
        audit.record(
            "selection.vacancy.create",
            request=request,
            target=vaga,
            process_id=edital.pk,
            quantity=vaga.quantity,
        )
    return Status(201, vaga)


@router.patch(
    "/processes/{int:process_id}/vacancies/{int:vacancy_id}/", response=VacancyOut
)
def update_vacancy(
    request: HttpRequest, process_id: int, vacancy_id: int, payload: VacancyPatch
):
    """Correção da grade, só em rascunho.

    Não existe DELETE de vaga (ao contrário de etapa): a linha zerada é o
    histórico de que ali havia vaga, e `quantity=0` é permitido justamente
    para isso.
    """
    require_perm(request, "selection.change_vacancy")
    program: Program = current_program(request)
    edital = _edital_do_programa(request, process_id)
    edital.ensure_editable()
    vaga = get_object_or_404(_vagas(edital), pk=vacancy_id)
    campos = payload.model_dump(exclude_unset=True)
    alvo = {
        campo: campos.pop(campo)
        for campo in ("project_id", "research_line_id")
        if campo in campos
    }
    if alvo:
        vaga.project, vaga.research_line = _alvo(
            program,
            alvo.get("project_id", vaga.project_id),
            alvo.get("research_line_id", vaga.research_line_id),
        )
    for campo, valor in campos.items():
        setattr(vaga, campo, valor)
    alterados = [*campos, *alvo]
    with transaction.atomic():
        vaga.clean()
        vaga.save(update_fields=[*alterados, "updated_at"] if alterados else None)
        audit.record(
            "selection.vacancy.update",
            request=request,
            target=vaga,
            fields=sorted(alterados),
        )
    return vaga
