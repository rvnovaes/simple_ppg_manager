"""A secretaria monta o edital de seleção pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. O conjunto canônico por recurso roda aqui — 201 + auditoria,
payload não escolhe tenant, duplicata com `code` estável, 403 sem
permissão, 401 sem sessão, 404 de outro programa, CSRF — mais o que é
próprio do edital: publicar cobra etapa, vaga e template.

O dado é criado nos DOIS programas em todo teste de escopo: com um só
programa semeado, um vazamento de tenant passa despercebido.
"""

from datetime import UTC, datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program
from apps.selection.models import (
    QuotaCategory,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionProcessStatus,
    SelectionStage,
    Vacancy,
)

pytestmark = pytest.mark.django_db

EDITAIS = "/api/v1/selection/processes/"


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
def outro_programa(db) -> Program:
    return Program.objects.create(name="Outro programa", acronym="PPGX")


def corpo(**extra) -> dict:
    dados = {
        "kind": SelectionKind.REGULAR.value,
        "year": 2028,
        "title": "Edital Regular 2028",
        "submission_opens_at": "2027-09-01T00:00:00Z",
        "submission_closes_at": "2027-09-30T00:00:00Z",
    }
    dados.update(extra)
    return dados


def _post(client: Client, url: str, dados: dict):
    return client.post(url, data=dados, content_type="application/json")


def _patch(client: Client, url: str, dados: dict):
    return client.patch(url, data=dados, content_type="application/json")


def criar_edital(program: Program, **extra) -> SelectionProcess:
    """Edital em rascunho, direto no banco, para os testes que não exercitam
    a criação pela rota."""
    campos = {
        "kind": SelectionKind.REGULAR,
        "year": 2029,
        "title": "Edital Regular 2029",
        "submission_opens_at": datetime(2028, 9, 1, tzinfo=UTC),
        "submission_closes_at": datetime(2028, 9, 30, tzinfo=UTC),
    }
    campos.update(extra)
    return SelectionProcess.objects.create(program=program, **campos)


def completar(edital: SelectionProcess, projeto: CollectiveProject) -> None:
    """Dá ao edital o que `publish_process` cobra: etapa, vaga e template."""
    SelectionStage.objects.create(process=edital, name="Prova oral", order=1)
    Vacancy.objects.create(
        program=edital.program,
        process=edital,
        level=SelectionLevel.MASTERS,
        project=projeto,
        quota_category=QuotaCategory.OPEN,
        quantity=5,
    )
    edital.convocation_subject = "Convocação — {etapa}"
    edital.convocation_body = "Prezado(a) {nome}, compareça em {data_hora}."
    edital.save()


# --- criação ---------------------------------------------------------------


def test_cria_o_edital_em_rascunho_e_registra_auditoria(
    client_da_secretaria: Client, program: Program
):
    resposta = _post(client_da_secretaria, EDITAIS, corpo())

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["status"] == SelectionProcessStatus.DRAFT.value
    assert dados["status_label"] == "Rascunho"
    assert dados["kind_label"] == "Regular"
    assert dados["submission_open"] is False
    assert dados["stage_count"] == 0
    assert dados["vacancy_count"] == 0
    assert dados["notice_url"] == ""
    edital = SelectionProcess.objects.get(pk=dados["id"])
    assert edital.program_id == program.pk
    assert edital.published_at is None
    registro = AuditLog.objects.get(event="selection.process.create")
    assert registro.program_id == program.pk
    assert registro.target_id == str(edital.pk)


def test_payload_nao_escolhe_o_programa_do_edital(
    client_da_secretaria: Client, program: Program, outro_programa: Program
):
    resposta = _post(client_da_secretaria, EDITAIS, corpo(program_id=outro_programa.pk))

    assert resposta.status_code == 201, resposta.content
    assert (
        SelectionProcess.objects.get(pk=resposta.json()["id"]).program_id == program.pk
    )


