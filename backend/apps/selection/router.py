"""Borda HTTP do app selection, montada em /api/v1/selection/.

Padrão de toda rota: require_perm na primeira linha, current_program logo
depois, chamada ao model/service, schema de saída explícito. Zero regra de
negócio aqui.
"""

from pathlib import Path

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import FileResponse, Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from ninja import File, Form, Router, Status, UploadedFile
from ninja.decorators import decorate_view
from ninja.pagination import paginate

from apps.academic.models import Teacher
from apps.core import audit
from apps.core.exceptions import InvalidStateTransition, NotAllowed
from apps.core.permissions import require_perm
from apps.core.ratelimit import client_ip, enforce_rate_limit
from apps.core.tenancy import current_program
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine

from .models import (
    Application,
    ApplicationDocument,
    ApplicationDocumentKind,
    ApplicationStatus,
    Board,
    Convocation,
    ConvocationEmail,
    ExaminationRecord,
    QuotaCategory,
    RecordSignature,
    RecordStatus,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionProcessStatus,
    SelectionStage,
    StageScore,
    Vacancy,
)
from .schemas import (
    ApplicationDecisionIn,
    ApplicationDetailOut,
    ApplicationIn,
    ApplicationOut,
    ApplicationReceiptOut,
    ApplicationStatusOut,
    BoardIn,
    BoardOut,
    BoardPatch,
    ConvocableApplicationOut,
    ConvocationDetailOut,
    ConvocationOut,
    ExaminationRecordOut,
    MyBoardOut,
    PublicProcessOut,
    PublicSignatureOut,
    PublicSignatureReceiptOut,
    RankingIn,
    RankingOut,
    RecordFreezeIn,
    RecordSignatureOut,
    RecordSignIn,
    RecordSummaryOut,
    SelectionProcessIn,
    SelectionProcessOut,
    SelectionProcessPatch,
    SelectionStageIn,
    SelectionStageOut,
    SelectionStagePatch,
    StageScoreIn,
    StageScoreOut,
    VacancyIn,
    VacancyOut,
    VacancyPatch,
)
from .services import (
    JANELA_DE_ASSINATURA_EM_SEGUNDOS,
    JANELA_DE_CONSULTA_EM_SEGUNDOS,
    JANELA_DE_INSCRICAO_EM_SEGUNDOS,
    JANELA_DE_LEITURA_EM_SEGUNDOS,
    LIMITE_DE_ASSINATURA_POR_TOKEN,
    LIMITE_DE_CONSULTA_DE_PROTOCOLO,
    LIMITE_DE_INSCRICAO_POR_IP,
    LIMITE_DE_LEITURA_DE_TOKEN,
    LIMITE_DE_LEITURA_PUBLICA,
    assinatura_por_token,
    compute_ranking,
    edital_com_inscricao_aberta,
    freeze_record,
    generate_record,
    publish_process,
    ranking_of,
    refresh_record,
    reopen_record,
    resend_convocation_emails,
    resend_signature_token,
    send_convocations,
    sign_record,
    sign_record_with_token,
    so_digitos,
    submit_application,
)

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


# ---------------------------------------------------------------------------
# Bancas examinadoras
# ---------------------------------------------------------------------------
#
# A banca NÃO pende de `ensure_editable` do edital: ela se compõe depois de
# o edital estar publicado, com as inscrições já abertas. O que a trava é a
# própria ata — `Board.ensure_editable()` devolve 409 `board_in_use` assim
# que existe ata fora do rascunho, porque o hash da ata congelada carrega a
# composição da banca.


def _professor_do_programa(program: Program, teacher_id: int) -> Teacher:
    """Examinador escopado no programa da sessão.

    404 e não 400 `teacher_from_other_program`: o id de outro programa não
    existe aqui, e responder com o código do domínio confirmaria que ele
    existe em algum lugar. O invariante do model continua valendo — é ele
    que guarda quem escreve fora da rota.
    """
    return get_object_or_404(Teacher.objects.for_program(program), pk=teacher_id)


def _bancas(program: Program):
    """Bancas do programa, com o que o `BoardOut` expande.

    A anotação evita uma consulta de "esta banca já tem ata?" por linha da
    listagem; `distinct=True` não é preciso porque há um só `Count`.
    """
    return (
        Board.objects.filter(program=program)
        .select_related(
            "process",
            "project",
            "research_line",
            *(f"{papel}__person" for papel in Board.PAPEIS),
        )
        .annotate(
            atas_fora_do_rascunho=Count(
                "records", filter=~Q(records__status=RecordStatus.DRAFT)
            )
        )
    )


@router.get("/boards/", response=list[BoardOut])
@paginate
def list_boards(
    request: HttpRequest,
    process_id: int | None = None,
    level: SelectionLevel | None = None,
    project_id: int | None = None,
    research_line_id: int | None = None,
    teacher_id: int | None = None,
):
    """As bancas do programa, com os filtros da tela.

    `teacher_id` passa por `Board.objects.with_teacher`, o único lugar em
    que o OU dos quatro papéis é escrito.
    """
    require_perm(request, "selection.view_board")
    program: Program = current_program(request)
    bancas = _bancas(program)
    filtros = {
        "process_id": process_id,
        "level": level,
        "project_id": project_id,
        "research_line_id": research_line_id,
    }
    bancas = bancas.filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )
    if teacher_id is not None:
        bancas = bancas.with_teacher(_professor_do_programa(program, teacher_id))
    return bancas


@router.post("/boards/", response={201: BoardOut})
def create_board(request: HttpRequest, payload: BoardIn):
    """A secretaria designa a banca de um nível × alvo do edital."""
    require_perm(request, "selection.add_board")
    program: Program = current_program(request)
    dados = payload.model_dump()
    edital = _edital_do_programa(request, dados.pop("process_id"))
    projeto, linha = _alvo(
        program, dados.pop("project_id"), dados.pop("research_line_id")
    )
    membros = {
        papel: _professor_do_programa(program, dados.pop(f"{papel}_id"))
        for papel in Board.PAPEIS
    }
    banca = Board(
        program=program,
        process=edital,
        project=projeto,
        research_line=linha,
        **membros,
        **dados,
    )
    with transaction.atomic():
        banca.clean()
        banca.save()
        audit.record(
            "selection.board.create",
            request=request,
            target=banca,
            process_id=edital.pk,
            level=banca.level,
        )
    return Status(201, banca)


