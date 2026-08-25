"""Operações do app selection que cruzam mais de um model.

`publish_process` está aqui, e não no router, porque publicar não é gravar
um campo: é conferir etapas, vagas e template — três models — antes de
mudar o estado do edital, tudo na mesma transação (ADR-002).

Quem escreve aqui chama `clean()` antes de `save()`: o Django não executa
`clean()` em `.save()`/`.create()`, e sem essa chamada o invariante do
model nunca roda no caminho real.
"""

import smtplib
from datetime import datetime
from decimal import Decimal
from functools import partial
from typing import Any

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest
from django.utils import timezone
from ninja import UploadedFile

from apps.core import audit
from apps.core.exceptions import DomainError, InvalidStateTransition, NotAllowed

from .emails import enviar_convocacao, enviar_token_de_assinatura
from .models import (
    Application,
    ApplicationDocument,
    ApplicationDocumentKind,
    ApplicationStatus,
    Board,
    Convocation,
    ConvocationEmail,
    ExaminationRecord,
    RecordSignature,
    RecordStatus,
    SelectionProcess,
    SelectionStage,
    StageScore,
    Vacancy,
    gerar_protocolo,
)
from .pdf import render_record_pdf
from .schemas import ApplicationIn


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


# ---------------------------------------------------------------------------
# Inscrição pública
# ---------------------------------------------------------------------------

# Limites por IP das rotas públicas (apps.core.ratelimit). Sem sessão não
# há conta para responsabilizar: o contador é o que sobra.
LIMITE_DE_LEITURA_PUBLICA = 60
JANELA_DE_LEITURA_EM_SEGUNDOS = 60
LIMITE_DE_INSCRICAO_POR_IP = 5
JANELA_DE_INSCRICAO_EM_SEGUNDOS = 60 * 60
LIMITE_DE_CONSULTA_DE_PROTOCOLO = 20
JANELA_DE_CONSULTA_EM_SEGUNDOS = 60
# Assinatura por token: a leitura acompanha a consulta de protocolo (o
# examinador recarrega a tela enquanto confere), e a assinatura é rara —
# dez por hora cobre erro de digitação e nada mais.
LIMITE_DE_LEITURA_DE_TOKEN = 20
LIMITE_DE_ASSINATURA_POR_TOKEN = 10
JANELA_DE_ASSINATURA_EM_SEGUNDOS = 60 * 60

# Colisão de protocolo é rara (32 bits), não impossível; cinco tentativas
# tornam a falha astronômica sem virar laço infinito.
TENTATIVAS_DE_PROTOCOLO = 5


def so_digitos(texto: str) -> str:
    """O CPF chega do formulário como o candidato digitou: com ponto e
    traço, ou sem. O model guarda os onze dígitos e a unique conta com
    isso — normalizar aqui é o que impede o mesmo CPF de entrar duas vezes
    com máscaras diferentes."""
    return "".join(c for c in texto if c.isdigit())


def edital_com_inscricao_aberta(*, process_id: int, at: datetime) -> SelectionProcess:
    """Resolve o tenant da inscrição pública pelo edital, não pelo chamador.

    É o substituto de `current_program()` nas rotas públicas: sem sessão
    não há Person de onde tirar o programa. O `process_id` do corpo não
    escolhe tenant livremente — ele só seleciona entre os editais que
    estão **publicados e com a janela aberta agora**, e o programa sai do
    edital encontrado.

    Edital inexistente, em rascunho, encerrado, fora da janela ou de outro
    programa dão todos a mesma resposta: não há inscrição aberta com esse
    id. Distinguir os casos transformaria a rota num inventário dos
    editais em rascunho de todos os programas.
    """
    edital = (
        SelectionProcess.objects.open_for_submission(at)
        .filter(pk=process_id)
        .select_related("program")
        .first()
    )
    if edital is None:
        raise DomainError(
            "As inscrições deste edital não estão abertas.",
            code="submission_window_closed",
        )
    return edital


def _exigir_vaga(inscricao: Application) -> None:
    """A combinação nível × alvo × cota escolhida precisa ter vaga.

    Vaga zerada é linha da grade que existe mas não abre inscrição, e o
    model permite o zero de propósito (`f5` conta com ele na realocação) —
    por isso o filtro é `quantity__gt=0` e não a mera existência da linha.
    """
    tem_vaga = Vacancy.objects.filter(
        process_id=inscricao.process_id,
        level=inscricao.level,
        project_id=inscricao.project_id,
        research_line_id=inscricao.research_line_id,
        quota_category=inscricao.quota_category,
        quantity__gt=0,
    ).exists()
    if not tem_vaga:
        raise DomainError(
            "Não há vaga neste edital para o nível, o alvo e a categoria escolhidos.",
            code="no_vacancy_for_choice",
        )


def _salvar_com_protocolo(inscricao: Application) -> None:
    """Grava a inscrição sorteando protocolo até um não colidir.

    O `atomic()` interno é um savepoint: sem ele, o `IntegrityError` da
    unique deixaria a transação da requisição inteira quebrada e a
    tentativa seguinte falharia com "current transaction is aborted".
    """
    for _ in range(TENTATIVAS_DE_PROTOCOLO):
        inscricao.protocol = gerar_protocolo(inscricao.process)
        try:
            with transaction.atomic():
                inscricao.save()
        except IntegrityError:
            continue
        return
    raise DomainError(
        "Não foi possível gerar o protocolo da inscrição. Tente novamente.",
        code="protocol_generation_failed",
    )


