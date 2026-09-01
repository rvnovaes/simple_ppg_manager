"""O comprovante do questionário: envio pelo candidato, download auditado.

Nível (b) da pirâmide (Seção 9). Os invariantes do anexo (extensão,
tamanho, substituição por tipo) ficam em `test_bolsas_documentos.py`; aqui
só a borda.

O caso que dá nome ao arquivo é o **download**: ele tem permissão própria
(`download_applicationdocument`) porque baixar laudo de vulnerabilidade e
contracheque é mais do que ver a inscrição. A Coordenação enxerga a fila
inteira e mesmo assim leva 403 aqui.
"""

from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.academic.models import Student
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program
from apps.scholarships.models import (
    TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO,
    ApplicationDocument,
    ApplicationDocumentKind,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
)

from .test_bolsas_api_inscricao import SENHA, criar_discente, logar

pytestmark = pytest.mark.django_db


@pytest.fixture
def aluno(program: Program) -> Student:
    return criar_discente(program=program, username="ana", nome="Ana Ribeiro")


@pytest.fixture
def colega(program: Program) -> Student:
    return criar_discente(program=program, username="bruno", nome="Bruno Lima")


@pytest.fixture
def client_do_aluno(client: Client, aluno: Student) -> Client:
    return logar(client, aluno)


def usuario_com_papel(program: Program, papel: str, username: str) -> User:
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name=papel))
    Person.objects.create(
        program=program,
        user=user,
        full_name=username.capitalize(),
        primary_email=f"{username}@exemplo.br",
    )
    return user


@pytest.fixture
def client_da_secretaria(client: Client, program: Program) -> Client:
    client.force_login(usuario_com_papel(program, "Secretaria", "carla"))
    return client


@pytest.fixture
def client_da_coordenacao(client: Client, program: Program) -> Client:
    """Só acompanha: tem `view_` de tudo e nenhuma permissão de download."""
    client.force_login(usuario_com_papel(program, "Coordenação", "denise"))
    return client


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.SUBMISSIONS_OPEN,
    )


@pytest.fixture
def inscricao(edicao: ScholarshipEdition, aluno: Student) -> ScholarshipApplication:
    candidatura = ScholarshipApplication.for_student(
        edition=edicao, student=aluno, affirmative_action=True
    )
    candidatura.save()
    return candidatura


def arquivo(nome: str = "laudo.pdf", conteudo: bytes = b"%PDF-1.4 laudo"):
    return SimpleUploadedFile(nome, conteudo, content_type="application/pdf")


def url_upload(inscricao: ScholarshipApplication) -> str:
    return f"/api/v1/scholarships/applications/{inscricao.pk}/documents"


def enviar(client: Client, inscricao: ScholarshipApplication, **extra):
    dados = {
        "kind": ApplicationDocumentKind.AFFIRMATIVE_ACTION.value,
        "file": arquivo(),
    }
    dados.update(extra)
    return client.post(url_upload(inscricao), data=dados)


# --- envio -----------------------------------------------------------------


def test_o_aluno_anexa_o_comprovante_e_a_pendencia_some(
    client_do_aluno: Client, inscricao: ScholarshipApplication, program: Program
):
    resposta = enviar(client_do_aluno, inscricao)

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["kind"] == ApplicationDocumentKind.AFFIRMATIVE_ACTION.value
    assert dados["kind_label"] == "Ação afirmativa"
    assert dados["filename"] == "laudo.pdf"
    assert dados["size"] > 0
    # O schema de saída nunca expõe o caminho do arquivo.
    assert "file" not in dados and "url" not in dados
    assert inscricao.pending_docs() == []
    registro = AuditLog.objects.get(event="scholarships.application.document_upload")
    assert registro.program_id == program.pk
    assert registro.target_id == str(inscricao.pk)
    assert registro.payload["replaced"] is False


