"""Autocadastro público: docente, discente e candidato.

Única rota de escrita sem sessão do projeto, então a suíte cobre menos o
caminho feliz e mais as travas que substituem a sessão: o interruptor
`accepts_self_signup` do programa, o limite por IP, o CSRF e a resposta
que não distingue e-mail novo de e-mail já cadastrado.

Sucessora de `test_isolada_signup.py`: a resolução do tenant saiu do
edital aberto e virou flag do programa, e o formulário passou a ter
perfil.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import AccessProfile, AccessRequest, Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/access/signup"
SENHA_FORTE = "autocadastro-de-2026-ok"

PAYLOAD = {
    "program_id": 0,  # preenchido em `_post`: o id sai da fixture `program`.
    "profile": AccessProfile.CANDIDATE.value,
    "full_name": "Marina Alves",
    "email": "marina@example.com",
    "phone_number": "31999990000",
    "password": SENHA_FORTE,
}

DOCENTE = {
    **PAYLOAD,
    "profile": AccessProfile.TEACHER.value,
    "teacher_category": Teacher.Category.PERMANENT.value,
    "academic_degree": Teacher.AcademicDegree.DOCTORATE.value,
    "lattes_url": "http://lattes.cnpq.br/1234567890",
}

DISCENTE = {**PAYLOAD, "profile": AccessProfile.STUDENT.value}


def _post(client: Client, payload: dict, *, program: Program | None = None):
    corpo = dict(payload)
    if program is not None:
        corpo["program_id"] = program.pk
    return client.post(URL, data=json.dumps(corpo), content_type="application/json")


@pytest.fixture
def programa_aberto(program: Program) -> Program:
    """O PPGD da data migration, com o autocadastro garantidamente ligado."""
    program.accepts_self_signup = True
    program.save(update_fields=["accepts_self_signup"])
    return program


def test_candidato_ganha_conta_pessoa_e_papel_sem_solicitacao(programa_aberto, client):
    resposta = _post(client, PAYLOAD, program=programa_aberto)

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["requires_confirmation"] is False

    pessoa = Person.objects.get(
        program=programa_aberto, primary_email="marina@example.com"
    )
    assert pessoa.full_name == "Marina Alves"
    assert pessoa.phone_number == "31999990000"

    user = pessoa.user
    assert user is not None
    assert user.username == "marina@example.com"
    assert [g.name for g in user.groups.all()] == ["Candidato"]
    # A senha do payload é a senha da conta: o candidato volta sozinho para
    # acompanhar o resultado e enviar o comprovante.
    assert user.check_password(SENHA_FORTE)
    # E nenhum poder além do papel.
    assert not user.is_staff and not user.is_superuser

    # Candidato não gera fila para a secretaria: o edital já é a fila dele.
    assert not AccessRequest.objects.filter(person=pessoa).exists()
    assert AuditLog.objects.filter(event="academic.access.signup").count() == 1


def test_docente_cria_solicitacao_pendente_e_so_o_grupo_marcador(
    programa_aberto, client
):
    resposta = _post(client, DOCENTE, program=programa_aberto)

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["requires_confirmation"] is True

    pessoa = Person.objects.get(
        program=programa_aberto, primary_email="marina@example.com"
    )
    solicitacao = AccessRequest.objects.get(person=pessoa)
    assert solicitacao.program_id == programa_aberto.pk
    assert solicitacao.profile == AccessProfile.TEACHER
    assert solicitacao.status == AccessRequest.Status.PENDING
    assert solicitacao.teacher_category == Teacher.Category.PERMANENT
    assert solicitacao.academic_degree == Teacher.AcademicDegree.DOCTORATE
    assert solicitacao.lattes_url == "http://lattes.cnpq.br/1234567890"
    # O deferimento é da secretaria: a pessoa ainda não é Teacher.
    assert not Teacher.objects.filter(person=pessoa).exists()

    user = pessoa.user
    assert user is not None
    assert [g.name for g in user.groups.all()] == ["Cadastro pendente"]
    assert not user.is_staff and not user.is_superuser


def test_discente_pendente_nao_guarda_campo_de_docente(programa_aberto, client):
    """Quem manda campo de docente sem ser docente sai com eles vazios.

    A CheckConstraint `access_non_teacher_has_no_teacher_fields` os proíbe;
    confiar no payload transformaria dado sujo em IntegrityError (500).
    """
    resposta = _post(
        client,
        {**DISCENTE, "teacher_category": Teacher.Category.PERMANENT.value},
        program=programa_aberto,
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["requires_confirmation"] is True

    solicitacao = AccessRequest.objects.get(person__primary_email="marina@example.com")
    assert solicitacao.profile == AccessProfile.STUDENT
    assert solicitacao.teacher_category == ""
    assert solicitacao.academic_degree == ""
    assert solicitacao.home_institution == ""
    assert solicitacao.lattes_url == ""


@pytest.mark.parametrize(
    "payload", [PAYLOAD, DOCENTE, DISCENTE], ids=["candidato", "docente", "discente"]
)
def test_email_repetido_devolve_o_mesmo_corpo_e_nao_duplica(
    programa_aberto, client, payload
):
    primeira = _post(client, payload, program=programa_aberto)
    segunda = _post(
        client, {**payload, "full_name": "Outra Pessoa"}, program=programa_aberto
    )

    assert segunda.status_code == primeira.status_code == 200
    # Idêntico byte a byte: é isto que impede a rota de virar oráculo de
    # quais e-mails já têm conta.
    assert segunda.content == primeira.content

    assert Person.objects.filter(primary_email="marina@example.com").count() == 1
    assert Person.objects.get(primary_email="marina@example.com").full_name == (
        "Marina Alves"
    )
    assert User.objects.filter(username="marina@example.com").count() == 1
    # A segunda passagem não abre uma segunda solicitação, nem para os
    # perfis que abrem a primeira.
    assert AccessRequest.objects.filter(
        person__primary_email="marina@example.com"
    ).count() == (0 if payload["profile"] == AccessProfile.CANDIDATE else 1)


def test_email_de_conta_existente_nao_tem_a_senha_trocada(programa_aberto, client):
    """Quem já tem conta (outro programa) não perde o acesso para um
    desconhecido que digite o e-mail dela no formulário público.
    """
    existente = User.objects.create_user(
        username="marina@example.com", password="senha-antiga-2026"
    )

    assert _post(client, PAYLOAD, program=programa_aberto).status_code == 200

    existente.refresh_from_db()
    assert existente.check_password("senha-antiga-2026")
    assert not existente.check_password(SENHA_FORTE)


def test_senha_fraca_e_recusada(programa_aberto, client):
    resposta = _post(client, {**PAYLOAD, "password": "123"}, program=programa_aberto)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "senha_invalida"
    assert not Person.objects.filter(primary_email="marina@example.com").exists()


def test_programa_com_o_autocadastro_desligado_e_recusado(program, client):
    program.accepts_self_signup = False
    program.save(update_fields=["accepts_self_signup"])

    resposta = _post(client, PAYLOAD, program=program)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "signup_closed"
    assert not Person.objects.filter(primary_email="marina@example.com").exists()
    assert not User.objects.filter(username="marina@example.com").exists()


def test_signup_closed_e_indistinguivel_entre_desligado_inativo_e_inexistente(
    program, client
):
    """Os três casos respondem a mesma coisa, byte a byte.

    Distinguir "não existe" de "existe mas não aceita" contaria a quem
    chuta id quais programas existem nesta instalação.
    """
    program.accepts_self_signup = False
    program.save(update_fields=["accepts_self_signup"])
    inativo = Program.objects.create(
        name="Pós em Economia",
        acronym="PPGE",
        is_active=False,
        accepts_self_signup=True,
    )
    inexistente = 10**6

    desligado = _post(client, PAYLOAD, program=program)
    fechado = _post(client, PAYLOAD, program=inativo)
    fantasma = _post(client, {**PAYLOAD, "program_id": inexistente})

    assert desligado.status_code == fechado.status_code == fantasma.status_code == 400
    assert desligado.content == fechado.content == fantasma.content


def test_limite_de_tentativas_por_ip_dispara(programa_aberto, client):
    for i in range(5):
        resposta = _post(
            client,
            {**PAYLOAD, "email": f"candidato{i}@example.com"},
            program=programa_aberto,
        )
        assert resposta.status_code == 200, resposta.content

    excedente = _post(
        client, {**PAYLOAD, "email": "candidato5@example.com"}, program=programa_aberto
    )

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"
    assert not Person.objects.filter(primary_email="candidato5@example.com").exists()


def test_signup_sem_token_csrf_e_recusado(programa_aberto):
    """auth=None desliga o CSRF do SessionAuth; o csrf_protect explícito da
    rota é o que segura — mesma trava do login.
    """
    client = Client(enforce_csrf_checks=True)

    assert _post(client, PAYLOAD, program=programa_aberto).status_code == 403
    assert not Person.objects.filter(primary_email="marina@example.com").exists()


@pytest.mark.parametrize("nome", ["Candidato", "Cadastro pendente"])
def test_grupo_do_autocadastro_nao_da_acesso_a_dados_de_negocio(nome):
    grupo = Group.objects.get(name=nome)
    codenames = set(grupo.permissions.values_list("codename", flat=True))

    assert not any(c.endswith(("_student", "_teacher", "_person")) for c in codenames)


@pytest.mark.parametrize(
    "url",
    ["/api/v1/people/", "/api/v1/academic/teachers/", "/api/v1/academic/students/"],
)
def test_pendente_nao_enxerga_pessoa_docente_nem_discente(programa_aberto, client, url):
    """O Group marcador não é papel: ele só diz "esperando deferimento".

    O cliente da listagem é um `Client()` próprio, e não a fixture `client`
    usada no cadastro — duas fixtures com `force_login` sobre o mesmo
    cliente disputam a mesma sessão, e a última a resolver vence em
    silêncio.
    """
    assert _post(client, DOCENTE, program=programa_aberto).status_code == 200
    pendente = User.objects.get(username="marina@example.com")

    logado = Client()
    logado.force_login(pendente)

    assert logado.get(url).status_code == 403