@transaction.atomic
def submit_application(
    *,
    process: SelectionProcess,
    dados: ApplicationIn,
    files: dict[str, UploadedFile],
    request: HttpRequest | None = None,
) -> Application:
    """Cria a inscrição do candidato com todos os anexos, de uma vez.

    Está aqui, e não no router, porque um POST escreve em dois models
    (`Application` e de cinco a sete `ApplicationDocument`) e nenhuma
    inscrição pode existir pela metade: falhar no sexto anexo e deixar os
    cinco primeiros gravados daria ao candidato um protocolo de uma
    inscrição incompleta, que ele não tem como corrigir — não há login
    para voltar.

    A ordem das guardas é deliberada: primeiro o que não depende de
    escrita nenhuma (janela, formato dos arquivos), depois os invariantes
    do model (`clean`: CPF, alvo, cota, duplicata), depois vaga e
    documentos exigidos. Só então grava.

    O `AuditLog` sai **sem CPF, sem nome e sem e-mail**: quem audita
    precisa saber que a inscrição existiu e em qual edital, e o dado
    pessoal já está na própria inscrição, atrás de permissão.
    """
    agora = timezone.now()
    if not process.submission_open(agora):
        raise DomainError(
            "As inscrições deste edital não estão abertas.",
            code="submission_window_closed",
        )

    # Antes de qualquer escrita: arquivo recusado depois de meio lote
    # gravado deixaria órfão no storage, que não participa do rollback.
    for arquivo in files.values():
        ApplicationDocument.validate_upload(
            filename=arquivo.name or "", size=arquivo.size or 0
        )

    inscricao = Application(
        program=process.program,
        process=process,
        full_name=dados.full_name.strip(),
        email=dados.email.strip(),
        cpf=so_digitos(dados.cpf),
        birth_date=dados.birth_date,
        phone_number=dados.phone_number.strip(),
        level=dados.level,
        project_id=dados.project_id,
        research_line_id=dados.research_line_id,
        quota_category=dados.quota_category,
        submitted_at=agora,
    )
    inscricao.clean()
    _exigir_vaga(inscricao)

    exigidos = inscricao.required_document_kinds()
    faltando = inscricao.missing_documents(present=files.keys())
    if faltando:
        rotulos = ", ".join(ApplicationDocumentKind(k).label.lower() for k in faltando)
        raise DomainError(
            f"Faltam documentos obrigatórios: {rotulos}.",
            code="missing_documents",
        )

    _salvar_com_protocolo(inscricao)
    # Só os exigidos viram anexo: memorial mandado a edital regular (ou
    # comprovação de cota em inscrição de ampla concorrência) é campo que
    # a tela deixou sobrar, não documento da inscrição.
    for kind in exigidos:
        ApplicationDocument.objects.create(
            application=inscricao, kind=kind, file=files[kind]
        )
    audit.record(
        "selection.application.submit",
        request=request,
        target=inscricao,
        program=process.program,
        process_id=process.pk,
        protocol=inscricao.protocol,
        level=inscricao.level,
        quota_category=inscricao.quota_category,
        documents=exigidos,
    )
    return inscricao


# ---------------------------------------------------------------------------
# Ata da etapa
# ---------------------------------------------------------------------------
#
# As quatro funções abaixo são o ciclo de vida da ata antes da assinatura:
# gerar (rascunho), atualizar, congelar e reabrir. Estão aqui, e não no
# router, porque nenhuma delas toca um model só — congelar escreve a ata,
# cria as assinaturas e emite token; reabrir apaga assinaturas.
#
# Quem pode fazer o quê é da borda (`require_perm` + o papel na banca):
# gerar e atualizar são de qualquer titular, congelar e reabrir são do
# presidente. Estes services recebem a ata já resolvida.


def _linhas_da_ata(record: ExaminationRecord) -> tuple[list[dict[str, Any]], list[str]]:
    """As linhas da ata a partir das notas vivas, e quem ainda não tem nota.

    A ata cobre as inscrições **vivas** do nível × alvo (`alive()`), não
    as notas: quem foi eliminado numa etapa anterior não volta a aparecer,
    e quem ainda não foi avaliado precisa ser contado como pendência — é
    o que `freeze_record` cobra em `scores_incomplete`.
    """
    candidatas = Application.objects.for_process(record.process_id).for_target(
        record.level, record.project, record.research_line
    )
    anterior = getattr(record, "supersedes", None)
    if anterior is None:
        candidatas = candidatas.alive()
    else:
        # Versão retificada: as linhas são **as mesmas pessoas** que a
        # versão anterior julgou, com as notas de agora. Filtrar por
        # `alive()` deixaria de fora justamente quem a v1 eliminou — e é
        # ele que a retificação costuma existir para reintegrar.
        candidatas = candidatas.filter(
            pk__in=[linha["application_id"] for linha in anterior.content]
        )
    inscricoes = list(candidatas.order_by("full_name", "protocol"))
    notas = {
        nota.application_id: nota
        for nota in StageScore.objects.for_stage(record.stage)
        .filter(application__in=inscricoes)
        .select_related("application")
    }
    linhas: list[dict[str, Any]] = []
    faltando: list[str] = []
    for inscricao in inscricoes:
        nota = notas.get(inscricao.pk)
        if nota is None:
            faltando.append(inscricao.protocol)
        else:
            linhas.append(nota.as_record_row())
    return linhas, faltando