def test_reenviar_o_mesmo_tipo_substitui_o_arquivo(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    """Nomes diferentes de propósito: com o mesmo nome o caminho é
    liberado no delete e reocupado pelo novo upload, e o teste passaria
    sem provar nada."""
    enviar(client_do_aluno, inscricao, file=arquivo("primeiro.pdf"))
    antigo = ApplicationDocument.objects.get().file.name

    resposta = enviar(client_do_aluno, inscricao, file=arquivo("segundo.pdf"))

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["filename"] == "segundo.pdf"
    assert ApplicationDocument.objects.count() == 1
    assert not default_storage.exists(antigo or "")
    registro = AuditLog.objects.filter(
        event="scholarships.application.document_upload"
    ).latest("created_at")
    assert registro.payload["replaced"] is True


def test_dois_tipos_convivem_na_mesma_inscricao(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    enviar(client_do_aluno, inscricao)
    resposta = enviar(
        client_do_aluno,
        inscricao,
        kind=ApplicationDocumentKind.PUBLIC_SERVICE.value,
        file=arquivo("contracheque.pdf"),
    )

    assert resposta.status_code == 201, resposta.content
    assert ApplicationDocument.objects.count() == 2


def test_extensao_recusada_nao_grava_nada(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    resposta = enviar(client_do_aluno, inscricao, file=arquivo("laudo.exe", b"MZ"))

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_document"
    assert not ApplicationDocument.objects.exists()


def test_arquivo_grande_demais_e_recusado(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    grande = arquivo("laudo.pdf", b"x" * (TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO + 1))

    resposta = enviar(client_do_aluno, inscricao, file=grande)

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_document"


def test_o_colega_nao_anexa_na_inscricao_alheia(
    client: Client, inscricao: ScholarshipApplication, colega: Student
):
    resposta = enviar(logar(client, colega), inscricao)

    assert resposta.status_code == 403, resposta.content
    assert resposta.json()["code"] == "not_application_owner"
    assert not ApplicationDocument.objects.exists()


def test_a_secretaria_nao_anexa_no_lugar_do_candidato(
    client_da_secretaria: Client, inscricao: ScholarshipApplication
):
    resposta = enviar(client_da_secretaria, inscricao)

    assert resposta.status_code == 403, resposta.content


def test_fora_da_janela_o_anexo_e_recusado(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    edicao: ScholarshipEdition,
):
    edicao.status = ScholarshipEditionStatus.UNDER_REVIEW
    edicao.save(update_fields=["status"])

    resposta = enviar(client_do_aluno, inscricao)

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "submissions_closed"


# --- download --------------------------------------------------------------


@pytest.fixture
def documento(inscricao: ScholarshipApplication) -> ApplicationDocument:
    """Gravado pelo ORM, e não pela rota de upload: a fixture do upload
    faria `force_login` no MESMO `client` que o teste de download usa
    para outro papel, e a última sessão a ser montada venceria — o teste
    passaria dizendo que a Coordenação baixa o que na verdade a candidata
    baixou.
    """
    return ApplicationDocument.objects.create(
        application=inscricao,
        kind=ApplicationDocumentKind.AFFIRMATIVE_ACTION,
        file=arquivo(),
    )


def conteudo(resposta: Any) -> bytes:
    """O corpo do `FileResponse`, que chega em pedaços (`streaming_content`
    não está no tipo do cliente de teste, daí o `Any`)."""
    return b"".join(resposta.streaming_content)


def url_download(documento: ApplicationDocument) -> str:
    return f"/api/v1/scholarships/documents/{documento.pk}/download"


def test_o_proprio_candidato_baixa_o_que_enviou(
    client_do_aluno: Client, documento: ApplicationDocument
):
    """Por posse, sem precisar da permissão de secretaria."""
    resposta = client_do_aluno.get(url_download(documento))

    assert resposta.status_code == 200, resposta.content
    assert conteudo(resposta) == b"%PDF-1.4 laudo"
    assert "laudo.pdf" in resposta["Content-Disposition"]


def test_a_secretaria_baixa_e_o_acesso_fica_registrado(
    client_da_secretaria: Client,
    documento: ApplicationDocument,
    inscricao: ScholarshipApplication,
):
    resposta = client_da_secretaria.get(url_download(documento))

    assert resposta.status_code == 200, resposta.content
    registro = AuditLog.objects.get(event="scholarships.application.document_download")
    assert registro.target_id == str(inscricao.pk)
    assert registro.payload["document_id"] == documento.pk


def test_a_comissao_baixa_para_conferir(
    client: Client, program: Program, documento: ApplicationDocument
):
    client.force_login(usuario_com_papel(program, "Comissão de Bolsas", "elisa"))

    assert client.get(url_download(documento)).status_code == 200


def test_quem_ve_a_inscricao_sem_a_permissao_de_download_leva_403(
    client_da_coordenacao: Client, documento: ApplicationDocument
):
    resposta = client_da_coordenacao.get(url_download(documento))

    assert resposta.status_code == 403, resposta.content
    assert not AuditLog.objects.filter(
        event="scholarships.application.document_download"
    ).exists()


def test_o_colega_nao_baixa_o_documento_alheio(
    client: Client, colega: Student, documento: ApplicationDocument
):
    resposta = logar(client, colega).get(url_download(documento))

    assert resposta.status_code == 403, resposta.content


def test_documento_de_outro_programa_nao_existe(
    client_da_secretaria: Client, documento: ApplicationDocument
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    documento.application.program = outro
    documento.application.edition.program = outro
    documento.application.edition.save(update_fields=["program"])
    documento.application.save(update_fields=["program"])

    resposta = client_da_secretaria.get(url_download(documento))

    assert resposta.status_code == 404, resposta.content
