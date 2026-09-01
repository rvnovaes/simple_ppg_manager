"""O docente lança as notas da sua banca pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. O que este arquivo guarda, e nenhum outro guarda, é o recorte
que **não** é permissão: todo Docente tem `add/change_stagescore`, e
mesmo assim só pontua a banca que compõe (`Board.is_member`). Um teste
com dois docentes e duas bancas prova isso; sem ele, a rota vazaria a
planilha de uma banca para a outra sem nenhum erro aparente.

A secretaria aparece aqui pelo motivo inverso: ela opera o edital inteiro
e ainda assim leva 403, porque avaliar é da banca.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
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
    RecordStatus,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    StageScore,
    gerar_protocolo,
)

pytestmark = pytest.mark.django_db

MINHAS_BANCAS = "/api/v1/selection/boards/mine"

SENHA = "senha-de-teste-123"


def notas_de(board_id: int, stage_id: int) -> str:
    return f"/api/v1/selection/boards/{board_id}/stages/{stage_id}/scores"


def _put(client: Client, url: str, dados: list[dict]):
    return client.put(url, data=dados, content_type="application/json")


def dar_conta(program: Program, teacher: Teacher, papel: str, username: str) -> User:
    """Liga um usuário do papel `papel` à `Person` do professor.

    É a `Person` que faz o `current_program` e o `teacher_da_sessao`
    resolverem — sem ela o docente é um usuário sem vínculo e leva 403 de
    tenant, não o 403 que estes testes querem provar.
    """
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name=papel))
    pessoa = teacher.person
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    return user


@pytest.fixture
def client_docente(
    client: Client, program: Program, banca_regular: Board, professores: list[Teacher]
) -> Client:
    """O presidente da `banca_regular`, logado como Docente."""
    client.force_login(dar_conta(program, professores[0], "Docente", "docente"))
    return client


@pytest.fixture
def client_de_fora(client: Client, program: Program) -> Client:
    """Docente do programa que não compõe a `banca_regular`."""
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
    return client


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
def etapa(edital_regular: SelectionProcess):
    return edital_regular.stages.get(order=1)


def criar_inscricao(
    program: Program,
    edital: SelectionProcess,
    nome: str,
    cpf: str,
    **extra,
) -> Application:
    campos = {
        "level": SelectionLevel.MASTERS,
        "quota_category": QuotaCategory.OPEN,
        "status": ApplicationStatus.HOMOLOGATED,
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


# --- boards/mine -----------------------------------------------------------


def test_minhas_bancas_traz_so_as_do_docente_da_sessao(
    client_docente: Client,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    linha: ResearchLine,
):
    """A banca em que o docente não entra não aparece — o filtro é
    `with_teacher`, não "todas as bancas do programa"."""
    outros = [
        Teacher.objects.create(
            program=banca_regular.program,
            person=Person.objects.create(
                program=banca_regular.program,
                full_name=f"Examinador {i}",
                primary_email=f"ex{i}@exemplo.br",
            ),
            category=Teacher.Category.PERMANENT,
            academic_degree=Teacher.AcademicDegree.DOCTORATE,
            accredited_since=date(2020, 3, 1),
        )
        for i in range(4)
    ]
    Board.objects.create(
        program=banca_regular.program,
        process=edital_regular,
        level=SelectionLevel.DOCTORATE,
        project=banca_regular.project,
        president=outros[0],
        member_1=outros[1],
        member_2=outros[2],
        alternate=outros[3],
    )

    resposta = client_docente.get(MINHAS_BANCAS)

    assert resposta.status_code == 200, resposta.content
    dados = resposta.json()
    assert [b["id"] for b in dados] == [banca_regular.pk]
    # As etapas viajam embutidas: o Docente não tem `view_selectionstage`.
    assert [e["name"] for e in dados[0]["stages"]] == [
        "Resumo expandido",
        "Prova oral",
        "Entrevista",
    ]


def test_minhas_bancas_para_quem_nao_e_docente_e_403(client_da_secretaria: Client):
    resposta = client_da_secretaria.get(MINHAS_BANCAS)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_a_board_member"


def test_minhas_bancas_sem_sessao_e_401(client: Client):
    assert client.get(MINHAS_BANCAS).status_code == 401


# --- planilha (GET) --------------------------------------------------------


def test_planilha_lista_os_vivos_do_alvo_mesmo_sem_nota(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    inscricao: Application,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """Quem ainda não foi avaliado aparece com `scored: false` — é o que
    faz a tela mostrar o que falta em vez de uma lista vazia."""
    criar_inscricao(
        program, edital_regular, "Beatriz Nunes", "10000000019", project=projeto
    )
    # Eliminada não disputa mais: fica fora da planilha.
    criar_inscricao(
        program,
        edital_regular,
        "Caio Prado",
        "10001371711",
        project=projeto,
        status=ApplicationStatus.ELIMINATED,
        eliminated_at_stage=etapa,
    )
    # Doutorado é outro recorte, com outra banca.
    criar_inscricao(
        program,
        edital_regular,
        "Dora Reis",
        "10002743493",
        project=projeto,
        level=SelectionLevel.DOCTORATE,
    )

    resposta = client_docente.get(notas_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 200, resposta.content
    linhas = resposta.json()
    assert [linha["full_name"] for linha in linhas] == ["Ana Lima", "Beatriz Nunes"]
    assert linhas[0]["application_id"] == inscricao.pk
    assert linhas[0]["scored"] is False
    assert linhas[0]["score"] is None
    assert linhas[0]["absent"] is False
    assert linhas[0]["passed"] is False
    assert linhas[0]["entered_by"] == ""


def test_planilha_mostra_a_nota_ja_lancada(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    nota: StageScore,
    professores: list[Teacher],
):
    nota.entered_by = professores[0]
    nota.save(update_fields=["entered_by"])

    linhas = client_docente.get(notas_de(banca_regular.pk, etapa.pk)).json()

    assert linhas[0]["scored"] is True
    assert linhas[0]["score"] == "85.50"
    assert linhas[0]["passed"] is True
    assert linhas[0]["entered_by"] == "Bruno Reis"


def test_planilha_de_banca_alheia_e_403(
    client_de_fora: Client, banca_regular: Board, etapa
):
    """O recorte real: o docente tem `view_stagescore`, e mesmo assim não
    lê a planilha de banca que não compõe."""
    resposta = client_de_fora.get(notas_de(banca_regular.pk, etapa.pk))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_a_board_member"


def test_planilha_de_banca_de_outro_programa_e_404(
    client_docente: Client, etapa, professores: list[Teacher]
):
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
    linha_de_fora = ResearchLine.objects.create(program=outro, name="Linha de fora")
    banca = Board.objects.create(
        program=outro,
        process=edital,
        level=SelectionLevel.MASTERS,
        research_line=linha_de_fora,
        president=forasteiros[0],
        member_1=forasteiros[1],
        member_2=forasteiros[2],
        alternate=forasteiros[3],
    )

    resposta = client_docente.get(notas_de(banca.pk, etapa.pk))

    assert resposta.status_code == 404


def test_etapa_de_outro_edital_e_404(
    client_docente: Client,
    banca_regular: Board,
    edital_suplementar: SelectionProcess,
):
    etapa_alheia = edital_suplementar.stages.get(order=1)

    resposta = client_docente.get(notas_de(banca_regular.pk, etapa_alheia.pk))

    assert resposta.status_code == 404


# --- lote (PUT) ------------------------------------------------------------


def test_lanca_o_lote_de_notas_e_registra_auditoria(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    inscricao: Application,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
):
    faltosa = criar_inscricao(
        program, edital_regular, "Beatriz Nunes", "10000000019", project=projeto
    )

    resposta = _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [
            {"application_id": inscricao.pk, "score": "72.5"},
            {"application_id": faltosa.pk, "absent": True},
        ],
    )

    assert resposta.status_code == 200, resposta.content
    linhas = {linha["full_name"]: linha for linha in resposta.json()}
    assert linhas["Ana Lima"]["score"] == "72.50"
    assert linhas["Ana Lima"]["passed"] is True
    assert linhas["Ana Lima"]["entered_by"] == "Bruno Reis"
    assert linhas["Beatriz Nunes"]["absent"] is True
    assert linhas["Beatriz Nunes"]["score"] is None
    assert linhas["Beatriz Nunes"]["passed"] is False

    gravada = StageScore.objects.get(application=inscricao, stage=etapa)
    assert gravada.score == Decimal("72.50")
    assert gravada.entered_by_id == professores[0].pk
    assert gravada.program_id == program.pk

    registro = AuditLog.objects.get(event="selection.stage_score.set")
    assert registro.program_id == program.pk
    assert registro.target_id == str(banca_regular.pk)
    assert registro.payload["stage_id"] == etapa.pk
    assert registro.payload["application_ids"] == sorted([inscricao.pk, faltosa.pk])


def test_lote_reescreve_a_nota_ja_lancada(
    client_docente: Client, banca_regular: Board, etapa, nota: StageScore
):
    """O lote é `PUT` da planilha: relançar corrige a linha, não cria
    segunda nota (a unique `(inscrição, etapa)` recusaria)."""
    resposta = _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": nota.application_id, "score": "40"}],
    )

    assert resposta.status_code == 200, resposta.content
    nota.refresh_from_db()
    assert nota.score == Decimal("40.00")
    assert nota.passed is False
    assert StageScore.objects.count() == 1


def test_lote_parcial_nao_apaga_quem_ficou_de_fora(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    nota: StageScore,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    outra = criar_inscricao(
        program, edital_regular, "Beatriz Nunes", "10000000019", project=projeto
    )

    _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": outra.pk, "score": "90"}],
    )

    nota.refresh_from_db()
    assert nota.score == Decimal("85.50")


@pytest.mark.parametrize(
    "corpo",
    [
        {"score": "80", "absent": True},
        {},
    ],
    ids=["nota-e-ausencia", "nem-nota-nem-ausencia"],
)
def test_lote_exige_nota_ou_ausencia_e_nunca_os_dois(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    inscricao: Application,
    corpo: dict,
):
    resposta = _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, **corpo}],
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "absent_xor_score"
    assert not StageScore.objects.exists()


def test_lote_recusa_nota_fora_do_intervalo(
    client_docente: Client, banca_regular: Board, etapa, inscricao: Application
):
    resposta = _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, "score": "120"}],
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_score"


def test_lote_com_ata_congelada_e_409_record_frozen(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    inscricao: Application,
    ata_regular: ExaminationRecord,
):
    """Congelada a ata, a nota por trás dela é só leitura: deixá-la mudar
    invalidaria em silêncio a assinatura que confere o `content_hash`."""
    ata_regular.freeze(
        content=[{"full_name": "Ana Lima", "protocol": inscricao.protocol}],
        at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    )
    ata_regular.save()

    resposta = _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, "score": "80"}],
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "record_frozen"
    assert not StageScore.objects.exists()


def test_lote_com_ata_ainda_em_rascunho_passa(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    inscricao: Application,
    ata_regular: ExaminationRecord,
):
    assert ata_regular.status == RecordStatus.DRAFT

    resposta = _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, "score": "80"}],
    )

    assert resposta.status_code == 200, resposta.content


def test_lote_recusa_inscricao_fora_do_recorte_da_banca(
    client_docente: Client,
    banca_regular: Board,
    etapa,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    de_outro_nivel = criar_inscricao(
        program,
        edital_regular,
        "Dora Reis",
        "10002743493",
        project=projeto,
        level=SelectionLevel.DOCTORATE,
    )

    resposta = _put(
        client_docente,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": de_outro_nivel.pk, "score": "80"}],
    )

    assert resposta.status_code == 404
    assert not StageScore.objects.exists()


def test_lote_de_banca_alheia_e_403(
    client_de_fora: Client, banca_regular: Board, etapa, inscricao: Application
):
    resposta = _put(
        client_de_fora,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, "score": "80"}],
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_a_board_member"
    assert not StageScore.objects.exists()


def test_lote_pela_secretaria_e_403(
    client_da_secretaria: Client, banca_regular: Board, etapa, inscricao: Application
):
    """A secretaria monta o edital inteiro e mesmo assim não pontua:
    avaliar é da banca (migration 0006 não lhe dá `add_stagescore`)."""
    resposta = _put(
        client_da_secretaria,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, "score": "80"}],
    )

    assert resposta.status_code == 403
    assert not StageScore.objects.exists()


def test_lote_sem_sessao_e_401(
    client: Client, banca_regular: Board, etapa, inscricao: Application
):
    resposta = _put(
        client,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, "score": "80"}],
    )

    assert resposta.status_code == 401


def test_lote_sem_token_csrf_e_recusado(
    program: Program,
    banca_regular: Board,
    etapa,
    inscricao: Application,
    professores: list[Teacher],
):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    user = dar_conta(program, professores[0], "Docente", "docente-csrf")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    resposta = _put(
        client,
        notas_de(banca_regular.pk, etapa.pk),
        [{"application_id": inscricao.pk, "score": "80"}],
    )

    assert resposta.status_code == 403
    assert not StageScore.objects.exists()
