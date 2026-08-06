"""Upload e download dos anexos do requerimento, pelos endpoints.

Nível (b) da pirâmide (Seção 9). O que só existe aqui é o que a borda
acrescenta ao model: o arquivo recusado antes de gravar, o documento que é
sempre do próprio candidato e as duas — e só duas — portas do download.
"""

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.academic.models import (
    TAMANHO_MAXIMO_DO_DOCUMENTO,
    IsolatedEnrollmentRequest,
    RequestDocument,
    RequestDocumentKind,
    Teacher,
)
from apps.academic.tests.conftest import SENHA, criar_candidato, logar
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program

pytestmark = pytest.mark.django_db

URL_REQUERIMENTOS = "/api/v1/academic/isolated/requests/"
URL_DOCUMENTOS = "/api/v1/academic/isolated/documents/"


def _url_upload(requerimento: IsolatedEnrollmentRequest) -> str:
    return f"{URL_REQUERIMENTOS}{requerimento.id}/documents"


def _url_download(documento: RequestDocument) -> str:
    return f"{URL_DOCUMENTOS}{documento.id}/download"


def _arquivo(nome: str = "identidade.pdf", conteudo: bytes = b"%PDF-1.4 falso"):
    return SimpleUploadedFile(nome, conteudo)


def _enviar(
    client: Client,
    requerimento: IsolatedEnrollmentRequest,
    *,
    kind: str = RequestDocumentKind.IDENTITY,
    arquivo=None,
):
    return client.post(
        _url_upload(requerimento),
        data={"kind": kind, "file": arquivo if arquivo is not None else _arquivo()},
    )


@pytest.fixture
def candidata(program: Program) -> Person:
    return criar_candidato(program=program, username="marina", nome="Marina Alves")


@pytest.fixture
def client_candidata(client: Client, candidata: Person) -> Client:
    return logar(client, candidata)


@pytest.fixture
def requerimento_da_candidata(
    program: Program, ciclo_aberto, candidata: Person
) -> IsolatedEnrollmentRequest:
    return IsolatedEnrollmentRequest.objects.create(
        program=program, cycle=ciclo_aberto, person=candidata
    )


@pytest.fixture
def documento(requerimento_da_candidata) -> RequestDocument:
    return RequestDocument.objects.create(
        request=requerimento_da_candidata,
        kind=RequestDocumentKind.IDENTITY,
        file=SimpleUploadedFile("identidade.pdf", b"conteudo do anexo"),
    )


@pytest.fixture
def secretaria_no_programa(secretaria: User, program: Program) -> Person:
    """`current_program` sai da Person ativa: usuário de papel sem cadastro
    no programa não passa nem da resolução do tenant.
    """
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


