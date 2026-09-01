"""A secretaria monta a edição do edital de bolsas pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. O conjunto canônico por recurso roda aqui — 201 + auditoria,
payload não escolhe tenant, duplicata com `code` estável, 403 sem
permissão, 401 sem sessão, 404 de outro programa, CSRF — mais o que é
próprio da edição: as cinco transições nomeadas, cada uma a partir do
estado certo e do errado.

O dado é criado nos DOIS programas em todo teste de escopo: com um só
programa semeado, um vazamento de tenant passa despercebido.

Os invariantes do model (transição sem salvar, guardas de leitura) ficam
em `test_bolsas_edital.py`, em memória. Aqui só o que é da borda.
"""

from datetime import date

import pytest
from django.contrib.auth.models import Permission
from django.test import Client

from apps.academic.models import Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program
from apps.scholarships.models import (
    CommitteeMember,
    ScholarshipEdition,
    ScholarshipEditionStatus,
)

pytestmark = pytest.mark.django_db

EDICOES = "/api/v1/scholarships/editions/"

# (rota, permissão exigida, estado de origem, estado de destino, code do 409).
TRANSICOES = (
    (
        "open-submissions",
        "change",
        ScholarshipEditionStatus.DRAFT,
        ScholarshipEditionStatus.SUBMISSIONS_OPEN,
        "edition_not_draft",
    ),
    (
        "start-review",
        "change",
        ScholarshipEditionStatus.SUBMISSIONS_OPEN,
        ScholarshipEditionStatus.UNDER_REVIEW,
        "edition_not_submissions_open",
    ),
    (
        "publish-preliminary",
        "publish",
        ScholarshipEditionStatus.UNDER_REVIEW,
        ScholarshipEditionStatus.PRELIMINARY_RESULT,
        "edition_not_under_review",
    ),
    (
        "open-appeals",
        "change",
        ScholarshipEditionStatus.PRELIMINARY_RESULT,
        ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
        "edition_not_preliminary_result",
    ),
    (
        "publish-final",
        "publish",
        ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
        ScholarshipEditionStatus.FINAL_RESULT,
        "edition_not_appeals_under_review",
    ),
)

TODOS_OS_ESTADOS = tuple(ScholarshipEditionStatus.values)


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
    dados = {"year": 2027, "title": "Edital de Bolsas 2027"}
    dados.update(extra)
    return dados


def _post(client: Client, url: str, dados: dict | None = None):
    if dados is None:
        return client.post(url)
    return client.post(url, data=dados, content_type="application/json")


def _patch(client: Client, url: str, dados: dict):
    return client.patch(url, data=dados, content_type="application/json")


def criar_edicao(program: Program, **extra) -> ScholarshipEdition:
    """Edição direto no banco, para os testes que não exercitam a criação."""
    campos = {"year": 2026, "title": "Edital de Bolsas 2026"}
    campos.update(extra)
    return ScholarshipEdition.objects.create(program=program, **campos)


def criar_docente(program: Program, nome: str, email: str) -> Teacher:
    pessoa = Person.objects.create(program=program, full_name=nome, primary_email=email)
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 3, 1),
    )


@pytest.fixture
def docente(program: Program) -> Teacher:
    return criar_docente(program, "Bruno Reis", "bruno@exemplo.br")


# --- criação ---------------------------------------------------------------


def test_cria_a_edicao_em_rascunho_e_registra_auditoria(
    client_da_secretaria: Client, program: Program
):
    resposta = _post(
        client_da_secretaria,
        EDICOES,
        corpo(submission_starts_on="2027-03-01", submission_ends_on="2027-03-20"),
    )

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["status"] == ScholarshipEditionStatus.DRAFT.value
    assert dados["status_label"] == "Rascunho"
    assert dados["bareme_editable"] is True
    assert dados["submission_open"] is False
    assert dados["results_visible_to_student"] is False
    assert dados["submission_starts_on"] == "2027-03-01"
    assert dados["notice_url"] == ""
    edicao = ScholarshipEdition.objects.get(pk=dados["id"])
    assert edicao.program_id == program.pk
    assert edicao.published_preliminary_at is None
    registro = AuditLog.objects.get(event="scholarships.edition.create")
    assert registro.program_id == program.pk
    assert registro.target_id == str(edicao.pk)


def test_o_cronograma_e_opcional(client_da_secretaria: Client):
    """As datas são informação publicada, e no dia em que a secretaria abre
    a edição o calendário ainda está sendo fechado."""
    resposta = _post(client_da_secretaria, EDICOES, corpo())

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["final_result_on"] is None


