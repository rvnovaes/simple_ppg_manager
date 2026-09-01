"""A convocação de etapa: o lote de e-mails que a secretaria dispara.

Nível (b) da pirâmide (Seção 9). O que este arquivo guarda, e nenhum
outro guarda:

- **o servidor de e-mail nunca derruba o lote.** Uma caixa postal
  inválida marca `failed` naquele destinatário e os demais continuam
  saindo; a rota responde 201 com o resultado por candidato, jamais 500.
- **reexecutar não duplica.** Quem já recebeu e-mail nesta etapa fica de
  fora do lote seguinte — é assim que a secretaria convoca quem foi
  homologado depois do primeiro disparo.
- **da segunda etapa em diante, quem convoca é a ata assinada da
  anterior.** Sem ela não há convocável: chamar antes seria chamar para
  a prova gente que a etapa anterior já eliminou.
- **o texto é o do lote, não o do edital de agora.** Assunto e corpo são
  congelados no disparo, com os placeholders já renderizados.
"""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.test import Client

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    ConvocationEmail,
    EmailDeliveryStatus,
    ExaminationRecord,
    QuotaCategory,
    RecordStatus,
    SelectionLevel,
    SelectionProcess,
    SelectionStage,
    gerar_protocolo,
)

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"


def convocacoes_de(process_id: int, stage_id: int) -> str:
    return f"/api/v1/selection/processes/{process_id}/stages/{stage_id}/convocations"


def convocaveis_de(process_id: int, stage_id: int) -> str:
    return f"/api/v1/selection/processes/{process_id}/stages/{stage_id}/convocable"


def reenvio_de(convocation_id: int) -> str:
    return f"/api/v1/selection/convocations/{convocation_id}/resend"


def lote_de(convocation_id: int) -> str:
    return f"/api/v1/selection/convocations/{convocation_id}"


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
def etapa(edital_regular: SelectionProcess) -> SelectionStage:
    """A primeira etapa, com sessão marcada — é o que os placeholders
    `{data_hora}` e `{local}` renderizam."""
    primeira = edital_regular.stages.get(order=1)
    primeira.session_at = datetime(2026, 3, 10, 14, 30, tzinfo=UTC)
    primeira.location = "Sala 201 — Faculdade de Direito"
    primeira.clean()
    primeira.save()
    return primeira


def criar_inscricao(
    program: Program,
    edital: SelectionProcess,
    nome: str,
    cpf: str,
    projeto: CollectiveProject,
    status: str = ApplicationStatus.HOMOLOGATED,
) -> Application:
    return Application.objects.create(
        program=program,
        process=edital,
        protocol=gerar_protocolo(edital),
        full_name=nome,
        email=f"{cpf}@exemplo.br",
        cpf=cpf,
        birth_date=date(1995, 5, 20),
        level=SelectionLevel.MASTERS,
        project=projeto,
        quota_category=QuotaCategory.OPEN,
        status=status,
        submitted_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
    )


@pytest.fixture
def outra_inscricao(
    program: Program, edital_regular: SelectionProcess, projeto: CollectiveProject
) -> Application:
    return criar_inscricao(
        program, edital_regular, "Bento Melo", "12345678909", projeto
    )


def ata_assinada(
    banca: Board, etapa_da_ata: SelectionStage, conteudo: list[dict[str, Any]]
) -> ExaminationRecord:
    """Ata assinada da etapa, gravada direto: o caminho pela banca já é
    exercido em `test_fechamento_de_etapa.py`, e aqui o que interessa é
    o efeito dela sobre quem pode ser convocado na etapa seguinte."""
    return ExaminationRecord.objects.create(
        program=banca.program,
        process=banca.process,
        stage=etapa_da_ata,
        level=banca.level,
        project=banca.project,
        board=banca,
        status=RecordStatus.SIGNED,
        content=conteudo,
        signed_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
    )


# --- o disparo do lote ------------------------------------------------------


