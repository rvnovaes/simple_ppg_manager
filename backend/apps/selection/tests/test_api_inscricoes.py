"""A secretaria confere as inscrições do edital pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. Além do conjunto canônico (auditoria, 403, 401, 404 de outro
programa, CSRF), o que é próprio da inscrição: os filtros e a busca da
tela, as transições (homologar/indeferir, e o 409 de decidir duas vezes)
e o download do anexo — a única leitura auditada do módulo, atrás de uma
permissão que só a Secretaria tem.
"""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Application,
    ApplicationDocument,
    ApplicationDocumentKind,
    ApplicationStatus,
    QuotaCategory,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    gerar_protocolo,
)

pytestmark = pytest.mark.django_db

INSCRICOES = "/api/v1/selection/applications/"
SENHA = "senha-de-teste-123"


def inscricao_de(application_id: int) -> str:
    return f"{INSCRICOES}{application_id}/"


def download_de(document_id: int) -> str:
    return f"{INSCRICOES}documents/{document_id}/download"


@pytest.fixture
def client_da_secretaria(client: Client, secretaria: User, program: Program) -> Client:
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client.force_login(secretaria)
    return client


@pytest.fixture
def coordenacao(program: Program) -> User:
    """Papel que vê a inscrição mas não baixa o anexo — é ele que prova
    que `download_applicationdocument` separa as duas coisas."""
    user = User.objects.create_user(username="coordenacao", password=SENHA)
    user.groups.add(Group.objects.get(name="Coordenação"))
    Person.objects.create(
        program=program,
        user=user,
        full_name="Décio Prado",
        primary_email="decio@exemplo.br",
    )
    return user


@pytest.fixture
def client_da_coordenacao(client: Client, coordenacao: User) -> Client:
    client.force_login(coordenacao)
    return client


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Outro programa", acronym="PPGX")


def edital_alheio(
    outro_programa: Program,
) -> tuple[SelectionProcess, CollectiveProject]:
    """Edital publicado de outro programa, com projeto próprio: o alvo é
    XOR no banco, então a inscrição alheia também precisa de um."""
    edital = SelectionProcess.objects.create(
        program=outro_programa,
        kind=SelectionKind.REGULAR,
        year=2029,
        title="Edital alheio",
        submission_opens_at="2028-09-01T00:00:00Z",
        submission_closes_at="2028-09-30T00:00:00Z",
    )
    projeto = CollectiveProject.objects.create(
        program=outro_programa,
        research_line=ResearchLine.objects.create(
            program=outro_programa, name="Linha alheia"
        ),
        name="Projeto alheio",
    )
    return edital, projeto


def criar_inscricao(
    program: Program,
    edital: SelectionProcess,
    *,
    nome: str = "Bruno Costa",
    cpf: str = "39053344705",
    **extra,
) -> Application:
    """Inscrição recém-enviada (`submitted`) — o estado em que a
    secretaria a encontra para conferir."""
    campos = {
        "level": SelectionLevel.MASTERS,
        "quota_category": QuotaCategory.OPEN,
        "project": None,
        "research_line": None,
    }
    campos.update(extra)
    return Application.objects.create(
        program=program,
        process=edital,
        protocol=gerar_protocolo(edital),
        full_name=nome,
        email="bruno@exemplo.br",
        cpf=cpf,
        birth_date=date(1994, 3, 12),
        submitted_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
        **campos,
    )


def anexar(inscricao: Application, kind: str = ApplicationDocumentKind.IDENTITY):
    return ApplicationDocument.objects.create(
        application=inscricao,
        kind=kind,
        file=SimpleUploadedFile(f"{kind}.pdf", b"%PDF-1.4 conteudo"),
    )


def _post(client: Client, url: str, dados: dict | None = None):
    return client.post(url, data=dados or {}, content_type="application/json")


def conteudo(resposta: Any) -> bytes:
    """O corpo do `FileResponse`, que chega em pedaços (`streaming_content`
    não está no tipo do cliente de teste, daí o `Any`)."""
    return b"".join(resposta.streaming_content)


def itens(resposta) -> list[dict]:
    """A listagem de inscrições é paginada, como a de editais e bancas."""
    return resposta.json()["items"]


# --- listagem, filtros e busca ---------------------------------------------


def test_lista_so_as_inscricoes_do_programa_da_sessao(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    outro_programa: Program,
):
    minha = criar_inscricao(program, edital_regular, project=projeto)
    alheio, projeto_alheio = edital_alheio(outro_programa)
    criar_inscricao(
        outro_programa,
        alheio,
        nome="Alheia",
        cpf="52998224725",
        project=projeto_alheio,
    )

    resposta = client_da_secretaria.get(INSCRICOES)

    assert resposta.status_code == 200
    assert [linha["id"] for linha in itens(resposta)] == [minha.pk]
    assert itens(resposta)[0]["target_label"] == str(projeto)