def test_payload_nao_escolhe_o_programa_da_edicao(
    client_da_secretaria: Client, program: Program, outro_programa: Program
):
    resposta = _post(client_da_secretaria, EDICOES, corpo(program_id=outro_programa.pk))

    assert resposta.status_code == 201, resposta.content
    assert (
        ScholarshipEdition.objects.get(pk=resposta.json()["id"]).program_id
        == program.pk
    )


def test_segunda_edicao_do_mesmo_ano_e_400(
    client_da_secretaria: Client, program: Program
):
    criar_edicao(program, year=2027)

    resposta = _post(client_da_secretaria, EDICOES, corpo(year=2027))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_edition"


def test_o_mesmo_ano_em_outro_programa_nao_e_duplicata(
    client_da_secretaria: Client, outro_programa: Program
):
    criar_edicao(outro_programa, year=2027)

    assert _post(client_da_secretaria, EDICOES, corpo(year=2027)).status_code == 201


def test_criar_edicao_sem_permissao_e_403(client_sem_permissao: Client):
    resposta = _post(client_sem_permissao, EDICOES, corpo())

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_edicao_sem_sessao_e_401(client: Client):
    assert _post(client, EDICOES, corpo()).status_code == 401


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

    assert _post(client, EDICOES, corpo()).status_code == 403
    assert not ScholarshipEdition.objects.filter(year=2027).exists()


# --- leitura ---------------------------------------------------------------


def test_lista_so_as_edicoes_do_programa_da_sessao(
    client_da_secretaria: Client, program: Program, outro_programa: Program
):
    minha = criar_edicao(program)
    alheia = criar_edicao(outro_programa)

    resposta = client_da_secretaria.get(EDICOES)

    assert resposta.status_code == 200
    ids = [item["id"] for item in resposta.json()["items"]]
    assert ids == [minha.pk]
    assert alheia.pk not in ids


def test_lista_filtra_por_ano_e_estado(client_da_secretaria: Client, program: Program):
    rascunho = criar_edicao(program, year=2026)
    criar_edicao(program, year=2025, status=ScholarshipEditionStatus.FINAL_RESULT)

    resposta = client_da_secretaria.get(f"{EDICOES}?year=2026&status=draft")

    assert [item["id"] for item in resposta.json()["items"]] == [rascunho.pk]


def test_ver_edicao_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = criar_edicao(outro_programa)

    assert client_da_secretaria.get(f"{EDICOES}{alheia.pk}/").status_code == 404


def test_ler_sem_permissao_e_403(client_sem_permissao: Client, program: Program):
    edicao = criar_edicao(program)

    assert client_sem_permissao.get(f"{EDICOES}{edicao.pk}/").status_code == 403


# --- retificação -----------------------------------------------------------


def test_retifica_o_cronograma_e_audita(client_da_secretaria: Client, program: Program):
    edicao = criar_edicao(program)

    resposta = _patch(
        client_da_secretaria,
        f"{EDICOES}{edicao.pk}/",
        {"title": "Edital de Bolsas 2026 — retificado", "appeal_ends_on": "2026-05-10"},
    )

    assert resposta.status_code == 200, resposta.content
    edicao.refresh_from_db()
    assert edicao.title == "Edital de Bolsas 2026 — retificado"
    assert edicao.appeal_ends_on == date(2026, 5, 10)
    registro = AuditLog.objects.get(event="scholarships.edition.update")
    assert registro.payload["fields"] == ["appeal_ends_on", "title"]


def test_retificar_para_um_ano_ja_usado_e_400(
    client_da_secretaria: Client, program: Program
):
    criar_edicao(program, year=2025)
    edicao = criar_edicao(program, year=2026)

    resposta = _patch(client_da_secretaria, f"{EDICOES}{edicao.pk}/", {"year": 2025})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_edition"


def test_retificar_edicao_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = criar_edicao(outro_programa)

    resposta = _patch(client_da_secretaria, f"{EDICOES}{alheia.pk}/", {"title": "X"})

    assert resposta.status_code == 404


def test_retificar_sem_permissao_e_403(client_sem_permissao: Client, program: Program):
    edicao = criar_edicao(program)

    resposta = _patch(client_sem_permissao, f"{EDICOES}{edicao.pk}/", {"title": "X"})

    assert resposta.status_code == 403


# --- as cinco transições ---------------------------------------------------