@router.get("/boards/{int:board_id}/", response=BoardOut)
def get_board(request: HttpRequest, board_id: int):
    require_perm(request, "selection.view_board")
    return get_object_or_404(_bancas(current_program(request)), pk=board_id)


@router.patch("/boards/{int:board_id}/", response=BoardOut)
def update_board(request: HttpRequest, board_id: int, payload: BoardPatch):
    """Troca de examinador ou correção do alvo, só enquanto a banca não
    tem ata fora do rascunho (409 `board_in_use`)."""
    require_perm(request, "selection.change_board")
    program: Program = current_program(request)
    banca = get_object_or_404(_bancas(program), pk=board_id)
    banca.ensure_editable()
    campos = payload.model_dump(exclude_unset=True)
    alvo = {
        campo: campos.pop(campo)
        for campo in ("project_id", "research_line_id")
        if campo in campos
    }
    if alvo:
        banca.project, banca.research_line = _alvo(
            program,
            alvo.get("project_id", banca.project_id),
            alvo.get("research_line_id", banca.research_line_id),
        )
    membros = [campo for campo in campos if campo.endswith("_id")]
    for campo in membros:
        setattr(
            banca,
            campo.removesuffix("_id"),
            _professor_do_programa(program, campos[campo]),
        )
    for campo, valor in campos.items():
        if campo not in membros:
            setattr(banca, campo, valor)
    alterados = [*campos, *alvo]
    with transaction.atomic():
        banca.clean()
        banca.save(update_fields=[*alterados, "updated_at"] if alterados else None)
        audit.record(
            "selection.board.update",
            request=request,
            target=banca,
            fields=sorted(alterados),
        )
    return banca


# ---------------------------------------------------------------------------
# Notas da etapa — o docente na sua própria banca
# ---------------------------------------------------------------------------
#
# Aqui o recorte muda de natureza. Nas rotas da secretaria a permissão
# responde tudo: quem tem `change_application` decide qualquer inscrição do
# programa. Na banca não — todo Docente tem `add/change_stagescore`, e nem
# por isso pontua o candidato de outra banca. O que separa é
# `Board.is_member(teacher)`, checado na rota, sempre depois do
# `require_perm`. Permissão sozinha aqui seria vazamento entre bancas.
#
# Quem não tem Teacher no programa (a secretaria, a coordenação) leva 403
# `not_a_board_member`, e não 404: a banca existe e ela até a enxerga na
# tela de bancas; o que falta é ser da banca.


def teacher_da_sessao(request: HttpRequest, program: Program) -> Teacher:
    """O vínculo de docente de quem está pedindo — nunca um `teacher_id`
    do payload.

    Mesmo espírito do `_aluno_da_sessao` de `academic`: o examinador sai
    da sessão, porque aceitar o id do corpo deixaria qualquer docente
    lançar nota em nome de outro. O `first()` basta — uma pessoa tem no
    máximo um vínculo de docente por programa.
    """
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    docente = Teacher.objects.for_program(program).filter(person__in=pessoas).first()
    if docente is None:
        raise NotAllowed(
            "Sua conta não compõe banca examinadora neste programa.",
            code="not_a_board_member",
        )
    return docente


@router.get("/boards/mine", response=list[MyBoardOut])
def list_my_boards(request: HttpRequest):
    """As bancas do docente da sessão, com as etapas de cada edital.

    Sem paginação: um docente compõe poucas bancas, e a tela dele é a
    lista inteira. Sem filtros pelo mesmo motivo.

    Não colide com `/boards/{id}/` porque aquela rota usa o conversor
    `int:` — "mine" nunca casa com ele.
    """
    require_perm(request, "selection.view_board")
    program: Program = current_program(request)
    docente = teacher_da_sessao(request, program)
    return (
        _bancas(program)
        .with_teacher(docente)
        .prefetch_related("process__stages")
        .order_by("process", "level")
    )


def _minha_banca(request: HttpRequest, board_id: int) -> tuple[Board, Teacher]:
    """A banca da URL e o docente da sessão, com a checagem de composição.

    404 para banca de outro programa (como em todo o app) e 403
    `not_a_board_member` para banca deste programa que não é sua — a
    diferença é deliberada: negar existência protege o outro tenant, e
    dentro do tenant a banca é pública para quem lê bancas.
    """
    program: Program = current_program(request)
    banca = get_object_or_404(_bancas(program), pk=board_id)
    docente = teacher_da_sessao(request, program)
    if not banca.is_member(docente):
        raise NotAllowed(
            "Você não compõe esta banca examinadora.",
            code="not_a_board_member",
        )
    return banca, docente


def _candidatos_da_banca(banca: Board, etapa: SelectionStage):
    """As inscrições vivas do nível × alvo da banca, com a nota da etapa.

    A planilha nasce das inscrições (`alive()` + `for_target`) e não das
    notas: quem ainda não foi avaliado precisa aparecer na tela. A nota
    vem por `Prefetch` com `to_attr`, numa consulta só — o `StageScoreOut`
    lê de `nota_da_etapa` e nunca consulta por linha.
    """
    return (
        Application.objects.for_process(banca.process_id)
        .alive()
        .for_target(banca.level, banca.project, banca.research_line)
        .prefetch_related(
            Prefetch(
                "scores",
                queryset=StageScore.objects.for_stage(etapa).select_related(
                    "entered_by__person"
                ),
                to_attr="nota_da_etapa",
            )
        )
        .order_by("full_name", "protocol")
    )


