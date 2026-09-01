"""Borda HTTP do app scholarships, montada em /api/v1/scholarships/.

Padrão de toda rota: `require_perm` na primeira linha, `current_program`
logo depois, chamada ao model/service, schema de saída explícito. Zero
regra de negócio aqui. As rotas entram nas stories de API.

**Nenhuma rota deste módulo é pública** — ao contrário do processo
seletivo, aqui até o candidato é aluno matriculado, e portanto logado.
"""

from io import BytesIO
from pathlib import Path

from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Form, Router, Status, UploadedFile
from ninja.pagination import paginate

from apps.academic.models import Student, Teacher
from apps.core import audit
from apps.core.exceptions import NotAllowed
from apps.core.permissions import require_perm
from apps.core.tenancy import current_program
from apps.people.models import Person
from apps.programs.models import Program

# Módulo inteiro, e não `from .services import publish_preliminary`: as
# rotas têm o nome do ato que chamam, e o `def` de baixo sombrearia o
# import — a rota chamaria a si mesma, sem erro de importação.
from . import pdf, services
from .models import (
    PAPEIS_COM_VISAO_DA_FILA,
    AppealState,
    ApplicationDocument,
    ApplicationDocumentKind,
    BaremeEntry,
    BaremeItem,
    CommitteeMember,
    ItemReview,
    ScholarshipAppeal,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)
from .schemas import (
    ApplicationDocumentOut,
    BandOut,
    BandOverrideIn,
    BaremeCloneIn,
    BaremeCloneOut,
    BaremeEntryIn,
    BaremeEntryOut,
    BaremeEntryPatch,
    BaremeEntryReviewIn,
    BaremeItemIn,
    BaremeItemOut,
    BaremeItemPatch,
    CommitteeMemberIn,
    CommitteeMemberOut,
    FumpLevelIn,
    ItemReviewIn,
    ItemReviewOut,
    ScholarshipAppealIn,
    ScholarshipAppealJudgeIn,
    ScholarshipAppealOut,
    ScholarshipApplicationIn,
    ScholarshipApplicationOut,
    ScholarshipApplicationPatch,
    ScholarshipApplicationQueueOut,
    ScholarshipEditionIn,
    ScholarshipEditionOut,
    ScholarshipEditionPatch,
)

router = Router(tags=["scholarships"])


# ---------------------------------------------------------------------------
# Edição do edital de bolsas
# ---------------------------------------------------------------------------


def _edicao_do_programa(request: HttpRequest, edition_id: int) -> ScholarshipEdition:
    """A edição desta requisição, já escopada.

    O escopo entra na busca: edição de outro programa simplesmente não
    existe aqui (404, nunca 403 — 403 revelaria que o id existe).
    """
    return get_object_or_404(
        ScholarshipEdition.objects.for_program(current_program(request)),
        pk=edition_id,
    )


@router.get("/editions/", response=list[ScholarshipEditionOut])
@paginate
def list_editions(
    request: HttpRequest,
    year: int | None = None,
    status: ScholarshipEditionStatus | None = None,
):
    """As edições do programa, do ano mais recente para o mais antigo."""
    require_perm(request, "scholarships.view_scholarshipedition")
    edicoes = ScholarshipEdition.objects.for_program(current_program(request))
    # Filtros de conveniência da tela. Nenhum deles é escopo de tenant —
    # esse já foi aplicado acima e não é opcional.
    filtros = {"year": year, "status": status}
    return edicoes.filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )


@router.post("/editions/", response={201: ScholarshipEditionOut})
def create_edition(request: HttpRequest, payload: ScholarshipEditionIn):
    """A secretaria abre a edição do ano, em rascunho."""
    require_perm(request, "scholarships.add_scholarshipedition")
    program: Program = current_program(request)
    edicao = ScholarshipEdition(program=program, **payload.model_dump())
    with transaction.atomic():
        edicao.clean()
        edicao.save()
        audit.record(
            "scholarships.edition.create",
            request=request,
            target=edicao,
            year=edicao.year,
        )
    return Status(201, edicao)


@router.get("/editions/{int:edition_id}/", response=ScholarshipEditionOut)
def get_edition(request: HttpRequest, edition_id: int):
    require_perm(request, "scholarships.view_scholarshipedition")
    return _edicao_do_programa(request, edition_id)


@router.patch("/editions/{int:edition_id}/", response=ScholarshipEditionOut)
def update_edition(
    request: HttpRequest, edition_id: int, payload: ScholarshipEditionPatch
):
    """Retificação da edição, em qualquer estado.

    Sem `ensure_editable` de propósito: o que se corrige aqui é título e
    cronograma, e cronograma é informação divulgada, não gatilho —
    retificar data publicada é rotina do edital. O que não pode mudar
    depois de aberta a inscrição é o **barema**, e quem guarda isso é
    `bareme_editable()`, na story do barema.
    """
    require_perm(request, "scholarships.change_scholarshipedition")
    edicao = _edicao_do_programa(request, edition_id)
    campos = payload.model_dump(exclude_unset=True)
    for campo, valor in campos.items():
        setattr(edicao, campo, valor)
    with transaction.atomic():
        edicao.clean()
        edicao.save(update_fields=[*campos, "updated_at"] if campos else None)
        audit.record(
            "scholarships.edition.update",
            request=request,
            target=edicao,
            fields=sorted(campos),
        )
    return edicao


# ---------------------------------------------------------------------------
# As cinco transições — uma rota nomeada cada
# ---------------------------------------------------------------------------
#
# Uma rota por transição, e não um PATCH de `status`: o nome do ato é o
# que a auditoria registra e o que a tela mostra num botão. A regra de
# quando cada uma pode acontecer é do model (409 com `code` próprio); aqui
# só se persiste, dentro do mesmo `transaction.atomic()` do `AuditLog`.


def _transicionar(
    request: HttpRequest,
    edition_id: int,
    *,
    perm: str,
    metodo: str,
    evento: str,
    campos: list[str],
    at: bool = False,
) -> ScholarshipEdition:
    """O corpo comum das cinco: checa, transiciona, salva e audita."""
    require_perm(request, perm)
    edicao = _edicao_do_programa(request, edition_id)
    with transaction.atomic():
        if at:
            getattr(edicao, metodo)(at=timezone.now())
        else:
            getattr(edicao, metodo)()
        edicao.save(update_fields=[*campos, "updated_at"])
        audit.record(evento, request=request, target=edicao, status=edicao.status)
    return edicao


@router.post(
    "/editions/{int:edition_id}/open-submissions", response=ScholarshipEditionOut
)
def open_submissions(request: HttpRequest, edition_id: int):
    """Abre as inscrições e congela o barema (409 `edition_not_draft`)."""
    return _transicionar(
        request,
        edition_id,
        perm="scholarships.change_scholarshipedition",
        metodo="open_submissions",
        evento="scholarships.edition.open_submissions",
        campos=["status"],
    )


