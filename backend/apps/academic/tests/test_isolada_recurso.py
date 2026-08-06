"""Recurso do candidato e comprovante da GRU, pelos endpoints.

Nível (b) da pirâmide (Seção 9). As duas rotas são multipart e as duas
dependem de janela do edital resolvida por `timezone.now()`, então os
ciclos daqui são relativos ao relógio — o `ciclo` de datas fixas do
conftest serve aos testes de janela em memória, não a estes.
"""

from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.academic.models import (
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentRequest,
    IsolatedPaymentStatus,
    IsolatedRequestStatus,
    RequestDocument,
    RequestDocumentKind,
)
from apps.academic.tests.conftest import criar_candidato, logar
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import AcademicTerm, Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/isolated/requests/"


def _url(requerimento: IsolatedEnrollmentRequest, acao: str) -> str:
    return f"{URL}{requerimento.id}/{acao}"


def _arquivo(nome: str = "diploma.pdf", conteudo: bytes = b"%PDF-1.4 falso"):
    return SimpleUploadedFile(nome, conteudo)


def _criar_ciclo(
    *,
    program: Program,
    ano: int,
    semestre: int,
    recurso_de: timedelta,
    recurso_ate: timedelta,
    pagamento_ate: timedelta,
) -> IsolatedEnrollmentCycle:
    """Ciclo com as janelas medidas a partir de agora.

    O período letivo é próprio de cada ciclo porque
    `unique_ciclo_isolada_por_programa_e_periodo` impede dois ciclos de
    dividirem o mesmo semestre.
    """
    agora = timezone.now()
    periodo = AcademicTerm.objects.create(
        year=ano,
        half=semestre,
        starts_on=date(ano, 3 if semestre == 1 else 8, 1),
        ends_on=date(ano, 7 if semestre == 1 else 12, 15),
    )
    return IsolatedEnrollmentCycle.objects.create(
        program=program,
        term=periodo,
        submission_opens_at=agora - timedelta(days=60),
        submission_closes_at=agora - timedelta(days=30),
        result_published_on=date(ano, 2, 12),
        appeal_opens_at=agora + recurso_de,
        appeal_closes_at=agora + recurso_ate,
        final_result_on=date(ano, 2, 17),
        payment_closes_at=agora + pagamento_ate,
    )


@pytest.fixture
def ciclo_em_recurso(program: Program) -> IsolatedEnrollmentCycle:
    return _criar_ciclo(
        program=program,
        ano=2028,
        semestre=1,
        recurso_de=timedelta(days=-1),
        recurso_ate=timedelta(days=1),
        pagamento_ate=timedelta(days=10),
    )


@pytest.fixture
def ciclo_com_recurso_encerrado(program: Program) -> IsolatedEnrollmentCycle:
    return _criar_ciclo(
        program=program,
        ano=2028,
        semestre=2,
        recurso_de=timedelta(days=-10),
        recurso_ate=timedelta(days=-5),
        pagamento_ate=timedelta(days=10),
    )


@pytest.fixture
def ciclo_com_pagamento_encerrado(program: Program) -> IsolatedEnrollmentCycle:
    return _criar_ciclo(
        program=program,
        ano=2029,
        semestre=1,
        recurso_de=timedelta(days=-10),
        recurso_ate=timedelta(days=-8),
        pagamento_ate=timedelta(days=-1),
    )


@pytest.fixture
def candidata(program: Program) -> Person:
    return criar_candidato(program=program, username="marina", nome="Marina Alves")


@pytest.fixture
def client_candidata(client: Client, candidata: Person) -> Client:
    return logar(client, candidata)


def _requerimento(
    *,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    pessoa: Person,
    status: str,
    payment_status: str = IsolatedPaymentStatus.PENDING,
) -> IsolatedEnrollmentRequest:
    return IsolatedEnrollmentRequest.objects.create(
        program=program,
        cycle=ciclo,
        person=pessoa,
        status=status,
        payment_status=payment_status,
        submitted_at=timezone.now(),
    )


@pytest.fixture
def indeferido(
    program: Program, ciclo_em_recurso: IsolatedEnrollmentCycle, candidata: Person
) -> IsolatedEnrollmentRequest:
    return _requerimento(
        program=program,
        ciclo=ciclo_em_recurso,
        pessoa=candidata,
        status=IsolatedRequestStatus.REJECTED,
    )


@pytest.fixture
def deferido(
    program: Program, ciclo_em_recurso: IsolatedEnrollmentCycle, candidata: Person
) -> IsolatedEnrollmentRequest:
    return _requerimento(
        program=program,
        ciclo=ciclo_em_recurso,
        pessoa=candidata,
        status=IsolatedRequestStatus.DEFERRED,
    )


# --- recurso ---------------------------------------------------------


