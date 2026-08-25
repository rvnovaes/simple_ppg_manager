"""O ciclo da ata antes da assinatura, pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. O que este arquivo guarda, e nenhum outro guarda:

- **quem** monta e quem congela — titular monta, presidente congela; a
  permissão `change_examinationrecord` é a mesma para os três titulares,
  então só o teste separa o presidente dos demais;
- a **ordem das etapas** — a etapa 2 não abre ata enquanto a 1 não foi
  assinada (`previous_stage_open`), que é o que impede avaliar quem já
  tinha sido eliminado;
- o **e-mail do examinador externo**, que sai em `transaction.on_commit`
  e por isso só aparece com `django_capture_on_commit_callbacks`. Um
  teste que esqueça o `execute=True` passa verde sem nada ter sido
  enviado — e é justamente o envio que se quer provar.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from smtplib import SMTPException
from unittest import mock

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.test import Client

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    ExaminationRecord,
    QuotaCategory,
    RecordSignature,
    RecordStatus,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SignatureMethod,
    StageScore,
    gerar_protocolo,
)

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"


def ata_de(board_id: int, stage_id: int, sufixo: str = "") -> str:
    return f"/api/v1/selection/boards/{board_id}/stages/{stage_id}/record{sufixo}"


def dar_conta(program: Program, teacher: Teacher, papel: str, username: str) -> User:
    """Liga um usuário do papel `papel` à `Person` do professor — é ela
    que faz `current_program` e `teacher_da_sessao` resolverem."""
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name=papel))
    pessoa = teacher.person
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    return user


@pytest.fixture
def etapa(edital_regular: SelectionProcess):
    return edital_regular.stages.get(order=1)


@pytest.fixture
def etapa_2(edital_regular: SelectionProcess):
    return edital_regular.stages.get(order=2)


@pytest.fixture
def client_presidente(
    client: Client, program: Program, banca_regular: Board, professores: list[Teacher]
) -> Client:
    client.force_login(dar_conta(program, professores[0], "Docente", "presidente"))
    return client


@pytest.fixture
def client_membro(
    program: Program, banca_regular: Board, professores: list[Teacher]
) -> Client:
    """Membro 1 da banca: titular, mas não presidente.

    Client **próprio**, e não o `client` do pytest-django: as fixtures
    que congelam a ata logam o presidente no client compartilhado, e o
    último `force_login` venceria — o teste passaria a exercer o
    presidente sem dizer nada.
    """
    membro = Client()
    membro.force_login(dar_conta(program, professores[1], "Docente", "membro"))
    return membro


@pytest.fixture
def banca_com_externo(banca_regular: Board, professores: list[Teacher]) -> Board:
    """A mesma banca, com o externo como membro titular.

    Na `banca_regular` o externo é o suplente e não assina — trocá-lo
    com o membro 2 é o caminho mais curto para uma ata cujo
    congelamento tem que emitir token e mandar e-mail.
    """
    banca_regular.member_2, banca_regular.alternate = professores[3], professores[2]
    banca_regular.clean()
    banca_regular.save()
    return banca_regular


def congelar(client: Client, banca: Board, etapa, **corpo):
    """POST de congelamento. O corpo vai sempre, mesmo vazio: `RecordFreezeIn`
    é schema de corpo e o Ninja recusa a requisição sem ele."""
    return client.post(
        ata_de(banca.pk, etapa.pk, "/freeze"),
        data=corpo,
        content_type="application/json",
    )


def criar_inscricao(
    program: Program,
    edital: SelectionProcess,
    nome: str,
    cpf: str,
    projeto: CollectiveProject,
    **extra,
) -> Application:
    campos = {
        "level": SelectionLevel.MASTERS,
        "quota_category": QuotaCategory.OPEN,
        "status": ApplicationStatus.HOMOLOGATED,
        "project": projeto,
    }
    campos.update(extra)
    return Application.objects.create(
        program=program,
        process=edital,
        protocol=gerar_protocolo(edital),
        full_name=nome,
        email=f"{cpf}@exemplo.br",
        cpf=cpf,
        birth_date=date(1995, 5, 20),
        submitted_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
        **campos,
    )


def pontuar(program: Program, inscricao: Application, etapa, valor: str) -> StageScore:
    nota = StageScore(
        program=program,
        application=inscricao,
        stage=etapa,
        score=Decimal(valor),
    )
    nota.clean()
    nota.save()
    return nota


# --- gerar -----------------------------------------------------------------


def test_presidente_gera_a_ata_com_as_notas_ja_lancadas(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    inscricao: Application,
    nota: StageScore,
):
    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["status"] == RecordStatus.DRAFT
    assert dados["version"] == 1
    assert dados["stage_name"] == etapa.name
    assert dados["signatures"] == []
    # A nota vai como texto: `float` mudaria o hash entre gravações.
    assert dados["content"] == [
        {
            "application_id": inscricao.pk,
            "protocol": inscricao.protocol,
            "full_name": "Ana Lima",
            "quota_category": QuotaCategory.OPEN,
            "score": "85.50",
            "absent": False,
            "passed": True,
        }
    ]
    assert AuditLog.objects.filter(event="selection.record.generate").count() == 1


def test_ata_gerada_ignora_quem_nao_esta_vivo_no_alvo(
    client_presidente: Client,
    program: Program,
    banca_regular: Board,
    etapa,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    inscricao: Application,
    nota: StageScore,
):
    """Eliminado não volta para a ata, e doutorado é outro recorte."""
    eliminada = criar_inscricao(
        program,
        edital_regular,
        "Caio Prado",
        "10001371711",
        projeto,
        status=ApplicationStatus.ELIMINATED,
        eliminated_at_stage=etapa,
    )
    pontuar(program, eliminada, etapa, "90")
    outro_nivel = criar_inscricao(
        program,
        edital_regular,
        "Dora Reis",
        "10002743493",
        projeto,
        level=SelectionLevel.DOCTORATE,
    )
    pontuar(program, outro_nivel, etapa, "95")

    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 201, resposta.content
    assert [r["protocol"] for r in resposta.json()["content"]] == [inscricao.protocol]


def test_gerar_a_ata_duas_vezes_e_400(
    client_presidente: Client, banca_regular: Board, etapa, ata_regular
):
    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "record_already_exists"


def test_gerar_ata_da_etapa_2_sem_a_1_assinada_e_409(
    client_presidente: Client, banca_regular: Board, etapa_2
):
    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa_2.pk))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "previous_stage_open"
    assert not ExaminationRecord.objects.exists()


def test_gerar_ata_da_etapa_2_com_a_1_assinada(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    etapa_2,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    program: Program,
):
    """A ata da etapa 1 assinada é o que libera a etapa 2."""
    pontuar(program, inscricao, etapa_2, "70")
    ata_regular.freeze(
        [{"full_name": "Ana", "protocol": "X", "score": "80"}],
        at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    ata_regular.mark_signed(at=datetime(2026, 3, 2, tzinfo=UTC))
    ata_regular.save()

    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa_2.pk))

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["stage_id"] == etapa_2.pk


def test_gerar_ata_por_quem_nao_e_titular_e_403(
    client: Client,
    program: Program,
    banca_regular: Board,
    etapa,
    professores: list[Teacher],
):
    """O suplente compõe a banca, mas não monta a ata."""
    client.force_login(dar_conta(program, professores[3], "Docente", "suplente"))

    resposta = client.post(ata_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_a_titular_member"


def test_gerar_ata_de_banca_alheia_e_403(
    client: Client, program: Program, banca_regular: Board, etapa
):
    pessoa = Person.objects.create(
        program=program, full_name="Otávio Lins", primary_email="otavio@exemplo.br"
    )
    professor = Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 3, 1),
    )
    client.force_login(dar_conta(program, professor, "Docente", "de-fora"))

    resposta = client.post(ata_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_a_board_member"


def test_gerar_ata_sem_sessao_e_401(client: Client, banca_regular: Board, etapa):
    assert client.post(ata_de(banca_regular.pk, etapa.pk)).status_code == 401


def test_gerar_ata_sem_token_csrf_e_recusado(
    program: Program, banca_regular: Board, etapa, professores: list[Teacher]
):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(dar_conta(program, professores[0], "Docente", "csrf"))

    resposta = client.post(ata_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 403
    assert not ExaminationRecord.objects.exists()


# --- ler e atualizar -------------------------------------------------------


def test_get_da_ata_inexistente_e_404(
    client_presidente: Client, banca_regular: Board, etapa
):
    assert client_presidente.get(ata_de(banca_regular.pk, etapa.pk)).status_code == 404


def test_get_traz_a_ata_corrente(
    client_presidente: Client, banca_regular: Board, etapa, ata_regular
):
    resposta = client_presidente.get(ata_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["id"] == ata_regular.pk


def test_refresh_regera_o_conteudo_do_rascunho(
    client_presidente: Client,
    program: Program,
    banca_regular: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
):
    """A ata é gerada antes de a banca terminar de lançar; o refresh é o
    que traz a nota que entrou depois."""
    assert ata_regular.content == []
    pontuar(program, inscricao, etapa, "62.5")

    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa.pk, "/refresh"))

    assert resposta.status_code == 200, resposta.content
    linhas = resposta.json()["content"]
    assert [(r["score"], r["passed"]) for r in linhas] == [("62.50", False)]
    assert AuditLog.objects.filter(event="selection.record.refresh").count() == 1


def test_refresh_de_ata_congelada_e_409(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    ata_congelada: ExaminationRecord,
):
    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa.pk, "/refresh"))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "record_not_draft"


# --- congelar --------------------------------------------------------------


@pytest.fixture
def ata_congelada(
    client_presidente: Client,
    program: Program,
    banca_regular: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    django_capture_on_commit_callbacks,
) -> ExaminationRecord:
    with django_capture_on_commit_callbacks(execute=True):
        resposta = congelar(client_presidente, banca_regular, etapa)
    assert resposta.status_code == 200, resposta.content
    ata_regular.refresh_from_db()
    return ata_regular


def test_congelar_fixa_conteudo_hash_e_assinaturas(
    ata_congelada: ExaminationRecord, professores: list[Teacher]
):
    assert ata_congelada.status == RecordStatus.AWAITING_SIGNATURES
    assert ata_congelada.frozen_at is not None
    assert ata_congelada.verify_hash()
    # Os três titulares, todos por login: nesta banca o externo é suplente.
    assinaturas = list(ata_congelada.signatures.all())
    assert len(assinaturas) == 3
    assert {a.signer_id for a in assinaturas} == {p.pk for p in professores[:3]}
    assert {a.method for a in assinaturas} == {SignatureMethod.LOGIN}
    assert not mail.outbox
    assert AuditLog.objects.filter(event="selection.record.freeze").count() == 1


def test_congelar_com_nota_faltando_e_400_listando_protocolos(
    client_presidente: Client,
    program: Program,
    banca_regular: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    sem_nota = criar_inscricao(
        program, edital_regular, "Beatriz Nunes", "10000000019", projeto
    )

    resposta = congelar(client_presidente, banca_regular, etapa)

    assert resposta.status_code == 400
    corpo = resposta.json()
    assert corpo["code"] == "scores_incomplete"
    assert sem_nota.protocol in corpo["detail"]
    assert inscricao.protocol not in corpo["detail"]
    ata_regular.refresh_from_db()
    assert ata_regular.status == RecordStatus.DRAFT
    assert not RecordSignature.objects.exists()


def test_congelar_manda_o_token_por_e_mail_ao_externo(
    client_presidente: Client,
    banca_com_externo: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    externo: Teacher,
    django_capture_on_commit_callbacks,
    settings,
):
    settings.SITE_URL = "https://ppgd.exemplo.br"

    with django_capture_on_commit_callbacks(execute=True):
        resposta = congelar(client_presidente, banca_com_externo, etapa)

    assert resposta.status_code == 200, resposta.content
    assinatura = RecordSignature.objects.get(signer=externo)
    assert assinatura.method == SignatureMethod.TOKEN
    assert assinatura.token_hash and assinatura.token_expires_at is not None
    assert assinatura.token_sent_at is not None
    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == [externo.person.primary_email]
    assert "https://ppgd.exemplo.br/selecao/assinatura/" in mensagem.body
    # O token em texto viaja só no e-mail; no banco fica o hash.
    assert assinatura.token_hash not in mensagem.body
    assert AuditLog.objects.filter(event="selection.record.token_issued").count() == 1


def test_falha_de_envio_nao_desfaz_o_congelamento(
    client_presidente: Client,
    banca_com_externo: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    externo: Teacher,
    django_capture_on_commit_callbacks,
):
    """Armadilha 3: o envio é `on_commit`, fora da transação. SMTP fora
    do ar deixa a ata congelada e o aviso reemissível."""
    with (
        mock.patch(
            "apps.selection.services.enviar_token_de_assinatura",
            side_effect=SMTPException("servidor fora do ar"),
        ),
        django_capture_on_commit_callbacks(execute=True),
    ):
        resposta = congelar(client_presidente, banca_com_externo, etapa)

    assert resposta.status_code == 200, resposta.content
    ata_regular.refresh_from_db()
    assert ata_regular.status == RecordStatus.AWAITING_SIGNATURES
    assinatura = RecordSignature.objects.get(signer=externo)
    assert assinatura.token_sent_at is None
    assert assinatura.token_hash
    assert AuditLog.objects.filter(event="selection.record.token_email_failed").exists()


def test_congelar_com_titular_impedido_troca_pelo_suplente(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    professores: list[Teacher],
    django_capture_on_commit_callbacks,
):
    """O suplente (externo, nesta banca) assina no lugar do membro 2, e
    o impedido entra no hash — assinatura não é reaproveitável."""
    impedido = professores[2]
    suplente = professores[3]

    with django_capture_on_commit_callbacks(execute=True):
        resposta = congelar(
            client_presidente, banca_regular, etapa, replaced_member_id=impedido.pk
        )

    assert resposta.status_code == 200, resposta.content
    dados = resposta.json()
    assert dados["replaced_member_id"] == impedido.pk
    assert dados["replaced_member_name"] == impedido.person.full_name
    assinantes = {a["signer_id"] for a in dados["signatures"]}
    assert assinantes == {professores[0].pk, professores[1].pk, suplente.pk}
    assert len(mail.outbox) == 1


def test_congelar_com_suplente_como_impedido_e_400(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
    professores: list[Teacher],
):
    resposta = congelar(
        client_presidente, banca_regular, etapa, replaced_member_id=professores[3].pk
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "not_a_titular_member"
    assert not RecordSignature.objects.exists()


def test_congelar_por_quem_nao_e_presidente_e_403(
    client_membro: Client,
    banca_regular: Board,
    etapa,
    ata_regular: ExaminationRecord,
    inscricao: Application,
    nota: StageScore,
):
    resposta = congelar(client_membro, banca_regular, etapa)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_the_board_president"


def test_congelar_ata_sem_candidato_vivo_e_400(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    ata_regular: ExaminationRecord,
):
    """Etapa sem ninguém vivo no alvo não tem o que assinar."""
    resposta = congelar(client_presidente, banca_regular, etapa)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_candidates"


def test_nota_de_ata_congelada_e_so_leitura(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    ata_congelada: ExaminationRecord,
    inscricao: Application,
):
    """O `content_hash` cobre a fotografia das notas: mudá-las por baixo
    invalidaria assinatura já dada."""
    resposta = client_presidente.put(
        f"/api/v1/selection/boards/{banca_regular.pk}/stages/{etapa.pk}/scores",
        data=[{"application_id": inscricao.pk, "score": "99"}],
        content_type="application/json",
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "record_frozen"


# --- reabrir ---------------------------------------------------------------


def test_reabrir_volta_ao_rascunho_e_apaga_as_pendentes(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    ata_congelada: ExaminationRecord,
):
    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa.pk, "/reopen"))

    assert resposta.status_code == 200, resposta.content
    dados = resposta.json()
    assert dados["status"] == RecordStatus.DRAFT
    assert dados["content_hash"] == ""
    assert dados["signatures"] == []
    assert not RecordSignature.objects.exists()
    registro = AuditLog.objects.get(event="selection.record.reopen")
    assert registro.payload["deleted_signatures"] == 3


def test_reabrir_ata_com_assinatura_e_409(
    client_presidente: Client,
    banca_regular: Board,
    etapa,
    ata_congelada: ExaminationRecord,
):
    """Assinatura dada é declaração de um examinador sobre um conteúdo:
    o caminho depois dela é retificar, não reabrir."""
    assinatura = ata_congelada.signatures.first()
    assert assinatura is not None
    assinatura.sign(
        at=datetime(2026, 3, 5, tzinfo=UTC), content_hash=ata_congelada.content_hash
    )
    assinatura.save()

    resposta = client_presidente.post(ata_de(banca_regular.pk, etapa.pk, "/reopen"))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "record_has_signatures"
    assert ata_congelada.signatures.count() == 3


def test_reabrir_por_quem_nao_e_presidente_e_403(
    client_membro: Client,
    banca_regular: Board,
    etapa,
    ata_congelada: ExaminationRecord,
):
    resposta = client_membro.post(ata_de(banca_regular.pk, etapa.pk, "/reopen"))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_the_board_president"


def test_ata_de_banca_de_outro_programa_e_404(
    client_presidente: Client, etapa, banca_regular: Board
):
    """404 e não 403: negar existência é o que protege o outro tenant."""
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    edital = SelectionProcess.objects.create(
        program=outro,
        kind=SelectionKind.SUPPLEMENTARY,
        year=2027,
        title="Edital de outro programa",
        submission_opens_at=datetime(2026, 1, 1, tzinfo=UTC),
        submission_closes_at=datetime(2026, 12, 31, tzinfo=UTC),
    )
    forasteiros = [
        Teacher.objects.create(
            program=outro,
            person=Person.objects.create(
                program=outro, full_name=f"X{i}", primary_email=f"x{i}@exemplo.br"
            ),
            category=Teacher.Category.PERMANENT,
            academic_degree=Teacher.AcademicDegree.DOCTORATE,
            accredited_since=date(2020, 3, 1),
        )
        for i in range(4)
    ]
    banca = Board.objects.create(
        program=outro,
        process=edital,
        level=SelectionLevel.MASTERS,
        research_line=ResearchLine.objects.create(program=outro, name="Linha de fora"),
        president=forasteiros[0],
        member_1=forasteiros[1],
        member_2=forasteiros[2],
        alternate=forasteiros[3],
    )

    resposta = client_presidente.get(ata_de(banca.pk, etapa.pk))

    assert resposta.status_code == 404