def _recusar_ata_congelada(banca: Board, etapa: SelectionStage) -> None:
    """409 `record_frozen` quando a ata corrente da (etapa × nível × alvo)
    já saiu do rascunho.

    A ata congelada guarda a fotografia das notas no `content`, e o
    `content_hash` é o que cada assinatura confere. Deixar a nota mudar
    por baixo invalidaria assinatura já dada — e, pior, em silêncio. Para
    corrigir depois de congelar, reabre-se a ata (ou se emite a versão
    `n+1`, se ela já foi assinada).
    """
    congelada = (
        ExaminationRecord.objects.for_program(banca.program)
        .current()
        .for_key(etapa, banca.level, banca.project, banca.research_line)
        .filter(status__in=(RecordStatus.AWAITING_SIGNATURES, RecordStatus.SIGNED))
        .exists()
    )
    if congelada:
        raise InvalidStateTransition(
            "A ata desta etapa já foi congelada: as notas são só leitura.",
            code="record_frozen",
        )


@router.get(
    "/boards/{int:board_id}/stages/{int:stage_id}/scores",
    response=list[StageScoreOut],
)
def list_stage_scores(request: HttpRequest, board_id: int, stage_id: int):
    """A planilha da banca naquela etapa: um candidato vivo por linha."""
    require_perm(request, "selection.view_stagescore")
    banca, _docente = _minha_banca(request, board_id)
    etapa = _etapa_do_edital(banca.process, stage_id)
    return _candidatos_da_banca(banca, etapa)


@router.put(
    "/boards/{int:board_id}/stages/{int:stage_id}/scores",
    response=list[StageScoreOut],
)
def set_stage_scores(
    request: HttpRequest, board_id: int, stage_id: int, payload: list[StageScoreIn]
):
    """Lança as notas da etapa em lote e devolve a planilha atualizada.

    Lote e não uma nota por requisição porque é assim que a banca
    trabalha: ela avalia a sessão inteira e salva uma vez. O lote é
    parcial de propósito — quem não vem no corpo fica como estava.

    As duas permissões juntas (`add` e `change`): a mesma chamada cria a
    linha de quem ainda não tinha nota e reescreve a de quem já tinha.

    Inscrição fora do recorte da banca é 404, como qualquer id de fora do
    escopo. Nota repetida no mesmo lote volta 400 `duplicate_score`, do
    `clean()` — o corpo se contradiz e não há como escolher qual vale.
    """
    require_perm(request, "selection.add_stagescore")
    require_perm(request, "selection.change_stagescore")
    banca, docente = _minha_banca(request, board_id)
    etapa = _etapa_do_edital(banca.process, stage_id)
    _recusar_ata_congelada(banca, etapa)

    candidatos = {
        inscricao.pk: inscricao for inscricao in _candidatos_da_banca(banca, etapa)
    }
    existentes = {
        nota.application_id: nota
        for nota in StageScore.objects.for_stage(etapa).filter(
            application_id__in=candidatos
        )
    }
    with transaction.atomic():
        for linha in payload:
            inscricao = candidatos.get(linha.application_id)
            if inscricao is None:
                raise Http404("Inscrição fora do recorte desta banca.")
            nota = existentes.get(linha.application_id) or StageScore(
                program=banca.program, application=inscricao, stage=etapa
            )
            nota.score = linha.score
            nota.absent = linha.absent
            nota.entered_by = docente
            nota.clean()
            nota.save()
        audit.record(
            "selection.stage_score.set",
            request=request,
            target=banca,
            stage_id=etapa.pk,
            teacher_id=docente.pk,
            application_ids=sorted(linha.application_id for linha in payload),
        )
    return _candidatos_da_banca(banca, etapa)


# ---------------------------------------------------------------------------
# Ata da etapa — o ciclo antes da assinatura
# ---------------------------------------------------------------------------
#
# A ata pende da banca, e não do edital, pelo mesmo motivo das notas: quem
# a monta é quem examinou. O recorte de papel dentro da banca é mais fino
# que nas notas, porém — gerar e atualizar são de qualquer titular,
# congelar e reabrir são só do presidente. Congelar é o ponto sem volta
# editorial da etapa (as notas viram só leitura e o hash passa a valer),
# e reabrir apaga assinatura pendente: as duas são responsabilidade de
# quem preside, não da banca inteira.
#
# O suplente compõe a banca (`_minha_banca` o aceita) mas não assina nem
# monta ata, a menos que substitua um titular impedido — e aí quem o põe
# lá é o `replaced_member_id` do congelamento, decidido pelo presidente.


def _exigir_titular(banca: Board, docente: Teacher) -> None:
    """Montar a ata é dos três titulares."""
    if docente.pk not in {m.pk for m in banca.titular_members()}:
        raise NotAllowed(
            "Só um membro titular da banca monta a ata da etapa.",
            code="not_a_titular_member",
        )


def _exigir_presidente(banca: Board, docente: Teacher) -> None:
    """Congelar e reabrir são do presidente."""
    if banca.president_id != docente.pk:
        raise NotAllowed(
            "Só o presidente da banca congela ou reabre a ata.",
            code="not_the_board_president",
        )


def _atas_da_banca(banca: Board):
    """As atas do nível × alvo da banca, com o que `ExaminationRecordOut`
    expande — inclusive as assinaturas, que a tela mostra junto."""
    return (
        ExaminationRecord.objects.for_program(banca.program)
        .select_related("process", "stage", "project", "research_line")
        .select_related("replaced_member__person")
        .prefetch_related(
            Prefetch(
                "signatures",
                queryset=RecordSignature.objects.select_related("signer__person"),
            )
        )
    )


def _ata_corrente(banca: Board, etapa: SelectionStage) -> ExaminationRecord:
    """A ata vigente da (etapa × nível × alvo), ou 404.

    404 e não corpo vazio: "ainda não há ata" é exatamente a ausência do
    recurso, e é assim que a tela do docente sabe que precisa gerar uma.
    """
    ata = (
        _atas_da_banca(banca)
        .current()
        .for_key(etapa, banca.level, banca.project, banca.research_line)
        .first()
    )
    if ata is None:
        raise Http404("Esta etapa ainda não tem ata.")
    return ata


def _com_assinaturas(ata: ExaminationRecord) -> ExaminationRecord:
    """Relê a ata recém-escrita pela consulta da listagem.

    O objeto que volta do service tem as assinaturas em cache antigo (ou
    nenhum), e `ExaminationRecordOut` as expõe embutidas — reler é o que
    faz o POST devolver a mesma coisa que o GET seguinte.
    """
    return _atas_da_banca(ata.board).get(pk=ata.pk)


