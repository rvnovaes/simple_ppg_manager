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
from functools import partial
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import UploadedFile

from apps.core import audit
from apps.core.exceptions import DomainError, InvalidStateTransition

from .emails import enviar_token_de_assinatura
from .models import (
    Application,
    ApplicationDocument,
    ApplicationDocumentKind,
    Board,
    ExaminationRecord,
    RecordSignature,
    RecordStatus,
    SelectionProcess,
    SelectionStage,
    StageScore,
    Vacancy,
    gerar_protocolo,
)
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

# Limites por IP das três rotas públicas (apps.core.ratelimit). Sem sessão
# não há conta para responsabilizar: o contador é o que sobra.
LIMITE_DE_LEITURA_PUBLICA = 60
JANELA_DE_LEITURA_EM_SEGUNDOS = 60
LIMITE_DE_INSCRICAO_POR_IP = 5
JANELA_DE_INSCRICAO_EM_SEGUNDOS = 60 * 60
LIMITE_DE_CONSULTA_DE_PROTOCOLO = 20
JANELA_DE_CONSULTA_EM_SEGUNDOS = 60

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
    inscricoes = list(
        Application.objects.for_process(record.process_id)
        .alive()
        .for_target(record.level, record.project, record.research_line)
        .order_by("full_name", "protocol")
    )
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
