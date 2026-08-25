"""A secretaria designa as bancas examinadoras do edital pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. O conjunto canônico roda aqui — 201 + auditoria, payload não
escolhe tenant, duplicata com `code` estável, 403 sem permissão, 401 sem
sessão, 404 de outro programa, CSRF — mais o que é próprio da banca: os
cinco filtros da listagem e o 409 `board_in_use` assim que a banca tem ata
fora do rascunho.

Ao contrário de etapa e vaga, a banca **não** exige edital em rascunho:
ela se compõe com o edital já publicado. Quem trava é a ata.
"""

from datetime import date

import pytest
from django.test import Client

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Board,
    ExaminationRecord,
    RecordStatus,
    SelectionLevel,
    SelectionProcess,
)

pytestmark = pytest.mark.django_db

BANCAS = "/api/v1/selection/boards/"


def banca_de(board_id: int) -> str:
    return f"{BANCAS}{board_id}/"


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


def criar_professor(program: Program, nome: str, email: str) -> Teacher:
    pessoa = Person.objects.create(program=program, full_name=nome, primary_email=email)
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 3, 1),
    )


@pytest.fixture
def outros_professores(program: Program) -> list[Teacher]:
    """Quatro examinadores diferentes dos da fixture `professores` — é o
    que permite provar que o filtro por docente separa as bancas."""
    return [
        criar_professor(program, "Fábio Nunes", "fabio@exemplo.br"),
        criar_professor(program, "Gisele Ramos", "gisele@exemplo.br"),
        criar_professor(program, "Hugo Teles", "hugo@exemplo.br"),
        criar_professor(program, "Iara Melo", "iara@exemplo.br"),
    ]


def corpo_de_banca(
    edital: SelectionProcess, professores: list[Teacher], **extra
) -> dict:
    presidente, membro_1, membro_2, suplente = professores
    dados = {
        "process_id": edital.pk,
        "level": SelectionLevel.MASTERS.value,
        "president_id": presidente.pk,
        "member_1_id": membro_1.pk,
        "member_2_id": membro_2.pk,
        "alternate_id": suplente.pk,
    }
    dados.update(extra)
    return dados


def criar_banca(
    program: Program,
    edital: SelectionProcess,
    professores: list[Teacher],
    **extra,
) -> Board:
    presidente, membro_1, membro_2, suplente = professores
    campos = {
        "level": SelectionLevel.MASTERS,
        "president": presidente,
        "member_1": membro_1,
        "member_2": membro_2,
        "alternate": suplente,
    }
    campos.update(extra)
    return Board.objects.create(program=program, process=edital, **campos)


def _post(client: Client, url: str, dados: dict):
    return client.post(url, data=dados, content_type="application/json")


def _patch(client: Client, url: str, dados: dict):
    return client.patch(url, data=dados, content_type="application/json")


def itens(resposta) -> list[dict]:
    """A listagem de bancas é paginada, como a de editais."""
    return resposta.json()["items"]


# --- criação ---------------------------------------------------------------


def test_cria_a_banca_e_registra_auditoria(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
    program: Program,
):
    resposta = _post(
        client_da_secretaria,
        BANCAS,
        corpo_de_banca(edital_regular, professores, project_id=projeto.pk),
    )

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["program_id"] == program.pk
    assert dados["process_id"] == edital_regular.pk
    assert dados["target_label"] == str(projeto)
    assert dados["level_label"] == "Mestrado"
    assert dados["in_use"] is False
    # Os quatro examinadores viajam expandidos: a tela não cruza id com nome.
    assert dados["president"]["full_name"] == "Bruno Reis"
    assert dados["alternate"]["full_name"] == "Carla Souza"
    assert dados["alternate"]["category"] == Teacher.Category.EXTERNAL.value
    assert dados["alternate"]["category_label"] == "Externo (banca)"
    assert dados["alternate"]["home_institution"] == "USP"

    registro = AuditLog.objects.get(event="selection.board.create")
    assert registro.program_id == program.pk
    assert registro.target_id == str(dados["id"])