@router.get(
    "/boards/{int:board_id}/stages/{int:stage_id}/record",
    response=ExaminationRecordOut,
)
def get_stage_record(request: HttpRequest, board_id: int, stage_id: int):
    """A ata vigente daquela etapa nesta banca."""
    require_perm(request, "selection.view_examinationrecord")
    banca, _docente = _minha_banca(request, board_id)
    etapa = _etapa_do_edital(banca.process, stage_id)
    return _ata_corrente(banca, etapa)


@router.post(
    "/boards/{int:board_id}/stages/{int:stage_id}/record",
    response={201: ExaminationRecordOut},
)
def create_stage_record(request: HttpRequest, board_id: int, stage_id: int):
    """Abre a ata em rascunho, com as notas já lançadas."""
    require_perm(request, "selection.add_examinationrecord")
    banca, docente = _minha_banca(request, board_id)
    _exigir_titular(banca, docente)
    etapa = _etapa_do_edital(banca.process, stage_id)
    ata = generate_record(board=banca, stage=etapa, request=request)
    return Status(201, _com_assinaturas(ata))


@router.post(
    "/boards/{int:board_id}/stages/{int:stage_id}/record/refresh",
    response=ExaminationRecordOut,
)
def refresh_stage_record(request: HttpRequest, board_id: int, stage_id: int):
    """Regera o rascunho com as notas de agora."""
    require_perm(request, "selection.change_examinationrecord")
    banca, docente = _minha_banca(request, board_id)
    _exigir_titular(banca, docente)
    etapa = _etapa_do_edital(banca.process, stage_id)
    ata = refresh_record(record=_ata_corrente(banca, etapa), request=request)
    return _com_assinaturas(ata)


@router.post(
    "/boards/{int:board_id}/stages/{int:stage_id}/record/freeze",
    response=ExaminationRecordOut,
)
def freeze_stage_record(
    request: HttpRequest, board_id: int, stage_id: int, payload: RecordFreezeIn
):
    """Fecha a ata para assinatura e emite o token do examinador externo."""
    require_perm(request, "selection.change_examinationrecord")
    banca, docente = _minha_banca(request, board_id)
    _exigir_presidente(banca, docente)
    etapa = _etapa_do_edital(banca.process, stage_id)
    impedido = (
        None
        if payload.replaced_member_id is None
        else _professor_do_programa(banca.program, payload.replaced_member_id)
    )
    ata = freeze_record(
        record=_ata_corrente(banca, etapa),
        replaced_member=impedido,
        request=request,
    )
    return _com_assinaturas(ata)


@router.post(
    "/boards/{int:board_id}/stages/{int:stage_id}/record/reopen",
    response=ExaminationRecordOut,
)
def reopen_stage_record(request: HttpRequest, board_id: int, stage_id: int):
    """Devolve a ata congelada ao rascunho, se ninguém assinou."""
    require_perm(request, "selection.change_examinationrecord")
    banca, docente = _minha_banca(request, board_id)
    _exigir_presidente(banca, docente)
    etapa = _etapa_do_edital(banca.process, stage_id)
    ata = reopen_record(record=_ata_corrente(banca, etapa), request=request)
    return _com_assinaturas(ata)


@router.post(
    "/boards/{int:board_id}/stages/{int:stage_id}/record/sign",
    response=ExaminationRecordOut,
)
def sign_stage_record(
    request: HttpRequest, board_id: int, stage_id: int, payload: RecordSignIn
):
    """Assina a ata congelada como examinador logado.

    Não exige titularidade: quem assina é quem está na lista de
    signatários da ata (`expected_signers`), e o suplente entra nela
    quando substitui um titular impedido. Quem compõe a banca mas não
    assina esta ata leva `not_the_signer`, não 404 — a ata existe e ele
    pode lê-la.

    A terceira assinatura fecha a etapa: desfechos aplicados e PDF
    gravado, tudo na mesma transação (`_close_stage`).
    """
    require_perm(request, "selection.sign_examinationrecord")
    banca, _docente = _minha_banca(request, board_id)
    etapa = _etapa_do_edital(banca.process, stage_id)
    ata = sign_record(
        record=_ata_corrente(banca, etapa),
        user=request.user,
        ip=client_ip(request) or None,
        content_hash=payload.content_hash,
        request=request,
    )
    return _com_assinaturas(ata)


# ---------------------------------------------------------------------------
# Atas do edital (secretaria)
# ---------------------------------------------------------------------------
#
# A secretaria não assina ata nem lança nota — ela acompanha. O que ela
# precisa é a fila de atas de um edital com a situação de cada uma e quem
# ainda não assinou, para cobrar; o poder que ela tem sobre a assinatura é
# um só, reemitir o link do examinador externo quando ele diz que não
# chegou, caiu no spam ou expirou. Reemitir não decide nada sobre o
# conteúdo: manda de novo, para o mesmo e-mail, invalidando o anterior.


def _atas_do_programa(program: Program):
    """As atas do programa, com o que `RecordSummaryOut` expande.

    Espelho de `_atas_da_banca`, e escopado pelo programa em vez de pela
    banca: aqui quem consulta é a secretaria, que vê o edital inteiro.
    """
    return (
        ExaminationRecord.objects.for_program(program)
        .select_related("process", "stage", "project", "research_line")
        .select_related("replaced_member__person")
        .prefetch_related(
            Prefetch(
                "signatures",
                queryset=RecordSignature.objects.select_related("signer__person"),
            )
        )
    )


def _ata_do_programa(request: HttpRequest, record_id: int) -> ExaminationRecord:
    """A ata do programa da sessão, ou 404 — id de outro tenant não existe."""
    program = current_program(request)
    return get_object_or_404(
        ExaminationRecord.objects.for_program(program).select_related(
            "process", "stage"
        ),
        pk=record_id,
    )