def _exigir_rascunho(record: ExaminationRecord) -> None:
    if not record.is_draft:
        raise InvalidStateTransition(
            "A ata precisa estar em rascunho; está "
            f"{record.get_status_display().lower()}.",
            code="record_not_draft",
        )


def _exigir_etapa_anterior_assinada(*, board: Board, stage: SelectionStage) -> None:
    """Etapa `k > 1` só abre ata depois que a `k-1` foi assinada.

    A ata assinada é o que promove e elimina candidato (`_close_stage`):
    montar a etapa 2 antes disso avaliaria gente que a etapa 1 já tinha
    eliminado, e o resultado sairia errado sem ninguém notar.
    """
    anterior = (
        board.process.stages.filter(order__lt=stage.order).order_by("-order").first()
    )
    if anterior is None:
        return
    assinada = (
        ExaminationRecord.objects.for_process(board.process_id)
        .for_key(anterior, board.level, board.project, board.research_line)
        .filter(status=RecordStatus.SIGNED)
        .exists()
    )
    if not assinada:
        raise InvalidStateTransition(
            f"A ata da etapa anterior ({anterior.name}) ainda não foi "
            "assinada; ela é o que define quem segue para esta.",
            code="previous_stage_open",
        )


def _exigir_etapa_seguinte_aberta(record: ExaminationRecord) -> None:
    """Retificar a etapa `k` exige que a `k+1` ainda não tenha congelado.

    O desfecho da etapa `k+1` foi decidido sobre quem a `k` promoveu:
    reintegrar alguém aqui depois que a etapa seguinte já fechou deixaria
    uma pessoa viva que a etapa seguinte nunca avaliou, e sem ninguém
    notar. O caminho é retificar de trás para frente — a `k+1` primeiro.
    """
    seguintes = record.process.stages.filter(order__gt=record.stage.order)
    fechada = (
        ExaminationRecord.objects.for_process(record.process_id)
        .current()
        .filter(
            stage__in=seguintes,
            level=record.level,
            project=record.project,
            research_line=record.research_line,
        )
        .exclude(status=RecordStatus.DRAFT)
        .first()
    )
    if fechada is not None:
        raise InvalidStateTransition(
            f"A ata da etapa seguinte ({fechada.stage.name}) já foi congelada; "
            "retifique-a antes desta.",
            code="next_stage_closed",
        )


@transaction.atomic
def generate_record(
    *,
    board: Board,
    stage: SelectionStage,
    request: HttpRequest | None = None,
) -> ExaminationRecord:
    """Abre a ata em rascunho da (etapa × nível × alvo) da banca.

    O `content` nasce das notas já lançadas — a ata em rascunho é a
    prévia do que a banca vai assinar, e serve justamente para conferir
    quem falta. Completá-lo é condição de `freeze_record`, não desta.

    Ata já vigente na mesma chave é `record_already_exists`, do
    `clean()` do model: uma chave tem no máximo uma ata corrente, e a
    segunda versão nasce de retificação, não de um POST repetido.
    """
    if not board.process.is_published:
        raise InvalidStateTransition(
            "A ata só existe em edital publicado.", code="process_not_published"
        )
    _exigir_etapa_anterior_assinada(board=board, stage=stage)

    ata = ExaminationRecord(
        program=board.program,
        process=board.process,
        stage=stage,
        level=board.level,
        project=board.project,
        research_line=board.research_line,
        board=board,
    )
    linhas, _faltando = _linhas_da_ata(ata)
    ata.content = ExaminationRecord.normalize_content(linhas)
    ata.clean()
    ata.save()
    audit.record(
        "selection.record.generate",
        request=request,
        target=ata,
        stage_id=stage.pk,
        board_id=board.pk,
        rows=len(ata.content),
    )
    return ata


@transaction.atomic
def refresh_record(
    *, record: ExaminationRecord, request: HttpRequest | None = None
) -> ExaminationRecord:
    """Regera o `content` do rascunho a partir das notas de agora.

    Existe porque a ata é gerada antes de a banca terminar de lançar: o
    rascunho é uma fotografia, e esta função tira outra. Depois de
    congelada a ata não se atualiza — reabre-se (`reopen_record`).
    """
    _exigir_rascunho(record)
    linhas, _faltando = _linhas_da_ata(record)
    record.content = ExaminationRecord.normalize_content(linhas)
    record.save(update_fields=["content", "updated_at"])
    audit.record(
        "selection.record.refresh",
        request=request,
        target=record,
        stage_id=record.stage_id,
        rows=len(record.content),
    )
    return record