@pytest.fixture
def client_docente(client: Client, docente: Teacher) -> Client:
    """Docente com conta: ele vê o requerimento de quem se inscreveu na
    oferta dele, e é justamente por isso que o 403 do download importa.
    """
    user = User.objects.create_user(username="bruno", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    docente.person.user = user
    docente.person.save(update_fields=["user"])
    client.force_login(user)
    return client


# --- upload ----------------------------------------------------------------


def test_anexar_documento_grava_e_audita(
    client_candidata, requerimento_da_candidata, candidata
):
    resposta = _enviar(client_candidata, requerimento_da_candidata)

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["kind"] == RequestDocumentKind.IDENTITY
    assert corpo["filename"] == "identidade.pdf"
    assert corpo["size"] > 0
    # A URL do arquivo não sai no corpo: MEDIA é servido sem passar pelo
    # Django, e publicá-la entregaria a identidade sem auditoria nenhuma.
    assert "file" not in corpo and "url" not in corpo
    log = AuditLog.objects.get(event="academic.isolated.document_upload")
    assert log.target_id == str(requerimento_da_candidata.pk)
    assert log.payload["kind"] == RequestDocumentKind.IDENTITY
    assert log.payload["replaced"] is False


def test_reenviar_o_mesmo_tipo_substitui_em_vez_de_empilhar(
    client_candidata, requerimento_da_candidata
):
    _enviar(client_candidata, requerimento_da_candidata)

    resposta = _enviar(
        client_candidata,
        requerimento_da_candidata,
        arquivo=_arquivo("identidade-correta.pdf"),
    )

    assert resposta.status_code == 201, resposta.content
    documentos = RequestDocument.objects.filter(
        request=requerimento_da_candidata, kind=RequestDocumentKind.IDENTITY
    )
    assert documentos.count() == 1
    assert documentos.get().file.name.endswith("identidade-correta.pdf")
    trilha = AuditLog.objects.filter(
        event="academic.isolated.document_upload"
    ).order_by("id")
    assert [linha.payload["replaced"] for linha in trilha] == [False, True]


def test_anexo_derruba_o_tipo_da_lista_de_pendencias(
    client_candidata, requerimento_da_candidata
):
    _enviar(client_candidata, requerimento_da_candidata)

    assert RequestDocumentKind.IDENTITY not in (
        requerimento_da_candidata.missing_documents()
    )


@pytest.mark.parametrize("nome", ["contrato.docx", "curriculo.exe", "sem-extensao"])
def test_extensao_fora_do_edital_e_recusada(
    client_candidata, requerimento_da_candidata, nome
):
    resposta = _enviar(
        client_candidata, requerimento_da_candidata, arquivo=_arquivo(nome)
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_document"
    assert not RequestDocument.objects.exists()


def test_arquivo_acima_do_limite_e_recusado(
    client_candidata, requerimento_da_candidata
):
    grande = _arquivo("identidade.pdf", b"x" * (TAMANHO_MAXIMO_DO_DOCUMENTO + 1))

    resposta = _enviar(client_candidata, requerimento_da_candidata, arquivo=grande)

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_document"
    assert not RequestDocument.objects.exists()


def test_tipo_inexistente_e_recusado_na_borda(
    client_candidata, requerimento_da_candidata
):
    resposta = _enviar(client_candidata, requerimento_da_candidata, kind="passaporte")

    assert resposta.status_code == 422, resposta.content


def test_depois_de_inscrito_a_documentacao_nao_muda(
    client_candidata, requerimento_da_candidata
):
    requerimento_da_candidata.status = IsolatedEnrollmentRequest.Status.SUBMITTED
    requerimento_da_candidata.save(update_fields=["status"])

    resposta = _enviar(client_candidata, requerimento_da_candidata)

    assert resposta.status_code == 409, resposta.content
    assert not RequestDocument.objects.exists()


def test_comprovante_da_gru_so_entra_depois_do_deferimento(
    client_candidata, requerimento_da_candidata
):
    """No rascunho a guia nem foi emitida; deferido, ela é o próximo passo
    do candidato (US-013).
    """
    recusado = _enviar(
        client_candidata,
        requerimento_da_candidata,
        kind=RequestDocumentKind.PAYMENT_RECEIPT,
        arquivo=_arquivo("gru.pdf"),
    )
    assert recusado.status_code == 409, recusado.content

    requerimento_da_candidata.status = IsolatedEnrollmentRequest.Status.DEFERRED
    requerimento_da_candidata.save(update_fields=["status"])
    aceito = _enviar(
        client_candidata,
        requerimento_da_candidata,
        kind=RequestDocumentKind.PAYMENT_RECEIPT,
        arquivo=_arquivo("gru.pdf"),
    )

    assert aceito.status_code == 201, aceito.content


def test_ninguem_anexa_no_requerimento_de_outro(
    client_candidata, program, ciclo_aberto
):
    alheio = IsolatedEnrollmentRequest.objects.create(
        program=program,
        cycle=ciclo_aberto,
        person=criar_candidato(program=program, username="joao", nome="João Dias"),
    )

    resposta = _enviar(client_candidata, alheio)

    assert resposta.status_code == 403, resposta.content
    assert not RequestDocument.objects.exists()


def test_nem_a_secretaria_anexa_pelo_candidato(
    client_secretaria, secretaria_no_programa, requerimento_da_candidata
):
    resposta = _enviar(client_secretaria, requerimento_da_candidata)

    assert resposta.status_code == 403, resposta.content


def test_upload_sem_sessao_e_401(client, requerimento_da_candidata):
    resposta = _enviar(client, requerimento_da_candidata)

    assert resposta.status_code == 401, resposta.content


# --- listagem --------------------------------------------------------------


def test_listagem_traz_o_anexo_sem_o_caminho_do_arquivo(
    client_candidata, requerimento_da_candidata, documento
):
    resposta = client_candidata.get(_url_upload(requerimento_da_candidata))

    assert resposta.status_code == 200, resposta.content
    (corpo,) = resposta.json()
    assert corpo["id"] == documento.pk
    assert corpo["kind_label"] == "Identidade e CPF"
    assert corpo["filename"] == "identidade.pdf"
    # O contrato é fechado de propósito: nenhum campo daqui leva ao arquivo
    # sem passar pelo download, que checa posse e audita.
    assert set(corpo) == {"id", "kind", "kind_label", "filename", "size", "uploaded_at"}


def test_candidato_nao_lista_documento_de_outro(
    client_candidata, program, ciclo_aberto
):
    alheio = IsolatedEnrollmentRequest.objects.create(
        program=program,
        cycle=ciclo_aberto,
        person=criar_candidato(program=program, username="joao", nome="João Dias"),
    )

    resposta = client_candidata.get(_url_upload(alheio))

    assert resposta.status_code == 404, resposta.content


# --- download --------------------------------------------------------------


def test_candidato_baixa_o_proprio_documento_e_o_acesso_fica_no_rastro(
    client_candidata, documento, requerimento_da_candidata
):
    resposta = client_candidata.get(_url_download(documento))

    assert resposta.status_code == 200, resposta.content
    assert b"".join(resposta.streaming_content) == b"conteudo do anexo"
    assert "identidade.pdf" in resposta["Content-Disposition"]
    log = AuditLog.objects.get(event="academic.isolated.document_download")
    assert log.target_id == str(requerimento_da_candidata.pk)
    assert log.payload["document_id"] == documento.pk


def test_secretaria_baixa_pela_permissao(
    client_secretaria, secretaria_no_programa, documento
):
    resposta = client_secretaria.get(_url_download(documento))

    assert resposta.status_code == 200, resposta.content
    assert AuditLog.objects.filter(event="academic.isolated.document_download").exists()


def test_docente_ve_o_requerimento_mas_nao_baixa_o_documento(client_docente, documento):
    resposta = client_docente.get(_url_download(documento))

    assert resposta.status_code == 403, resposta.content
    assert not AuditLog.objects.filter(
        event="academic.isolated.document_download"
    ).exists()


def test_download_sem_sessao_e_401(client, documento):
    resposta = client.get(_url_download(documento))

    assert resposta.status_code == 401, resposta.content


def test_documento_de_outro_programa_nao_existe_para_esta_sessao(
    client_secretaria, secretaria_no_programa, documento
):
    """Escopo de tenant é o primeiro filtro da busca: fora dele o
    documento é 404, nunca 403 — 403 revelaria que o id existe.
    """
    outro_programa = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    documento.request.program = outro_programa
    documento.request.save(update_fields=["program"])

    resposta = client_secretaria.get(_url_download(documento))

    assert resposta.status_code == 404, resposta.content