@router.get("/records/", response=list[RecordSummaryOut])
@paginate
def list_records(
    request: HttpRequest,
    process_id: int,
    stage_id: int | None = None,
    status: RecordStatus | None = None,
):
    """As atas de um edital, da primeira etapa à última.

    `process_id` é obrigatório: a tela é sempre "as atas deste edital", e
    uma listagem de todas as atas do programa misturaria anos e não
    responderia a pergunta de ninguém. O edital passa por
    `_edital_do_programa`, então id de outro tenant dá 404 antes de a
    consulta rodar.

    Devolve **todas as versões**, inclusive as substituídas: a retificação
    guarda a anterior como histórico, e é justamente a secretaria quem
    precisa enxergar que houve uma. A versão vigente de cada chave é a de
    maior `version`, e vem primeiro.
    """
    require_perm(request, "selection.view_examinationrecord")
    program: Program = current_program(request)
    edital = _edital_do_programa(request, process_id)
    atas = _atas_do_programa(program).for_process(edital)
    if stage_id is not None:
        atas = atas.filter(stage=_etapa_do_edital(edital, stage_id))
    if status is not None:
        atas = atas.filter(status=status)
    return atas.order_by(
        "stage__order",
        "level",
        "project__name",
        "research_line__name",
        "-version",
    )


@router.get("/records/{int:record_id}/pdf")
def download_record_pdf(request: HttpRequest, record_id: int):
    """O PDF da ata assinada — pelo Django, nunca por URL direta do MEDIA.

    Só existe depois da terceira assinatura: é `_close_stage` que o grava.
    Antes disso a resposta é 404, e não um PDF de rascunho — ata que não
    foi assinada não é documento, e entregá-la como arquivo convida a
    imprimi-la como se fosse.

    A leitura é auditada. Auditar leitura é exceção no projeto (Seção 3),
    e aqui vale pelo mesmo motivo do anexo da inscrição: o PDF é o
    documento que registra a decisão da banca sobre pessoas, com as notas
    de cada uma, e quem o baixou é parte do rastro.
    """
    require_perm(request, "selection.view_examinationrecord")
    ata = _ata_do_programa(request, record_id)
    if not ata.pdf:
        raise Http404("Esta ata ainda não tem PDF.")
    with transaction.atomic():
        audit.record(
            "selection.record.pdf_download",
            request=request,
            target=ata,
            version=ata.version,
            stage_id=ata.stage_id,
        )
    return FileResponse(
        ata.pdf.open("rb"),
        as_attachment=True,
        filename=Path(ata.pdf.name or "").name,
    )


@router.post(
    "/records/{int:record_id}/signatures/{int:signature_id}/resend-token",
    response=RecordSignatureOut,
)
def resend_signature_token_endpoint(
    request: HttpRequest, record_id: int, signature_id: int
):
    """Emite um token novo para o examinador externo e reenvia o e-mail.

    O link anterior morre na hora: `issue_token` sorteia outro segredo e
    sobrescreve o hash. É de propósito — dois links vivos para a mesma
    assinatura significam que um deles, o que se perdeu, continua
    assinando por alguém.
    """
    require_perm(request, "selection.change_recordsignature")
    ata = _ata_do_programa(request, record_id)
    assinatura = get_object_or_404(
        ata.signatures.select_related("signer__person"), pk=signature_id
    )
    # A instância da ata já lida é a que o service confere: sem isto, o
    # `signature.record` dispararia outra consulta para o mesmo objeto.
    assinatura.record = ata
    return resend_signature_token(signature=assinatura, request=request)


# ---------------------------------------------------------------------------
# Rotas públicas — candidato sem login
# ---------------------------------------------------------------------------
#
# As três rotas abaixo são as únicas do app sem sessão. Elas existem porque
# o candidato do processo seletivo NÃO tem vínculo com a instituição no
# momento em que se inscreve: exigir conta seria exigir que ele criasse uma
# só para mandar o formulário, e a secretaria acabaria digitando inscrição
# no lugar dele — o trabalho que este módulo tira dela.
#
# O que substitui a sessão, em toda rota daqui:
#   1. limite por IP (`enforce_rate_limit`, apps/core/ratelimit.py);
#   2. `csrf_protect` explícito na escrita — `auth=None` desliga junto a
#      checagem de CSRF que o SessionAuth faria (mesma armadilha do login);
#   3. tenant tirado do edital aberto (`edital_com_inscricao_aberta`), nunca
#      de `program_id` no corpo.
# O Nginx dá 80m de corpo só no prefixo `/api/v1/selection/public/`: são até
# sete anexos num POST só.


@router.get("/public/processes", auth=None, response=list[PublicProcessOut])
def list_public_processes(request: HttpRequest):
    """Os editais com inscrição aberta agora, de todos os programas.

    # público: é o cartaz do processo seletivo — edital publicado é
    # documento público, e quem o lê ainda não tem conta para autenticar.
    # Não escapa nada de pessoal: só edital, etapas e grade de vagas.
    #
    # Sem escopo de tenant, de propósito e ao contrário de toda rota
    # autenticada: não há sessão de onde tirar `current_program`, e
    # aceitar `program_id` do chamador só decidiria o que já é público.
    # `program_acronym` no schema é o que distingue os editais na tela.
    """
    enforce_rate_limit(
        request,
        scope="selection-public-read",
        limit=LIMITE_DE_LEITURA_PUBLICA,
        window_seconds=JANELA_DE_LEITURA_EM_SEGUNDOS,
    )
    return (
        SelectionProcess.objects.open_for_submission(timezone.now())
        .select_related("program")
        .prefetch_related("stages", "vacancies__project", "vacancies__research_line")
        .order_by("program__acronym", "year", "kind")
    )