@router.post("/editions/{int:edition_id}/start-review", response=ScholarshipEditionOut)
def start_review(request: HttpRequest, edition_id: int):
    """Encerra as inscrições e entrega a fila para a comissão."""
    return _transicionar(
        request,
        edition_id,
        perm="scholarships.change_scholarshipedition",
        metodo="start_review",
        evento="scholarships.edition.start_review",
        campos=["status"],
    )


@router.post(
    "/editions/{int:edition_id}/publish-preliminary", response=ScholarshipEditionOut
)
def publish_preliminary(request: HttpRequest, edition_id: int):
    """Publica o resultado preliminar e **congela a lista**.

    Permissão própria `publish_scholarshipedition`, e não `change_`:
    publicar congela o ano e é o que o candidato lê como resultado — quem
    monta o edital não é necessariamente quem assina a lista.

    Fora do padrão `_transicionar` porque o ato cruza dois agregados: o
    service classifica os dois níveis, grava o snapshot em toda inscrição
    e escreve um `AuditLog` só, com as contagens.
    """
    require_perm(request, "scholarships.publish_scholarshipedition")
    edicao = _edicao_do_programa(request, edition_id)
    return services.publish_preliminary(edition=edicao, request=request)


@router.post("/editions/{int:edition_id}/open-appeals", response=ScholarshipEditionOut)
def open_appeals(request: HttpRequest, edition_id: int):
    """Abre a fase de recursos: o discente interpõe e a comissão julga."""
    return _transicionar(
        request,
        edition_id,
        perm="scholarships.change_scholarshipedition",
        metodo="open_appeals",
        evento="scholarships.edition.open_appeals",
        campos=["status"],
    )


@router.post("/editions/{int:edition_id}/publish-final", response=ScholarshipEditionOut)
def publish_final(request: HttpRequest, edition_id: int):
    """Publica o resultado final, depois dos recursos julgados.

    Mesmo service do preliminar, com a **mesma** semente de sorteio: o
    que muda entre as duas listas é o que os recursos mudaram, e nada
    mais.
    """
    require_perm(request, "scholarships.publish_scholarshipedition")
    edicao = _edicao_do_programa(request, edition_id)
    return services.publish_final(edition=edicao, request=request)


@router.get("/editions/{int:edition_id}/result", response=list[BandOut])
def edition_result(request: HttpRequest, edition_id: int, level: ScholarshipLevel):
    """As dez faixas de um nível — a lista publicada, ou a prévia.

    Um nível por chamada: mestrado e doutorado correm independentes e saem
    em documentos separados, e é este mesmo objeto que alimenta a tela e o
    PDF do resultado.

    Antes da publicação a rota devolve a **prévia** (`classify()`), e ela é
    só de quem trabalha o edital — Secretaria, Coordenação e Comissão de
    Bolsas, o mesmo recorte de `ScholarshipApplicationQuerySet.visible_to`.
    Para o candidato o resultado começa a existir com o preliminar
    publicado (`results_visible_to_student()`); antes disso, 403.
    """
    require_perm(request, "scholarships.view_scholarshipedition")
    edicao = _edicao_do_programa(request, edition_id)
    _garantir_resultado_visivel(request, edicao)
    return edicao.result(level)


@router.get("/editions/{int:edition_id}/result.pdf")
def edition_result_pdf(request: HttpRequest, edition_id: int, level: ScholarshipLevel):
    """O mesmo resultado, em papel — um documento por nível.

    A rota não monta nada: a permissão e a regra de visibilidade são as
    **mesmas** do JSON (`_garantir_resultado_visivel`, e é de propósito
    que sejam uma função só — duas cópias divergiriam, e a que vazasse
    seria justamente a imprimível), e o documento sai inteiro de
    `pdf.montar_resultado`.
    """
    require_perm(request, "scholarships.view_scholarshipedition")
    edicao = _edicao_do_programa(request, edition_id)
    _garantir_resultado_visivel(request, edicao)
    tipo = pdf.tipo_do_resultado(edicao)
    return FileResponse(
        BytesIO(pdf.montar_resultado(edicao, level, tipo)),
        as_attachment=True,
        filename=pdf.nome_do_arquivo(edicao, level, tipo),
        content_type="application/pdf",
    )


def _garantir_resultado_visivel(
    request: HttpRequest, edicao: ScholarshipEdition
) -> None:
    """Quem ainda não pode ver esta lista toma 403 `result_not_published`."""
    if not _ve_a_previa(request) and not edicao.results_visible_to_student():
        raise NotAllowed(
            "O resultado desta edição ainda não foi publicado.",
            code="result_not_published",
        )


def _ve_a_previa(request: HttpRequest) -> bool:
    """Quem enxerga a lista antes de ela ser publicada.

    Mesmo recorte de `visible_to` (e a mesma constante), porque é a mesma
    pergunta: quem acompanha a edição inteira vê a prévia; quem só tem a
    própria inscrição espera o resultado sair.
    """
    return (
        request.user.is_superuser
        or request.user.groups.filter(name__in=PAPEIS_COM_VISAO_DA_FILA).exists()
    )


# ---------------------------------------------------------------------------
# Barema — as linhas pontuáveis daquela edição, por nível
# ---------------------------------------------------------------------------
#
# TODA ESCRITA DAQUI PARA BAIXO PASSA POR `ensure_bareme_editable()`: item
# só nasce, muda ou some com a edição em rascunho (409 `bareme_frozen`).
# Depois de `open-submissions` o candidato lança contra os pontos que leu,
# e mexer no `points_per_unit` mudaria nota já dada. A leitura continua
# aberta em qualquer estado — é o barema publicado do edital.


def _itens_do_barema(edicao: ScholarshipEdition):
    """O barema é filho de agregado: buscar dentro da edição já escopada
    é o que garante o tenant, sem um `for_program` próprio."""
    return edicao.bareme_items.all()


@router.get("/editions/{int:edition_id}/bareme/", response=list[BaremeItemOut])
def list_bareme(
    request: HttpRequest, edition_id: int, level: ScholarshipLevel | None = None
):
    """O barema da edição, na ordem do edital (nível, depois código).

    Sem paginação de propósito: o barema é a tabela do edital e a tela de
    lançamento monta as seis seções de uma vez — paginar aqui obrigaria o
    front a remontar a tabela em pedaços.
    """
    require_perm(request, "scholarships.view_baremeitem")
    itens = _itens_do_barema(_edicao_do_programa(request, edition_id))
    if level is not None:
        itens = itens.for_level(level)
    return itens


@router.post("/editions/{int:edition_id}/bareme/", response={201: BaremeItemOut})
def add_bareme_item(request: HttpRequest, edition_id: int, payload: BaremeItemIn):
    """A secretaria acrescenta uma linha ao barema, em rascunho."""
    require_perm(request, "scholarships.add_baremeitem")
    edicao = _edicao_do_programa(request, edition_id)
    edicao.ensure_bareme_editable()
    item = BaremeItem(edition=edicao, **payload.model_dump())
    with transaction.atomic():
        item.clean()
        item.save()
        audit.record(
            "scholarships.bareme.add",
            request=request,
            target=item,
            program=edicao.program,
            edition_id=edicao.pk,
            level=item.level,
            code=item.code,
        )
    return Status(201, item)


