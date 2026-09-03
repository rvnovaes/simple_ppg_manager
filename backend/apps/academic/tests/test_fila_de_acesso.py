"""A fila da secretaria: ler os cadastros pendentes e decidir sobre eles.

Nível (b) da pirâmide (Seção 9): bate nos endpoints reais, sem mock de
ORM. O que só existe aqui é o que a borda acrescenta ao model e ao
service — o escopo de tenant (por isso o cenário tem DOIS programas: com
um só, o vazamento não aparece nem em teste), a posse invertida (ninguém
confirma o próprio cadastro) e o corte de permissão por papel.

Cada papel que age no mesmo teste recebe um `Client()` próprio: duas
fixtures com `force_login` sobre a fixture `client` do pytest-django
disputam a MESMA sessão, e a última a ser resolvida vence em silêncio —
o teste de "papel X não pode" passaria rodando como o papel Y.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import AccessProfile, AccessRequest, Student, Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine

pytestmark = pytest.mark.django_db

URL = "/api/v1/access/requests/"
SENHA = "fila-de-acesso-2026"


def _post(client: Client, url: str, payload: dict | None = None):
    return client.post(
        url, data=json.dumps(payload or {}), content_type="application/json"
    )


def _url(solicitacao: AccessRequest, acao: str) -> str:
    return f"{URL}{solicitacao.pk}/{acao}"


def _pendente(
    program: Program,
    *,
    email: str,
    nome: str,
    profile: str = AccessProfile.TEACHER,
    com_conta: bool = True,
) -> AccessRequest:
    """Um cadastro pendente gravado pelo ORM.

    Sem passar pelo endpoint público de signup de propósito: o que se
    testa aqui é a decisão, e o autocadastro tem suíte própria
    (`test_autocadastro.py`). O marcador "Cadastro pendente" entra porque
    é dele que a aprovação precisa se livrar.
    """
    user = None
    if com_conta:
        user = User.objects.create_user(username=email, email=email, password=SENHA)
        user.groups.add(Group.objects.get(name="Cadastro pendente"))
    person = Person.objects.create(
        program=program, user=user, full_name=nome, primary_email=email
    )
    campos = (
        {
            "teacher_category": Teacher.Category.PERMANENT,
            "academic_degree": Teacher.AcademicDegree.DOCTORATE,
            "lattes_url": "http://lattes.cnpq.br/1234567890",
        }
        if profile == AccessProfile.TEACHER
        else {}
    )
    return AccessRequest.objects.create(
        program=program, person=person, profile=profile, **campos
    )


def _com_papel(program: Program, *, papel: str, username: str) -> Client:
    """Uma sessão própria para o papel, com `Person` ativa no programa.

    A `Person` ativa não é enfeite: é dela que `current_program` tira o
    tenant. Sem ela a rota devolveria 403 por falta de programa, e o
    teste do corte de permissão passaria pelo motivo errado.
    """
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name=papel))
    Person.objects.create(
        program=program,
        user=user,
        full_name=username.title(),
        primary_email=f"{username}@exemplo.br",
    )
    cliente = Client()
    cliente.force_login(user)
    return cliente


@pytest.fixture
def secretaria_no_programa(secretaria: User, program: Program) -> Person:
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Pós em Economia", acronym="PPGE")


@pytest.fixture
def projeto(program: Program) -> CollectiveProject:
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name="Justiça e Trabalho"
    )


@pytest.fixture
def docente_pendente(program: Program) -> AccessRequest:
    return _pendente(program, email="ana.doc@example.com", nome="Ana Docente")


@pytest.fixture
def discente_pendente(program: Program) -> AccessRequest:
    return _pendente(
        program,
        email="bruno.disc@example.com",
        nome="Bruno Discente",
        profile=AccessProfile.STUDENT,
    )


# --- a fila ----------------------------------------------------------


def test_fila_traz_as_pendentes_do_programa(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    docente_pendente: AccessRequest,
    discente_pendente: AccessRequest,
):
    resposta = client_secretaria.get(URL)

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["count"] == 2
    por_id = {item["id"]: item for item in corpo["items"]}
    assert set(por_id) == {docente_pendente.pk, discente_pendente.pk}
    linha = por_id[docente_pendente.pk]
    assert linha["person_name"] == "Ana Docente"
    assert linha["person_email"] == "ana.doc@example.com"
    assert linha["profile"] == AccessProfile.TEACHER.value
    assert linha["teacher_category"] == Teacher.Category.PERMANENT.value
    assert linha["academic_degree"] == Teacher.AcademicDegree.DOCTORATE.value
    assert linha["status"] == AccessRequest.Status.PENDING.value
    assert linha["decided_at"] is None


def test_fila_nao_mostra_solicitacao_de_outro_programa(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    outro_programa: Program,
    docente_pendente: AccessRequest,
):
    """O cenário precisa de dois programas: com um só, o vazamento de
    tenant não aparece nem em teste."""
    alheia = _pendente(outro_programa, email="clara@example.com", nome="Clara Externa")

    corpo = client_secretaria.get(URL).json()

    assert [item["id"] for item in corpo["items"]] == [docente_pendente.pk]
    assert alheia.pk not in {item["id"] for item in corpo["items"]}


def test_fila_omite_o_que_ja_foi_decidido(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    docente_pendente: AccessRequest,
):
    decidida = _pendente(program, email="dora@example.com", nome="Dora Recusada")
    decidida.reject(note="Titulação não comprovada.")
    decidida.save()

    pendentes = client_secretaria.get(URL).json()
    historico = client_secretaria.get(
        URL, {"status": AccessRequest.Status.REJECTED.value}
    ).json()

    assert [item["id"] for item in pendentes["items"]] == [docente_pendente.pk]
    assert [item["id"] for item in historico["items"]] == [decidida.pk]


def test_fila_com_situacao_fora_do_enum_e_recusada(
    client_secretaria: Client, secretaria_no_programa: Person
):
    assert client_secretaria.get(URL, {"status": "inventado"}).status_code == 422


# --- aprovar ---------------------------------------------------------


def test_aprovar_docente_cria_a_ficha_com_a_categoria_declarada(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    docente_pendente: AccessRequest,
):
    resposta = _post(
        client_secretaria,
        _url(docente_pendente, "approve"),
        {"accredited_since": "2026-03-01"},
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == AccessRequest.Status.APPROVED.value
    assert corpo["decided_at"] is not None

    docente = Teacher.objects.get(person=docente_pendente.person)
    assert docente.program_id == program.pk
    assert docente.category == Teacher.Category.PERMANENT
    assert docente.academic_degree == Teacher.AcademicDegree.DOCTORATE
    assert docente.lattes_url == "http://lattes.cnpq.br/1234567890"
    assert str(docente.accredited_since) == "2026-03-01"

    user = docente_pendente.person.user
    assert user is not None
    papeis = {g.name for g in user.groups.all()}
    assert "Docente" in papeis
    assert "Cadastro pendente" not in papeis

    assert AuditLog.objects.filter(
        event="academic.access_request.approve", program=program
    ).exists()


def test_aprovar_docente_sem_data_de_credenciamento_e_400(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    docente_pendente: AccessRequest,
):
    resposta = _post(client_secretaria, _url(docente_pendente, "approve"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "accredited_since_required"
    docente_pendente.refresh_from_db()
    assert docente_pendente.status == AccessRequest.Status.PENDING


def test_aprovar_discente_cria_aluno_regular_com_prazo(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    projeto: CollectiveProject,
    discente_pendente: AccessRequest,
):
    resposta = _post(
        client_secretaria,
        _url(discente_pendente, "approve"),
        {
            "level": Student.Level.MASTERS.value,
            "project_id": projeto.pk,
            "admission_date": "2026-03-02",
        },
    )

    assert resposta.status_code == 200, resposta.content
    aluno = Student.objects.get(person=discente_pendente.person)
    assert aluno.modality == Student.Modality.REGULAR
    assert aluno.status == Student.Status.ACTIVE
    assert aluno.project_id == projeto.pk
    # O prazo sai sozinho do `Student.save()`: 2 anos no mestrado.
    assert str(aluno.deadline) == "2028-03-02"

    user = discente_pendente.person.user
    assert user is not None
    papeis = {g.name for g in user.groups.all()}
    assert "Discente" in papeis
    assert "Cadastro pendente" not in papeis


def test_aprovar_discente_sem_os_campos_do_regular_e_400(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    discente_pendente: AccessRequest,
):
    resposta = _post(client_secretaria, _url(discente_pendente, "approve"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "incomplete_regular"
    assert not Student.objects.filter(person=discente_pendente.person).exists()


def test_aprovar_com_projeto_de_outro_programa_e_404(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    outro_programa: Program,
    discente_pendente: AccessRequest,
):
    linha = ResearchLine.objects.create(program=outro_programa, name="Macroeconomia")
    alheio = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha, name="Câmbio"
    )

    resposta = _post(
        client_secretaria,
        _url(discente_pendente, "approve"),
        {
            "level": Student.Level.MASTERS.value,
            "project_id": alheio.pk,
            "admission_date": "2026-03-02",
        },
    )

    assert resposta.status_code == 404


def test_aprovar_duas_vezes_e_409(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    docente_pendente: AccessRequest,
):
    payload = {"accredited_since": "2026-03-01"}
    assert (
        _post(client_secretaria, _url(docente_pendente, "approve"), payload).status_code
        == 200
    )

    resposta = _post(client_secretaria, _url(docente_pendente, "approve"), payload)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "already_decided"
    # E nenhum segundo Teacher para a mesma pessoa.
    assert Teacher.objects.filter(person=docente_pendente.person).count() == 1


def test_solicitacao_de_outro_programa_e_404(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    outro_programa: Program,
):
    alheia = _pendente(outro_programa, email="clara@example.com", nome="Clara Externa")

    assert (
        _post(
            client_secretaria,
            _url(alheia, "approve"),
            {"accredited_since": "2026-03-01"},
        ).status_code
        == 404
    )


# --- recusar ---------------------------------------------------------


def test_recusar_sem_motivo_e_400(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    docente_pendente: AccessRequest,
):
    resposta = _post(
        client_secretaria, _url(docente_pendente, "reject"), {"note": "  "}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "rejection_requires_note"
    docente_pendente.refresh_from_db()
    assert docente_pendente.status == AccessRequest.Status.PENDING
    docente_pendente.person.refresh_from_db()
    assert docente_pendente.person.status == Person.Status.ACTIVE


def test_recusar_com_motivo_arquiva_a_pessoa(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    docente_pendente: AccessRequest,
):
    resposta = _post(
        client_secretaria,
        _url(docente_pendente, "reject"),
        {"note": "Titulação não comprovada."},
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == AccessRequest.Status.REJECTED.value
    assert corpo["decision_note"] == "Titulação não comprovada."
    assert corpo["decided_at"] is not None

    pessoa = docente_pendente.person
    pessoa.refresh_from_db()
    assert pessoa.status == Person.Status.ARCHIVED
    assert not Teacher.objects.filter(person=pessoa).exists()
    assert AuditLog.objects.filter(
        event="academic.access_request.reject", program=program
    ).exists()


def test_recusar_o_que_ja_foi_decidido_e_409(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    docente_pendente: AccessRequest,
):
    _post(
        client_secretaria,
        _url(docente_pendente, "reject"),
        {"note": "Titulação não comprovada."},
    )

    resposta = _post(
        client_secretaria, _url(docente_pendente, "reject"), {"note": "De novo."}
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "already_decided"


# --- quem decide -----------------------------------------------------


def test_ninguem_confirma_o_proprio_cadastro(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
):
    """A secretária que se cadastrasse como docente teria a permissão de
    decidir — é a posse que a barra, não o papel."""
    propria = AccessRequest.objects.create(
        program=program,
        person=secretaria_no_programa,
        profile=AccessProfile.TEACHER,
        teacher_category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
    )

    resposta = _post(
        client_secretaria, _url(propria, "approve"), {"accredited_since": "2026-03-01"}
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    propria.refresh_from_db()
    assert propria.status == AccessRequest.Status.PENDING
    assert not Teacher.objects.filter(person=secretaria_no_programa).exists()


def test_ninguem_recusa_o_proprio_cadastro(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
):
    propria = AccessRequest.objects.create(
        program=program,
        person=secretaria_no_programa,
        profile=AccessProfile.STUDENT,
    )

    resposta = _post(client_secretaria, _url(propria, "reject"), {"note": "Desisti."})

    assert resposta.status_code == 403
    propria.refresh_from_db()
    assert propria.status == AccessRequest.Status.PENDING


@pytest.mark.parametrize("papel", ["Docente", "Discente", "Candidato"])
def test_papel_sem_permissao_nao_le_a_fila(
    program: Program, docente_pendente: AccessRequest, papel: str
):
    cliente = _com_papel(program, papel=papel, username=f"{papel.lower()}-fila")

    assert cliente.get(URL).status_code == 403


@pytest.mark.parametrize("papel", ["Docente", "Discente", "Candidato"])
def test_papel_sem_permissao_nao_decide(
    program: Program, docente_pendente: AccessRequest, papel: str
):
    cliente = _com_papel(program, papel=papel, username=f"{papel.lower()}-decide")

    assert (
        _post(
            cliente,
            _url(docente_pendente, "approve"),
            {"accredited_since": "2026-03-01"},
        ).status_code
        == 403
    )
    assert (
        _post(cliente, _url(docente_pendente, "reject"), {"note": "Não."}).status_code
        == 403
    )
    docente_pendente.refresh_from_db()
    assert docente_pendente.status == AccessRequest.Status.PENDING


def test_sem_sessao_nao_le_a_fila(client: Client, docente_pendente: AccessRequest):
    assert client.get(URL).status_code == 401
    assert _post(client, _url(docente_pendente, "approve"), {}).status_code == 401


def test_aprovar_sem_csrf_e_recusado(
    secretaria: User,
    secretaria_no_programa: Person,
    docente_pendente: AccessRequest,
):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(secretaria)

    resposta = strict.post(
        _url(docente_pendente, "approve"),
        data="{}",
        content_type="application/json",
    )

    assert resposta.status_code == 403
