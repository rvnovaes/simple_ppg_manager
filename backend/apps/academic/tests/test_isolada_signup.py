"""Auto-registro do candidato a disciplina isolada.

Única rota pública de escrita do projeto, então a suíte cobre menos o
caminho feliz e mais as travas que substituem a sessão: janela do edital,
limite por IP, CSRF e a resposta que não distingue e-mail novo de e-mail
já cadastrado.
"""

import json
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from apps.academic.models import IsolatedEnrollmentCycle
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import AcademicTerm, Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/isolated/signup"
SENHA_FORTE = "isolada-de-2026-ok"

PAYLOAD = {
    "full_name": "Marina Alves",
    "email": "marina@example.com",
    "phone_number": "31999990000",
    "password": SENHA_FORTE,
}


def _post(client: Client, payload: dict):
    return client.post(URL, data=json.dumps(payload), content_type="application/json")


def _ciclo(program: Program, term: AcademicTerm, *, aberto: bool) -> None:
    """Ciclo com a janela de inscrição em torno de agora, ou já encerrada.

    As datas saem de `timezone.now()` porque quem decide se a inscrição
    está aberta é o relógio do servidor no momento da chamada — a rota é
    pública e não recebe `at` de ninguém.
    """
    agora = timezone.now()
    abre = agora - timedelta(days=1) if aberto else agora - timedelta(days=30)
    fecha = agora + timedelta(days=1) if aberto else agora - timedelta(days=20)
    IsolatedEnrollmentCycle.objects.create(
        program=program,
        term=term,
        submission_opens_at=abre,
        submission_closes_at=fecha,
        result_published_on=date(2026, 2, 12),
        appeal_opens_at=fecha + timedelta(days=1),
        appeal_closes_at=fecha + timedelta(days=3),
        final_result_on=date(2026, 2, 17),
        payment_closes_at=fecha + timedelta(days=10),
    )


@pytest.fixture
def inscricao_aberta(program: Program, periodo: AcademicTerm) -> None:
    _ciclo(program, periodo, aberto=True)


def test_signup_cria_conta_pessoa_e_papel_candidato(program, inscricao_aberta, client):
    resposta = _post(client, PAYLOAD)

    assert resposta.status_code == 200, resposta.content
    pessoa = Person.objects.get(program=program, primary_email="marina@example.com")
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

    assert AuditLog.objects.filter(event="academic.isolated.signup").count() == 1


def test_email_repetido_devolve_o_mesmo_corpo_e_nao_duplica(
    program, inscricao_aberta, client
):
    primeira = _post(client, PAYLOAD)
    segunda = _post(client, {**PAYLOAD, "full_name": "Outra Pessoa"})

    assert segunda.status_code == primeira.status_code == 200
    # Idêntico byte a byte: é isto que impede a rota de virar oráculo de
    # quais e-mails já têm conta.
    assert segunda.json() == primeira.json()

    assert Person.objects.filter(primary_email="marina@example.com").count() == 1
    assert Person.objects.get(primary_email="marina@example.com").full_name == (
        "Marina Alves"
    )
    assert User.objects.filter(username="marina@example.com").count() == 1


def test_email_de_conta_existente_nao_tem_a_senha_trocada(
    program, inscricao_aberta, client
):
    """Quem já tem conta (outro programa) não perde o acesso para um
    desconhecido que digite o e-mail dela no formulário público.
    """
    existente = User.objects.create_user(
        username="marina@example.com", password="senha-antiga-2026"
    )

    assert _post(client, PAYLOAD).status_code == 200

    existente.refresh_from_db()
    assert existente.check_password("senha-antiga-2026")
    assert not existente.check_password(SENHA_FORTE)


def test_fora_da_janela_de_inscricao_e_recusado(program, periodo, client):
    _ciclo(program, periodo, aberto=False)

    resposta = _post(client, PAYLOAD)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_open_cycle"
    assert not Person.objects.filter(primary_email="marina@example.com").exists()


def test_sem_edital_nenhum_e_recusado(program, client):
    resposta = _post(client, PAYLOAD)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_open_cycle"
    assert not User.objects.filter(username="marina@example.com").exists()


def test_senha_fraca_e_recusada(program, inscricao_aberta, client):
    resposta = _post(client, {**PAYLOAD, "password": "123"})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "senha_invalida"
    assert not Person.objects.filter(primary_email="marina@example.com").exists()


def test_limite_de_tentativas_por_ip_dispara(program, inscricao_aberta, client):
    for i in range(5):
        resposta = _post(client, {**PAYLOAD, "email": f"candidato{i}@example.com"})
        assert resposta.status_code == 200, resposta.content

    excedente = _post(client, {**PAYLOAD, "email": "candidato5@example.com"})

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"
    assert not Person.objects.filter(primary_email="candidato5@example.com").exists()


def test_signup_sem_token_csrf_e_recusado(program, inscricao_aberta):
    """auth=None desliga o CSRF do SessionAuth; o csrf_protect explícito da
    rota é o que segura — mesma trava do login.
    """
    client = Client(enforce_csrf_checks=True)

    assert _post(client, PAYLOAD).status_code == 403
    assert not Person.objects.filter(primary_email="marina@example.com").exists()


def test_program_id_desempata_quando_ha_dois_editais_abertos(program, periodo, client):
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    outro_periodo = AcademicTerm.objects.create(
        year=2027, half=1, starts_on=date(2027, 3, 1), ends_on=date(2027, 7, 15)
    )
    _ciclo(program, periodo, aberto=True)
    _ciclo(outro, outro_periodo, aberto=True)

    ambiguo = _post(client, PAYLOAD)
    assert ambiguo.status_code == 400
    assert ambiguo.json()["code"] == "program_required"

    escolhido = _post(client, {**PAYLOAD, "program_id": outro.id})
    assert escolhido.status_code == 200, escolhido.content
    assert Person.objects.get(primary_email="marina@example.com").program_id == outro.id


def test_program_id_de_programa_sem_edital_aberto_e_recusado(program, periodo, client):
    """O tenant sai do edital aberto, nunca da escolha livre de quem chama:
    sem isso a rota criaria conta em qualquer programa a qualquer momento.
    """
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    _ciclo(program, periodo, aberto=True)

    resposta = _post(client, {**PAYLOAD, "program_id": outro.id})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_open_cycle"


def test_grupo_candidato_nao_ganha_acesso_a_dados_de_negocio():
    grupo = Group.objects.get(name="Candidato")
    codenames = set(grupo.permissions.values_list("codename", flat=True))

    assert not any(c.endswith(("_student", "_teacher", "_person")) for c in codenames)