def test_disparo_renderiza_placeholders_e_grava_auditoria(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    resposta = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert (corpo["total"], corpo["sent"], corpo["failed"]) == (1, 1, 0)
    assert corpo["stage_id"] == etapa.pk
    assert corpo["sent_by_name"] == "secretaria"

    assert len(mail.outbox) == 1
    enviado = mail.outbox[0]
    assert enviado.to == [inscricao.email]
    assert enviado.subject == f"Convocação — {etapa.name} — {edital_regular.title}"
    assert inscricao.full_name in enviado.body
    assert inscricao.protocol in enviado.body
    assert "10/03/2026 11:30" in enviado.body  # America/Sao_Paulo
    assert etapa.location in enviado.body

    email = ConvocationEmail.objects.get()
    assert email.status == EmailDeliveryStatus.SENT
    assert email.attempts == 1
    assert email.sent_at is not None
    assert AuditLog.objects.filter(event="selection.convocation.send").count() == 1


def test_texto_do_lote_congela_e_nao_segue_a_edicao_do_edital(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    """O candidato não pode receber duas versões de uma convocação: o
    reenvio manda o texto do disparo, não o template de agora."""
    client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))
    email = ConvocationEmail.objects.get()
    texto_original = email.rendered_body

    edital_regular.convocation_body = "Texto novo para {nome}."
    edital_regular.save(update_fields=["convocation_body"])
    email.refresh_from_db()

    assert email.rendered_body == texto_original
    assert "Texto novo" not in email.rendered_body


def test_falha_de_um_destinatario_nao_derruba_o_lote(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
    outra_inscricao: Application,
):
    """A armadilha central do módulo: SMTP fora do ar não vira 500 nem
    desfaz o lote — vira uma linha `failed` com o motivo."""

    def enviar(self, *args, **kwargs):
        if self.to == [inscricao.email]:
            raise OSError("caixa postal recusada")
        return 1

    with patch("django.core.mail.EmailMessage.send", autospec=True, side_effect=enviar):
        resposta = client_da_secretaria.post(
            convocacoes_de(edital_regular.pk, etapa.pk)
        )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert (corpo["total"], corpo["sent"], corpo["failed"]) == (2, 1, 1)

    falhou = ConvocationEmail.objects.get(application=inscricao)
    assert falhou.status == EmailDeliveryStatus.FAILED
    assert "caixa postal recusada" in falhou.error
    assert falhou.attempts == 1
    assert falhou.sent_at is None
    assert ConvocationEmail.objects.get(application=outra_inscricao).is_sent
    assert AuditLog.objects.filter(event="selection.convocation.email_failed").exists()


def test_reexecucao_convoca_so_quem_ainda_nao_recebeu(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
    program: Program,
    projeto: CollectiveProject,
):
    primeiro = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))
    assert primeiro.json()["total"] == 1

    atrasada = criar_inscricao(
        program, edital_regular, "Bento Melo", "12345678909", projeto
    )
    segundo = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))

    assert segundo.status_code == 201, segundo.content
    assert [e["application_id"] for e in segundo.json()["emails"]] == [atrasada.pk]
    assert ConvocationEmail.objects.filter(application=inscricao).count() == 1
    assert len(mail.outbox) == 2


def test_sem_convocavel_a_rota_recusa_em_vez_de_criar_lote_vazio(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))
    resposta = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "no_convocable_applications"
    assert len(mail.outbox) == 1


def test_inscricao_nao_homologada_nao_e_convocada(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    program: Program,
    projeto: CollectiveProject,
):
    criar_inscricao(
        program,
        edital_regular,
        "Célia Nunes",
        "12345678909",
        projeto,
        status=ApplicationStatus.SUBMITTED,
    )
    resposta = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "no_convocable_applications"


# --- da segunda etapa em diante, quem promove é a ata assinada --------------


def test_segunda_etapa_so_convoca_depois_da_ata_assinada_da_primeira(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    banca_regular: Board,
    inscricao: Application,
):
    segunda = edital_regular.stages.get(order=2)

    sem_ata = client_da_secretaria.post(convocacoes_de(edital_regular.pk, segunda.pk))
    assert sem_ata.status_code == 400, sem_ata.content
    assert sem_ata.json()["code"] == "no_convocable_applications"

    ata_assinada(
        banca_regular,
        edital_regular.stages.get(order=1),
        [{"application_id": inscricao.pk, "full_name": inscricao.full_name}],
    )
    com_ata = client_da_secretaria.post(convocacoes_de(edital_regular.pk, segunda.pk))

    assert com_ata.status_code == 201, com_ata.content
    assert [e["application_id"] for e in com_ata.json()["emails"]] == [inscricao.pk]