@router.patch(
    "/editions/{int:edition_id}/bareme/{int:item_id}/", response=BaremeItemOut
)
def update_bareme_item(
    request: HttpRequest, edition_id: int, item_id: int, payload: BaremeItemPatch
):
    """Retificação da linha do barema, só em rascunho."""
    require_perm(request, "scholarships.change_baremeitem")
    edicao = _edicao_do_programa(request, edition_id)
    edicao.ensure_bareme_editable()
    item = get_object_or_404(_itens_do_barema(edicao), pk=item_id)
    campos = payload.model_dump(exclude_unset=True)
    for campo, valor in campos.items():
        setattr(item, campo, valor)
    with transaction.atomic():
        item.clean()
        item.save(update_fields=[*campos, "updated_at"] if campos else None)
        audit.record(
            "scholarships.bareme.update",
            request=request,
            target=item,
            program=edicao.program,
            edition_id=edicao.pk,
            fields=sorted(campos),
        )
    return item


@router.delete("/editions/{int:edition_id}/bareme/{int:item_id}/", response={204: None})
def remove_bareme_item(request: HttpRequest, edition_id: int, item_id: int):
    """Tira uma linha do barema, só em rascunho.

    A permissão exigida é `change_baremeitem`, e não `delete_`: nenhum
    papel de domínio recebe `delete_*` (migration `0008_papeis_da_bolsa`,
    com teste guardando) — mesmo precedente do `DELETE` da comissão. Em
    rascunho ainda não existe lançamento contra o item, então remover não
    apaga nota de ninguém.

    A auditoria é gravada **antes** do `delete()`: depois dele a instância
    perde o pk e o alvo do registro sairia vazio.
    """
    require_perm(request, "scholarships.change_baremeitem")
    edicao = _edicao_do_programa(request, edition_id)
    edicao.ensure_bareme_editable()
    item = get_object_or_404(_itens_do_barema(edicao), pk=item_id)
    with transaction.atomic():
        audit.record(
            "scholarships.bareme.remove",
            request=request,
            target=item,
            program=edicao.program,
            edition_id=edicao.pk,
            level=item.level,
            code=item.code,
        )
        item.delete()
    return Status(204, None)


@router.post("/editions/{int:edition_id}/bareme/clone", response=BaremeCloneOut)
def clone_bareme_from_edition(
    request: HttpRequest, edition_id: int, payload: BaremeCloneIn
):
    """Copia o barema de outra edição do programa para esta.

    A edição da URL é o **destino** — é ela que precisa estar em rascunho.
    A origem é buscada com o mesmo escopo: edição de outro programa é 404.

    Cruza dois agregados, então o corpo é do service (ADR-002); aqui só
    permissão, escopo e contrato.
    """
    require_perm(request, "scholarships.add_baremeitem")
    destino = _edicao_do_programa(request, edition_id)
    origem = _edicao_do_programa(request, payload.source_edition_id)
    novos = services.clone_bareme(source=origem, target=destino, request=request)
    return {
        "source_edition_id": origem.pk,
        "created": len(novos),
        "items": list(_itens_do_barema(destino)),
    }


# ---------------------------------------------------------------------------
# Comissão de Bolsas — a composição daquele ano
# ---------------------------------------------------------------------------
#
# ESTAS ROTAS NÃO DECIDEM ACESSO. Estar em `CommitteeMember` é registro
# histórico (portaria, data); quem pode avaliar é quem está no Group
# "Comissão de Bolsas", conferido por `require_perm` como em todo o resto
# do projeto. Nenhuma rota deste app pode consultar a comissão para
# autorizar — isso seria um RBAC paralelo ao do Django.


def _membros(edicao: ScholarshipEdition):
    """A comissão é filha de agregado: buscar dentro da edição já escopada
    é o que garante o tenant, sem um `for_program` próprio."""
    return edicao.committee_members.select_related("teacher__person")


@router.get("/editions/{int:edition_id}/committee/", response=list[CommitteeMemberOut])
def list_committee(request: HttpRequest, edition_id: int):
    """A composição da comissão daquele ano.

    Sem paginação de propósito: são poucos membros por edição, e a tela
    monta a portaria inteira de uma vez.
    """
    require_perm(request, "scholarships.view_committeemember")
    return _membros(_edicao_do_programa(request, edition_id))


@router.post(
    "/editions/{int:edition_id}/committee/", response={201: CommitteeMemberOut}
)
def add_committee_member(
    request: HttpRequest, edition_id: int, payload: CommitteeMemberIn
):
    """A secretaria designa um professor do programa na comissão."""
    require_perm(request, "scholarships.add_committeemember")
    program: Program = current_program(request)
    edicao = get_object_or_404(
        ScholarshipEdition.objects.for_program(program), pk=edition_id
    )
    dados = payload.model_dump()
    # 404 e não 400 `program_mismatch`: o id de outro programa não existe
    # aqui, e responder com o código do domínio confirmaria que ele existe
    # em algum lugar. O `clean()` do model continua guardando quem escreve
    # fora da rota.
    docente = get_object_or_404(
        Teacher.objects.for_program(program), pk=dados.pop("teacher_id")
    )
    membro = CommitteeMember(edition=edicao, teacher=docente, **dados)
    with transaction.atomic():
        membro.clean()
        membro.save()
        audit.record(
            "scholarships.committee.add",
            request=request,
            target=membro,
            program=edicao.program,
            edition_id=edicao.pk,
            teacher_id=docente.pk,
        )
    return Status(201, membro)


@router.delete(
    "/editions/{int:edition_id}/committee/{int:member_id}/", response={204: None}
)
def remove_committee_member(request: HttpRequest, edition_id: int, member_id: int):
    """Tira um professor da comissão — retificação de portaria.

    Vale em qualquer estado da edição: a comissão é registro de quem
    compôs, e não autorização, então remover uma linha não invalida nota
    já lançada nem reabre nada. O que se corrige aqui é o erro de digitação
    e a substituição que a portaria retificadora fez.

    A permissão exigida é `change_committeemember`, e não `delete_`:
    nenhum papel de domínio recebe `delete_*` (migration
    `0008_papeis_da_bolsa`, com teste guardando), porque apagar dado da
    bolsa é quebra-vidro de sysadmin — e recompor a comissão do ano é a
    mesma edição da composição que o POST faz.

    A auditoria é gravada **antes** do `delete()`: depois dele a instância
    perde o pk e o alvo do registro sairia vazio.
    """
    require_perm(request, "scholarships.change_committeemember")
    edicao = _edicao_do_programa(request, edition_id)
    membro = get_object_or_404(_membros(edicao), pk=member_id)
    with transaction.atomic():
        audit.record(
            "scholarships.committee.remove",
            request=request,
            target=membro,
            program=edicao.program,
            edition_id=edicao.pk,
            teacher_id=membro.teacher_id,
        )
        membro.delete()
    return Status(204, None)


