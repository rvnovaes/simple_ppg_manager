"""A conversão do classificado em aluno regular — o fim do processo seletivo.

Nível (b) da pirâmide (Seção 9): o que interessa aqui é a travessia entre
dois módulos, e ela tem quatro pontos que só o banco revela:

- **a `Person` é reaproveitada** quando já existe com aquele e-mail no
  programa (quem cursou isolada antes, tipicamente). Criar outra esbarraria
  na unique `unique_email_por_programa`.
- **o projeto é obrigatório e casa com o alvo**: no Regular é o da própria
  inscrição; no Suplementar a inscrição só tem linha, e a secretaria escolhe
  dentro dela (armadilha 16 do plano).
- **aprovado nos dois editais não força escolha**: converte-se um, e a outra
  inscrição fica `approved` sem `student` (assunção do plano).
- **a matrícula tranca a classificação** daquele nível × alvo
  (`ranking_locked`).
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import Student, Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    ExaminationRecord,
    QuotaCategory,
    RankingOutcome,
    RecordStatus,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    gerar_protocolo,
)
from apps.selection.services import convert_to_student

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"

# CPFs válidos (mod-11) para as inscrições dos cenários.
CPFS = ["52998224725", "11144477735", "12345678909", "39053344705"]

INGRESSO = "2027-03-01"


def enroll_de(application_id: int) -> str:
    return f"/api/v1/selection/applications/{application_id}/enroll"


def payload(projeto_id: int, matricula: str = "2027000001") -> dict:
    return {
        "registration_number": matricula,
        "admission_date": INGRESSO,
        "project_id": projeto_id,
    }


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


def classificada(
    program: Program,
    edital: SelectionProcess,
    *,
    nome: str = "Ana Lima",
    cpf: str = CPFS[0],
    email: str | None = None,
    projeto: CollectiveProject | None = None,
    linha: ResearchLine | None = None,
    outcome: str = RankingOutcome.CLASSIFIED_OPEN,
    level: str = SelectionLevel.MASTERS,
) -> Application:
    """Inscrição aprovada e já classificada — o estado de onde a conversão parte."""
    return Application.objects.create(
        program=program,
        process=edital,
        protocol=gerar_protocolo(edital),
        full_name=nome,
        email=email or f"{cpf}@exemplo.br",
        cpf=cpf,
        birth_date=date(1995, 5, 20),
        level=level,
        project=projeto,
        research_line=linha,
        quota_category=QuotaCategory.OPEN,
        status=ApplicationStatus.APPROVED,
        final_score=Decimal("90.00"),
        final_rank=1,
        final_outcome=outcome,
        ranked_at=datetime(2027, 1, 10, 12, 0, tzinfo=UTC),
        submitted_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
    )


# --- o caminho feliz --------------------------------------------------------


def test_conversao_cria_aluno_pessoa_papel_e_auditoria(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    inscricao = classificada(program, edital_regular, projeto=projeto)

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk),
        payload(projeto.pk),
        content_type="application/json",
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["registration_number"] == "2027000001"
    assert corpo["level"] == Student.Level.MASTERS
    assert corpo["project_id"] == projeto.pk
    # O prazo regimental não entrou no payload: sai do `Student.save()`
    # (mestrado = 2 anos a partir do ingresso).
    assert corpo["deadline"] == "2029-03-01"
    assert corpo["application"]["status"] == ApplicationStatus.ENROLLED

    aluno = Student.objects.get(pk=corpo["student_id"])
    assert (aluno.modality, aluno.status) == (
        Student.Modality.REGULAR,
        Student.Status.ACTIVE,
    )
    assert aluno.admission_date == date(2027, 3, 1)

    inscricao.refresh_from_db()
    assert inscricao.status == ApplicationStatus.ENROLLED
    assert inscricao.student_id == aluno.pk

    pessoa = aluno.person
    assert (pessoa.program_id, pessoa.primary_email, pessoa.full_name) == (
        program.pk,
        inscricao.email,
        "Ana Lima",
    )
    # A conta nasce com a pessoa (sem senha utilizável) e já entra no papel:
    # o acesso é liberado quando alguém define a senha.
    assert pessoa.user is not None
    assert pessoa.user.groups.filter(name="Discente").exists()

    evento = AuditLog.objects.get(event="selection.application.enroll")
    assert evento.payload["student_id"] == aluno.pk
    assert evento.payload["protocol"] == inscricao.protocol
    assert evento.payload["registration_number"] == "2027000001"


def test_pessoa_existente_com_o_mesmo_email_e_reaproveitada(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    inscricao = classificada(
        program, edital_regular, projeto=projeto, email="ana@exemplo.br"
    )
    ja_existia = Person.objects.create(
        program=program, full_name="Ana Lima", primary_email="ana@exemplo.br"
    )

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 201, resposta.content
    assert resposta.json()["person_id"] == ja_existia.pk
    assert (
        Person.objects.filter(program=program, primary_email="ana@exemplo.br").count()
        == 1
    )


def test_suplementar_escolhe_o_projeto_dentro_da_linha(
    client_da_secretaria: Client,
    program: Program,
    edital_suplementar: SelectionProcess,
    linha: ResearchLine,
    projeto: CollectiveProject,
):
    inscricao = classificada(
        program,
        edital_suplementar,
        linha=linha,
        outcome=RankingOutcome.CLASSIFIED_QUOTA,
    )

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 201, resposta.content
    aluno = Student.objects.get(pk=resposta.json()["student_id"])
    assert aluno.project_id == projeto.pk


# --- as recusas -------------------------------------------------------------


def test_projeto_de_outra_linha_e_recusado_no_suplementar(
    client_da_secretaria: Client,
    program: Program,
    edital_suplementar: SelectionProcess,
    linha: ResearchLine,
):
    outra_linha = ResearchLine.objects.create(program=program, name="Direito Penal")
    de_fora = CollectiveProject.objects.create(
        program=program, research_line=outra_linha, name="Execução penal"
    )
    inscricao = classificada(program, edital_suplementar, linha=linha)

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(de_fora.pk), content_type="application/json"
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "project_target_mismatch"
    assert not Student.objects.exists()


def test_projeto_diferente_do_da_inscricao_e_recusado_no_regular(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    linha: ResearchLine,
    projeto: CollectiveProject,
):
    outro = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Governança de dados"
    )
    inscricao = classificada(program, edital_regular, projeto=projeto)

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(outro.pk), content_type="application/json"
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "project_target_mismatch"


def test_service_sem_projeto_recusa_com_project_required(
    program: Program, edital_regular: SelectionProcess, projeto: CollectiveProject
):
    """A rota sempre resolve um projeto (o schema o exige), então quem pode
    chegar sem ele é o service — e é ele que carrega a regra."""
    inscricao = classificada(program, edital_regular, projeto=projeto)

    with pytest.raises(DomainError) as erro:
        convert_to_student(
            application=inscricao,
            registration_number="2027000001",
            admission_date=date(2027, 3, 1),
            project=None,
        )

    assert erro.value.code == "project_required"


def test_matricula_em_branco_e_recusada(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    inscricao = classificada(program, edital_regular, projeto=projeto)

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk),
        payload(projeto.pk, matricula="   "),
        content_type="application/json",
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "registration_number_required"


def test_matricula_repetida_vira_invalid_student(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """A matrícula é unique no banco: sem o `full_clean()` do service isto
    seria IntegrityError 500, e não 400 com código."""
    pessoa = Person.objects.create(
        program=program, full_name="Já Matriculado", primary_email="ja@exemplo.br"
    )
    Student.objects.create(
        program=program,
        person=pessoa,
        registration_number="2027000001",
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2026, 3, 1),
        deadline=date(2028, 3, 1),
    )
    inscricao = classificada(program, edital_regular, projeto=projeto)

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_student"
    inscricao.refresh_from_db()
    assert inscricao.status == ApplicationStatus.APPROVED
    assert Person.objects.filter(primary_email=inscricao.email).count() == 0


def test_aprovada_sem_classificacao_nao_converte(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    inscricao = classificada(
        program, edital_regular, projeto=projeto, outcome=RankingOutcome.NOT_CLASSIFIED
    )

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "not_classified"
    assert not Student.objects.exists()


def test_converter_duas_vezes_e_409(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    inscricao = classificada(program, edital_regular, projeto=projeto)
    primeira = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )
    assert primeira.status_code == 201, primeira.content

    segunda = client_da_secretaria.post(
        enroll_de(inscricao.pk),
        payload(projeto.pk, matricula="2027000002"),
        content_type="application/json",
    )

    assert segunda.status_code == 409, segunda.content
    assert segunda.json()["code"] == "application_not_approved"
    assert Student.objects.count() == 1


# --- os dois editais e a trava da classificação -----------------------------


def test_aprovado_nos_dois_editais_converte_um_e_o_outro_fica_approved(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    edital_suplementar: SelectionProcess,
    linha: ResearchLine,
    projeto: CollectiveProject,
):
    """Assunção do plano: o sistema não força a escolha. A secretaria
    converte uma das inscrições e a outra continua aprovada, sem aluno."""
    no_regular = classificada(
        program, edital_regular, projeto=projeto, email="dupla@exemplo.br"
    )
    no_suplementar = classificada(
        program,
        edital_suplementar,
        cpf=CPFS[0],
        email="dupla@exemplo.br",
        linha=linha,
    )

    resposta = client_da_secretaria.post(
        enroll_de(no_regular.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 201, resposta.content
    no_suplementar.refresh_from_db()
    assert no_suplementar.status == ApplicationStatus.APPROVED
    assert no_suplementar.student_id is None
    # Uma pessoa só: as duas inscrições têm o mesmo e-mail.
    assert (
        Person.objects.filter(program=program, primary_email="dupla@exemplo.br").count()
        == 1
    )


def test_matricula_tranca_o_recalculo_da_classificacao(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    banca_regular: Board,
):
    ultima = edital_regular.stages.order_by("-order").first()
    assert ultima is not None
    ExaminationRecord.objects.create(
        program=program,
        process=edital_regular,
        stage=ultima,
        level=SelectionLevel.MASTERS,
        project=projeto,
        board=banca_regular,
        status=RecordStatus.SIGNED,
        content=[],
        signed_at=datetime(2027, 1, 5, 10, 0, tzinfo=UTC),
    )
    inscricao = classificada(program, edital_regular, projeto=projeto)
    matricula = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )
    assert matricula.status_code == 201, matricula.content

    recalculo = client_da_secretaria.post(
        f"/api/v1/selection/processes/{edital_regular.pk}/ranking",
        {"level": SelectionLevel.MASTERS, "project_id": projeto.pk},
        content_type="application/json",
    )

    assert recalculo.status_code == 409, recalculo.content
    assert recalculo.json()["code"] == "ranking_locked"


# --- tenant, permissão e CSRF -----------------------------------------------


def test_inscricao_de_outro_programa_e_404(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGY")
    linha_alheia = ResearchLine.objects.create(program=outro, name="Linha de fora")
    projeto_alheio = CollectiveProject.objects.create(
        program=outro, research_line=linha_alheia, name="Projeto de fora"
    )
    alheio = SelectionProcess.objects.create(
        program=outro,
        kind=SelectionKind.REGULAR,
        year=2027,
        title="Edital de outro programa",
        submission_opens_at=edital_regular.submission_opens_at,
        submission_closes_at=edital_regular.submission_closes_at,
        convocation_subject="Assunto",
        convocation_body="Corpo",
    )
    inscricao = classificada(outro, alheio, projeto=projeto_alheio)

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 404, resposta.content


def test_projeto_de_outro_programa_e_404(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGZ")
    linha_alheia = ResearchLine.objects.create(program=outro, name="Linha de fora")
    projeto_alheio = CollectiveProject.objects.create(
        program=outro, research_line=linha_alheia, name="Projeto de fora"
    )
    inscricao = classificada(program, edital_regular, projeto=projeto)

    resposta = client_da_secretaria.post(
        enroll_de(inscricao.pk),
        payload(projeto_alheio.pk),
        content_type="application/json",
    )

    assert resposta.status_code == 404, resposta.content


def test_docente_nao_converte(
    client: Client,
    program: Program,
    docente: Teacher,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    user = User.objects.create_user(username="docente", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    pessoa = docente.person
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    client.force_login(user)
    inscricao = classificada(program, edital_regular, projeto=projeto)

    resposta = client.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 403, resposta.content


def test_sem_sessao_e_401(
    program: Program, edital_regular: SelectionProcess, projeto: CollectiveProject
):
    inscricao = classificada(program, edital_regular, projeto=projeto)
    sessao = Client()

    resposta = sessao.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 401, resposta.content


def test_sem_csrf_a_conversao_e_recusada(
    secretaria: User,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    inscricao = classificada(program, edital_regular, projeto=projeto)
    sessao = Client(enforce_csrf_checks=True)
    sessao.force_login(secretaria)

    resposta = sessao.post(
        enroll_de(inscricao.pk), payload(projeto.pk), content_type="application/json"
    )

    assert resposta.status_code == 403, resposta.content
