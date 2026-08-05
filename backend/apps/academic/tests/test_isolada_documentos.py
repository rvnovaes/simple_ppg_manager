"""Documentos do requerimento de isolada — nível (b) da pirâmide, com banco.

A UniqueConstraint barra o INSERT e `missing_documents()` conta linhas
relacionadas: nenhum dos dois cabe em memória. O recorte de quais tipos são
obrigatórios, esse sim, é exercitado sem banco em `test_models.py`.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.academic.models import (
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
    RequestDocument,
    RequestDocumentKind,
)
from apps.academic.tests.conftest import (
    DENTRO_DA_INSCRICAO,
    anexar_documentos_obrigatorios,
    criar_requerimento,
)
from apps.core.exceptions import DomainError


def _anexar(requerimento: IsolatedEnrollmentRequest, kind: str) -> RequestDocument:
    return RequestDocument.objects.create(
        request=requerimento,
        kind=kind,
        file=SimpleUploadedFile(f"{kind}.pdf", b"conteudo"),
    )


def test_documento_repetido_do_mesmo_tipo_e_rejeitado(requerimento):
    """Duas versões do mesmo comprovante deixariam a secretaria adivinhar
    qual vale; reenviar é substituir.
    """
    _anexar(requerimento, RequestDocumentKind.IDENTITY)

    with pytest.raises(IntegrityError), transaction.atomic():
        _anexar(requerimento, RequestDocumentKind.IDENTITY)


def test_arquivo_e_gravado_particionado_por_ciclo_e_requerimento(requerimento):
    documento = _anexar(requerimento, RequestDocumentKind.DIPLOMA)

    assert documento.file.name.startswith(
        f"isoladas/ciclo-{requerimento.cycle_id}/requerimento-{requerimento.pk}/"
    )


def test_faltando_um_documento_a_lista_traz_so_ele(requerimento):
    for kind in requerimento.required_document_kinds():
        if kind != RequestDocumentKind.ADDRESS:
            _anexar(requerimento, kind)

    assert requerimento.missing_documents() == [RequestDocumentKind.ADDRESS]


def test_documentacao_completa_esvazia_a_lista(requerimento):
    anexar_documentos_obrigatorios(requerimento)

    assert requerimento.missing_documents() == []


def test_comprovante_da_gru_nao_conta_para_a_submissao(requerimento):
    """A GRU só é emitida depois do deferimento: exigi-la na inscrição
    fecharia a porta antes de a secretaria abrir.
    """
    anexar_documentos_obrigatorios(requerimento)
    _anexar(requerimento, RequestDocumentKind.PAYMENT_RECEIPT)

    assert requerimento.missing_documents() == []


def test_inscrever_sem_documentacao_completa_levanta(requerimento, oferta):
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)
    for kind in requerimento.required_document_kinds():
        if kind != RequestDocumentKind.LATTES:
            _anexar(requerimento, kind)

    with pytest.raises(DomainError) as exc:
        requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert exc.value.code == "missing_documents"
    assert exc.value.status_code == 400
    assert requerimento.status == IsolatedEnrollmentRequest.Status.DRAFT


def test_servidor_da_ufmg_nao_se_inscreve_sem_contracheque(program, ciclo, oferta):
    requerimento = criar_requerimento(
        program=program, ciclo=ciclo, nome="Davi Melo", is_ufmg_staff=True
    )
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)
    for kind in (
        RequestDocumentKind.IDENTITY,
        RequestDocumentKind.DIPLOMA,
        RequestDocumentKind.LATTES,
        RequestDocumentKind.ADDRESS,
        RequestDocumentKind.SUPERVISOR_AUTH,
    ):
        _anexar(requerimento, kind)

    with pytest.raises(DomainError) as exc:
        requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert exc.value.code == "missing_documents"
    assert requerimento.missing_documents() == [RequestDocumentKind.PAYSLIP]


def test_servidor_da_ufmg_com_tudo_anexado_se_inscreve(program, ciclo, oferta):
    requerimento = criar_requerimento(
        program=program, ciclo=ciclo, nome="Elisa Nunes", is_ufmg_staff=True
    )
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)
    anexar_documentos_obrigatorios(requerimento)

    requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert requerimento.status == IsolatedEnrollmentRequest.Status.SUBMITTED