@router.post("/public/applications", auth=None, response={201: ApplicationReceiptOut})
@decorate_view(csrf_protect)
def submit_public_application(
    request: HttpRequest,
    payload: ApplicationIn = Form(...),
    identity: UploadedFile = File(...),
    diploma: UploadedFile = File(...),
    lattes: UploadedFile = File(...),
    payment_receipt: UploadedFile = File(...),
    expanded_abstract: UploadedFile | None = File(None),
    memorial: UploadedFile | None = File(None),
    quota_proof: UploadedFile | None = File(None),
):
    """A inscrição inteira num POST: dados e anexos juntos.

    # público: o candidato não tem conta (ver o bloco acima). Um POST só, e
    # não um rascunho com anexos incrementais, porque sem login não há a
    # quem devolver o rascunho depois.
    #
    # Os três anexos opcionais na assinatura são condicionais no domínio,
    # não dispensáveis: resumo expandido é do Regular, memorial é do
    # Suplementar e a comprovação é de quem concorre por cota. Quem cobra é
    # `required_document_kinds()` do model, pelo edital e pela cota
    # escolhidos — a assinatura só não pode exigir os três de todo mundo.
    """
    enforce_rate_limit(
        request,
        scope="selection-apply",
        limit=LIMITE_DE_INSCRICAO_POR_IP,
        window_seconds=JANELA_DE_INSCRICAO_EM_SEGUNDOS,
    )
    # O tenant sai daqui: só edital publicado e com a janela aberta agora.
    edital = edital_com_inscricao_aberta(
        process_id=payload.process_id, at=timezone.now()
    )
    # Projeto e linha escopados no programa DO EDITAL — id de outro
    # programa é 404, como nas rotas da secretaria.
    projeto, linha = _alvo(edital.program, payload.project_id, payload.research_line_id)
    payload.project_id = projeto.pk if projeto is not None else None
    payload.research_line_id = linha.pk if linha is not None else None
    enviados = {
        ApplicationDocumentKind.IDENTITY: identity,
        ApplicationDocumentKind.DIPLOMA: diploma,
        ApplicationDocumentKind.LATTES: lattes,
        ApplicationDocumentKind.PAYMENT_RECEIPT: payment_receipt,
        ApplicationDocumentKind.EXPANDED_ABSTRACT: expanded_abstract,
        ApplicationDocumentKind.MEMORIAL: memorial,
        ApplicationDocumentKind.QUOTA_PROOF: quota_proof,
    }
    inscricao = submit_application(
        process=edital,
        dados=payload,
        files={
            str(kind): arquivo
            for kind, arquivo in enviados.items()
            if arquivo is not None
        },
        request=request,
    )
    return Status(201, inscricao)


@router.get("/public/applications/{protocol}", auth=None, response=ApplicationStatusOut)
def get_public_application(request: HttpRequest, protocol: str):
    """Consulta pública pelo protocolo.

    # público: é como o candidato sem conta descobre se a inscrição dele
    # foi homologada. O protocolo é o segredo que substitui a senha —
    # `secrets` o gera (ver `gerar_protocolo`).
    #
    # A resposta não tem nome, CPF nem documento: quem digita o protocolo
    # pode não ser o candidato. Protocolo inexistente é 404 genérico, sem
    # dizer se o número nunca existiu ou se é de outro edital.
    """
    enforce_rate_limit(
        request,
        scope="selection-protocol",
        limit=LIMITE_DE_CONSULTA_DE_PROTOCOLO,
        window_seconds=JANELA_DE_CONSULTA_EM_SEGUNDOS,
    )
    return get_object_or_404(
        Application.objects.select_related("process"),
        protocol=protocol.strip().upper(),
    )


@router.get("/public/signatures/{token}", auth=None, response=PublicSignatureOut)
def get_public_signature(request: HttpRequest, token: str):
    """A ata que o link do e-mail abre, para conferência antes de assinar.

    # público: o examinador externo não tem conta (é professor de outra
    # instituição, convidado para uma banca). O token do e-mail é o que
    # substitui a sessão: ele identifica o signatário, vale uma vez e
    # expira — ver `assinatura_por_token`.
    #
    # Sem escopo de tenant, e sem `program_id` no caminho: o programa sai
    # da ata que o token encontrou. Token inexistente, expirado, já usado
    # ou de ata reaberta dão o mesmo 404 genérico — distinguir os casos
    # diria a quem chuta link se ele existiu algum dia.
    """
    enforce_rate_limit(
        request,
        scope="selection-signature-read",
        limit=LIMITE_DE_LEITURA_DE_TOKEN,
        window_seconds=JANELA_DE_CONSULTA_EM_SEGUNDOS,
    )
    return assinatura_por_token(token=token, at=timezone.now())


@router.post(
    "/public/signatures/{token}/sign", auth=None, response=PublicSignatureReceiptOut
)
@decorate_view(csrf_protect)
def sign_public_signature(request: HttpRequest, token: str, payload: RecordSignIn):
    """Assina a ata pelo link do e-mail; na terceira, fecha a etapa.

    # público: mesma justificativa da rota acima. O `csrf_protect`
    # explícito é obrigatório aqui — `auth=None` desliga junto a checagem
    # que o SessionAuth faria, e sem ele o link viraria alvo de CSRF.
    #
    # `content_hash` é o hash que a tela de conferência mostrou: se a ata
    # foi reaberta e recongelada nesse meio-tempo, a assinatura é recusada
    # com `record_changed` em vez de valer sobre um texto que o examinador
    # não leu.
    """
    enforce_rate_limit(
        request,
        scope="selection-signature-sign",
        limit=LIMITE_DE_ASSINATURA_POR_TOKEN,
        window_seconds=JANELA_DE_ASSINATURA_EM_SEGUNDOS,
    )
    sign_record_with_token(
        token=token,
        ip=client_ip(request) or None,
        content_hash=payload.content_hash,
        request=request,
    )
    # O hash do token não muda ao ser consumido: reler por ele é o jeito
    # de devolver o comprovante já com a ata no estado de agora.
    return get_object_or_404(
        RecordSignature.objects.select_related("record", "signer__person").by_token(
            token
        )
    )


# ---------------------------------------------------------------------------
# Inscrições (secretaria)
# ---------------------------------------------------------------------------
#
# A inscrição chega pelo formulário público e é conferida aqui: a
# secretaria lista, abre os anexos e homologa ou indefere. Um model só em
# cada escrita, então tudo fica no router (Seção 3) — a regra de transição
# é do `Application` (`homologate`/`reject`), que devolve 409 quando a
# inscrição já foi decidida.


def _inscricoes(program: Program):
    """As inscrições do programa, com o que `ApplicationOut` expande."""
    return Application.objects.for_program(program).select_related(
        "process", "project", "research_line"
    )