def _enviar_token(signature_id: int, token: str, request: HttpRequest | None) -> None:
    """Envio do token, já **fora** da transação que congelou a ata.

    Roda em `transaction.on_commit`: se o SMTP cair, a ata continua
    congelada e as assinaturas continuam de pé — o que se perde é o
    aviso, e ele é reemissível (`resend_signature_token`). O contrário
    (enviar dentro do bloco) desfaria o congelamento por causa do
    servidor de e-mail, e ainda assim o e-mail poderia ter saído.

    Falha vira `token_sent_at = None` e evento próprio: é como a tela da
    secretaria descobre que precisa reenviar.
    """
    assinatura = RecordSignature.objects.select_related(
        "record__process", "record__stage", "signer__person"
    ).get(pk=signature_id)
    try:
        enviar_token_de_assinatura(assinatura, token)
    except (OSError, smtplib.SMTPException) as erro:
        assinatura.token_sent_at = None
        assinatura.save(update_fields=["token_sent_at", "updated_at"])
        audit.record(
            "selection.record.token_email_failed",
            request=request,
            target=assinatura.record,
            signature_id=assinatura.pk,
            signer_id=assinatura.signer_id,
            error=str(erro),
        )
        return
    assinatura.token_sent_at = timezone.now()
    assinatura.save(update_fields=["token_sent_at", "updated_at"])
    audit.record(
        "selection.record.token_issued",
        request=request,
        target=assinatura.record,
        signature_id=assinatura.pk,
        signer_id=assinatura.signer_id,
    )


def _emitir_token(
    signature: RecordSignature, at: datetime, request: HttpRequest | None
) -> None:
    """Emite o token da assinatura e agenda o e-mail para depois do commit."""
    token = signature.issue_token(at)
    signature.save(
        update_fields=[
            "token_hash",
            "token_expires_at",
            "token_sent_at",
            "token_used_at",
            "updated_at",
        ]
    )
    transaction.on_commit(partial(_enviar_token, signature.pk, token, request))


@transaction.atomic
def freeze_record(
    *,
    record: ExaminationRecord,
    replaced_member: Any | None = None,
    request: HttpRequest | None = None,
) -> ExaminationRecord:
    """Fecha o rascunho para assinatura: fotografia, hash e signatários.

    Congelar é o ponto sem volta editorial da etapa: daqui em diante as
    notas da chave são só leitura (`record_frozen`, na rota de notas), o
    `content_hash` é o que cada examinador confere ao assinar, e mudar
    qualquer coisa exige reabrir (enquanto ninguém assinou) ou retificar.

    Por isso a ata só congela **completa**: inscrição viva sem nota é
    `scores_incomplete`, com os protocolos na mensagem — é a lista que a
    banca precisa para terminar o trabalho.

    `replaced_member` é o titular impedido; o suplente assina no lugar
    dele (`expected_signers`). Ele entra no `canonical_document`, então
    precisa ser decidido **antes** do hash, e não depois.
    """
    record.replaced_member = replaced_member
    # Levanta `not_a_titular_member` se o impedido não for titular desta
    # banca — antes de qualquer escrita.
    signatarios = record.expected_signers()

    linhas, faltando = _linhas_da_ata(record)
    if faltando:
        raise DomainError(
            "Faltam notas nesta etapa para: " + ", ".join(faltando) + ".",
            code="scores_incomplete",
        )

    agora = timezone.now()
    record.freeze(linhas, at=agora)
    record.clean()
    record.save(
        update_fields=[
            "replaced_member",
            "content",
            "content_hash",
            "frozen_at",
            "status",
            "updated_at",
        ]
    )

    for signatario in signatarios:
        assinatura = RecordSignature.for_signer(record, signatario)
        assinatura.clean()
        assinatura.save()
        if assinatura.uses_token:
            _emitir_token(assinatura, agora, request)

    audit.record(
        "selection.record.freeze",
        request=request,
        target=record,
        stage_id=record.stage_id,
        replaced_member_id=record.replaced_member_id,
        content_hash=record.content_hash,
        signers=[s.pk for s in signatarios],
    )
    return record


@transaction.atomic
def reopen_record(
    *, record: ExaminationRecord, request: HttpRequest | None = None
) -> ExaminationRecord:
    """Volta a ata congelada para rascunho, se ninguém assinou ainda.

    Uma assinatura dada já é declaração de um examinador sobre um
    conteúdo: reabrir depois disso apagaria a declaração dele sem que ele
    soubesse (`record_has_signatures`). Nesse caso o caminho é a
    retificação, que cria a versão `n+1` e preserva a anterior.

    É o **único `delete` do app**, e ele só alcança assinatura pendente —
    linha que nunca significou nada além de "falta este aqui".
    """
    if record.signatures.filter(signed_at__isnull=False).exists():
        raise InvalidStateTransition(
            "Esta ata já tem assinatura; para corrigi-la, retifique-a "
            "com uma versão nova.",
            code="record_has_signatures",
        )
    record.reopen()
    record.save(update_fields=["status", "content_hash", "frozen_at", "updated_at"])
    apagadas, _detalhe = record.signatures.all().delete()
    audit.record(
        "selection.record.reopen",
        request=request,
        target=record,
        stage_id=record.stage_id,
        deleted_signatures=apagadas,
    )
    return record


# ---------------------------------------------------------------------------
# Assinatura e fechamento da etapa
# ---------------------------------------------------------------------------
#
# A terceira assinatura é o que fecha a etapa: é ela que promove, elimina
# e aprova candidato. Nada disso acontece no congelamento — enquanto a ata
# não está assinada por todos, ela é só uma proposta da banca.
#
# Duas travas moram aqui, e não na borda:
#
#   1. `select_for_update()` na ata ANTES de contar as assinaturas. Duas
#      assinaturas simultâneas leriam "faltam 2" e "faltam 2" e a etapa
#      nunca fecharia — ou, pior, leriam "faltam 0" as duas e o
#      fechamento rodaria duas vezes.
#   2. Tudo num `atomic` só: marcar assinada, aplicar desfecho e gravar o
#      PDF. Um PDF sem os desfechos aplicados (ou o contrário) é ata que
#      não corresponde ao que o sistema fez.


