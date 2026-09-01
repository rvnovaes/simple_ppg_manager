"""Borda HTTP do app scholarships, montada em /api/v1/scholarships/.

Padrão de toda rota: `require_perm` na primeira linha, `current_program`
logo depois, chamada ao model/service, schema de saída explícito. Zero
regra de negócio aqui. As rotas entram nas stories de API.

**Nenhuma rota deste módulo é pública** — ao contrário do processo
seletivo, aqui até o candidato é aluno matriculado, e portanto logado.
"""

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Status
from ninja.pagination import paginate

from apps.academic.models import Teacher
from apps.core import audit
from apps.core.permissions import require_perm
from apps.core.tenancy import current_program
from apps.programs.models import Program

from .models import (
    CommitteeMember,
    ScholarshipEdition,
    ScholarshipEditionStatus,
)
from .schemas import (
    CommitteeMemberIn,
    CommitteeMemberOut,
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