@router.get("/applications/", response=list[ApplicationOut])
@paginate
def list_applications(
    request: HttpRequest,
    process_id: int | None = None,
    status: ApplicationStatus | None = None,
    level: SelectionLevel | None = None,
    quota_category: QuotaCategory | None = None,
    project_id: int | None = None,
    research_line_id: int | None = None,
    search: str | None = None,
):
    """As inscrições do programa, com os filtros da tela de conferência."""
    require_perm(request, "selection.view_application")
    inscricoes = _inscricoes(current_program(request))
    # Filtros de conveniência. Nenhum é escopo de tenant — esse já entrou
    # em `_inscricoes` e não é opcional.
    filtros = {
        "process_id": process_id,
        "status": status,
        "level": level,
        "quota_category": quota_category,
        "project_id": project_id,
        "research_line_id": research_line_id,
    }
    inscricoes = inscricoes.filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )
    if search:
        # Uma caixa só: nome, protocolo ou CPF. O CPF é gravado só com
        # dígitos, então o que a secretaria digitar com ponto e traço é
        # normalizado antes de comparar (`529.982.247-25` acha `52998224725`).
        alvo = Q(full_name__icontains=search) | Q(protocol__icontains=search)
        digitos = so_digitos(search)
        if digitos:
            alvo |= Q(cpf__contains=digitos)
        inscricoes = inscricoes.filter(alvo)
    return inscricoes


def _inscricao_do_programa(request: HttpRequest, application_id: int) -> Application:
    """A inscrição desta requisição, já escopada (404 para a de outro
    programa, nunca 403 — ver `_edital_do_programa`)."""
    return get_object_or_404(
        _inscricoes(current_program(request)).prefetch_related("documents"),
        pk=application_id,
    )


@router.get("/applications/{int:application_id}/", response=ApplicationDetailOut)
def get_application(request: HttpRequest, application_id: int):
    """O detalhe com os anexos — a lista deles, não o conteúdo: abrir o
    arquivo é a rota de download, com permissão própria."""
    require_perm(request, "selection.view_application")
    return _inscricao_do_programa(request, application_id)


def _decidir(
    request: HttpRequest,
    application_id: int,
    evento: str,
    decidir,
) -> Application:
    """O que homologar e indeferir têm em comum: permissão, escopo,
    transição do model, gravação e auditoria dentro da mesma transação."""
    require_perm(request, "selection.change_application")
    inscricao = _inscricao_do_programa(request, application_id)
    with transaction.atomic():
        decidir(inscricao)
        inscricao.save(
            update_fields=["status", "decision_note", "decided_at", "updated_at"]
        )
        audit.record(
            evento,
            request=request,
            target=inscricao,
            protocol=inscricao.protocol,
            process_id=inscricao.process_id,
        )
    return inscricao


@router.post(
    "/applications/{int:application_id}/homologate", response=ApplicationDetailOut
)
def homologate_application(
    request: HttpRequest, application_id: int, payload: ApplicationDecisionIn
):
    """Homologa a inscrição: a partir daqui o candidato disputa as etapas.

    A nota é opcional — homologar é o caminho normal, e não precisa de
    justificativa.
    """
    return _decidir(
        request,
        application_id,
        "selection.application.homologate",
        lambda inscricao: inscricao.homologate(at=timezone.now(), note=payload.note),
    )


@router.post("/applications/{int:application_id}/reject", response=ApplicationDetailOut)
def reject_application(
    request: HttpRequest, application_id: int, payload: ApplicationDecisionIn
):
    """Indefere a inscrição — com justificativa obrigatória.

    Quem cobra a nota é `Application.reject` (400 `rejection_requires_note`)
    e não o schema: o candidato tem direito de saber por que ficou de fora,
    e essa é regra do domínio, não validação de formulário.
    """
    return _decidir(
        request,
        application_id,
        "selection.application.reject",
        lambda inscricao: inscricao.reject(at=timezone.now(), note=payload.note),
    )


@router.get("/applications/documents/{int:document_id}/download")
def download_application_document(request: HttpRequest, document_id: int):
    """Entrega o anexo — pelo Django, nunca por URL direta do MEDIA.

    Duas permissões, e as duas juntas: `view_application` para chegar até
    a inscrição e `download_applicationdocument` para abrir o arquivo.
    Coordenação e Docente enxergam a inscrição e mesmo assim levam 403
    aqui — identidade, diploma e comprovante de pagamento não são insumo
    de classificação. Só a Secretaria tem a segunda (migration 0006).

    Diferente do download de `academic`, não há caminho por posse: o
    candidato do processo seletivo não tem conta, e o que ele consulta
    pelo protocolo é a situação, não o conteúdo que ele mesmo mandou.
    """
    require_perm(request, "selection.view_application")
    require_perm(request, "selection.download_applicationdocument")
    program: Program = current_program(request)
    documento = get_object_or_404(
        ApplicationDocument.objects.filter(
            application__in=Application.objects.for_program(program)
        ).select_related("application"),
        pk=document_id,
    )
    with transaction.atomic():
        # Auditar leitura é exceção no projeto e aqui é obrigatório: é o
        # documento pessoal de alguém que sequer tem conta no sistema.
        audit.record(
            "selection.application.document_download",
            request=request,
            target=documento.application,
            document_id=documento.pk,
            kind=documento.kind,
        )
    return FileResponse(
        documento.file.open("rb"),
        as_attachment=True,
        filename=Path(documento.file.name or "").name,
    )


# ---------------------------------------------------------------------------
# Convocação de etapa — a secretaria chama os candidatos para a prova
# ---------------------------------------------------------------------------
#
# O disparo é `add_convocation`, permissão que só a Secretaria tem
# (migration 0006): convocar é ato de expediente, não avaliação. Nenhuma
# das três rotas devolve 500 por causa do servidor de e-mail — o lote é
# criado numa transação e o envio acontece fora dela, com o resultado
# gravado por destinatário (`send_convocations`).


def _lotes_da_etapa(edital: SelectionProcess, etapa: SelectionStage):
    """Os lotes já disparados para esta etapa, do mais recente ao mais
    antigo (`Meta.ordering`), com os e-mails pré-carregados: as contagens
    de `ConvocationOut` saem deles, e sem o `prefetch` seriam quatro
    consultas por lote."""
    return (
        etapa.convocations.filter(process=edital)
        .select_related("stage", "sent_by")
        .prefetch_related("emails")
    )