def test_filtra_por_edital_status_nivel_cota_e_alvo(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    outro_projeto = CollectiveProject.objects.create(
        program=program,
        research_line=projeto.research_line,
        name="Outro projeto coletivo",
    )
    procurada = criar_inscricao(
        program,
        edital_regular,
        project=projeto,
        level=SelectionLevel.DOCTORATE,
        quota_category=QuotaCategory.RACIAL,
    )
    criar_inscricao(
        program, edital_regular, nome="Outra", cpf="52998224725", project=outro_projeto
    )

    for filtro in (
        f"process_id={edital_regular.pk}&level={SelectionLevel.DOCTORATE.value}",
        f"quota_category={QuotaCategory.RACIAL.value}",
        f"project_id={projeto.pk}",
        f"status={ApplicationStatus.SUBMITTED.value}&project_id={projeto.pk}",
    ):
        resposta = client_da_secretaria.get(f"{INSCRICOES}?{filtro}")

        assert resposta.status_code == 200, filtro
        assert [linha["id"] for linha in itens(resposta)] == [procurada.pk], filtro


def test_filtra_por_linha_de_pesquisa_no_edital_suplementar(
    client_da_secretaria: Client,
    program: Program,
    edital_suplementar: SelectionProcess,
    linha: ResearchLine,
):
    procurada = criar_inscricao(
        program,
        edital_suplementar,
        research_line=linha,
        quota_category=QuotaCategory.QUILOMBOLA,
    )

    resposta = client_da_secretaria.get(
        f"{INSCRICOES}?research_line_id={linha.pk}",
    )

    assert [linha_["id"] for linha_ in itens(resposta)] == [procurada.pk]
    assert itens(resposta)[0]["target_label"] == str(linha)


@pytest.mark.parametrize(
    "termo",
    ["Bruno", "bruno cos", "390.533.447-05", "39053344705"],
)
def test_busca_por_nome_protocolo_ou_cpf(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    termo: str,
):
    procurada = criar_inscricao(program, edital_regular, project=projeto)
    criar_inscricao(
        program,
        edital_regular,
        nome="Zulmira Antunes",
        cpf="52998224725",
        project=projeto,
    )

    resposta = client_da_secretaria.get(f"{INSCRICOES}?search={termo}")

    assert [linha["id"] for linha in itens(resposta)] == [procurada.pk]


def test_busca_pelo_protocolo_exato(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    procurada = criar_inscricao(program, edital_regular, project=projeto)
    criar_inscricao(
        program, edital_regular, nome="Zulmira", cpf="52998224725", project=projeto
    )

    resposta = client_da_secretaria.get(f"{INSCRICOES}?search={procurada.protocol}")

    assert [linha["id"] for linha in itens(resposta)] == [procurada.pk]


def test_listar_inscricoes_sem_permissao_e_403(client_sem_permissao: Client):
    resposta = client_sem_permissao.get(INSCRICOES)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_listar_inscricoes_sem_sessao_e_401(client: Client):
    assert client.get(INSCRICOES).status_code == 401


# --- detalhe ---------------------------------------------------------------


def test_detalhe_traz_documentos_e_o_que_falta(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    candidata = criar_inscricao(program, edital_regular, project=projeto)
    anexar(candidata, ApplicationDocumentKind.IDENTITY)
    anexar(candidata, ApplicationDocumentKind.DIPLOMA)

    resposta = client_da_secretaria.get(inscricao_de(candidata.pk))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [doc["kind"] for doc in corpo["documents"]] == [
        ApplicationDocumentKind.DIPLOMA.value,
        ApplicationDocumentKind.IDENTITY.value,
    ]
    assert corpo["documents"][0]["filename"] == "diploma.pdf"
    assert corpo["documents"][0]["size"] > 0
    # Regular sem cota: identidade, diploma, lattes, pagamento e resumo.
    assert corpo["missing_documents"] == [
        ApplicationDocumentKind.LATTES.value,
        ApplicationDocumentKind.PAYMENT_RECEIPT.value,
        ApplicationDocumentKind.EXPANDED_ABSTRACT.value,
    ]
    assert corpo["cpf"] == candidata.cpf


def test_detalhe_de_inscricao_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio, projeto_alheio = edital_alheio(outro_programa)
    alheia = criar_inscricao(outro_programa, alheio, project=projeto_alheio)

    resposta = client_da_secretaria.get(inscricao_de(alheia.pk))

    assert resposta.status_code == 404


# --- homologar e indeferir -------------------------------------------------


def test_homologa_a_inscricao_e_registra_auditoria(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    candidata = criar_inscricao(program, edital_regular, project=projeto)

    resposta = _post(
        client_da_secretaria,
        f"{inscricao_de(candidata.pk)}homologate",
        {"note": "Documentação conferida."},
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == ApplicationStatus.HOMOLOGATED.value
    candidata.refresh_from_db()
    assert candidata.status == ApplicationStatus.HOMOLOGATED
    assert candidata.decision_note == "Documentação conferida."
    assert candidata.decided_at is not None
    registro = AuditLog.objects.get(event="selection.application.homologate")
    assert registro.program_id == program.pk
    assert registro.target_id == str(candidata.pk)
    assert registro.payload["protocol"] == candidata.protocol


def test_homologa_sem_nota(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    candidata = criar_inscricao(program, edital_regular, project=projeto)

    resposta = _post(
        client_da_secretaria, f"{inscricao_de(candidata.pk)}homologate", {}
    )

    assert resposta.status_code == 200
    candidata.refresh_from_db()
    assert candidata.status == ApplicationStatus.HOMOLOGATED


def test_indefere_com_justificativa(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    candidata = criar_inscricao(program, edital_regular, project=projeto)

    resposta = _post(
        client_da_secretaria,
        f"{inscricao_de(candidata.pk)}reject",
        {"note": "Diploma ilegível."},
    )

    assert resposta.status_code == 200
    candidata.refresh_from_db()
    assert candidata.status == ApplicationStatus.REJECTED
    assert candidata.decision_note == "Diploma ilegível."
    assert AuditLog.objects.filter(event="selection.application.reject").exists()


@pytest.mark.parametrize("nota", ["", "   "])
def test_indeferir_sem_justificativa_e_recusado(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    nota: str,
):
    candidata = criar_inscricao(program, edital_regular, project=projeto)

    resposta = _post(
        client_da_secretaria, f"{inscricao_de(candidata.pk)}reject", {"note": nota}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "rejection_requires_note"
    candidata.refresh_from_db()
    assert candidata.status == ApplicationStatus.SUBMITTED


def test_decidir_duas_vezes_e_409(client_da_secretaria: Client, inscricao: Application):
    """A fixture `inscricao` já está homologada."""
    resposta = _post(
        client_da_secretaria, f"{inscricao_de(inscricao.pk)}homologate", {}
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "application_not_submitted"


def test_homologar_sem_permissao_e_403(
    client_da_coordenacao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """Coordenação lê tudo do módulo e não decide nada."""
    candidata = criar_inscricao(program, edital_regular, project=projeto)

    resposta = _post(
        client_da_coordenacao, f"{inscricao_de(candidata.pk)}homologate", {}
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    candidata.refresh_from_db()
    assert candidata.status == ApplicationStatus.SUBMITTED


def test_homologar_sem_sessao_e_401(client: Client, inscricao: Application):
    resposta = _post(client, f"{inscricao_de(inscricao.pk)}homologate", {})

    assert resposta.status_code == 401


def test_homologar_sem_token_csrf_e_recusado(
    secretaria: User,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    candidata = criar_inscricao(program, edital_regular, project=projeto)
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    resposta = _post(client, f"{inscricao_de(candidata.pk)}homologate", {})

    assert resposta.status_code == 403
    candidata.refresh_from_db()
    assert candidata.status == ApplicationStatus.SUBMITTED


def test_homologar_inscricao_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio, projeto_alheio = edital_alheio(outro_programa)
    alheia = criar_inscricao(outro_programa, alheio, project=projeto_alheio)

    resposta = _post(client_da_secretaria, f"{inscricao_de(alheia.pk)}homologate", {})

    assert resposta.status_code == 404
    alheia.refresh_from_db()
    assert alheia.status == ApplicationStatus.SUBMITTED


# --- download do anexo -----------------------------------------------------


def test_baixa_o_anexo_e_audita_a_leitura(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    candidata = criar_inscricao(program, edital_regular, project=projeto)
    documento = anexar(candidata)

    resposta = client_da_secretaria.get(download_de(documento.pk))

    assert resposta.status_code == 200
    assert conteudo(resposta) == b"%PDF-1.4 conteudo"
    assert "attachment" in resposta["Content-Disposition"]
    registro = AuditLog.objects.get(event="selection.application.document_download")
    assert registro.program_id == program.pk
    assert registro.target_id == str(candidata.pk)
    assert registro.payload["document_id"] == documento.pk
    assert registro.payload["kind"] == ApplicationDocumentKind.IDENTITY.value


def test_baixar_anexo_sem_a_permissao_de_download_e_403(
    client_da_coordenacao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """Coordenação vê a inscrição e a lista de anexos, mas não abre o
    arquivo: identidade e diploma não são insumo de acompanhamento."""
    candidata = criar_inscricao(program, edital_regular, project=projeto)
    documento = anexar(candidata)

    assert client_da_coordenacao.get(inscricao_de(candidata.pk)).status_code == 200

    resposta = client_da_coordenacao.get(download_de(documento.pk))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not AuditLog.objects.filter(
        event="selection.application.document_download"
    ).exists()


def test_baixar_anexo_sem_sessao_e_401(
    client: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    documento = anexar(criar_inscricao(program, edital_regular, project=projeto))

    assert client.get(download_de(documento.pk)).status_code == 401


def test_baixar_anexo_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio, projeto_alheio = edital_alheio(outro_programa)
    documento = anexar(criar_inscricao(outro_programa, alheio, project=projeto_alheio))

    resposta = client_da_secretaria.get(download_de(documento.pk))

    assert resposta.status_code == 404
    assert not AuditLog.objects.filter(
        event="selection.application.document_download"
    ).exists()