def _desfechos_anteriores(record: ExaminationRecord) -> dict[int, bool] | None:
    """Como a versão anterior da ata classificou cada inscrição.

    `None` na versão 1: não há anterior, então todo desfecho é novo. Nas
    seguintes, o dicionário é o que permite re-sincronizar **só quem
    mudou** — reaplicar a ata inteira reeliminaria quem já estava
    eliminado e explodiria em `application_not_homologated`.
    """
    anterior = getattr(record, "supersedes", None)
    if anterior is None:
        return None
    return {
        int(linha["application_id"]): bool(linha["passed"])
        for linha in anterior.content
    }


def _aplicar_desfecho(
    *,
    inscricao: Application,
    stage: SelectionStage,
    passou: bool,
    nota: Decimal | None,
    ultima_etapa: bool,
) -> str:
    """Leva a inscrição ao estado que a linha da ata determina.

    Devolve o que aconteceu (`promoted`/`eliminated`/`approved`) para o
    payload da auditoria. Reprovar quem a versão anterior aprovou passa
    por `revoke_approval`; promover quem ela eliminou, por `reinstate`.
    """
    if not passou:
        if inscricao.status == ApplicationStatus.APPROVED:
            inscricao.revoke_approval()
        inscricao.eliminate(stage)
        inscricao.save()
        return "eliminated"

    if inscricao.status == ApplicationStatus.ELIMINATED:
        inscricao.reinstate()
    if not ultima_etapa:
        # Passar numa etapa intermediária não muda o status: seguir vivo
        # já é a promoção, e ela deriva da ata assinada.
        inscricao.save()
        return "promoted"

    if inscricao.status == ApplicationStatus.APPROVED:
        # Retificação que só mexeu na nota: reaprova com a nota nova.
        inscricao.revoke_approval()
    inscricao.approve(nota if nota is not None else Decimal(0))
    inscricao.save()
    return "approved"


def _close_stage(
    record: ExaminationRecord, request: HttpRequest | None = None
) -> ExaminationRecord:
    """Fecha a etapa: ata assinada, desfechos aplicados e PDF gravado.

    Chamado pela última assinatura (por login ou por token), já dentro da
    transação dela. O que vale é o `content` congelado, não as notas de
    agora: é o `content` que o `content_hash` cobre e que os examinadores
    assinaram.
    """
    agora = timezone.now()
    record.mark_signed(agora)
    record.save(update_fields=["status", "signed_at", "updated_at"])

    antes = _desfechos_anteriores(record)
    ultima = record.stage.is_last
    inscricoes = {
        inscricao.pk: inscricao
        for inscricao in Application.objects.filter(
            pk__in=[linha["application_id"] for linha in record.content]
        )
    }
    resultado: dict[str, list[int]] = {
        "promoted": [],
        "eliminated": [],
        "approved": [],
    }
    for linha in record.content:
        inscricao = inscricoes.get(int(linha["application_id"]))
        if inscricao is None:  # pragma: no cover - linha órfã não existe
            continue
        passou = bool(linha["passed"])
        nota = None if linha["score"] is None else Decimal(str(linha["score"]))
        # Desfecho igual ao da versão anterior: nada a re-sincronizar, a
        # não ser que a nota final da última etapa tenha mudado.
        repetido = antes is not None and antes.get(inscricao.pk) == passou
        nota_final_mudou = ultima and passou and inscricao.final_score != nota
        if repetido and not nota_final_mudou:
            continue
        acao = _aplicar_desfecho(
            inscricao=inscricao,
            stage=record.stage,
            passou=passou,
            nota=nota,
            ultima_etapa=ultima,
        )
        resultado[acao].append(inscricao.pk)

    anterior = getattr(record, "supersedes", None)
    if anterior is not None and anterior.status == RecordStatus.SIGNED:
        # A retificação pode já ter substituído a anterior ao criar esta
        # versão — o `clean()` da ata não admite duas correntes na mesma
        # chave, então a v2 em rascunho só existe com a v1 já substituída.
        anterior.supersede()
        anterior.save(update_fields=["status", "updated_at"])

    record.pdf.save(
        f"ata-{record.pk}-v{record.version}.pdf",
        ContentFile(render_record_pdf(record)),
        save=True,
    )

    audit.record(
        "selection.stage.close",
        request=request,
        target=record,
        stage_id=record.stage_id,
        version=record.version,
        superseded_id=None if anterior is None else anterior.pk,
        promoted=resultado["promoted"],
        eliminated=resultado["eliminated"],
        approved=resultado["approved"],
    )
    return record


def _assinatura_do_usuario(record: ExaminationRecord, user: Any) -> RecordSignature:
    """A linha de assinatura desta ata que pertence ao usuário logado.

    Quem não é signatário não recebe 404 — a ata existe e ele até pode
    lê-la se compõe a banca; o que ele não pode é assinar por outro.
    """
    assinatura = (
        record.signatures.select_related("signer__person")
        .filter(signer__person__user=user)
        .first()
    )
    if assinatura is None:
        raise NotAllowed("Você não é signatário desta ata.", code="not_the_signer")
    # A instância travada é a que conta: `sign()` confere o hash pela
    # `record` da própria assinatura.
    assinatura.record = record
    return assinatura


