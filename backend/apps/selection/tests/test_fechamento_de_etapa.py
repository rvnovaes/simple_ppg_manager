"""A assinatura da ata e o fechamento da etapa, pela API.

Nível (b) da pirâmide (Seção 9). O que este arquivo guarda, e nenhum
outro guarda:

- **a terceira assinatura é o que promove, elimina e aprova.** Congelar
  não muda o destino de ninguém; enquanto falta assinatura, a ata é
  proposta da banca. O teste de cada etapa (primeira, intermediária e
  última) existe porque o desfecho depende de onde a etapa está: no
  meio, quem passa apenas continua vivo; na última, quem passa é
  `approved` com `final_score` carimbado.
- **o corte é `>= 70`, e ele é exato.** 70.00 passa, 69.99 elimina — é a
  única regra do módulo em que um centésimo muda a vida de alguém.
- **assinatura vale sobre um texto, não sobre um id de ata.** Se o
  `content` mudar entre congelar e assinar, `record_changed`.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.programs.models import CollectiveProject, Program
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    ExaminationRecord,
    QuotaCategory,
    RecordStatus,
    SelectionLevel,
    SelectionProcess,
    SelectionStage,
    StageScore,
    gerar_protocolo,
)

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"


def ata_de(board_id: int, stage_id: int, sufixo: str = "") -> str:
    return f"/api/v1/selection/boards/{board_id}/stages/{stage_id}/record{sufixo}"


def dar_conta(teacher: Teacher, username: str) -> User:
    """Liga um usuário Docente à `Person` do professor — é ela que faz
    `current_program` e `teacher_da_sessao` resolverem."""
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    pessoa = teacher.person
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    return user


@pytest.fixture
def clients_da_banca(professores: list[Teacher], banca_regular: Board) -> list[Client]:
    """Um `Client` **próprio** por titular, na ordem presidente, membro 1,
    membro 2.

    Client próprio, e não o `client` do pytest-django: três `force_login`
    no mesmo client fariam o último vencer, e as três assinaturas sairiam
    todas do mesmo professor sem o teste notar.
    """
    clients = []
    for indice, papel in enumerate(("presidente", "membro1", "membro2")):
        sessao = Client()
        sessao.force_login(dar_conta(professores[indice], papel))
        clients.append(sessao)
    return clients


def criar_inscricao(
    program: Program,
    edital: SelectionProcess,
    nome: str,
    cpf: str,
    projeto: CollectiveProject,
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
        status=ApplicationStatus.HOMOLOGATED,
        submitted_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
    )


def pontuar(
    program: Program,
    inscricao: Application,
    etapa: SelectionStage,
    valor: str | None = None,
    *,
    ausente: bool = False,
) -> StageScore:
    nota = StageScore(
        program=program,
        application=inscricao,
        stage=etapa,
        score=None if ausente else Decimal(valor or "0"),
        absent=ausente,
    )
    nota.clean()
    nota.save()
    return nota


def congelar(client: Client, banca: Board, etapa: SelectionStage):
    resposta = client.post(
        ata_de(banca.pk, etapa.pk, "/freeze"), data={}, content_type="application/json"
    )
    assert resposta.status_code == 200, resposta.content
    return resposta


def ata_congelada(
    client: Client, banca: Board, etapa: SelectionStage
) -> ExaminationRecord:
    """Gera e congela a ata da etapa, pela API, como presidente."""
    criada = client.post(ata_de(banca.pk, etapa.pk))
    assert criada.status_code == 201, criada.content
    congelar(client, banca, etapa)
    return ExaminationRecord.objects.get(pk=criada.json()["id"])


def assinar(client: Client, banca: Board, etapa: SelectionStage, **corpo):
    return client.post(
        ata_de(banca.pk, etapa.pk, "/sign"),
        data=corpo,
        content_type="application/json",
    )


def assinar_todos(
    clients: list[Client], banca: Board, etapa: SelectionStage
) -> ExaminationRecord:
    for sessao in clients:
        resposta = assinar(sessao, banca, etapa)
        assert resposta.status_code == 200, resposta.content
    return (
        ExaminationRecord.objects.current()
        .for_key(etapa, banca.level, banca.project, banca.research_line)
        .get(process=banca.process)
    )


def etapa_aberta(
    banca: Board, etapa: SelectionStage, conteudo: list[dict]
) -> SelectionStage:
    """Marca as etapas anteriores como assinadas, para poder abrir a ata
    de uma etapa do meio ou do fim sem encenar as anteriores inteiras."""
    for anterior in banca.process.stages.filter(order__lt=etapa.order):
        ata = ExaminationRecord(
            program=banca.program,
            process=banca.process,
            stage=anterior,
            level=banca.level,
            project=banca.project,
            board=banca,
            status=RecordStatus.SIGNED,
            content=conteudo,
            signed_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        )
        ata.save()
    return etapa


# --- a etapa fecha na terceira assinatura -----------------------------------


def test_tres_assinaturas_fecham_a_primeira_etapa(
    clients_da_banca: list[Client],
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    """Passar na primeira etapa não muda o status: seguir vivo já é a
    promoção, e ela deriva da ata assinada."""
    etapa = edital_regular.stages.get(order=1)
    ata = ata_congelada(clients_da_banca[0], banca_regular, etapa)

    primeira = assinar(clients_da_banca[0], banca_regular, etapa)
    assert primeira.status_code == 200, primeira.content
    assert primeira.json()["status"] == RecordStatus.AWAITING_SIGNATURES
    assert primeira.json()["pending_signatures"] == 2

    assinar(clients_da_banca[1], banca_regular, etapa)
    ultima = assinar(clients_da_banca[2], banca_regular, etapa)

    dados = ultima.json()
    assert dados["status"] == RecordStatus.SIGNED
    assert dados["pending_signatures"] == 0
    assert dados["has_pdf"] is True
    assert dados["hash_ok"] is True

    ata.refresh_from_db()
    inscricao.refresh_from_db()
    assert ata.signed_at is not None
    assert ata.pdf.read().startswith(b"%PDF")
    assert inscricao.status == ApplicationStatus.HOMOLOGATED
    assert inscricao.final_score is None

    fechamento = AuditLog.objects.get(event="selection.stage.close")
    assert fechamento.payload["promoted"] == [inscricao.pk]
    assert fechamento.payload["eliminated"] == []
    assert fechamento.payload["approved"] == []
    assert fechamento.payload["version"] == 1
    assert AuditLog.objects.filter(event="selection.record.sign").count() == 3


def test_etapa_intermediaria_promove_sem_carimbar_nota_final(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
):
    etapa = edital_regular.stages.get(order=2)
    etapa_aberta(banca_regular, etapa, [])
    pontuar(program, inscricao, etapa, "80")
    ata_congelada(clients_da_banca[0], banca_regular, etapa)

    assinar_todos(clients_da_banca, banca_regular, etapa)

    inscricao.refresh_from_db()
    assert inscricao.status == ApplicationStatus.HOMOLOGATED
    assert inscricao.final_score is None
    assert AuditLog.objects.get(event="selection.stage.close").payload["promoted"] == [
        inscricao.pk
    ]


def test_ultima_etapa_aprova_com_a_nota_final(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
):
    etapa = edital_regular.stages.get(order=3)
    etapa_aberta(banca_regular, etapa, [])
    pontuar(program, inscricao, etapa, "91.25")
    ata_congelada(clients_da_banca[0], banca_regular, etapa)

    assinar_todos(clients_da_banca, banca_regular, etapa)

    inscricao.refresh_from_db()
    assert inscricao.status == ApplicationStatus.APPROVED
    assert inscricao.final_score == Decimal("91.25")
    assert AuditLog.objects.get(event="selection.stage.close").payload["approved"] == [
        inscricao.pk
    ]


def test_ausente_e_eliminado_na_etapa(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    projeto: CollectiveProject,
):
    etapa = edital_regular.stages.get(order=1)
    presente = criar_inscricao(
        program, edital_regular, "Caio Prado", "10001371711", projeto
    )
    pontuar(program, inscricao, etapa, ausente=True)
    pontuar(program, presente, etapa, "75")
    ata_congelada(clients_da_banca[0], banca_regular, etapa)

    assinar_todos(clients_da_banca, banca_regular, etapa)

    inscricao.refresh_from_db()
    presente.refresh_from_db()
    assert inscricao.status == ApplicationStatus.ELIMINATED
    assert inscricao.eliminated_at_stage_id == etapa.pk
    assert presente.status == ApplicationStatus.HOMOLOGATED
    payload = AuditLog.objects.get(event="selection.stage.close").payload
    assert payload["eliminated"] == [inscricao.pk]
    assert payload["promoted"] == [presente.pk]


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("70.00", ApplicationStatus.HOMOLOGATED),
        ("69.99", ApplicationStatus.ELIMINATED),
    ],
)
def test_o_corte_e_exato(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    valor: str,
    esperado: str,
):
    """70.00 passa, 69.99 elimina — um centésimo separa os dois."""
    etapa = edital_regular.stages.get(order=1)
    pontuar(program, inscricao, etapa, valor)
    ata_congelada(clients_da_banca[0], banca_regular, etapa)

    assinar_todos(clients_da_banca, banca_regular, etapa)

    inscricao.refresh_from_db()
    assert inscricao.status == esperado


# --- o que a assinatura recusa ----------------------------------------------


def test_assinatura_recusada_quando_o_conteudo_mudou(
    clients_da_banca: list[Client],
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    """Ata adulterada no banco depois do congelamento: o hash gravado
    deixa de bater com o conteúdo e ninguém mais assina."""
    etapa = edital_regular.stages.get(order=1)
    ata = ata_congelada(clients_da_banca[0], banca_regular, etapa)
    ata.content[0]["score"] = "99.00"
    ata.save(update_fields=["content"])

    resposta = assinar(clients_da_banca[0], banca_regular, etapa)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "record_changed"
    ata.refresh_from_db()
    assert ata.status == RecordStatus.AWAITING_SIGNATURES


def test_hash_divergente_no_corpo_e_recusado(
    clients_da_banca: list[Client],
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    """O hash do corpo é o que a tela mostrou; diferente do corrente
    significa que a ata foi recongelada entre a leitura e o clique."""
    etapa = edital_regular.stages.get(order=1)
    ata_congelada(clients_da_banca[0], banca_regular, etapa)

    resposta = assinar(clients_da_banca[0], banca_regular, etapa, content_hash="a" * 64)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "record_changed"


def test_mesma_pessoa_nao_assina_duas_vezes(
    clients_da_banca: list[Client],
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    etapa = edital_regular.stages.get(order=1)
    ata_congelada(clients_da_banca[0], banca_regular, etapa)
    assert assinar(clients_da_banca[0], banca_regular, etapa).status_code == 200

    repetida = assinar(clients_da_banca[0], banca_regular, etapa)

    assert repetida.status_code == 409
    assert repetida.json()["code"] == "already_signed"


def test_suplente_que_nao_substitui_ninguem_nao_assina(
    clients_da_banca: list[Client],
    banca_regular: Board,
    edital_regular: SelectionProcess,
    professores: list[Teacher],
    inscricao: Application,
    nota: StageScore,
):
    """O suplente compõe a banca (lê a ata), mas só assina quando entra no
    lugar de um titular impedido."""
    etapa = edital_regular.stages.get(order=1)
    ata_congelada(clients_da_banca[0], banca_regular, etapa)
    suplente = Client()
    suplente.force_login(dar_conta(professores[3], "suplente"))

    resposta = assinar(suplente, banca_regular, etapa)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_the_signer"


def test_assinatura_exige_permissao(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    professores: list[Teacher],
    inscricao: Application,
    nota: StageScore,
):
    etapa = edital_regular.stages.get(order=1)
    ata_congelada(clients_da_banca[0], banca_regular, etapa)
    conta = User.objects.get(username="presidente")
    conta.groups.clear()

    resposta = assinar(clients_da_banca[0], banca_regular, etapa)

    assert resposta.status_code == 403


def test_assinatura_sem_sessao_e_401(
    client: Client,
    clients_da_banca: list[Client],
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    etapa = edital_regular.stages.get(order=1)
    ata_congelada(clients_da_banca[0], banca_regular, etapa)

    resposta = assinar(client, banca_regular, etapa)

    assert resposta.status_code == 401


# --- retificação: a versão nova re-sincroniza só quem mudou -----------------


def test_versao_2_reintegra_quem_mudou_e_substitui_a_anterior(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    projeto: CollectiveProject,
):
    """A v2 corrige a nota de quem tinha sido eliminado; quem já passava
    na v1 não é tocado de novo (e continuaria vivo de qualquer forma)."""
    etapa = edital_regular.stages.get(order=1)
    outra = criar_inscricao(
        program, edital_regular, "Caio Prado", "10001371711", projeto
    )
    reprovada = pontuar(program, inscricao, etapa, "40")
    pontuar(program, outra, etapa, "80")
    v1 = ata_congelada(clients_da_banca[0], banca_regular, etapa)
    assinar_todos(clients_da_banca, banca_regular, etapa)
    inscricao.refresh_from_db()
    assert inscricao.status == ApplicationStatus.ELIMINATED

    # A retificação em si é de outra story; aqui a v2 é montada à mão.
    reprovada.score = Decimal("88")
    reprovada.save(update_fields=["score"])
    v1.refresh_from_db()
    v1.supersede()
    v1.save(update_fields=["status"])
    v2 = ExaminationRecord(
        program=program,
        process=edital_regular,
        stage=etapa,
        level=banca_regular.level,
        project=banca_regular.project,
        board=banca_regular,
        version=2,
        supersedes=v1,
        rectification_reason="Erro de digitação na nota.",
    )
    v2.clean()
    v2.save()
    congelar(clients_da_banca[0], banca_regular, etapa)

    assinar_todos(clients_da_banca, banca_regular, etapa)

    v1.refresh_from_db()
    v2.refresh_from_db()
    inscricao.refresh_from_db()
    outra.refresh_from_db()
    assert v1.status == RecordStatus.SUPERSEDED
    assert v2.status == RecordStatus.SIGNED
    assert inscricao.status == ApplicationStatus.HOMOLOGATED
    assert inscricao.eliminated_at_stage is None
    assert outra.status == ApplicationStatus.HOMOLOGATED
    # `order_by("id")`: a ordenação padrão do AuditLog é decrescente, e
    # `.last()` traria o fechamento da v1.
    fechamento = (
        AuditLog.objects.filter(event="selection.stage.close").order_by("id").last()
    )
    assert fechamento is not None
    assert fechamento.payload["version"] == 2
    assert fechamento.payload["promoted"] == [inscricao.pk]