def test_recurso_grava_as_razoes_sem_mudar_o_status(
    client_candidata: Client, indeferido: IsolatedEnrollmentRequest
):
    """Recorrer é pedir rejulgamento, não deferir-se: quem decide de novo
    é a secretaria, pelos mesmos defer/reject da US-012.
    """
    resposta = client_candidata.post(
        _url(indeferido, "appeal"), data={"note": "O diploma foi anexado ilegível."}
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == IsolatedRequestStatus.REJECTED
    assert corpo["appeal_note"] == "O diploma foi anexado ilegível."
    assert corpo["appealed_at"] is not None
    indeferido.refresh_from_db()
    assert indeferido.status == IsolatedRequestStatus.REJECTED
    assert AuditLog.objects.filter(
        event="academic.isolated.appeal", target_id=indeferido.pk
    ).exists()


def test_recurso_anexa_o_documento_que_faltou(
    client_candidata: Client, indeferido: IsolatedEnrollmentRequest
):
    resposta = client_candidata.post(
        _url(indeferido, "appeal"),
        data={
            "note": "Segue o diploma legível.",
            "kind": RequestDocumentKind.DIPLOMA,
            "file": _arquivo(),
        },
    )

    assert resposta.status_code == 200, resposta.content
    documento = RequestDocument.objects.get(request=indeferido)
    assert documento.kind == RequestDocumentKind.DIPLOMA


def test_recurso_substitui_o_documento_anterior_do_mesmo_tipo(
    client_candidata: Client, indeferido: IsolatedEnrollmentRequest
):
    RequestDocument.objects.create(
        request=indeferido,
        kind=RequestDocumentKind.DIPLOMA,
        file=SimpleUploadedFile("velho.pdf", b"ilegivel"),
    )

    resposta = client_candidata.post(
        _url(indeferido, "appeal"),
        data={
            "note": "Segue o diploma legível.",
            "kind": RequestDocumentKind.DIPLOMA,
            "file": _arquivo("novo.pdf"),
        },
    )

    assert resposta.status_code == 200, resposta.content
    documento = RequestDocument.objects.get(
        request=indeferido, kind=RequestDocumentKind.DIPLOMA
    )
    assert "novo" in (documento.file.name or "")


def test_recurso_fora_da_janela_e_recusado(
    client_candidata: Client,
    program: Program,
    ciclo_com_recurso_encerrado: IsolatedEnrollmentCycle,
    candidata: Person,
):
    requerimento = _requerimento(
        program=program,
        ciclo=ciclo_com_recurso_encerrado,
        pessoa=candidata,
        status=IsolatedRequestStatus.REJECTED,
    )

    resposta = client_candidata.post(
        _url(requerimento, "appeal"), data={"note": "Fora do prazo."}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "appeal_window_closed"
    requerimento.refresh_from_db()
    assert requerimento.appealed_at is None


def test_recurso_de_requerimento_deferido_e_recusado(
    client_candidata: Client, deferido: IsolatedEnrollmentRequest
):
    resposta = client_candidata.post(
        _url(deferido, "appeal"), data={"note": "Não cabe."}
    )

    assert resposta.status_code == 409


def test_recurso_sem_razoes_e_recusado(
    client_candidata: Client, indeferido: IsolatedEnrollmentRequest
):
    resposta = client_candidata.post(_url(indeferido, "appeal"), data={"note": "   "})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "appeal_requires_note"


def test_recurso_nao_aceita_comprovante_da_gru_como_anexo(
    client_candidata: Client, indeferido: IsolatedEnrollmentRequest
):
    """A guia só nasce no deferimento; quem recorre está indeferido."""
    resposta = client_candidata.post(
        _url(indeferido, "appeal"),
        data={
            "note": "Segue comprovante.",
            "kind": RequestDocumentKind.PAYMENT_RECEIPT,
            "file": _arquivo(),
        },
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_document_kind"
    assert not RequestDocument.objects.filter(request=indeferido).exists()


def test_recurso_com_tipo_sem_arquivo_e_recusado(
    client_candidata: Client, indeferido: IsolatedEnrollmentRequest
):
    resposta = client_candidata.post(
        _url(indeferido, "appeal"),
        data={"note": "Anexo pela metade.", "kind": RequestDocumentKind.DIPLOMA},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "incomplete_document"


def test_recurso_de_outro_candidato_e_recusado(
    client_candidata: Client,
    program: Program,
    ciclo_em_recurso: IsolatedEnrollmentCycle,
):
    outra = criar_candidato(program=program, username="joana", nome="Joana Lima")
    requerimento = _requerimento(
        program=program,
        ciclo=ciclo_em_recurso,
        pessoa=outra,
        status=IsolatedRequestStatus.REJECTED,
    )

    resposta = client_candidata.post(
        _url(requerimento, "appeal"), data={"note": "Não é meu."}
    )

    assert resposta.status_code == 403


def test_recurso_sem_sessao_e_recusado(
    client: Client, indeferido: IsolatedEnrollmentRequest
):
    resposta = client.post(_url(indeferido, "appeal"), data={"note": "Anônimo."})

    assert resposta.status_code == 401


# --- comprovante da GRU ----------------------------------------------


def test_comprovante_marca_a_taxa_como_paga_e_audita(
    client_candidata: Client, deferido: IsolatedEnrollmentRequest
):
    resposta = client_candidata.post(
        _url(deferido, "payment-receipt"), data={"file": _arquivo("gru.pdf")}
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["payment_status"] == IsolatedPaymentStatus.PAID
    deferido.refresh_from_db()
    assert deferido.payment_status == IsolatedPaymentStatus.PAID
    assert deferido.status == IsolatedRequestStatus.DEFERRED
    assert RequestDocument.objects.filter(
        request=deferido, kind=RequestDocumentKind.PAYMENT_RECEIPT
    ).exists()
    assert AuditLog.objects.filter(
        event="academic.isolated.payment_receipt", target_id=deferido.pk
    ).exists()


def test_comprovante_de_requerimento_isento_e_recusado(
    client_candidata: Client,
    program: Program,
    ciclo_em_recurso: IsolatedEnrollmentCycle,
    candidata: Person,
):
    """Servidor da UFMG já pagou com o contracheque que anexou."""
    requerimento = _requerimento(
        program=program,
        ciclo=ciclo_em_recurso,
        pessoa=candidata,
        status=IsolatedRequestStatus.DEFERRED,
        payment_status=IsolatedPaymentStatus.EXEMPT,
    )

    resposta = client_candidata.post(
        _url(requerimento, "payment-receipt"), data={"file": _arquivo("gru.pdf")}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "payment_not_required"
    requerimento.refresh_from_db()
    assert requerimento.payment_status == IsolatedPaymentStatus.EXEMPT
    assert not RequestDocument.objects.filter(request=requerimento).exists()


def test_comprovante_fora_do_prazo_e_recusado(
    client_candidata: Client,
    program: Program,
    ciclo_com_pagamento_encerrado: IsolatedEnrollmentCycle,
    candidata: Person,
):
    requerimento = _requerimento(
        program=program,
        ciclo=ciclo_com_pagamento_encerrado,
        pessoa=candidata,
        status=IsolatedRequestStatus.DEFERRED,
    )

    resposta = client_candidata.post(
        _url(requerimento, "payment-receipt"), data={"file": _arquivo("gru.pdf")}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "payment_window_closed"
    requerimento.refresh_from_db()
    assert requerimento.payment_status == IsolatedPaymentStatus.PENDING
    assert not RequestDocument.objects.filter(request=requerimento).exists()


def test_comprovante_de_requerimento_nao_deferido_e_recusado(
    client_candidata: Client, indeferido: IsolatedEnrollmentRequest
):
    resposta = client_candidata.post(
        _url(indeferido, "payment-receipt"), data={"file": _arquivo("gru.pdf")}
    )

    assert resposta.status_code == 409


def test_reenviar_o_comprovante_substitui_o_anterior(
    client_candidata: Client, deferido: IsolatedEnrollmentRequest
):
    """Quem mandou a página errada corrige: a conferência da secretaria é
    posterior, e não existe caminho de volta de PAGO para PENDENTE.
    """
    client_candidata.post(
        _url(deferido, "payment-receipt"), data={"file": _arquivo("errado.pdf")}
    )

    resposta = client_candidata.post(
        _url(deferido, "payment-receipt"), data={"file": _arquivo("certo.pdf")}
    )

    assert resposta.status_code == 200, resposta.content
    documento = RequestDocument.objects.get(
        request=deferido, kind=RequestDocumentKind.PAYMENT_RECEIPT
    )
    assert "certo" in (documento.file.name or "")


def test_comprovante_de_outro_candidato_e_recusado(
    client_candidata: Client,
    program: Program,
    ciclo_em_recurso: IsolatedEnrollmentCycle,
):
    outra = criar_candidato(program=program, username="joana", nome="Joana Lima")
    requerimento = _requerimento(
        program=program,
        ciclo=ciclo_em_recurso,
        pessoa=outra,
        status=IsolatedRequestStatus.DEFERRED,
    )

    resposta = client_candidata.post(
        _url(requerimento, "payment-receipt"), data={"file": _arquivo("gru.pdf")}
    )

    assert resposta.status_code == 403


def test_comprovante_sem_sessao_e_recusado(
    client: Client, deferido: IsolatedEnrollmentRequest
):
    resposta = client.post(
        _url(deferido, "payment-receipt"), data={"file": _arquivo("gru.pdf")}
    )

    assert resposta.status_code == 401