@pytest.mark.parametrize(("rota", "_perm", "origem", "destino", "_code"), TRANSICOES)
def test_transicao_a_partir_do_estado_certo_e_200_com_auditoria(
    client_da_secretaria: Client,
    program: Program,
    rota: str,
    _perm: str,
    origem: str,
    destino: str,
    _code: str,
):
    edicao = criar_edicao(program, status=origem)

    resposta = _post(client_da_secretaria, f"{EDICOES}{edicao.pk}/{rota}")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["status"] == destino
    edicao.refresh_from_db()
    assert edicao.status == destino
    evento = f"scholarships.edition.{rota.replace('-', '_')}"
    registro = AuditLog.objects.get(event=evento)
    assert registro.program_id == program.pk
    assert registro.payload["status"] == destino


@pytest.mark.parametrize(("rota", "_perm", "origem", "_destino", "code"), TRANSICOES)
@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_transicao_a_partir_do_estado_errado_e_409(
    client_da_secretaria: Client,
    program: Program,
    rota: str,
    _perm: str,
    origem: str,
    _destino: str,
    code: str,
    estado: str,
):
    """A matriz inteira (transição × estado) pega de graça o caso "a
    transição não repete o próprio destino"."""
    if estado == origem:
        pytest.skip("estado de origem válido, coberto pelo teste do 200")
    edicao = criar_edicao(program, status=estado)

    resposta = _post(client_da_secretaria, f"{EDICOES}{edicao.pk}/{rota}")

    assert resposta.status_code == 409, resposta.content
    corpo_da_resposta = resposta.json()
    assert corpo_da_resposta["code"] == code
    assert corpo_da_resposta["detail"]
    edicao.refresh_from_db()
    assert edicao.status == estado
    assert not AuditLog.objects.filter(
        event__startswith="scholarships.edition"
    ).exists()


@pytest.mark.parametrize(("rota", "_perm", "origem", "_destino", "_code"), TRANSICOES)
def test_transicao_sem_permissao_e_403(
    client_sem_permissao: Client,
    program: Program,
    rota: str,
    _perm: str,
    origem: str,
    _destino: str,
    _code: str,
):
    edicao = criar_edicao(program, status=origem)

    resposta = _post(client_sem_permissao, f"{EDICOES}{edicao.pk}/{rota}")

    assert resposta.status_code == 403
    edicao.refresh_from_db()
    assert edicao.status == origem


@pytest.mark.parametrize(("rota", "_perm", "origem", "_destino", "_code"), TRANSICOES)
def test_transicao_em_edicao_de_outro_programa_e_404(
    client_da_secretaria: Client,
    outro_programa: Program,
    rota: str,
    _perm: str,
    origem: str,
    _destino: str,
    _code: str,
):
    alheia = criar_edicao(outro_programa, status=origem)

    assert (
        _post(client_da_secretaria, f"{EDICOES}{alheia.pk}/{rota}").status_code == 404
    )


@pytest.mark.parametrize(
    ("rota", "origem", "carimbo"),
    (
        (
            "publish-preliminary",
            ScholarshipEditionStatus.UNDER_REVIEW,
            "published_preliminary_at",
        ),
        (
            "publish-final",
            ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
            "published_final_at",
        ),
    ),
)
def test_publicacao_carimba_o_instante(
    client_da_secretaria: Client,
    program: Program,
    rota: str,
    origem: str,
    carimbo: str,
):
    edicao = criar_edicao(program, status=origem)

    resposta = _post(client_da_secretaria, f"{EDICOES}{edicao.pk}/{rota}")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()[carimbo] is not None
    edicao.refresh_from_db()
    assert getattr(edicao, carimbo) is not None


@pytest.mark.parametrize(
    ("rota", "origem"),
    (
        ("publish-preliminary", ScholarshipEditionStatus.UNDER_REVIEW),
        ("publish-final", ScholarshipEditionStatus.APPEALS_UNDER_REVIEW),
    ),
)
def test_publicar_exige_a_permissao_propria_e_nao_a_de_alterar(
    client: Client, program: Program, rota: str, origem: str
):
    """`change_scholarshipedition` move a edição entre estados de trabalho;
    congelar o ano é `publish_scholarshipedition`, permissão própria."""
    usuario = User.objects.create_user(username="montador", password="x-123-abc")
    usuario.user_permissions.add(
        Permission.objects.get(codename="change_scholarshipedition"),
        Permission.objects.get(codename="view_scholarshipedition"),
    )
    Person.objects.create(
        program=program,
        user=usuario,
        full_name="Marta Lopes",
        primary_email="marta@exemplo.br",
    )
    client.force_login(usuario)
    edicao = criar_edicao(program, status=origem)

    assert _post(client, f"{EDICOES}{edicao.pk}/{rota}").status_code == 403