# ---------------------------------------------------------------------------
# Inscrição do discente
# ---------------------------------------------------------------------------
#
# A janela e a guarda são do model: `ScholarshipApplication.ensure_editable`
# cobra o estado (409 `submissions_closed`) e a posse (403
# `not_application_owner`) nas quatro escritas do candidato — criar, alterar,
# excluir e anexar. Aqui só permissão, escopo, contrato e auditoria.
#
# A Secretaria não passa por estas rotas: o que ela escreve na inscrição
# alheia são dois campos, com permissão e rota próprias (`set_fump_level`,
# `override_band`, f14). "Editar como se fosse o aluno" não existe.


def _meus_alunos(request: HttpRequest, program: Program):
    """Os vínculos de aluno de quem está pedindo, já escopados.

    Mesmo caminho de `_aluno_da_sessao` (`apps/academic/router.py`): a
    Person ativa é o elo entre o usuário da sessão e o discente, e é ela
    que `current_program` já usou para achar o tenant.
    """
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    return Student.objects.for_program(program).filter(person__in=pessoas)


def _aluno_da_sessao(request: HttpRequest, program: Program) -> Student:
    """O discente desta sessão — nunca um `student_id` do corpo.

    O vínculo regular ganha do não regular porque é o que tem nível
    (isolada e eletiva têm `level` nulo). Quem só tem isolada chega em
    `for_student` e recebe o 400 `student_without_level`, que explica o
    problema, em vez de um 403 dizendo "você não é aluno".
    """
    meus = _meus_alunos(request, program)
    aluno = meus.regular().first() or meus.first()
    if aluno is None:
        raise NotAllowed(
            "Sua conta não tem vínculo de aluno neste programa.",
            code="not_a_student",
        )
    return aluno


def _inscricoes(program: Program):
    return ScholarshipApplication.objects.for_program(program).select_related(
        "edition", "student__person"
    )


@router.get(
    "/editions/{int:edition_id}/my-application", response=ScholarshipApplicationOut
)
def get_my_application(request: HttpRequest, edition_id: int):
    """A inscrição do próprio discente naquela edição, se existir.

    404 quando ele ainda não se inscreveu — é assim que a tela sabe que
    deve oferecer o formulário em branco em vez do questionário
    preenchido. Rota separada de um `GET /applications/{id}` de propósito:
    o candidato não guarda o id da própria inscrição, ele guarda o edital.
    """
    require_perm(request, "scholarships.view_scholarshipapplication")
    program: Program = current_program(request)
    edicao = _edicao_do_programa(request, edition_id)
    inscricao = (
        _inscricoes(program)
        .for_edition(edicao)
        .filter(student__in=_meus_alunos(request, program))
        .first()
    )
    if inscricao is None:
        raise Http404("Você ainda não se inscreveu nesta edição do edital.")
    return inscricao


@router.post("/applications/", response={201: ScholarshipApplicationOut})
def create_application(request: HttpRequest, payload: ScholarshipApplicationIn):
    """O discente se inscreve na edição, com o questionário respondido.

    `for_student` copia programa e nível do vínculo e congela o nível; a
    duplicata por (edição, discente) é o `clean()` (400
    `duplicate_application`). A guarda roda sobre a instância ainda não
    salva — ela só lê a edição e o dono, e é justamente antes de gravar
    que a janela precisa ser conferida.
    """
    require_perm(request, "scholarships.add_scholarshipapplication")
    program: Program = current_program(request)
    dados = payload.model_dump()
    edicao = _edicao_do_programa(request, dados.pop("edition_id"))
    inscricao = ScholarshipApplication.for_student(
        edition=edicao, student=_aluno_da_sessao(request, program), **dados
    )
    inscricao.ensure_editable(request.user)
    with transaction.atomic():
        inscricao.clean()
        inscricao.submitted_at = timezone.now()
        inscricao.save()
        audit.record(
            "scholarships.application.create",
            request=request,
            target=inscricao,
            edition_id=edicao.pk,
            student_id=inscricao.student_id,
            level=inscricao.level,
        )
    return Status(201, inscricao)


@router.patch("/applications/{int:application_id}/", response=ScholarshipApplicationOut)
def update_application(
    request: HttpRequest, application_id: int, payload: ScholarshipApplicationPatch
):
    """Retificação do questionário, só na janela aberta e só pelo dono."""
    require_perm(request, "scholarships.change_scholarshipapplication")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    inscricao.ensure_editable(request.user)
    campos = payload.model_dump(exclude_unset=True)
    for campo, valor in campos.items():
        setattr(inscricao, campo, valor)
    with transaction.atomic():
        inscricao.clean()
        inscricao.save(update_fields=[*campos, "updated_at"] if campos else None)
        audit.record(
            "scholarships.application.update",
            request=request,
            target=inscricao,
            edition_id=inscricao.edition_id,
            fields=sorted(campos),
        )
    return inscricao


@router.delete("/applications/{int:application_id}/", response={204: None})
def remove_application(request: HttpRequest, application_id: int):
    """O candidato desiste e apaga a própria inscrição, na janela aberta.

    Fechada a janela, a inscrição é a peça que a comissão pontua e some
    da mão dele — quem cobra isso é o mesmo `ensure_editable` das outras
    escritas (409 `submissions_closed`).

    A permissão exigida é `change_scholarshipapplication`, e não
    `delete_`: nenhum papel de domínio recebe `delete_*` (migration
    `0008_papeis_da_bolsa`, com teste guardando), mesmo precedente do
    DELETE do barema e do da comissão. O `CASCADE` leva junto os
    comprovantes do questionário e os lançamentos do barema; os arquivos
    saem do storage com eles, porque o `delete()` do model não o faz.

    A auditoria é gravada **antes** do `delete()`: depois dele a
    instância perde o pk e o alvo do registro sairia vazio.
    """
    require_perm(request, "scholarships.change_scholarshipapplication")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    inscricao.ensure_editable(request.user)
    with transaction.atomic():
        audit.record(
            "scholarships.application.remove",
            request=request,
            target=inscricao,
            edition_id=inscricao.edition_id,
            student_id=inscricao.student_id,
        )
        for documento in inscricao.documents.all():
            documento.file.delete(save=False)
        inscricao.delete()
    return Status(204, None)