def test_eliminada_na_primeira_etapa_nao_e_convocada_na_segunda(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    banca_regular: Board,
    inscricao: Application,
    outra_inscricao: Application,
):
    primeira, segunda = (edital_regular.stages.get(order=n) for n in (1, 2))
    outra_inscricao.eliminate(primeira)
    outra_inscricao.save(update_fields=["status", "eliminated_at_stage"])
    ata_assinada(banca_regular, primeira, [])

    resposta = client_da_secretaria.post(convocacoes_de(edital_regular.pk, segunda.pk))

    assert resposta.status_code == 201, resposta.content
    assert [e["application_id"] for e in resposta.json()["emails"]] == [inscricao.pk]


# --- reenvio ----------------------------------------------------------------


def test_reenvio_pega_so_o_que_falhou(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
    outra_inscricao: Application,
):
    def enviar(self, *args, **kwargs):
        if self.to == [inscricao.email]:
            raise OSError("indisponível")
        return 1

    with patch("django.core.mail.EmailMessage.send", autospec=True, side_effect=enviar):
        lote = client_da_secretaria.post(
            convocacoes_de(edital_regular.pk, etapa.pk)
        ).json()
    mail.outbox.clear()

    resposta = client_da_secretaria.post(reenvio_de(lote["id"]))

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert (corpo["sent"], corpo["failed"]) == (2, 0)
    assert [m.to for m in mail.outbox] == [[inscricao.email]]

    reenviado = ConvocationEmail.objects.get(application=inscricao)
    assert reenviado.status == EmailDeliveryStatus.SENT
    assert reenviado.attempts == 2
    assert reenviado.error == ""
    assert AuditLog.objects.filter(event="selection.convocation.resend").count() == 1


def test_reenvio_sem_falha_e_recusado(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    lote = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk)).json()
    mail.outbox.clear()

    resposta = client_da_secretaria.post(reenvio_de(lote["id"]))

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "no_failed_emails"
    assert mail.outbox == []


# --- listagem ---------------------------------------------------------------