# --- comissão --------------------------------------------------------------


def test_designa_membro_da_comissao_e_audita(
    client_da_secretaria: Client, program: Program, docente: Teacher
):
    edicao = criar_edicao(program)

    resposta = _post(
        client_da_secretaria,
        f"{EDICOES}{edicao.pk}/committee/",
        {
            "teacher_id": docente.pk,
            "appointed_on": "2026-02-01",
            "ordinance": "Portaria 3/2026",
        },
    )

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["teacher_name"] == "Bruno Reis"
    assert dados["ordinance"] == "Portaria 3/2026"
    assert CommitteeMember.objects.get(pk=dados["id"]).edition_id == edicao.pk
    registro = AuditLog.objects.get(event="scholarships.committee.add")
    assert registro.program_id == program.pk
    assert registro.payload["teacher_id"] == docente.pk


def test_o_mesmo_professor_duas_vezes_e_400(
    client_da_secretaria: Client, program: Program, docente: Teacher
):
    edicao = criar_edicao(program)
    CommitteeMember.objects.create(edition=edicao, teacher=docente)

    resposta = _post(
        client_da_secretaria,
        f"{EDICOES}{edicao.pk}/committee/",
        {"teacher_id": docente.pk},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_committee_member"


def test_professor_de_outro_programa_e_404(
    client_da_secretaria: Client, program: Program, outro_programa: Program
):
    """404 e não 400 `program_mismatch`: o id de outro programa não existe
    aqui, e o código do domínio confirmaria que ele existe em algum lugar."""
    edicao = criar_edicao(program)
    alheio = criar_docente(outro_programa, "Zeca Alves", "zeca@exemplo.br")

    resposta = _post(
        client_da_secretaria,
        f"{EDICOES}{edicao.pk}/committee/",
        {"teacher_id": alheio.pk},
    )

    assert resposta.status_code == 404
    assert not CommitteeMember.objects.exists()


def test_lista_a_comissao_da_edicao(
    client_da_secretaria: Client, program: Program, docente: Teacher
):
    edicao = criar_edicao(program)
    membro = CommitteeMember.objects.create(
        edition=edicao, teacher=docente, ordinance="Portaria 3/2026"
    )

    resposta = client_da_secretaria.get(f"{EDICOES}{edicao.pk}/committee/")

    assert resposta.status_code == 200
    assert [item["id"] for item in resposta.json()] == [membro.pk]


def test_listar_comissao_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = criar_edicao(outro_programa)

    assert (
        client_da_secretaria.get(f"{EDICOES}{alheia.pk}/committee/").status_code == 404
    )


def test_remove_membro_da_comissao_e_audita(
    client_da_secretaria: Client, program: Program, docente: Teacher
):
    edicao = criar_edicao(program)
    membro = CommitteeMember.objects.create(edition=edicao, teacher=docente)

    resposta = client_da_secretaria.delete(
        f"{EDICOES}{edicao.pk}/committee/{membro.pk}/"
    )

    assert resposta.status_code == 204, resposta.content
    assert not CommitteeMember.objects.filter(pk=membro.pk).exists()
    registro = AuditLog.objects.get(event="scholarships.committee.remove")
    assert registro.program_id == program.pk
    assert registro.target_id == str(membro.pk)


def test_remover_membro_de_edicao_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = criar_edicao(outro_programa)
    alheio = criar_docente(outro_programa, "Zeca Alves", "zeca@exemplo.br")
    membro = CommitteeMember.objects.create(edition=alheia, teacher=alheio)

    resposta = client_da_secretaria.delete(
        f"{EDICOES}{alheia.pk}/committee/{membro.pk}/"
    )

    assert resposta.status_code == 404
    assert CommitteeMember.objects.filter(pk=membro.pk).exists()


def test_escrever_na_comissao_sem_permissao_e_403(
    client_sem_permissao: Client, program: Program, docente: Teacher
):
    edicao = criar_edicao(program)
    membro = CommitteeMember.objects.create(edition=edicao, teacher=docente)

    assert (
        _post(
            client_sem_permissao,
            f"{EDICOES}{edicao.pk}/committee/",
            {"teacher_id": docente.pk},
        ).status_code
        == 403
    )
    assert (
        client_sem_permissao.delete(
            f"{EDICOES}{edicao.pk}/committee/{membro.pk}/"
        ).status_code
        == 403
    )
    assert CommitteeMember.objects.filter(pk=membro.pk).exists()