# ---------------------------------------------------------------------------
# Comprovantes do questionário
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{int:application_id}/documents",
    response={200: ApplicationDocumentOut, 201: ApplicationDocumentOut},
)
def upload_application_document(
    request: HttpRequest,
    application_id: int,
    kind: ApplicationDocumentKind = Form(...),
    file: UploadedFile = File(...),
):
    """Anexa (ou substitui) o comprovante de um "Sim" do questionário.

    A permissão é a de montar a própria inscrição — anexar é parte de
    montar —, e não há permissão de `add_applicationdocument` para papel
    nenhum: o comprovante não é entidade que alguém administre à parte.
    Mesmo desenho do anexo do requerimento de isolada.

    Substituir, e não empilhar: um tipo tem uma versão
    (`unique_documento_por_inscricao_de_bolsa_e_tipo`), e o reenvio é a
    correção de quem mandou a página errada. 201 quando é o primeiro
    envio daquele tipo, 200 quando substituiu.
    """
    require_perm(request, "scholarships.change_scholarshipapplication")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    inscricao.ensure_editable(request.user)
    # As duas cobranças são do model e voltam como 4xx do handler central:
    # estado errado é 409, arquivo recusado é 400 com code invalid_document.
    ApplicationDocument.validate_upload(filename=file.name or "", size=file.size or 0)

    with transaction.atomic():
        documento, substituiu = ApplicationDocument.replace_for(
            application=inscricao, kind=kind, file=file
        )
        audit.record(
            "scholarships.application.document_upload",
            request=request,
            target=inscricao,
            document_id=documento.pk,
            kind=str(kind),
            filename=file.name,
            replaced=substituiu,
        )
    return Status(200 if substituiu else 201, documento)


