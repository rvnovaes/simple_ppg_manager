"""A fila de atas de um edital, como a secretaria a acompanha.

Nível (b) da pirâmide (Seção 9). O que este arquivo guarda, e nenhum
outro guarda:

- **a listagem é do edital, não do programa** — `process_id` é
  obrigatório e passa pelo escopo antes da consulta, então edital de
  outro tenant é 404 e não uma lista vazia (que pareceria "este edital
  não tem ata");
- **as versões antigas aparecem** — a retificação guarda a anterior como
  `superseded`, e é a secretaria quem precisa enxergar que houve uma;
- **o PDF só existe depois de assinado**, e baixá-lo grava `AuditLog`:
  auditar leitura é exceção no projeto, e aqui é obrigatório.

O reenvio do token do externo — o outro poder da secretaria sobre a ata —
mora em `test_api_assinatura_token.py`, junto do que ele invalida.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from django.core.files.base import ContentFile
from django.test import Client

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program
from apps.selection.models import (
    Application,
    Board,
    ExaminationRecord,
    RecordStatus,
    SelectionProcess,
    StageScore,
)
from apps.selection.services import freeze_record

pytestmark = pytest.mark.django_db

ATAS = "/api/v1/selection/records/"


def pdf_de(record_id: int) -> str:
    return f"/api/v1/selection/records/{record_id}/pdf"


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


@pytest.fixture
def banca_com_externo(banca_regular: Board, professores: list[Teacher]) -> Board:
    """A mesma banca, com o externo como titular — é ele que assina por
    token, e é o token que a secretaria reemite."""
    banca_regular.member_2, banca_regular.alternate = professores[3], professores[2]
    banca_regular.clean()
    banca_regular.save()
    return banca_regular


@pytest.fixture
def ata_congelada(
    banca_com_externo: Board,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    django_capture_on_commit_callbacks,
    settings,
) -> ExaminationRecord:
    """Ata aguardando as três assinaturas, com o token do externo enviado.

    O `django_capture_on_commit_callbacks(execute=True)` não é detalhe: o
    e-mail sai em `transaction.on_commit`, e sem ele `token_sent_at`
    ficaria nulo e o teste passaria verde sem nada ter sido enviado.
    """
    settings.SITE_URL = "https://ppgd.exemplo.br"
    with django_capture_on_commit_callbacks(execute=True):
        freeze_record(record=ata_regular)
    ata_regular.refresh_from_db()
    return ata_regular


def _ata(
    banca: Board,
    ordem: int,
    *,
    status: str = RecordStatus.DRAFT,
    version: int = 1,
    supersedes: ExaminationRecord | None = None,
) -> ExaminationRecord:
    """Uma ata daquela etapa da banca, sem passar pelos services.

    O que se testa aqui é a leitura: montar o estado direto é o caminho
    mais curto para ter, no mesmo edital, uma ata de cada situação — e
    congelar de verdade exigiria nota, banca e ordem de etapa, que os
    testes do ciclo já cobrem.
    """
    ata = ExaminationRecord(
        program=banca.program,
        process=banca.process,
        stage=banca.process.stages.get(order=ordem),
        level=banca.level,
        project=banca.project,
        board=banca,
        status=status,
        version=version,
        supersedes=supersedes,
    )
    ata.save()
    return ata


def listar(client: Client, **query):
    return client.get(ATAS, query)


def conteudo(resposta: Any) -> bytes:
    """O corpo do `FileResponse`, que chega em pedaços (`streaming_content`
    não está no tipo do cliente de teste, daí o `Any`)."""
    return b"".join(resposta.streaming_content)


# --- GET /records/ ---------------------------------------------------------


def test_lista_traz_a_ata_do_edital_com_situacao_e_assinaturas(
    client_da_secretaria: Client,
    banca_regular: Board,
    ata_regular: ExaminationRecord,
    edital_regular: SelectionProcess,
):
    resposta = listar(client_da_secretaria, process_id=edital_regular.pk)

    assert resposta.status_code == 200, resposta.content
    (linha,) = resposta.json()["items"]
    assert linha["id"] == ata_regular.pk
    assert linha["status"] == RecordStatus.DRAFT
    assert linha["status_label"] == ata_regular.get_status_display()
    assert linha["stage_name"] == ata_regular.stage.name
    assert linha["level_label"] == "Mestrado"
    assert linha["target_label"] == str(banca_regular.project)
    assert linha["version"] == 1
    assert linha["has_pdf"] is False
    # Rascunho ainda não tem assinatura: elas nascem no congelamento.
    assert linha["signatures"] == []
    assert linha["pending_signatures"] == 0


def test_lista_nao_carrega_o_conteudo_da_ata(
    client_da_secretaria: Client,
    ata_regular: ExaminationRecord,
    edital_regular: SelectionProcess,
):
    """`content` é a planilha inteira de cada alvo — quem quer as notas
    abre a ata ou o PDF, não a fila do edital."""
    (linha,) = listar(client_da_secretaria, process_id=edital_regular.pk).json()[
        "items"
    ]

    assert "content" not in linha
    assert linha["content_hash"] == ""


def test_lista_mostra_as_assinaturas_com_nome_metodo_e_datas(
    client_da_secretaria: Client,
    banca_com_externo: Board,
    ata_congelada: ExaminationRecord,
    externo,
    edital_regular: SelectionProcess,
):
    (linha,) = listar(client_da_secretaria, process_id=edital_regular.pk).json()[
        "items"
    ]

    assert linha["status"] == RecordStatus.AWAITING_SIGNATURES
    assert linha["pending_signatures"] == 3
    do_externo = next(
        a for a in linha["signatures"] if a["signer_name"] == externo.person.full_name
    )
    assert do_externo["method"] == "token"
    assert do_externo["signed"] is False
    assert do_externo["signed_at"] is None
    assert do_externo["token_sent_at"] is not None
    assert do_externo["token_expires_at"] is not None
    # O segredo não viaja: o que a secretaria vê é que o e-mail saiu.
    assert "token_hash" not in do_externo


def test_lista_traz_as_versoes_antigas_com_a_vigente_primeiro(
    client_da_secretaria: Client,
    banca_regular: Board,
    ata_regular: ExaminationRecord,
    edital_regular: SelectionProcess,
):
    ata_regular.status = RecordStatus.SUPERSEDED
    ata_regular.save(update_fields=["status"])
    versao_2 = _ata(banca_regular, 1, version=2, supersedes=ata_regular)

    itens = listar(client_da_secretaria, process_id=edital_regular.pk).json()["items"]

    assert [i["id"] for i in itens] == [versao_2.pk, ata_regular.pk]
    assert [i["version"] for i in itens] == [2, 1]


def test_lista_ordena_pela_ordem_das_etapas(
    client_da_secretaria: Client,
    banca_regular: Board,
    ata_regular: ExaminationRecord,
    edital_regular: SelectionProcess,
):
    da_etapa_2 = _ata(banca_regular, 2)

    itens = listar(client_da_secretaria, process_id=edital_regular.pk).json()["items"]

    assert [i["id"] for i in itens] == [ata_regular.pk, da_etapa_2.pk]


def test_filtra_por_etapa(
    client_da_secretaria: Client,
    banca_regular: Board,
    ata_regular: ExaminationRecord,
    edital_regular: SelectionProcess,
):
    da_etapa_2 = _ata(banca_regular, 2)

    itens = listar(
        client_da_secretaria,
        process_id=edital_regular.pk,
        stage_id=da_etapa_2.stage_id,
    ).json()["items"]

    assert [i["id"] for i in itens] == [da_etapa_2.pk]


def test_filtra_por_situacao(
    client_da_secretaria: Client,
    banca_regular: Board,
    ata_regular: ExaminationRecord,
    edital_regular: SelectionProcess,
):
    assinada = _ata(banca_regular, 2, status=RecordStatus.SIGNED)

    itens = listar(
        client_da_secretaria,
        process_id=edital_regular.pk,
        status=RecordStatus.SIGNED.value,
    ).json()["items"]

    assert [i["id"] for i in itens] == [assinada.pk]


def test_etapa_de_outro_edital_e_404(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    edital_suplementar: SelectionProcess,
):
    de_fora = edital_suplementar.stages.get(order=1)

    resposta = listar(
        client_da_secretaria, process_id=edital_regular.pk, stage_id=de_fora.pk
    )

    assert resposta.status_code == 404


def test_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    """404 e não lista vazia: vazio diria "este edital não tem ata", que
    é resposta diferente de "este edital não é seu"."""
    alheio = SelectionProcess.objects.create(
        program=outro_programa,
        kind="regular",
        year=2027,
        title="Edital de outro programa",
        submission_opens_at=datetime(2026, 1, 1, tzinfo=UTC),
        submission_closes_at=datetime(2026, 12, 31, tzinfo=UTC),
    )

    assert listar(client_da_secretaria, process_id=alheio.pk).status_code == 404


def test_process_id_e_obrigatorio(client_da_secretaria: Client):
    assert listar(client_da_secretaria).status_code == 422


def test_lista_sem_permissao_e_403(
    client_sem_permissao: Client, edital_regular: SelectionProcess
):
    assert listar(client_sem_permissao, process_id=edital_regular.pk).status_code == 403


def test_lista_sem_sessao_e_401(client: Client, edital_regular: SelectionProcess):
    assert listar(client, process_id=edital_regular.pk).status_code == 401


# --- GET /records/{id}/pdf -------------------------------------------------


@pytest.fixture
def ata_com_pdf(ata_regular: ExaminationRecord) -> ExaminationRecord:
    ata_regular.status = RecordStatus.SIGNED
    ata_regular.save(update_fields=["status"])
    ata_regular.pdf.save("ata.pdf", ContentFile(b"%PDF-1.4 ata"), save=True)
    return ata_regular


def test_baixa_o_pdf_como_anexo(
    client_da_secretaria: Client, ata_com_pdf: ExaminationRecord
):
    resposta = client_da_secretaria.get(pdf_de(ata_com_pdf.pk))

    assert resposta.status_code == 200, resposta.content
    assert resposta["Content-Disposition"].startswith("attachment;")
    assert conteudo(resposta) == b"%PDF-1.4 ata"


def test_baixar_o_pdf_grava_auditoria(
    client_da_secretaria: Client, ata_com_pdf: ExaminationRecord, program: Program
):
    """Auditar leitura é exceção no projeto: o PDF registra a decisão da
    banca sobre pessoas, e quem o baixou é parte do rastro."""
    client_da_secretaria.get(pdf_de(ata_com_pdf.pk))

    registro = AuditLog.objects.get(event="selection.record.pdf_download")
    assert registro.program_id == program.pk
    assert registro.target_id == str(ata_com_pdf.pk)
    assert registro.payload["version"] == 1


def test_ata_sem_pdf_e_404(
    client_da_secretaria: Client, ata_regular: ExaminationRecord
):
    """Rascunho não é documento: não há PDF para imprimir antes das três
    assinaturas."""
    assert client_da_secretaria.get(pdf_de(ata_regular.pk)).status_code == 404
    assert not AuditLog.objects.filter(event="selection.record.pdf_download").exists()


def test_pdf_de_ata_de_outro_programa_e_404(
    client_da_secretaria: Client,
    outro_programa: Program,
    ata_com_pdf: ExaminationRecord,
):
    """O tenant é o único campo mexido: é exatamente ele que `for_program`
    filtra, e trocá-lo isola o que este teste quer provar."""
    ExaminationRecord.objects.filter(pk=ata_com_pdf.pk).update(program=outro_programa)

    assert client_da_secretaria.get(pdf_de(ata_com_pdf.pk)).status_code == 404


def test_pdf_sem_permissao_e_403(
    client_sem_permissao: Client, ata_com_pdf: ExaminationRecord
):
    assert client_sem_permissao.get(pdf_de(ata_com_pdf.pk)).status_code == 403


def test_pdf_sem_sessao_e_401(client: Client, ata_com_pdf: ExaminationRecord):
    assert client.get(pdf_de(ata_com_pdf.pk)).status_code == 401
