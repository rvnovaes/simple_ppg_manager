"""Operações do app selection que cruzam mais de um model.

`publish_process` está aqui, e não no router, porque publicar não é gravar
um campo: é conferir etapas, vagas e template — três models — antes de
mudar o estado do edital, tudo na mesma transação (ADR-002).

Quem escreve aqui chama `clean()` antes de `save()`: o Django não executa
`clean()` em `.save()`/`.create()`, e sem essa chamada o invariante do
model nunca roda no caminho real.
"""

from datetime import datetime

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import UploadedFile

from apps.core import audit
from apps.core.exceptions import DomainError

from .models import (
    Application,
    ApplicationDocument,
    ApplicationDocumentKind,
    SelectionProcess,
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
