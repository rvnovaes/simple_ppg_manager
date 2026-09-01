"""O discente se inscreve no edital de bolsas pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão e permissão. Os
invariantes do questionário (renda obrigatória, nível congelado,
`ensure_editable` em memória) ficam em `test_bolsas_inscricao.py`; aqui só
o que é da borda.

Os dois casos que dão nome ao arquivo são a **janela** — fora de
`submissions_open` as três escritas devolvem 409 — e a **posse**: a
inscrição do colega é intocável, e a Secretaria, que lê todas, também não
edita nenhuma.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import Student
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Program,
    ResearchLine,
)
from apps.scholarships.models import (
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"

# Os cinco estados em que a janela de inscrição está fechada.
ESTADOS_FECHADOS = tuple(
    estado
    for estado in ScholarshipEditionStatus.values
    if estado != ScholarshipEditionStatus.SUBMISSIONS_OPEN
)


def criar_discente(*, program: Program, username: str, nome: str, **campos) -> Student:
    """Discente completo: usuário no papel, Person ativa e vínculo de aluno.

    A Person ativa não é detalhe de fixture — é dela que `current_program`
    tira o tenant, e é por ela que a rota chega ao vínculo de aluno.
    """
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name="Discente"))
    pessoa = Person.objects.create(
        program=program,
        user=user,
        full_name=nome,
        primary_email=f"{username}@exemplo.br",
    )
    dados = {
        "modality": Student.Modality.REGULAR,
        "level": Student.Level.MASTERS,
        "project": projeto_do_programa(program),
        "admission_date": date(2026, 3, 2),
    }
    dados.update(campos)
    return Student.objects.create(program=program, person=pessoa, **dados)


def projeto_do_programa(program: Program) -> CollectiveProject:
    """O vínculo regular exige projeto (CheckConstraint
    `student_regular_requires_degree_fields`); um por programa basta."""
    projeto = CollectiveProject.objects.filter(program=program).first()
    if projeto is not None:
        return projeto
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )


@pytest.fixture
def aluno(program: Program) -> Student:
    return criar_discente(program=program, username="ana", nome="Ana Ribeiro")


@pytest.fixture
def colega(program: Program) -> Student:
    return criar_discente(program=program, username="bruno", nome="Bruno Lima")


def logar(client: Client, aluno: Student) -> Client:
    user = aluno.person.user
    assert user is not None
    client.force_login(user)
    return client


@pytest.fixture
def client_do_aluno(client: Client, aluno: Student) -> Client:
    return logar(client, aluno)


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
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.SUBMISSIONS_OPEN,
    )


def criar_inscricao(edicao: ScholarshipEdition, aluno: Student, **extra):
    inscricao = ScholarshipApplication.for_student(
        edition=edicao, student=aluno, **extra
    )
    inscricao.save()
    return inscricao


def corpo(edicao: ScholarshipEdition, **extra) -> dict:
    dados = {"edition_id": edicao.pk, "affirmative_action": True}
    dados.update(extra)
    return dados


def _post(client: Client, endereco: str, dados: dict):
    return client.post(endereco, data=dados, content_type="application/json")


def _patch(client: Client, endereco: str, dados: dict):
    return client.patch(endereco, data=dados, content_type="application/json")


# --- inscrição -------------------------------------------------------------


def test_o_aluno_se_inscreve_e_o_nivel_vem_do_vinculo(
    client_do_aluno: Client,
    edicao: ScholarshipEdition,
    aluno: Student,
    program: Program,
):
    resposta = _post(
        client_do_aluno, "/api/v1/scholarships/applications/", corpo(edicao)
    )

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["student_id"] == aluno.pk
    assert dados["student_name"] == "Ana Ribeiro"
    assert dados["level"] == ScholarshipLevel.MASTERS.value
    assert dados["level_label"] == "Mestrado"
    assert dados["affirmative_action"] is True
    assert dados["submitted_at"] is not None
    assert dados["submission_open"] is True
    # O "Sim" do questionário nasce devendo comprovante.
    assert [item["kind"] for item in dados["pending_docs"]] == ["affirmative_action"]
    assert dados["documents"] == []
    registro = AuditLog.objects.get(event="scholarships.application.create")
    assert registro.program_id == program.pk
    assert registro.payload["level"] == ScholarshipLevel.MASTERS.value


def test_o_nivel_do_payload_e_ignorado_porque_o_schema_nao_o_tem(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student
):
    """Quem escolhe a lista em que compete é o vínculo, não o corpo."""
    resposta = _post(
        client_do_aluno,
        "/api/v1/scholarships/applications/",
        corpo(edicao, level=ScholarshipLevel.DOCTORATE.value, student_id=999),
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["level"] == ScholarshipLevel.MASTERS.value
    assert resposta.json()["student_id"] == aluno.pk


def test_a_segunda_inscricao_na_mesma_edicao_e_recusada(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student
):
    criar_inscricao(edicao, aluno)

    resposta = _post(
        client_do_aluno, "/api/v1/scholarships/applications/", corpo(edicao)
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "duplicate_application"
    assert ScholarshipApplication.objects.count() == 1


def test_atividade_remunerada_sem_renda_e_recusada(
    client_do_aluno: Client, edicao: ScholarshipEdition
):
    resposta = _post(
        client_do_aluno,
        "/api/v1/scholarships/applications/",
        corpo(edicao, has_paid_activity=True),
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "income_required"


def test_atividade_remunerada_com_renda_e_carga_horaria_entra(
    client_do_aluno: Client, edicao: ScholarshipEdition
):
    resposta = _post(
        client_do_aluno,
        "/api/v1/scholarships/applications/",
        corpo(
            edicao,
            has_paid_activity=True,
            monthly_income="3500.00",
            weekly_hours=20,
        ),
    )

    assert resposta.status_code == 201, resposta.content
    assert Decimal(resposta.json()["monthly_income"]) == Decimal("3500.00")
    assert resposta.json()["weekly_hours"] == 20


@pytest.mark.parametrize("estado", ESTADOS_FECHADOS)
def test_fora_da_janela_a_inscricao_e_recusada(
    client_do_aluno: Client, edicao: ScholarshipEdition, estado: str
):
    edicao.status = estado
    edicao.save(update_fields=["status"])

    resposta = _post(
        client_do_aluno, "/api/v1/scholarships/applications/", corpo(edicao)
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "submissions_closed"


def test_aluno_de_isolada_nao_se_inscreve_por_nao_ter_nivel(
    client: Client, program: Program, edicao: ScholarshipEdition
):
    # Isolada não tem nível, e o CheckConstraint
    # `student_non_regular_requires_term` exige o período letivo no lugar
    # dos campos do vínculo regular.
    periodo = AcademicTerm.objects.create(
        year=2026, half=1, starts_on=date(2026, 3, 2), ends_on=date(2026, 7, 10)
    )
    aluno = criar_discente(
        program=program,
        username="iris",
        nome="Iris Nunes",
        modality=Student.Modality.ISOLATED,
        level=None,
        term=periodo,
        project=None,
        admission_date=None,
    )

    resposta = _post(
        logar(client, aluno), "/api/v1/scholarships/applications/", corpo(edicao)
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "student_without_level"


def test_edicao_de_outro_programa_nao_existe_para_o_aluno(
    client_do_aluno: Client,
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    alheia = ScholarshipEdition.objects.create(
        program=outro,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.SUBMISSIONS_OPEN,
    )

    resposta = _post(
        client_do_aluno, "/api/v1/scholarships/applications/", corpo(alheia)
    )

    assert resposta.status_code == 404, resposta.content


def test_sem_permissao_nao_se_inscreve(
    client_sem_permissao: Client, edicao: ScholarshipEdition
):
    resposta = _post(
        client_sem_permissao, "/api/v1/scholarships/applications/", corpo(edicao)
    )

    assert resposta.status_code in (403, 404)


# --- leitura da própria inscrição -----------------------------------------


def test_my_application_devolve_a_inscricao_do_proprio_aluno(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student
):
    inscricao = criar_inscricao(edicao, aluno)

    resposta = client_do_aluno.get(
        f"/api/v1/scholarships/editions/{edicao.pk}/my-application"
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["id"] == inscricao.pk


def test_my_application_e_404_antes_de_se_inscrever(
    client_do_aluno: Client, edicao: ScholarshipEdition
):
    """404 é como a tela sabe que deve oferecer o formulário em branco."""
    resposta = client_do_aluno.get(
        f"/api/v1/scholarships/editions/{edicao.pk}/my-application"
    )

    assert resposta.status_code == 404, resposta.content


def test_my_application_nao_devolve_a_inscricao_do_colega(
    client: Client, edicao: ScholarshipEdition, aluno: Student, colega: Student
):
    criar_inscricao(edicao, aluno)

    resposta = logar(client, colega).get(
        f"/api/v1/scholarships/editions/{edicao.pk}/my-application"
    )

    assert resposta.status_code == 404, resposta.content


# --- retificação -----------------------------------------------------------


def test_o_aluno_retifica_o_proprio_questionario(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student
):
    inscricao = criar_inscricao(edicao, aluno, affirmative_action=True)

    resposta = _patch(
        client_do_aluno,
        f"/api/v1/scholarships/applications/{inscricao.pk}/",
        {"affirmative_action": False, "cadastro_unico": True},
    )

    assert resposta.status_code == 200, resposta.content
    inscricao.refresh_from_db()
    assert inscricao.affirmative_action is False
    assert inscricao.cadastro_unico is True
    registro = AuditLog.objects.get(event="scholarships.application.update")
    assert registro.payload["fields"] == ["affirmative_action", "cadastro_unico"]


def test_o_patch_valida_o_questionario_ja_alterado(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student
):
    inscricao = criar_inscricao(edicao, aluno)

    resposta = _patch(
        client_do_aluno,
        f"/api/v1/scholarships/applications/{inscricao.pk}/",
        {"has_paid_activity": True},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "income_required"


def test_o_colega_nao_edita_a_inscricao_alheia(
    client: Client, edicao: ScholarshipEdition, aluno: Student, colega: Student
):
    inscricao = criar_inscricao(edicao, aluno)

    resposta = _patch(
        logar(client, colega),
        f"/api/v1/scholarships/applications/{inscricao.pk}/",
        {"cadastro_unico": True},
    )

    assert resposta.status_code == 403, resposta.content
    assert resposta.json()["code"] == "not_application_owner"


def test_a_secretaria_le_mas_nao_edita_a_inscricao_do_candidato(
    client_da_secretaria: Client, edicao: ScholarshipEdition, aluno: Student
):
    """`set_fump_level` e `override_band` são as portas dela (f14); o
    questionário do candidato não é uma delas."""
    inscricao = criar_inscricao(edicao, aluno)

    resposta = _patch(
        client_da_secretaria,
        f"/api/v1/scholarships/applications/{inscricao.pk}/",
        {"cadastro_unico": True},
    )

    assert resposta.status_code == 403, resposta.content


@pytest.mark.parametrize("estado", ESTADOS_FECHADOS)
def test_fora_da_janela_o_patch_e_recusado(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student, estado: str
):
    inscricao = criar_inscricao(edicao, aluno)
    edicao.status = estado
    edicao.save(update_fields=["status"])

    resposta = _patch(
        client_do_aluno,
        f"/api/v1/scholarships/applications/{inscricao.pk}/",
        {"cadastro_unico": True},
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "submissions_closed"


def test_inscricao_de_outro_programa_nao_existe(
    client_do_aluno: Client, edicao: ScholarshipEdition
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    alheia = ScholarshipEdition.objects.create(
        program=outro,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.SUBMISSIONS_OPEN,
    )
    forasteiro = criar_discente(program=outro, username="zeca", nome="Zeca Alves")
    inscricao = criar_inscricao(alheia, forasteiro)

    resposta = _patch(
        client_do_aluno,
        f"/api/v1/scholarships/applications/{inscricao.pk}/",
        {"cadastro_unico": True},
    )

    assert resposta.status_code == 404, resposta.content


# --- desistência -----------------------------------------------------------


def test_o_aluno_apaga_a_propria_inscricao_na_janela_aberta(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student
):
    inscricao = criar_inscricao(edicao, aluno)

    resposta = client_do_aluno.delete(
        f"/api/v1/scholarships/applications/{inscricao.pk}/"
    )

    assert resposta.status_code == 204, resposta.content
    assert not ScholarshipApplication.objects.filter(pk=inscricao.pk).exists()
    registro = AuditLog.objects.get(event="scholarships.application.remove")
    assert registro.target_id == str(inscricao.pk)


@pytest.mark.parametrize("estado", ESTADOS_FECHADOS)
def test_fora_da_janela_a_inscricao_some_da_mao_do_candidato(
    client_do_aluno: Client, edicao: ScholarshipEdition, aluno: Student, estado: str
):
    inscricao = criar_inscricao(edicao, aluno)
    edicao.status = estado
    edicao.save(update_fields=["status"])

    resposta = client_do_aluno.delete(
        f"/api/v1/scholarships/applications/{inscricao.pk}/"
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "submissions_closed"
    assert ScholarshipApplication.objects.filter(pk=inscricao.pk).exists()


def test_o_colega_nao_apaga_a_inscricao_alheia(
    client: Client, edicao: ScholarshipEdition, aluno: Student, colega: Student
):
    inscricao = criar_inscricao(edicao, aluno)

    resposta = logar(client, colega).delete(
        f"/api/v1/scholarships/applications/{inscricao.pk}/"
    )

    assert resposta.status_code == 403, resposta.content
    assert ScholarshipApplication.objects.filter(pk=inscricao.pk).exists()