@router.get("/documents/{int:document_id}/download")
def download_application_document(request: HttpRequest, document_id: int):
    """Entrega o arquivo — pelo Django, nunca por URL direta do MEDIA.

    Duas portas, e só duas: `download_applicationdocument` (Secretaria e
    Comissão de Bolsas) e o próprio candidato por posse. Quem apenas
    enxerga a inscrição — a Coordenação, que só acompanha — leva 403
    aqui: laudo de vulnerabilidade e contracheque não são insumo de
    acompanhamento. Mesmo desenho do download de `RequestDocument`
    (`apps/academic/router.py`).

    A permissão ampla é checada só depois da posse porque ela é a
    exceção, e não a regra: o dono do documento não precisa de permissão
    de secretaria para ler o que ele mesmo enviou.
    """
    require_perm(request, "scholarships.view_scholarshipapplication")
    program: Program = current_program(request)
    documento = get_object_or_404(
        ApplicationDocument.objects.for_program(program).select_related(
            "application__student"
        ),
        pk=document_id,
    )
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    if not pessoas.filter(pk=documento.application.student.person_id).exists():
        require_perm(request, "scholarships.download_applicationdocument")

    with transaction.atomic():
        # Auditar leitura é exceção no projeto e aqui é obrigatório: é o
        # acesso ao documento pessoal de outro candidato.
        audit.record(
            "scholarships.application.document_download",
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
# Lançamentos do barema
# ---------------------------------------------------------------------------
#
# O comprovante vem **no mesmo POST** (multipart), e não em um segundo
# passo: sem comprovante o lançamento não existe (Q11), então um lançamento
# vazio à espera de anexo seria um estado que o domínio não reconhece — e
# que a comissão acabaria recebendo para analisar.
#
# `candidate_score` é gravado pelo servidor (`item.raw_score(quantity)`) e
# não existe no schema de entrada: aceitá-lo do corpo deixaria o candidato
# escolher a própria nota. `committee_score` e `committee_note` também
# ficam de fora — são da rota de avaliação (f13), com permissão própria.


def _lancamentos(program: Program):
    return BaremeEntry.objects.for_program(program).select_related(
        # `application__edition` porque a avaliação cobra o estado da
        # edição (`ensure_committee_can_review`): sem ele é uma consulta a
        # mais por lançamento avaliado.
        "item",
        "application__edition",
        "application__student__person",
    )


def _garantir_acesso_a_inscricao(
    request: HttpRequest, inscricao: ScholarshipApplication, program: Program
) -> None:
    """Quem não é o dono da inscrição precisa da permissão ampla.

    `view_baremeentry` sozinha não serve de porteiro: o papel Discente
    também a tem (é com ela que o candidato lê os próprios lançamentos),
    então uma checagem só de permissão abriria o barema de um candidato
    para todos os outros do programa.

    A permissão que de fato marca "pode ver o material de candidato
    alheio" é `download_applicationdocument` — Secretaria e Comissão de
    Bolsas a têm, a Coordenação não. É a mesma linha do download do
    comprovante do questionário, e pelo mesmo motivo: acompanhar o edital
    não é ler a papelada de cada candidato.
    """
    pessoas = Person.objects.active().filter(user=request.user, program=program)
    if pessoas.filter(pk=inscricao.student.person_id).exists():
        return
    require_perm(request, "scholarships.download_applicationdocument")


@router.get(
    "/applications/{int:application_id}/entries/", response=list[BaremeEntryOut]
)
def list_entries(request: HttpRequest, application_id: int):
    """Os lançamentos de uma inscrição, na ordem do barema.

    Sem paginação, de propósito: a tela do candidato e a da comissão
    mostram o barema inteiro de uma vez, agrupado por seção, e uma
    segunda página quebraria o agrupamento — são dezenas de linhas, não
    milhares.
    """
    require_perm(request, "scholarships.view_baremeentry")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    _garantir_acesso_a_inscricao(request, inscricao, program)
    return list(_lancamentos(program).for_application(inscricao))


@router.post(
    "/applications/{int:application_id}/entries/", response={201: BaremeEntryOut}
)
def create_entry(
    request: HttpRequest,
    application_id: int,
    payload: BaremeEntryIn = Form(...),
    proof: UploadedFile = File(...),
):
    """O candidato lança uma linha do barema, com o comprovante junto.

    O arquivo é obrigatório na assinatura: faltando, o Ninja devolve 422
    antes de qualquer regra — e é exatamente a resposta certa, porque
    "lançamento sem comprovante" não é um estado a ser recusado pelo
    domínio, é um corpo incompleto.

    Repetir o mesmo item é normal e não é duplicata: dois semestres de
    docência são duas linhas, e é a soma delas que enfrenta o teto do
    item. Por isso não há guarda de unicidade aqui.
    """
    require_perm(request, "scholarships.add_baremeentry")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    inscricao.ensure_editable(request.user)
    BaremeEntry.validate_upload(filename=proof.name or "", size=proof.size or 0)
    # 404 e não `bareme_item_mismatch`: id de outro programa não existe
    # aqui. O item de outra edição ou de outro nível **existe** no
    # programa, e esse é o caso que o `clean()` recusa com o código.
    item = get_object_or_404(
        BaremeItem.objects.for_program(program), pk=payload.item_id
    )
    lancamento = BaremeEntry(
        application=inscricao,
        item=item,
        description=payload.description,
        quantity=payload.quantity,
        # A nota do candidato é derivada, nunca digitada.
        candidate_score=item.raw_score(payload.quantity),
        proof=proof,
    )
    with transaction.atomic():
        lancamento.clean()
        lancamento.save()
        audit.record(
            "scholarships.entry.create",
            request=request,
            target=lancamento,
            program=program,
            application_id=inscricao.pk,
            item_id=item.pk,
            quantity=str(lancamento.quantity),
            candidate_score=str(lancamento.candidate_score),
        )
    return Status(201, lancamento)


@router.patch(
    "/applications/{int:application_id}/entries/{int:entry_id}/",
    response=BaremeEntryOut,
)
def update_entry(
    request: HttpRequest,
    application_id: int,
    entry_id: int,
    payload: BaremeEntryPatch,
):
    """Retificação do lançamento pelo candidato, na janela aberta.

    JSON, e não multipart como o POST: **o Django só monta `request.POST`
    e `request.FILES` em requisição POST** (`HttpRequest
    ._load_post_and_files`), então um corpo multipart em PATCH chegaria
    vazio ao Ninja, sem erro nenhum. Trocar o comprovante tem rota
    própria (`POST .../proof`), pelo mesmo motivo pelo qual anexar o
    comprovante do questionário também é um POST.

    Trocar item ou quantidade **recalcula** `candidate_score`: a nota é
    derivada, e deixá-la para trás daria ao candidato uma pontuação que
    não corresponde ao que ele lançou.
    """
    require_perm(request, "scholarships.change_baremeentry")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    lancamento = get_object_or_404(
        _lancamentos(program).for_application(inscricao), pk=entry_id
    )
    inscricao.ensure_editable(request.user)

    dados = payload.model_dump(exclude_unset=True)
    campos: list[str] = []
    if "item_id" in dados:
        lancamento.item = get_object_or_404(
            BaremeItem.objects.for_program(program), pk=dados["item_id"]
        )
        campos.append("item")
    for campo in ("description", "quantity"):
        if campo in dados:
            setattr(lancamento, campo, dados[campo])
            campos.append(campo)
    if "item" in campos or "quantity" in campos:
        lancamento.candidate_score = lancamento.item.raw_score(lancamento.quantity)
        campos.append("candidate_score")

    with transaction.atomic():
        lancamento.clean()
        lancamento.save(update_fields=[*campos, "updated_at"] if campos else None)
        audit.record(
            "scholarships.entry.update",
            request=request,
            target=lancamento,
            program=program,
            application_id=inscricao.pk,
            fields=sorted(campos),
            candidate_score=str(lancamento.candidate_score),
        )
    return lancamento


@router.post(
    "/applications/{int:application_id}/entries/{int:entry_id}/proof",
    response=BaremeEntryOut,
)
def replace_entry_proof(
    request: HttpRequest,
    application_id: int,
    entry_id: int,
    proof: UploadedFile = File(...),
):
    """Troca o comprovante de um lançamento já feito.

    Existe porque o `PATCH` não pode ser multipart (ver a docstring dele)
    e porque mandar o candidato apagar e relançar para corrigir a página
    errada do certificado perderia a linha inteira.

    Substitui, e não empilha: o comprovante é um por lançamento
    (`FileField`, não relação), e o arquivo antigo sai do storage — mas
    só depois do commit, porque apagar arquivo não participa do rollback.
    """
    require_perm(request, "scholarships.change_baremeentry")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    lancamento = get_object_or_404(
        _lancamentos(program).for_application(inscricao), pk=entry_id
    )
    inscricao.ensure_editable(request.user)
    BaremeEntry.validate_upload(filename=proof.name or "", size=proof.size or 0)

    anterior = lancamento.proof.name
    lancamento.proof = proof
    with transaction.atomic():
        lancamento.save(update_fields=["proof", "updated_at"])
        audit.record(
            "scholarships.entry.proof_replace",
            request=request,
            target=lancamento,
            program=program,
            application_id=inscricao.pk,
            filename=proof.name,
        )
    if anterior and anterior != lancamento.proof.name:
        lancamento.proof.storage.delete(anterior)
    return lancamento


@router.delete(
    "/applications/{int:application_id}/entries/{int:entry_id}/",
    response={204: None},
)
def remove_entry(request: HttpRequest, application_id: int, entry_id: int):
    """O candidato apaga um lançamento que fez, na janela aberta.

    Exige `change_baremeentry`, e não `delete_`: nenhum papel de domínio
    recebe `delete_*` (migration `0008_papeis_da_bolsa`, com teste
    guardando), mesmo precedente do DELETE da inscrição, do barema e da
    comissão.

    O arquivo sai do storage junto, porque o `delete()` do model não o
    faz; e a auditoria é gravada **antes**, porque depois a instância
    perde o pk e o alvo do registro sairia vazio.
    """
    require_perm(request, "scholarships.change_baremeentry")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    lancamento = get_object_or_404(
        _lancamentos(program).for_application(inscricao), pk=entry_id
    )
    inscricao.ensure_editable(request.user)
    with transaction.atomic():
        audit.record(
            "scholarships.entry.remove",
            request=request,
            target=lancamento,
            program=program,
            application_id=inscricao.pk,
            item_id=lancamento.item_id,
        )
        lancamento.proof.delete(save=False)
        lancamento.delete()
    return Status(204, None)


@router.get("/entries/{int:entry_id}/proof/download")
def download_entry_proof(request: HttpRequest, entry_id: int):
    """Entrega o comprovante do lançamento — pelo Django, nunca por URL
    direta do MEDIA.

    Sem esta rota o comprovante seria inalcançável: `BaremeEntryOut` não
    publica caminho nem URL, justamente porque o Nginx serve o MEDIA sem
    passar pelo Django. E é o comprovante que a comissão lê para decidir
    a nota — é o insumo central da análise (f13).

    Mesmas duas portas do comprovante do questionário: o dono por posse e
    quem tem `download_applicationdocument`. Leitura auditada, porque é
    documento pessoal de outro candidato.
    """
    require_perm(request, "scholarships.view_baremeentry")
    program: Program = current_program(request)
    lancamento = get_object_or_404(_lancamentos(program), pk=entry_id)
    _garantir_acesso_a_inscricao(request, lancamento.application, program)

    with transaction.atomic():
        audit.record(
            "scholarships.entry.proof_download",
            request=request,
            target=lancamento,
            program=program,
            application_id=lancamento.application_id,
        )
    return FileResponse(
        lancamento.proof.open("rb"),
        as_attachment=True,
        filename=Path(lancamento.proof.name or "").name,
    )


# ---------------------------------------------------------------------------
# Fila de análise da comissão
# ---------------------------------------------------------------------------
#
# A fila é a tela de trabalho da comissão, e por isso o `level` é
# **obrigatório**: a classificação corre por nível, e uma fila que mistura
# mestrado e doutorado não é a fila de ninguém — é uma lista que precisa
# ser separada à mão antes de servir para alguma coisa. Faltando o
# parâmetro, o Ninja devolve 422.
#
# O recorte de quem vê o quê é `ScholarshipApplicationQuerySet.visible_to`:
# `view_scholarshipapplication` diz que a pessoa acompanha inscrição, não
# QUAIS inscrições — o Discente também a tem, é com ela que lê a própria.


@router.get(
    "/editions/{int:edition_id}/applications/",
    response=list[ScholarshipApplicationQueueOut],
)
@paginate
def list_applications(
    request: HttpRequest,
    edition_id: int,
    level: ScholarshipLevel,
    research_line_id: int | None = None,
    advisor_id: int | None = None,
    admission_year: int | None = None,
    has_paid_activity: bool | None = None,
    affirmative_action: bool | None = None,
    socioeconomic_vulnerability: bool | None = None,
    substitute_teacher: bool | None = None,
    basic_education_or_collective_health: bool | None = None,
    public_service: bool | None = None,
    private_service: bool | None = None,
    other_non_public_scholarship: bool | None = None,
    appeal: AppealState | None = None,
    pending_review: bool | None = None,
):
    """A fila de trabalho da comissão, com os filtros do legado.

    Paginada de propósito: cada linha lê os lançamentos da inscrição para
    somar as duas notas (o teto é do item, aplicado sobre a soma dos
    lançamentos daquele item — não há SQL de uma consulta só que faça
    isso), e uma edição inteira sem página seria uma consulta por
    candidato.

    Os oito booleanos são as oito respostas do questionário.
    `cadastro_unico` fica de fora porque não é pergunta de faixa e sim
    critério de desempate (ver o campo no model): filtrar a fila por ele
    não é trabalho da análise.
    """
    require_perm(request, "scholarships.view_scholarshipapplication")
    program: Program = current_program(request)
    edicao = _edicao_do_programa(request, edition_id)
    inscricoes = (
        ScholarshipApplication.objects.for_program(program)
        .for_edition(edicao)
        .for_level(level)
        # Duas camadas, nesta ordem: o tenant primeiro (não é opcional) e o
        # papel depois.
        .visible_to(request.user, program)
        .select_related(
            "edition",
            "student__person",
            "student__advisor__person",
            "student__project__research_line",
            "appeal",
        )
        .prefetch_related("documents")
    )
    # Filtros de conveniência da tela. Nenhum deles é escopo de tenant —
    # esse já foi aplicado acima e não é opcional.
    filtros = {
        "student__project__research_line_id": research_line_id,
        "student__advisor_id": advisor_id,
        "student__admission_date__year": admission_year,
        "has_paid_activity": has_paid_activity,
        "affirmative_action": affirmative_action,
        "socioeconomic_vulnerability": socioeconomic_vulnerability,
        "substitute_teacher": substitute_teacher,
        "basic_education_or_collective_health": basic_education_or_collective_health,
        "public_service": public_service,
        "private_service": private_service,
        "other_non_public_scholarship": other_non_public_scholarship,
    }
    inscricoes = inscricoes.filter(
        **{campo: valor for campo, valor in filtros.items() if valor is not None}
    )
    if appeal is not None:
        inscricoes = inscricoes.with_appeal_state(appeal)
    if pending_review is not None:
        inscricoes = inscricoes.pending_review(pending_review)
    return inscricoes


@router.patch("/entries/{int:entry_id}/review", response=BaremeEntryOut)
def review_entry(request: HttpRequest, entry_id: int, payload: BaremeEntryReviewIn):
    """A comissão pontua um lançamento.

    Permissão própria (`review_baremeentry`), separada de
    `change_baremeentry` justamente porque o candidato tem esta última
    sobre o próprio lançamento: uma permissão só para as duas coisas
    juntaria "corrigir o que digitei" com "decidir quanto vale".

    O schema de entrada tem **dois campos** e nenhum deles é do candidato
    — é o contrato, e não uma checagem, que impede a comissão de reescrever
    quantidade ou descrição. A janela (`under_review` e
    `appeals_under_review`) e a observação obrigatória na divergência são
    do model.
    """
    require_perm(request, "scholarships.review_baremeentry")
    program: Program = current_program(request)
    lancamento = get_object_or_404(_lancamentos(program), pk=entry_id)
    lancamento.review(
        committee_score=payload.committee_score,
        committee_note=payload.committee_note,
        at=timezone.now(),
    )
    with transaction.atomic():
        lancamento.clean()
        lancamento.save(
            update_fields=[
                "committee_score",
                "committee_note",
                "reviewed_at",
                "updated_at",
            ]
        )
        audit.record(
            "scholarships.entry.review",
            request=request,
            target=lancamento,
            program=program,
            application_id=lancamento.application_id,
            item_id=lancamento.item_id,
            candidate_score=str(lancamento.candidate_score),
            committee_score=str(lancamento.committee_score),
        )
    return lancamento


@router.get(
    "/applications/{int:application_id}/item-reviews/", response=list[ItemReviewOut]
)
def list_item_reviews(request: HttpRequest, application_id: int):
    """As observações por item de uma inscrição.

    Sem esta rota o `PUT` seria escrita sem leitura: a tela da análise
    precisa mostrar o que a comissão já comentou para poder retificar, e
    o candidato precisa ler o comentário para poder recorrer dele — é a
    mesma razão pela qual `committee_note` já viaja no lançamento.
    """
    require_perm(request, "scholarships.view_itemreview")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    _garantir_acesso_a_inscricao(request, inscricao, program)
    return list(
        ItemReview.objects.for_program(program)
        .for_application(inscricao)
        .select_related("item")
    )


@router.put("/applications/{int:application_id}/item-review", response=ItemReviewOut)
def set_item_review(request: HttpRequest, application_id: int, payload: ItemReviewIn):
    """Grava a observação da comissão sobre um item do barema.

    `PUT` e não `POST` porque a observação é uma por (inscrição, item):
    reenviar sobrescreve o texto, e não empilha um segundo comentário que
    deixaria o candidato adivinhando qual vale. Por isso responde 200
    também na primeira vez — o recurso identificado pela chave existe a
    partir do momento em que se escreve nele.

    Exige `review_baremeentry`, a mesma permissão da nota: comentar o item
    é parte do ato de analisar, e um papel que comentasse sem poder
    pontuar não existe no edital.
    """
    require_perm(request, "scholarships.review_baremeentry")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    inscricao.edition.ensure_committee_can_review()
    # 404 e não `bareme_item_mismatch`: id de outro programa não existe
    # aqui. O item de outra edição ou de outro nível **existe** no
    # programa, e esse é o caso que o `clean()` recusa com o código.
    item = get_object_or_404(
        BaremeItem.objects.for_program(program), pk=payload.item_id
    )
    observacao = (
        ItemReview.objects.for_program(program)
        .for_application(inscricao)
        .filter(item=item)
        .first()
    )
    if observacao is None:
        observacao = ItemReview(application=inscricao, item=item)
    observacao.note = payload.note
    with transaction.atomic():
        observacao.clean()
        observacao.save()
        audit.record(
            "scholarships.item_review.set",
            request=request,
            target=observacao,
            program=program,
            application_id=inscricao.pk,
            item_id=item.pk,
        )
    return observacao


# ---------------------------------------------------------------------------
# Lançamentos da Secretaria na inscrição alheia
# ---------------------------------------------------------------------------
#
# Os dois únicos campos que alguém escreve na inscrição de outra pessoa, e
# cada um com a sua permissão (`set_fump_level`, `override_band`). Dar
# `change_scholarshipapplication` à Secretaria para isso abriria o
# questionário inteiro do candidato à edição de quem não o respondeu —
# por isso o `PATCH /applications/{id}/` continua sendo só do dono.
#
# Os dois são decisão sobre a vida acadêmica: o `AuditLog` grava o valor
# **anterior** e o novo, porque "qual era a faixa antes de a secretaria
# mexer" é a pergunta que se faz depois, e sem o anterior o rastro não a
# responde.


@router.patch(
    "/applications/{int:application_id}/fump", response=ScholarshipApplicationOut
)
def set_fump_level(request: HttpRequest, application_id: int, payload: FumpLevelIn):
    """A Secretaria transcreve o nível da FUMP do candidato.

    Sem guarda de estado de propósito: o resultado da FUMP chega fora do
    sistema e no calendário dela, não no da edição — travá-lo por status
    obrigaria a secretaria a reabrir a edição para digitar um dado que
    ela recebeu por e-mail.
    """
    require_perm(request, "scholarships.set_fump_level")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    anterior = inscricao.fump_level
    inscricao.fump_level = payload.fump_level
    with transaction.atomic():
        inscricao.clean()
        inscricao.save(update_fields=["fump_level", "updated_at"])
        audit.record(
            "scholarships.application.set_fump_level",
            request=request,
            target=inscricao,
            edition_id=inscricao.edition_id,
            student_id=inscricao.student_id,
            previous_fump_level=anterior,
            fump_level=inscricao.fump_level,
        )
    return inscricao


@router.patch(
    "/applications/{int:application_id}/band", response=ScholarshipApplicationOut
)
def override_band(request: HttpRequest, application_id: int, payload: BandOverrideIn):
    """A Secretaria sobrescreve a faixa de prioridade, com justificativa.

    A justificativa vazia é recusada pelo `clean()` do model
    (`override_reason_required`) — a regra é do domínio, não da borda.
    Enviar `band_override: null` limpa a sobrescrita, e a faixa volta a
    ser a derivada do questionário.
    """
    require_perm(request, "scholarships.override_band")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    anterior = inscricao.band_override
    inscricao.band_override = payload.band_override
    inscricao.band_override_reason = payload.band_override_reason
    with transaction.atomic():
        inscricao.clean()
        inscricao.save(
            update_fields=["band_override", "band_override_reason", "updated_at"]
        )
        audit.record(
            "scholarships.application.override_band",
            request=request,
            target=inscricao,
            edition_id=inscricao.edition_id,
            student_id=inscricao.student_id,
            previous_band=anterior,
            band=inscricao.band_override,
            reason=inscricao.band_override_reason,
        )
    return inscricao


# ---------------------------------------------------------------------------
# Recurso contra o resultado preliminar
# ---------------------------------------------------------------------------
#
# Duas rotas e dois papéis: o candidato interpõe (`add_scholarshipappeal`,
# só o Discente a tem) e a comissão julga (`change_scholarshipappeal`, só
# ela a tem). É a separação que faz "o aluno não julga o próprio recurso"
# ser 403 de permissão, e não uma checagem escrita à mão que alguém pode
# esquecer na rota seguinte.
#
# **Não há rota de anexo aqui, e a ausência é o edital.** O item 1.3 veta
# postagem de documento fora do prazo de inscrição — ver a docstring de
# `ScholarshipAppeal`.
#
# O deferimento também não dispara recálculo: a nota da inscrição é
# derivada dos lançamentos, e `committee_can_review()` já vale em
# `appeals_under_review`. Deferir é decidir; refazer o lançamento atacado
# é o ato seguinte da comissão, pela rota de avaliação que já existe.


def _recursos(program: Program):
    return ScholarshipAppeal.objects.for_program(program).select_related(
        # `application__edition` porque as duas escritas cobram o estado da
        # edição (`ensure_appealable`, `judge`).
        "application__edition",
        "application__student__person",
    )


@router.post(
    "/applications/{int:application_id}/appeal", response={201: ScholarshipAppealOut}
)
def create_appeal(
    request: HttpRequest, application_id: int, payload: ScholarshipAppealIn
):
    """O candidato interpõe recurso contra o resultado preliminar.

    A guarda é do model (`ensure_appealable`): fase fechada é 409
    `appeals_closed`, inscrição alheia é 403 `not_application_owner`, e o
    segundo recurso é 400 `duplicate_appeal` do `clean()`. Publicar o
    preliminar não abre a fase — quem abre é `open_appeals()`, e é por
    isso que a janela é conferida pelo estado e não pela data.
    """
    require_perm(request, "scholarships.add_scholarshipappeal")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    inscricao.ensure_appealable(request.user)
    recurso = ScholarshipAppeal(application=inscricao, text=payload.text)
    with transaction.atomic():
        recurso.clean()
        recurso.save()
        audit.record(
            "scholarships.appeal.create",
            request=request,
            target=recurso,
            program=program,
            edition_id=inscricao.edition_id,
            application_id=inscricao.pk,
            student_id=inscricao.student_id,
        )
    return Status(201, recurso)


@router.get("/applications/{int:application_id}/appeal", response=ScholarshipAppealOut)
def get_appeal(request: HttpRequest, application_id: int):
    """O recurso de uma inscrição, para a tela da comissão e a do dono.

    404 quando não há recurso — "não recorreu" é o caso normal, e é assim
    que a tela sabe que deve oferecer o formulário em branco. Quem não é
    o dono passa pelo mesmo porteiro dos lançamentos
    (`_garantir_acesso_a_inscricao`): `view_scholarshipappeal` sozinha não
    serve, porque o Discente também a tem — é com ela que lê o próprio.
    """
    require_perm(request, "scholarships.view_scholarshipappeal")
    program: Program = current_program(request)
    inscricao = get_object_or_404(_inscricoes(program), pk=application_id)
    _garantir_acesso_a_inscricao(request, inscricao, program)
    recurso = inscricao.submitted_appeal()
    if recurso is None:
        raise Http404("Esta inscrição não tem recurso interposto.")
    return recurso


@router.patch("/appeals/{int:appeal_id}/judge", response=ScholarshipAppealOut)
def judge_appeal(
    request: HttpRequest, appeal_id: int, payload: ScholarshipAppealJudgeIn
):
    """A comissão julga o recurso, com fundamentação.

    Rota nomeada pelo ato, e não um `PATCH` de `outcome`: julgar é
    transição, e o model a cobra (fase aberta, recurso ainda não julgado,
    fundamentação não vazia). O instante vai explícito, como nas demais
    transições deste app.
    """
    require_perm(request, "scholarships.change_scholarshipappeal")
    program: Program = current_program(request)
    recurso = get_object_or_404(_recursos(program), pk=appeal_id)
    recurso.judge(
        outcome=payload.outcome, reasoning=payload.reasoning, at=timezone.now()
    )
    with transaction.atomic():
        recurso.save(update_fields=["outcome", "reasoning", "decided_at", "updated_at"])
        audit.record(
            "scholarships.appeal.judge",
            request=request,
            target=recurso,
            program=program,
            edition_id=recurso.application.edition_id,
            application_id=recurso.application_id,
            student_id=recurso.application.student_id,
            outcome=recurso.outcome,
        )
    return recurso