@transaction.atomic
def sign_record(
    *,
    record: ExaminationRecord,
    user: Any,
    ip: str | None = None,
    content_hash: str = "",
    request: HttpRequest | None = None,
) -> ExaminationRecord:
    """Assina a ata como o professor logado; na última, fecha a etapa.

    `content_hash` é o hash que a tela mostrou. Vazio significa "assino o
    que está aí agora"; preenchido e diferente do corrente vira
    `record_changed` — é como o presidente que reabriu e recongelou a ata
    entre a leitura e o clique não colhe assinatura sobre texto velho.
    """
    # `select_for_update()` sem `select_related`: o Postgres recusa
    # `FOR UPDATE` sobre o lado nulável de um outer join, e `supersedes`,
    # `project` e `research_line` são todos nuláveis.
    ata = ExaminationRecord.objects.select_for_update().get(pk=record.pk)
    assinatura = _assinatura_do_usuario(ata, user)
    assinatura.ensure_can_sign_by_login(user)

    agora = timezone.now()
    assinatura.sign(agora, content_hash or ata.content_hash, user=user, ip=ip)
    assinatura.save(
        update_fields=[
            "signed_at",
            "signed_hash",
            "signed_by_user",
            "ip_address",
            "updated_at",
        ]
    )
    audit.record(
        "selection.record.sign",
        request=request,
        target=ata,
        stage_id=ata.stage_id,
        signature_id=assinatura.pk,
        signer_id=assinatura.signer_id,
        method=assinatura.method,
    )

    if not ata.signatures.pending().exists():
        _close_stage(ata, request=request)
    return ata


# ---------------------------------------------------------------------------
# Assinatura por token (examinador externo, sem conta)
# ---------------------------------------------------------------------------
#
# O examinador externo compõe a banca mas não é da instituição: não tem
# conta, e criar uma para ele assinar uma ata seria pedir cadastro a quem
# passa por aqui uma vez. O que substitui a sessão é o token que saiu por
# e-mail no congelamento — pessoal, de uso único e com prazo.
#
# Três cuidados que valem para as duas funções daqui:
#
#   1. **O texto do token nunca é gravado.** O banco guarda só o sha256
#      (`hash_do_token`); quem lê a tabela não assina por ninguém. O
#      lookup é sempre `RecordSignature.objects.by_token(raw)`.
#   2. **Nada distingue os casos ruins.** Token inexistente, de outro
#      programa, já assinado ou de ata reaberta dão o mesmo 404 na
#      leitura — a rota é pública, e responder diferente para cada um a
#      transformaria num oráculo para quem chuta link.
#   3. **A auditoria leva `program=` explícito** (armadilha 12): não há
#      sessão de onde tirar tenant, e sem a chave o AuditLog fica órfão.


def assinatura_por_token(*, token: str, at: datetime) -> RecordSignature:
    """A assinatura pendente que o token em texto abre, ou 404 genérico.

    É o `edital_com_inscricao_aberta` desta rota: o tenant sai do que o
    token encontrou, e não de nada que o chamador escolha. Só passa
    assinatura pendente, com token no prazo e ata ainda aguardando
    assinaturas — as três condições da tela de conferência.
    """
    assinatura = (
        RecordSignature.objects.by_token(token)
        .select_related(
            "record__process",
            "record__stage",
            "record__project",
            "record__research_line",
            "signer__person",
        )
        .first()
    )
    if (
        assinatura is None
        or assinatura.is_signed
        or not assinatura.token_valid_at(at)
        or assinatura.record.status != RecordStatus.AWAITING_SIGNATURES
    ):
        raise Http404("Link de assinatura inválido ou expirado.")
    return assinatura


@transaction.atomic
def sign_record_with_token(
    *,
    token: str,
    ip: str | None = None,
    content_hash: str = "",
    request: HttpRequest | None = None,
) -> ExaminationRecord:
    """Assina a ata pelo link do e-mail; na última assinatura, fecha a etapa.

    Aqui o token vale por identidade **e** por autorização: quem o tem é
    o examinador a quem ele foi mandado, e ele só serve para esta ata.
    Por isso `consume_token` e `sign` acontecem na mesma transação — o
    token queima exatamente quando a assinatura entra, e não antes.

    Ao contrário da leitura, os casos ruins aqui **têm código**:
    `token_expired` e `token_already_used` são o que a tela precisa dizer
    ao examinador ("peça um novo à secretaria"). O 404 genérico continua
    valendo só para token que não existe.
    """
    encontrada = RecordSignature.objects.by_token(token).first()
    if encontrada is None:
        raise Http404("Link de assinatura inválido ou expirado.")

    # `select_for_update()` sem `select_related` (o Postgres recusa
    # `FOR UPDATE` sobre o lado nulável de um outer join) e ANTES de reler
    # a assinatura: é o que serializa dois cliques simultâneos no mesmo
    # link e impede o fechamento da etapa rodar duas vezes.
    ata = ExaminationRecord.objects.select_for_update().get(pk=encontrada.record_id)
    assinatura = RecordSignature.objects.select_related("signer__person").get(
        pk=encontrada.pk
    )
    assinatura.record = ata

    agora = timezone.now()
    assinatura.consume_token(agora)
    assinatura.sign(agora, content_hash or ata.content_hash, ip=ip)
    assinatura.save(
        update_fields=[
            "token_used_at",
            "signed_at",
            "signed_hash",
            "signed_by_user",
            "ip_address",
            "updated_at",
        ]
    )
    audit.record(
        "selection.record.sign",
        request=request,
        target=ata,
        program=ata.program,
        stage_id=ata.stage_id,
        signature_id=assinatura.pk,
        signer_id=assinatura.signer_id,
        method=assinatura.method,
    )

    if not ata.signatures.pending().exists():
        _close_stage(ata, request=request)
    return ata


