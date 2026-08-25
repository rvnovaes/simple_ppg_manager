"""Mensagens que o processo seletivo manda para fora.

Um módulo só, e não `send_mail` espalhado pelos services, por dois
motivos práticos: o assunto e o corpo são texto que a secretaria vai
querer reler, e o teste de e-mail fica sendo sempre o mesmo — montar a
mensagem aqui, conferir em `django.core.mail.outbox` lá.

Duas regras valem para tudo o que sai daqui:

1. **O link é montado com `settings.SITE_URL`**, nunca com
   `request.build_absolute_uri`. Atrás do Nginx o Django enxerga o host
   interno (`backend:8000`), e o e-mail é lido fora do navegador — o
   endereço precisa ser o público, que só a configuração conhece.
2. **Ninguém chama isto dentro de `transaction.atomic`.** Falha de SMTP
   dentro do bloco reverteria a escrita que o e-mail apenas comunica; o
   envio acontece em `transaction.on_commit` (ADR-009, sem fila).
"""

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import formats

from apps.core.exceptions import DomainError

from .models import ConvocationEmail, RecordSignature


def link_de_assinatura(token: str) -> str:
    """A URL pública da tela de assinatura por token."""
    return f"{settings.SITE_URL}/selecao/assinatura/{token}"


def enviar_token_de_assinatura(signature: RecordSignature, token: str) -> None:
    """Manda ao examinador externo o link com que ele assina a ata.

    O token viaja **só aqui**: no banco fica o hash (`hash_do_token`), e
    quem lê a tabela não consegue assinar por ninguém. Por isso o texto
    chega por parâmetro, vindo direto de `issue_token`.
    """
    if signature.token_expires_at is None:
        raise DomainError(
            "Não há token emitido para esta assinatura.",
            code="token_not_applicable",
        )
    ata = signature.record
    prazo = formats.date_format(
        signature.token_expires_at, "DATETIME_FORMAT", use_l10n=True
    )
    corpo = (
        f"Prezado(a) {signature.signer.person.full_name},\n\n"
        f"A ata da etapa {ata.stage.name} do {ata.process.title} "
        f"({ata.get_level_display()} — {ata.project or ata.research_line}) "
        "está pronta para assinatura.\n\n"
        "Confira o conteúdo e assine no endereço abaixo:\n"
        f"{link_de_assinatura(token)}\n\n"
        f"O link é pessoal, vale uma única vez e expira em {prazo}.\n\n"
        "Esta mensagem é automática; não responda."
    )
    EmailMessage(
        subject=f"Assinatura da ata — {ata.stage.name} — {ata.process.title}",
        body=corpo,
        to=[signature.signer.person.primary_email],
    ).send(fail_silently=False)


def enviar_convocacao(email: ConvocationEmail) -> None:
    """Manda ao candidato o e-mail de convocação já renderizado.

    Nada é montado aqui: assunto e corpo foram congelados em
    `Convocation.email_for` no instante do disparo do lote, e reenviar é
    mandar de novo **o mesmo texto** — o candidato não pode receber duas
    versões de uma convocação porque a secretaria editou o edital no meio.

    `fail_silently=False` de propósito: quem chama (`send_convocations`)
    trata a exceção por destinatário e a grava em `mark_failed`. Engolir
    a falha aqui deixaria o lote inteiro com cara de entregue.
    """
    EmailMessage(
        subject=email.rendered_subject,
        body=email.rendered_body,
        to=[email.to_email],
    ).send(fail_silently=False)