@router.get(
    "/processes/{int:process_id}/stages/{int:stage_id}/convocable",
    response=list[ConvocableApplicationOut],
)
def list_convocable(request: HttpRequest, process_id: int, stage_id: int):
    """Quem esta etapa pode convocar — o que o botão de disparo vai mandar.

    A regra de quem é convocável mora no manager (`convocable_for`); esta
    rota só a expõe para a tela não ter de refazê-la. `already_convoked`
    marca quem já recebeu e-mail nesta etapa em lote nenhum, que é
    exatamente o que `_abrir_lote` exclui — a soma dos não marcados é o
    tamanho do próximo lote.

    Sem paginação, como a listagem de lotes: são os candidatos vivos de
    uma etapa de um edital, e a tela mostra todos.
    """
    require_perm(request, "selection.view_convocation")
    edital = _edital_do_programa(request, process_id)
    etapa = _etapa_do_edital(edital, stage_id)
    ja_convocado = ConvocationEmail.objects.filter(
        convocation__stage=etapa, application=OuterRef("pk")
    )
    return (
        Application.objects.convocable_for(etapa)
        .select_related("project", "research_line")
        .annotate(already_convoked=Exists(ja_convocado))
        .order_by("full_name", "pk")
    )


@router.get(
    "/processes/{int:process_id}/stages/{int:stage_id}/convocations",
    response=list[ConvocationOut],
)
def list_convocations(request: HttpRequest, process_id: int, stage_id: int):
    """Os lotes de convocação de uma etapa, com a contagem por situação.

    Sem paginação: são poucos lotes por etapa (o primeiro disparo e os
    reforços de quem foi homologado depois), e a tela mostra todos.
    """
    require_perm(request, "selection.view_convocation")
    edital = _edital_do_programa(request, process_id)
    etapa = _etapa_do_edital(edital, stage_id)
    return _lotes_da_etapa(edital, etapa)


@router.post(
    "/processes/{int:process_id}/stages/{int:stage_id}/convocations",
    response={201: ConvocationDetailOut},
)
def send_convocations_endpoint(request: HttpRequest, process_id: int, stage_id: int):
    """Dispara a convocação da etapa para quem ainda não foi chamado.

    Reexecutar é seguro e é o fluxo previsto: quem já recebeu e-mail
    nesta etapa fica de fora, então a secretaria clica de novo depois de
    homologar mais uma inscrição e só ela é convocada. Se não sobrou
    ninguém, a resposta é 4xx (`no_convocable_applications`) — e não um
    lote vazio.
    """
    require_perm(request, "selection.add_convocation")
    edital = _edital_do_programa(request, process_id)
    etapa = _etapa_do_edital(edital, stage_id)
    return Status(201, send_convocations(process=edital, stage=etapa, request=request))


def _lote_do_programa(request: HttpRequest, convocation_id: int) -> Convocation:
    """O lote desta requisição, já escopado (404 para o de outro
    programa, nunca 403 — ver `_edital_do_programa`)."""
    return get_object_or_404(
        Convocation.objects.filter(program=current_program(request)).select_related(
            "stage", "process", "sent_by"
        ),
        pk=convocation_id,
    )


@router.get("/convocations/{int:convocation_id}", response=ConvocationDetailOut)
def get_convocation(request: HttpRequest, convocation_id: int):
    """Um lote com os destinatários — quem recebeu, quem falhou e por quê.

    A listagem por etapa devolve só a contagem; é aqui que a secretaria
    abre o lote para achar o endereço errado antes de mandar reenviar.
    """
    require_perm(request, "selection.view_convocation")
    return _lote_do_programa(request, convocation_id)


@router.post("/convocations/{int:convocation_id}/resend", response=ConvocationDetailOut)
def resend_convocation_endpoint(request: HttpRequest, convocation_id: int):
    """Reenvia os e-mails que falharam neste lote — só eles."""
    require_perm(request, "selection.add_convocation")
    lote = _lote_do_programa(request, convocation_id)
    return resend_convocation_emails(convocation=lote, request=request)


# ---------------------------------------------------------------------------
# Classificação (secretaria)
# ---------------------------------------------------------------------------
#
# Calcular é escrever em inscrição (`change_application`): o cálculo grava
# posição e desfecho em cada aprovado da chave. Ler é `view_application`,
# como qualquer outra consulta da lista de inscritos.
#
# As duas rotas pedem o mesmo recorte — nível × alvo —, uma no corpo e a
# outra na query, porque é ele que define quem disputa com quem.


@router.post("/processes/{int:process_id}/ranking", response=RankingOut)
def compute_ranking_endpoint(request: HttpRequest, process_id: int, payload: RankingIn):
    """Calcula (ou recalcula) a classificação de um nível × alvo.

    Rodar de novo é o fluxo previsto — depois de retificação de ata ou de
    realocação de vaga a lista muda. A trava é o primeiro matriculado da
    chave (`ranking_locked`), e antes dela a exigência é a ata da última
    etapa assinada (`final_record_not_signed`).
    """
    require_perm(request, "selection.change_application")
    program: Program = current_program(request)
    edital = _edital_do_programa(request, process_id)
    projeto, linha = _alvo(program, payload.project_id, payload.research_line_id)
    return compute_ranking(
        process=edital,
        level=payload.level,
        project=projeto,
        research_line=linha,
        request=request,
    )


@router.get("/processes/{int:process_id}/ranking", response=RankingOut)
def get_ranking(
    request: HttpRequest,
    process_id: int,
    level: SelectionLevel,
    project_id: int | None = None,
    research_line_id: int | None = None,
):
    """A classificação já calculada do nível × alvo.

    Sem cálculo nenhum: chave ainda não classificada devolve a grade de
    vagas e a lista vazia, que é o que a tela mostra antes do primeiro
    clique em "calcular".
    """
    require_perm(request, "selection.view_application")
    program: Program = current_program(request)
    edital = _edital_do_programa(request, process_id)
    projeto, linha = _alvo(program, project_id, research_line_id)
    return ranking_of(process=edital, level=level, project=projeto, research_line=linha)
