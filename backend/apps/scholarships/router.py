"""Borda HTTP do app scholarships, montada em /api/v1/scholarships/.

Padrão de toda rota: `require_perm` na primeira linha, `current_program`
logo depois, chamada ao model/service, schema de saída explícito. Zero
regra de negócio aqui. As rotas entram nas stories de API.

**Nenhuma rota deste módulo é pública** — ao contrário do processo
seletivo, aqui até o candidato é aluno matriculado, e portanto logado.
"""

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

from .models import (
    ApplicationDocument,
    ApplicationDocumentKind,
    BaremeItem,
    CommitteeMember,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)
from .schemas import (
    ApplicationDocumentOut,
    BaremeCloneIn,
    BaremeCloneOut,
    BaremeItemIn,
    BaremeItemOut,
    BaremeItemPatch,
    CommitteeMemberIn,
    CommitteeMemberOut,
    ScholarshipApplicationIn,
    ScholarshipApplicationOut,
    ScholarshipApplicationPatch,
    ScholarshipEditionIn,
    ScholarshipEditionOut,
    ScholarshipEditionPatch,
)
from .services import clone_bareme

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
    """Publica o resultado preliminar.

    Permissão própria `publish_scholarshipedition`, e não `change_`:
    publicar congela o ano e é o que o candidato lê como resultado — quem
    monta o edital não é necessariamente quem assina a lista.

    O corpo desta rota **vai migrar para o service de publicação** (story
    do snapshot): lá a mesma transição passa a gravar a faixa, a nota, a
    posição e a ordem de sorteio em cada inscrição, num `AuditLog` único.
    Enquanto o service não existe, a transição sozinha já é o ato — e a
    rota não muda de nome nem de contrato quando ele chegar.
    """
    return _transicionar(
        request,
        edition_id,
        perm="scholarships.publish_scholarshipedition",
        metodo="publish_preliminary",
        evento="scholarships.edition.publish_preliminary",
        campos=["status", "published_preliminary_at"],
        at=True,
    )


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
    """Publica o resultado final. Mesma nota do preliminar sobre o
    service de publicação e sobre a permissão própria."""
    return _transicionar(
        request,
        edition_id,
        perm="scholarships.publish_scholarshipedition",
        metodo="publish_final",
        evento="scholarships.edition.publish_final",
        campos=["status", "published_final_at"],
        at=True,
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
    novos = clone_bareme(source=origem, target=destino, request=request)
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