def test_listagem_traz_os_lotes_da_etapa_com_a_contagem(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))

    resposta = client_da_secretaria.get(convocacoes_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 200, resposta.content
    lotes = resposta.json()
    assert len(lotes) == 1
    assert (lotes[0]["total"], lotes[0]["sent"]) == (1, 1)
    assert lotes[0]["stage_name"] == etapa.name
    # O lote guarda o template copiado, não o texto renderizado: quem
    # rende por candidato é `ConvocationEmail.rendered_subject`.
    assert lotes[0]["subject"] == edital_regular.convocation_subject


# --- quem a etapa pode convocar ---------------------------------------------


def test_convocaveis_marcam_quem_ja_recebeu_o_e_mail(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
    outra_inscricao: Application,
):
    client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk))

    resposta = client_da_secretaria.get(convocaveis_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 200, resposta.content
    por_id = {c["id"]: c for c in resposta.json()}
    assert set(por_id) == {inscricao.pk, outra_inscricao.pk}
    assert por_id[inscricao.pk]["already_convoked"] is True
    assert por_id[outra_inscricao.pk]["already_convoked"] is True
    assert por_id[inscricao.pk]["protocol"] == inscricao.protocol
    assert por_id[inscricao.pk]["email"] == inscricao.email


def test_convocaveis_nao_incluem_quem_nao_foi_homologado(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
    program: Program,
    projeto: CollectiveProject,
):
    criar_inscricao(
        program,
        edital_regular,
        "Célia Nunes",
        "12345678909",
        projeto,
        status=ApplicationStatus.SUBMITTED,
    )

    resposta = client_da_secretaria.get(convocaveis_de(edital_regular.pk, etapa.pk))

    assert [c["id"] for c in resposta.json()] == [inscricao.pk]
    assert resposta.json()[0]["already_convoked"] is False


def test_convocaveis_da_segunda_etapa_sao_vazios_sem_ata_assinada(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    banca_regular: Board,
    inscricao: Application,
):
    segunda = edital_regular.stages.get(order=2)

    sem_ata = client_da_secretaria.get(convocaveis_de(edital_regular.pk, segunda.pk))
    assert sem_ata.json() == []

    ata_assinada(
        banca_regular,
        edital_regular.stages.get(order=1),
        [{"application_id": inscricao.pk, "full_name": inscricao.full_name}],
    )
    com_ata = client_da_secretaria.get(convocaveis_de(edital_regular.pk, segunda.pk))

    assert [c["id"] for c in com_ata.json()] == [inscricao.pk]


def test_convocaveis_de_edital_de_outro_programa_e_404(
    client_da_secretaria: Client,
    edital_suplementar: SelectionProcess,
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGY")
    alheio = SelectionProcess.objects.create(
        program=outro,
        kind=edital_suplementar.kind,
        year=2027,
        title="Edital de outro programa",
        submission_opens_at=edital_suplementar.submission_opens_at,
        submission_closes_at=edital_suplementar.submission_closes_at,
        convocation_subject="Assunto",
        convocation_body="Corpo",
    )
    etapa_alheia = SelectionStage.objects.create(process=alheio, name="Etapa", order=1)

    resposta = client_da_secretaria.get(convocaveis_de(alheio.pk, etapa_alheia.pk))

    assert resposta.status_code == 404, resposta.content


def test_convocaveis_sem_sessao_e_401(
    client: Client, edital_regular: SelectionProcess, etapa: SelectionStage
):
    resposta = client.get(convocaveis_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 401, resposta.content


def test_detalhe_do_lote_lista_os_destinatarios(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    lote = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk)).json()

    resposta = client_da_secretaria.get(lote_de(lote["id"]))

    assert resposta.status_code == 200, resposta.content
    emails = resposta.json()["emails"]
    assert [e["application_id"] for e in emails] == [inscricao.pk]
    assert emails[0]["status"] == EmailDeliveryStatus.SENT
    assert emails[0]["to_email"] == inscricao.email


def test_detalhe_de_lote_de_outro_programa_e_404(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    lote = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk)).json()
    outro = Program.objects.create(name="Outro programa", acronym="PPGZ")
    Person.objects.filter(user__username="secretaria").update(program=outro)

    resposta = client_da_secretaria.get(lote_de(lote["id"]))

    assert resposta.status_code == 404, resposta.content


# --- tenant, permissão, sessão e CSRF ---------------------------------------


def test_edital_de_outro_programa_e_404(
    client_da_secretaria: Client,
    etapa: SelectionStage,
    edital_suplementar: SelectionProcess,
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    alheio = SelectionProcess.objects.create(
        program=outro,
        kind=edital_suplementar.kind,
        year=2027,
        title="Edital de outro programa",
        submission_opens_at=edital_suplementar.submission_opens_at,
        submission_closes_at=edital_suplementar.submission_closes_at,
        convocation_subject="Assunto",
        convocation_body="Corpo",
    )
    etapa_alheia = SelectionStage.objects.create(process=alheio, name="Etapa", order=1)

    resposta = client_da_secretaria.post(convocacoes_de(alheio.pk, etapa_alheia.pk))

    assert resposta.status_code == 404, resposta.content
    assert mail.outbox == []


def test_lote_de_outro_programa_nao_reenvia(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    lote = client_da_secretaria.post(convocacoes_de(edital_regular.pk, etapa.pk)).json()
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    Person.objects.filter(user__username="secretaria").update(program=outro)

    resposta = client_da_secretaria.post(reenvio_de(lote["id"]))

    assert resposta.status_code == 404, resposta.content


def test_docente_nao_convoca(
    client: Client,
    program: Program,
    docente: Teacher,
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    inscricao: Application,
):
    user = User.objects.create_user(username="docente", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    pessoa = docente.person
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    client.force_login(user)

    resposta = client.post(convocacoes_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 403, resposta.content
    assert mail.outbox == []


def test_sem_sessao_e_401(
    client: Client, edital_regular: SelectionProcess, etapa: SelectionStage
):
    resposta = client.post(convocacoes_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 401, resposta.content


def test_sem_csrf_a_escrita_e_recusada(
    edital_regular: SelectionProcess,
    etapa: SelectionStage,
    secretaria: User,
    program: Program,
    inscricao: Application,
):
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    sessao = Client(enforce_csrf_checks=True)
    sessao.force_login(secretaria)

    resposta = sessao.post(convocacoes_de(edital_regular.pk, etapa.pk))

    assert resposta.status_code == 403, resposta.content
    assert mail.outbox == []