def test_janela_fora_de_ordem_e_400(client_da_secretaria: Client):
    resposta = _post(
        client_da_secretaria,
        EDITAIS,
        corpo(submission_closes_at="2027-08-01T00:00:00Z"),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_submission_window"


def test_segundo_edital_do_mesmo_tipo_e_ano_e_400(
    client_da_secretaria: Client, program: Program
):
    criar_edital(program, year=2028)

    resposta = _post(client_da_secretaria, EDITAIS, corpo(year=2028))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_process"


def test_o_mesmo_ano_em_outro_programa_nao_e_duplicata(
    client_da_secretaria: Client, outro_programa: Program
):
    criar_edital(outro_programa, year=2028)

    assert _post(client_da_secretaria, EDITAIS, corpo(year=2028)).status_code == 201


def test_criar_edital_sem_permissao_e_403(client_sem_permissao: Client):
    resposta = _post(client_sem_permissao, EDITAIS, corpo())

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_edital_sem_sessao_e_401(client: Client):
    assert _post(client, EDITAIS, corpo()).status_code == 401


def test_escrita_sem_token_csrf_e_recusada(secretaria: User, program: Program):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    assert _post(client, EDITAIS, corpo()).status_code == 403
    assert not SelectionProcess.objects.filter(year=2028).exists()


# --- leitura ---------------------------------------------------------------


def test_lista_so_os_editais_do_programa_da_sessao(
    client_da_secretaria: Client, program: Program, outro_programa: Program
):
    meu = criar_edital(program)
    alheio = criar_edital(outro_programa)

    resposta = client_da_secretaria.get(EDITAIS)

    assert resposta.status_code == 200
    ids = [item["id"] for item in resposta.json()["items"]]
    assert ids == [meu.pk]
    assert alheio.pk not in ids


def test_lista_filtra_por_tipo_status_e_ano(
    client_da_secretaria: Client, program: Program
):
    regular = criar_edital(program, kind=SelectionKind.REGULAR, year=2029)
    criar_edital(program, kind=SelectionKind.SUPPLEMENTARY, year=2029)

    resposta = client_da_secretaria.get(
        f"{EDITAIS}?kind=regular&status=draft&year=2029"
    )

    assert [item["id"] for item in resposta.json()["items"]] == [regular.pk]


def test_detalhe_traz_as_contagens_de_etapa_e_vaga(
    client_da_secretaria: Client, program: Program, projeto: CollectiveProject
):
    edital = criar_edital(program)
    completar(edital, projeto)

    dados = client_da_secretaria.get(f"{EDITAIS}{edital.pk}/").json()

    assert dados["stage_count"] == 1
    assert dados["vacancy_count"] == 1


def test_ver_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio = criar_edital(outro_programa)

    assert client_da_secretaria.get(f"{EDITAIS}{alheio.pk}/").status_code == 404


# --- edição ----------------------------------------------------------------


def test_altera_o_edital_em_rascunho(client_da_secretaria: Client, program: Program):
    edital = criar_edital(program)

    resposta = _patch(
        client_da_secretaria,
        f"{EDITAIS}{edital.pk}/",
        {"title": "Edital Regular 2029 — retificado"},
    )

    assert resposta.status_code == 200, resposta.content
    edital.refresh_from_db()
    assert edital.title == "Edital Regular 2029 — retificado"
    registro = AuditLog.objects.get(event="selection.process.update")
    assert registro.payload["fields"] == ["title"]


def test_alterar_edital_publicado_e_409(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    resposta = _patch(
        client_da_secretaria, f"{EDITAIS}{edital_regular.pk}/", {"title": "Outro"}
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_editable"


def test_alterar_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio = criar_edital(outro_programa)

    resposta = _patch(client_da_secretaria, f"{EDITAIS}{alheio.pk}/", {"title": "X"})

    assert resposta.status_code == 404


def test_alterar_sem_permissao_e_403(client_sem_permissao: Client, program: Program):
    edital = criar_edital(program)

    resposta = _patch(client_sem_permissao, f"{EDITAIS}{edital.pk}/", {"title": "X"})

    assert resposta.status_code == 403


# --- publicar e encerrar ---------------------------------------------------


def test_publica_o_edital_completo(
    client_da_secretaria: Client, program: Program, projeto: CollectiveProject
):
    edital = criar_edital(program)
    completar(edital, projeto)

    resposta = client_da_secretaria.post(f"{EDITAIS}{edital.pk}/publish")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["status"] == SelectionProcessStatus.PUBLISHED.value
    edital.refresh_from_db()
    assert edital.published_at is not None
    registro = AuditLog.objects.get(event="selection.process.publish")
    assert registro.program_id == program.pk


@pytest.mark.parametrize("faltando", ["etapa", "vaga", "template"])
def test_publicar_edital_incompleto_e_400(
    client_da_secretaria: Client,
    program: Program,
    projeto: CollectiveProject,
    faltando: str,
):
    edital = criar_edital(program)
    completar(edital, projeto)
    if faltando == "etapa":
        edital.stages.all().delete()
    elif faltando == "vaga":
        edital.vacancies.all().delete()
    else:
        edital.convocation_body = ""
        edital.save()

    resposta = client_da_secretaria.post(f"{EDITAIS}{edital.pk}/publish")

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "process_incomplete"
    edital.refresh_from_db()
    assert edital.is_draft
    assert not AuditLog.objects.filter(event="selection.process.publish").exists()


def test_publicar_duas_vezes_e_409(
    client_da_secretaria: Client, program: Program, projeto: CollectiveProject
):
    edital = criar_edital(program)
    completar(edital, projeto)
    client_da_secretaria.post(f"{EDITAIS}{edital.pk}/publish")

    resposta = client_da_secretaria.post(f"{EDITAIS}{edital.pk}/publish")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_draft"


def test_encerra_o_edital_publicado(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    resposta = client_da_secretaria.post(f"{EDITAIS}{edital_regular.pk}/close")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["status"] == SelectionProcessStatus.CLOSED.value
    edital_regular.refresh_from_db()
    assert edital_regular.closed_at is not None
    assert AuditLog.objects.filter(event="selection.process.close").exists()


def test_encerrar_edital_em_rascunho_e_409(
    client_da_secretaria: Client, program: Program
):
    edital = criar_edital(program)

    resposta = client_da_secretaria.post(f"{EDITAIS}{edital.pk}/close")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_published"


def test_publicar_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio = criar_edital(outro_programa)

    assert client_da_secretaria.post(f"{EDITAIS}{alheio.pk}/publish").status_code == 404


# --- arquivo do edital -----------------------------------------------------


def pdf(nome: str = "edital.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        nome, b"%PDF-1.4 conteudo", content_type="application/pdf"
    )


def test_anexa_o_pdf_do_edital(client_da_secretaria: Client, program: Program):
    edital = criar_edital(program)

    resposta = client_da_secretaria.post(
        f"{EDITAIS}{edital.pk}/notice-file", {"file": pdf()}
    )

    assert resposta.status_code == 200, resposta.content
    dados = resposta.json()
    assert dados["notice_filename"].endswith(".pdf")
    assert dados["notice_url"] != ""
    edital.refresh_from_db()
    assert (edital.notice_file.name or "").startswith(f"selecao/edital-{edital.pk}/")
    registro = AuditLog.objects.get(event="selection.process.notice_file")
    assert registro.payload["replaced"] is False


def test_reenviar_o_pdf_substitui_o_anterior(
    client_da_secretaria: Client, program: Program
):
    edital = criar_edital(program)
    client_da_secretaria.post(f"{EDITAIS}{edital.pk}/notice-file", {"file": pdf()})

    resposta = client_da_secretaria.post(
        f"{EDITAIS}{edital.pk}/notice-file", {"file": pdf("retificado.pdf")}
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["notice_filename"].startswith("retificado")
    registros = AuditLog.objects.filter(event="selection.process.notice_file").order_by(
        "id"
    )
    assert [r.payload["replaced"] for r in registros] == [False, True]


def test_arquivo_que_nao_e_pdf_e_400(client_da_secretaria: Client, program: Program):
    edital = criar_edital(program)

    resposta = client_da_secretaria.post(
        f"{EDITAIS}{edital.pk}/notice-file",
        {"file": SimpleUploadedFile("edital.exe", b"binario")},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_notice_file"
    edital.refresh_from_db()
    assert not edital.notice_file


def test_anexar_pdf_em_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio = criar_edital(outro_programa)

    resposta = client_da_secretaria.post(
        f"{EDITAIS}{alheio.pk}/notice-file", {"file": pdf()}
    )

    assert resposta.status_code == 404


def test_pdf_do_edital_publicado_pode_ser_trocado(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    """Retificar o PDF não muda vaga nem etapa — `ensure_editable` não vale
    aqui, ao contrário do PATCH."""
    resposta = client_da_secretaria.post(
        f"{EDITAIS}{edital_regular.pk}/notice-file", {"file": pdf()}
    )

    assert resposta.status_code == 200, resposta.content


def test_criar_edital_com_ano_e_tipo_do_outro_programa_nao_vaza(
    client_da_secretaria: Client, outro_programa: Program, program: Program
):
    criar_edital(outro_programa, year=2030, kind=SelectionKind.SUPPLEMENTARY)

    resposta = _post(
        client_da_secretaria,
        EDITAIS,
        corpo(year=2030, kind=SelectionKind.SUPPLEMENTARY.value),
    )

    assert resposta.status_code == 201
    assert SelectionProcess.objects.filter(year=2030).count() == 2