@transaction.atomic
def resend_signature_token(
    *, signature: RecordSignature, request: HttpRequest | None = None
) -> RecordSignature:
    """Emite um token novo para o examinador externo e o manda de novo.

    Existe porque o e-mail se perde: cai no spam, o SMTP estava fora do ar
    no congelamento (`token_email_failed`) ou o prazo passou antes de o
    examinador abrir. Reemitir **invalida o anterior** — `issue_token`
    sorteia outro segredo e sobrescreve o hash, então o link velho deixa
    de abrir a tela. É o que impede dois links vivos para a mesma
    assinatura, um deles em caixa de e-mail que já vazou.

    Recusas vêm dos métodos do model: `already_signed` (quem já assinou
    não precisa de link), `token_not_applicable` (o professor do programa
    assina logado).
    """
    if signature.record.status != RecordStatus.AWAITING_SIGNATURES:
        raise InvalidStateTransition(
            "A ata não está aguardando assinaturas.",
            code="record_not_awaiting_signatures",
        )
    _emitir_token(signature, timezone.now(), request)
    audit.record(
        "selection.record.token_reissued",
        request=request,
        target=signature.record,
        stage_id=signature.record.stage_id,
        signature_id=signature.pk,
        signer_id=signature.signer_id,
    )
    return signature


# ---------------------------------------------------------------------------
# Retificação (versão n+1 da ata)
# ---------------------------------------------------------------------------
#
# Ata assinada não se reabre: apagar assinatura dada seria desfazer a
# declaração de um examinador sem que ele soubesse (`reopen_record` recusa
# por isso). O que existe é a **versão nova** — a v1 fica no banco como
# `superseded`, com o PDF que os três assinaram, e a v2 nasce em rascunho
# para a banca corrigir a nota e assinar de novo.
#
# Duas coisas que a ordem aqui esconde e que custam caro se invertidas:
#
#   1. **A anterior é substituída ANTES de a nova ser salva.** O `clean()`
#      da ata não admite duas correntes na mesma chave; com a v1 ainda
#      `signed`, o `save()` da v2 morreria em `record_already_exists`.
#      `_close_stage` sabe disso e só chama `supersede()` se a anterior
#      ainda estiver assinada.
#   2. **A edição das notas volta sozinha.** `_recusar_ata_congelada`
#      olha a ata **corrente** da chave; corrente passa a ser a v2, que
#      está em rascunho — nada mais a liberar.


@transaction.atomic
def rectify_record(
    *,
    record: ExaminationRecord,
    reason: str,
    request: HttpRequest | None = None,
) -> ExaminationRecord:
    """Abre a versão `n+1` da ata assinada, preservando a anterior.

    O `content` da v2 nasce das inscrições que a v1 julgou, com as notas
    de agora (`_linhas_da_ata` faz essa distinção quando há `supersedes`):
    filtrar por `alive()` deixaria de fora quem a v1 eliminou, que é
    justamente quem a retificação costuma existir para reintegrar.

    Quem re-sincroniza os desfechos é `_close_stage`, na última assinatura
    da versão nova — até lá nada muda para candidato nenhum.
    """
    motivo = reason.strip()
    if not motivo:
        raise DomainError(
            "A retificação precisa de um motivo — ele vai no PDF da versão nova.",
            code="rectification_reason_required",
        )

    # Trava a ata antes de ler a versão: duas retificações simultâneas
    # criariam duas v2 para a mesma chave, e só a UniqueConstraint
    # separaria as duas — tarde demais, com a v1 já substituída.
    # Sem `select_related`: `supersedes`, `project` e `research_line` são
    # nuláveis e o Postgres recusa `FOR UPDATE` sobre outer join.
    anterior = ExaminationRecord.objects.select_for_update().get(pk=record.pk)
    if anterior.status != RecordStatus.SIGNED:
        raise InvalidStateTransition(
            "Só ata assinada se retifica; a que ainda não foi assinada se reabre.",
            code="record_not_signed",
        )
    _exigir_etapa_seguinte_aberta(anterior)

    anterior.supersede()
    anterior.save(update_fields=["status", "updated_at"])

    nova = ExaminationRecord(
        program=anterior.program,
        process=anterior.process,
        stage=anterior.stage,
        level=anterior.level,
        project=anterior.project,
        research_line=anterior.research_line,
        board=anterior.board,
        replaced_member=anterior.replaced_member,
        version=anterior.version + 1,
        supersedes=anterior,
        rectification_reason=motivo,
    )
    linhas, _faltando = _linhas_da_ata(nova)
    nova.content = ExaminationRecord.normalize_content(linhas)
    nova.clean()
    nova.save()

    audit.record(
        "selection.record.rectify",
        request=request,
        target=nova,
        stage_id=nova.stage_id,
        version=nova.version,
        supersedes_id=anterior.pk,
        reason=motivo,
        rows=len(nova.content),
    )
    return nova