def test_payload_nao_escolhe_o_programa_da_banca(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
    program: Program,
    outro_programa: Program,
):
    resposta = _post(
        client_da_secretaria,
        BANCAS,
        corpo_de_banca(
            edital_regular,
            professores,
            project_id=projeto.pk,
            program_id=outro_programa.pk,
        ),
    )

    assert resposta.status_code == 201, resposta.content
    assert Board.objects.get().program_id == program.pk


def test_banca_duplicada_no_mesmo_nivel_e_alvo_e_400(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    banca_regular: Board,
    outros_professores: list[Teacher],
):
    resposta = _post(
        client_da_secretaria,
        BANCAS,
        corpo_de_banca(edital_regular, outros_professores, project_id=projeto.pk),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_board"
    assert Board.objects.count() == 1


def test_membro_repetido_e_400(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
):
    presidente = professores[0]
    resposta = _post(
        client_da_secretaria,
        BANCAS,
        corpo_de_banca(
            edital_regular,
            professores,
            project_id=projeto.pk,
            member_2_id=presidente.pk,
        ),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_board_member"
    assert not Board.objects.exists()


def test_professor_descredenciado_nao_compoe_banca(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
):
    professores[1].accredited_until = date(2025, 12, 31)
    professores[1].save(update_fields=["accredited_until"])

    resposta = _post(
        client_da_secretaria,
        BANCAS,
        corpo_de_banca(edital_regular, professores, project_id=projeto.pk),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "teacher_not_accredited"


def test_alvo_incompativel_com_o_tipo_do_edital_e_400(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    linha: ResearchLine,
    professores: list[Teacher],
):
    """Edital Regular pede projeto coletivo; linha de pesquisa é do
    Suplementar."""
    resposta = _post(
        client_da_secretaria,
        BANCAS,
        corpo_de_banca(edital_regular, professores, research_line_id=linha.pk),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "target_mismatch"


def test_docente_de_outro_programa_e_404(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
    outro_programa: Program,
):
    """404 e não 400: o id de outro programa não existe nesta sessão, e o
    código do domínio confirmaria que ele existe em algum lugar."""
    alheio = criar_professor(outro_programa, "Zeca Alheio", "zeca@exemplo.br")

    resposta = _post(
        client_da_secretaria,
        BANCAS,
        corpo_de_banca(
            edital_regular, professores, project_id=projeto.pk, member_2_id=alheio.pk
        ),
    )

    assert resposta.status_code == 404
    assert not Board.objects.exists()


def test_criar_banca_em_edital_de_outro_programa_e_404(
    client_da_secretaria: Client,
    professores: list[Teacher],
    outro_programa: Program,
):
    alheio = SelectionProcess.objects.create(
        program=outro_programa,
        kind="regular",
        year=2029,
        title="Edital alheio",
        submission_opens_at="2028-09-01T00:00:00Z",
        submission_closes_at="2028-09-30T00:00:00Z",
    )

    resposta = _post(client_da_secretaria, BANCAS, corpo_de_banca(alheio, professores))

    assert resposta.status_code == 404
    assert not Board.objects.exists()


def test_criar_banca_sem_permissao_e_403(
    client_sem_permissao: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
):
    resposta = _post(
        client_sem_permissao,
        BANCAS,
        corpo_de_banca(edital_regular, professores, project_id=projeto.pk),
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_banca_sem_sessao_e_401(
    client: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
):
    resposta = _post(
        client,
        BANCAS,
        corpo_de_banca(edital_regular, professores, project_id=projeto.pk),
    )

    assert resposta.status_code == 401


def test_criar_banca_sem_token_csrf_e_recusada(
    secretaria: User,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    professores: list[Teacher],
):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    resposta = _post(
        client,
        BANCAS,
        corpo_de_banca(edital_regular, professores, project_id=projeto.pk),
    )

    assert resposta.status_code == 403
    assert not Board.objects.exists()


# --- listagem e filtros ----------------------------------------------------


def test_lista_so_as_bancas_do_programa_da_sessao(
    client_da_secretaria: Client,
    banca_regular: Board,
    outro_programa: Program,
):
    alheio = SelectionProcess.objects.create(
        program=outro_programa,
        kind="regular",
        year=2029,
        title="Edital alheio",
        submission_opens_at="2028-09-01T00:00:00Z",
        submission_closes_at="2028-09-30T00:00:00Z",
    )
    projeto_alheio = CollectiveProject.objects.create(
        program=outro_programa,
        research_line=ResearchLine.objects.create(
            program=outro_programa, name="Linha alheia"
        ),
        name="Projeto alheio",
    )
    criar_banca(
        outro_programa,
        alheio,
        [
            criar_professor(outro_programa, f"Docente {i}", f"docente{i}@alheio.br")
            for i in range(4)
        ],
        project=projeto_alheio,
    )

    resposta = client_da_secretaria.get(BANCAS)

    assert resposta.status_code == 200
    assert [item["id"] for item in itens(resposta)] == [banca_regular.pk]


def test_filtra_por_edital_e_por_nivel(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    edital_suplementar: SelectionProcess,
    projeto: CollectiveProject,
    linha: ResearchLine,
    banca_regular: Board,
    professores: list[Teacher],
):
    doutorado = criar_banca(
        program,
        edital_regular,
        professores,
        level=SelectionLevel.DOCTORATE,
        project=projeto,
    )
    suplementar = criar_banca(
        program, edital_suplementar, professores, research_line=linha
    )

    por_edital = client_da_secretaria.get(BANCAS, {"process_id": edital_regular.pk})
    assert sorted(item["id"] for item in itens(por_edital)) == sorted(
        [banca_regular.pk, doutorado.pk]
    )

    por_nivel = client_da_secretaria.get(
        BANCAS, {"level": SelectionLevel.DOCTORATE.value}
    )
    assert [item["id"] for item in itens(por_nivel)] == [doutorado.pk]

    por_linha = client_da_secretaria.get(BANCAS, {"research_line_id": linha.pk})
    assert [item["id"] for item in itens(por_linha)] == [suplementar.pk]

    por_projeto = client_da_secretaria.get(BANCAS, {"project_id": projeto.pk})
    assert sorted(item["id"] for item in itens(por_projeto)) == sorted(
        [banca_regular.pk, doutorado.pk]
    )


def test_filtra_por_docente_em_qualquer_um_dos_quatro_papeis(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    banca_regular: Board,
    outros_professores: list[Teacher],
):
    outra = criar_banca(
        program,
        edital_regular,
        outros_professores,
        level=SelectionLevel.DOCTORATE,
        project=projeto,
    )

    for professor, esperada in (
        (banca_regular.president, banca_regular),
        (banca_regular.alternate, banca_regular),
        (outra.member_2, outra),
    ):
        resposta = client_da_secretaria.get(BANCAS, {"teacher_id": professor.pk})
        assert [item["id"] for item in itens(resposta)] == [esperada.pk]


def test_filtrar_por_docente_de_outro_programa_e_404(
    client_da_secretaria: Client, banca_regular: Board, outro_programa: Program
):
    alheio = criar_professor(outro_programa, "Zeca Alheio", "zeca@exemplo.br")

    resposta = client_da_secretaria.get(BANCAS, {"teacher_id": alheio.pk})

    assert resposta.status_code == 404


def test_detalhe_da_banca_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio = SelectionProcess.objects.create(
        program=outro_programa,
        kind="regular",
        year=2029,
        title="Edital alheio",
        submission_opens_at="2028-09-01T00:00:00Z",
        submission_closes_at="2028-09-30T00:00:00Z",
    )
    projeto_alheio = CollectiveProject.objects.create(
        program=outro_programa,
        research_line=ResearchLine.objects.create(
            program=outro_programa, name="Linha alheia"
        ),
        name="Projeto alheio",
    )
    banca = criar_banca(
        outro_programa,
        alheio,
        [
            criar_professor(outro_programa, f"Docente {i}", f"docente{i}@alheio.br")
            for i in range(4)
        ],
        project=projeto_alheio,
    )

    assert client_da_secretaria.get(banca_de(banca.pk)).status_code == 404


def test_detalhe_traz_os_quatro_examinadores(
    client_da_secretaria: Client, banca_regular: Board
):
    resposta = client_da_secretaria.get(banca_de(banca_regular.pk))

    assert resposta.status_code == 200
    dados = resposta.json()
    assert [
        dados[papel]["full_name"]
        for papel in ("president", "member_1", "member_2", "alternate")
    ] == ["Bruno Reis", "Daniel Alves", "Elisa Prado", "Carla Souza"]
    assert dados["process_title"] == str(banca_regular.process)


# --- edição ----------------------------------------------------------------


def test_troca_examinador_e_registra_auditoria(
    client_da_secretaria: Client,
    banca_regular: Board,
    outros_professores: list[Teacher],
):
    substituto = outros_professores[0]

    resposta = _patch(
        client_da_secretaria,
        banca_de(banca_regular.pk),
        {"member_1_id": substituto.pk},
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["member_1"]["full_name"] == "Fábio Nunes"
    banca_regular.refresh_from_db()
    assert banca_regular.member_1_id == substituto.pk
    registro = AuditLog.objects.get(event="selection.board.update")
    assert registro.payload["fields"] == ["member_1_id"]


def test_edicao_com_membro_repetido_e_400(
    client_da_secretaria: Client, banca_regular: Board
):
    resposta = _patch(
        client_da_secretaria,
        banca_de(banca_regular.pk),
        {"member_1_id": banca_regular.president_id},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_board_member"


@pytest.mark.parametrize(
    "status",
    [RecordStatus.AWAITING_SIGNATURES, RecordStatus.SIGNED, RecordStatus.SUPERSEDED],
)
def test_banca_com_ata_fora_do_rascunho_nao_e_editavel(
    client_da_secretaria: Client,
    banca_regular: Board,
    ata_regular: ExaminationRecord,
    outros_professores: list[Teacher],
    status: RecordStatus,
):
    """A ata congelada carrega a composição da banca no hash: trocar
    membro depois disso invalidaria assinatura já dada."""
    ExaminationRecord.objects.filter(pk=ata_regular.pk).update(status=status)

    resposta = _patch(
        client_da_secretaria,
        banca_de(banca_regular.pk),
        {"member_1_id": outros_professores[0].pk},
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "board_in_use"
    banca_regular.refresh_from_db()
    assert banca_regular.member_1_id != outros_professores[0].pk


def test_banca_com_ata_em_rascunho_continua_editavel(
    client_da_secretaria: Client,
    banca_regular: Board,
    ata_regular: ExaminationRecord,
    outros_professores: list[Teacher],
):
    resposta = _patch(
        client_da_secretaria,
        banca_de(banca_regular.pk),
        {"member_1_id": outros_professores[0].pk},
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["in_use"] is False


def test_in_use_na_listagem_quando_ha_ata_congelada(
    client_da_secretaria: Client, banca_regular: Board, ata_regular: ExaminationRecord
):
    ExaminationRecord.objects.filter(pk=ata_regular.pk).update(
        status=RecordStatus.SIGNED
    )

    resposta = client_da_secretaria.get(BANCAS)

    assert [item["in_use"] for item in itens(resposta)] == [True]


def test_editar_banca_sem_permissao_e_403(
    client_sem_permissao: Client, banca_regular: Board
):
    resposta = _patch(
        client_sem_permissao, banca_de(banca_regular.pk), {"level": "doctorate"}
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_editar_banca_sem_sessao_e_401(client: Client, banca_regular: Board):
    resposta = _patch(client, banca_de(banca_regular.pk), {"level": "doctorate"})

    assert resposta.status_code == 401