# ---------------------------------------------------------------------------
# Convocação de etapa (lote de e-mails)
# ---------------------------------------------------------------------------
#
# A regra que organiza tudo daqui para baixo: **escrever dentro da
# transação, enviar fora dela**. O lote e os e-mails `pending` nascem
# atômicos — ou o lote inteiro existe, ou nenhum e-mail existe. O envio
# vem depois do commit, um destinatário por vez, e cada falha fica na
# linha do próprio e-mail (`mark_failed`).
#
# Enviar dentro do bloco teria os dois defeitos ao mesmo tempo: uma caixa
# postal inválida desfaria o registro dos e-mails que já tinham saído, e
# esses e-mails continuariam entregues — rastro perdido, mensagem no ar.
# Por isso nenhuma falha de SMTP vira 500 nesta operação (armadilha 3 do
# plano): o lote é sempre criado, e a tela mostra quem falhou.


def _usuario_de(request: HttpRequest | None) -> Any | None:
    """O usuário autenticado da requisição, ou `None` (mesma regra de
    `audit.record`: sessão anônima não carimba autoria)."""
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return None
    return usuario


def _despachar(
    emails: list[ConvocationEmail],
    *,
    convocation: Convocation,
    request: HttpRequest | None,
) -> tuple[int, int]:
    """Envia os e-mails um a um, **fora** de qualquer transação.

    Devolve (enviados, falhados). O `except` é por destinatário de
    propósito: endereço inválido de um candidato não pode calar a
    convocação dos outros trinta.
    """
    enviados = 0
    falhados: list[int] = []
    for email in emails:
        try:
            enviar_convocacao(email)
        except (OSError, smtplib.SMTPException) as erro:
            email.mark_failed(str(erro))
            email.save(update_fields=["status", "error", "attempts", "updated_at"])
            falhados.append(email.pk)
            continue
        email.mark_sent(timezone.now())
        email.save(
            update_fields=["status", "error", "attempts", "sent_at", "updated_at"]
        )
        enviados += 1
    if falhados:
        # Evento próprio, como no token da ata: é assim que a secretaria
        # descobre, sem abrir o lote, que sobrou e-mail para reenviar.
        audit.record(
            "selection.convocation.email_failed",
            request=request,
            target=convocation,
            stage_id=convocation.stage_id,
            failed=len(falhados),
            emails=falhados,
        )
    return enviados, len(falhados)


@transaction.atomic
def _abrir_lote(
    *,
    process: SelectionProcess,
    stage: SelectionStage,
    request: HttpRequest | None,
) -> tuple[Convocation, list[ConvocationEmail]]:
    """Cria o lote da etapa com um e-mail `pending` por convocável novo.

    "Novo" é quem ainda não recebeu e-mail **nesta etapa**, em lote
    nenhum: reexecutar a convocação depois que mais uma inscrição foi
    homologada chama só ela, e quem já foi chamado não recebe duas vezes.
    Se não sobrou ninguém, o lote não é criado — um lote vazio seria uma
    linha a mais na tela dizendo que nada aconteceu.
    """
    ja_convocados = ConvocationEmail.objects.filter(convocation__stage=stage).values(
        "application_id"
    )
    convocaveis = list(
        Application.objects.convocable_for(stage)
        .exclude(pk__in=ja_convocados)
        .order_by("full_name", "pk")
    )
    if not convocaveis:
        raise DomainError(
            "Não há candidato para convocar nesta etapa — ou todos já foram "
            "convocados, ou a ata da etapa anterior ainda não foi assinada.",
            code="no_convocable_applications",
        )

    lote = Convocation.from_process(process, stage, sent_by=_usuario_de(request))
    lote.clean()
    lote.save()

    emails = []
    for inscricao in convocaveis:
        email = lote.email_for(inscricao)
        email.clean()
        email.save()
        emails.append(email)

    audit.record(
        "selection.convocation.send",
        request=request,
        target=lote,
        stage_id=stage.pk,
        process_id=process.pk,
        emails=len(emails),
    )
    return lote, emails


def send_convocations(
    *,
    process: SelectionProcess,
    stage: SelectionStage,
    request: HttpRequest | None = None,
) -> Convocation:
    """Dispara a convocação da etapa para quem ainda não foi chamado."""
    lote, emails = _abrir_lote(process=process, stage=stage, request=request)
    _despachar(emails, convocation=lote, request=request)
    return lote


def resend_convocation_emails(
    *, convocation: Convocation, request: HttpRequest | None = None
) -> Convocation:
    """Reenvia só o que falhou neste lote — nunca o que já foi entregue.

    Reenviar e-mail entregue é spam para o candidato, e ainda por cima
    apaga a diferença entre "a mensagem chegou" e "a mensagem foi tentada
    de novo". O texto é o mesmo do disparo original: ele está congelado
    na linha desde então.
    """
    falhados = list(
        convocation.emails.failed()
        .select_related("application")
        .order_by("application__full_name", "pk")
    )
    if not falhados:
        raise DomainError(
            "Não há e-mail falhado neste lote para reenviar.",
            code="no_failed_emails",
        )
    with transaction.atomic():
        audit.record(
            "selection.convocation.resend",
            request=request,
            target=convocation,
            stage_id=convocation.stage_id,
            emails=[email.pk for email in falhados],
        )
    _despachar(falhados, convocation=convocation, request=request)
    return convocation
