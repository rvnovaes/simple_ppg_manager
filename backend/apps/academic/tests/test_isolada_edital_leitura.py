"""Leitura do edital pela secretaria: os ciclos e as ofertas de um ciclo.

Nível (b) da pirâmide (Seção 9). O que só existe aqui é o que a borda
acrescenta: quem pode escolher o ciclo livremente e quem continua preso à
janela de inscrição.
"""

import pytest
from django.test import Client

from apps.academic.models import (
    DisciplineOffering,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
    IsolatedRequestStatus,
)
from apps.academic.tests.conftest import criar_candidato, criar_requerimento, logar
from apps.accounts.models import User
from apps.people.models import Person
from apps.programs.models import AcademicTerm, Program

pytestmark = pytest.mark.django_db

CICLOS = "/api/v1/academic/isolated/cycles/"
OFERTAS = "/api/v1/academic/isolated/offerings/"


@pytest.fixture
def client_da_secretaria(client: Client, secretaria: User, program: Program) -> Client:
    """Secretaria com Person no programa: é dela que sai `current_program`."""
    pessoa = Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    return logar(client, pessoa)


def test_lista_os_ciclos_do_programa_com_o_calendario(
    client_da_secretaria: Client, ciclo: IsolatedEnrollmentCycle
):
    resposta = client_da_secretaria.get(CICLOS)

    assert resposta.status_code == 200
    (corpo,) = resposta.json()
    assert corpo["id"] == ciclo.pk
    assert corpo["term_label"] == "2026/1"
    assert corpo["is_active"] is True
    # A janela do `ciclo` é de fevereiro de 2026 e o teste roda depois:
    # o booleano sai do relógio do servidor, não da data no navegador.
    assert corpo["submission_open"] is False
    assert corpo["payment_closes_at"].startswith("2026-02-25")


def test_ciclo_de_outro_programa_nao_aparece(
    client_da_secretaria: Client, ciclo: IsolatedEnrollmentCycle
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    periodo = AcademicTerm.objects.get(pk=ciclo.term_id)
    IsolatedEnrollmentCycle.objects.create(
        program=outro,
        term=periodo,
        submission_opens_at=ciclo.submission_opens_at,
        submission_closes_at=ciclo.submission_closes_at,
        result_published_on=ciclo.result_published_on,
        appeal_opens_at=ciclo.appeal_opens_at,
        appeal_closes_at=ciclo.appeal_closes_at,
        final_result_on=ciclo.final_result_on,
        payment_closes_at=ciclo.payment_closes_at,
    )

    resposta = client_da_secretaria.get(CICLOS)

    assert [item["id"] for item in resposta.json()] == [ciclo.pk]


def test_candidato_nao_le_o_edital_como_entidade(
    client: Client, program: Program, ciclo: IsolatedEnrollmentCycle
):
    candidato = criar_candidato(program=program, username="ana", nome="Ana Souza")

    resposta = logar(client, candidato).get(CICLOS)

    assert resposta.status_code == 403


def test_ciclos_exigem_sessao(client: Client):
    assert client.get(CICLOS).status_code == 401


def test_ofertas_do_ciclo_escolhido_ignoram_a_janela_de_inscricao(
    client_da_secretaria: Client,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
):
    """A análise acontece depois que a inscrição fecha — é aí que a
    secretaria precisa das vagas restantes e de saber onde falta
    classificação.
    """
    requerimento: IsolatedEnrollmentRequest = criar_requerimento(
        program=program,
        ciclo=ciclo,
        nome="Ana Souza",
        status=IsolatedRequestStatus.DEFERRED,
    )
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta, rank=1)

    resposta = client_da_secretaria.get(OFERTAS, {"cycle_id": ciclo.pk})

    assert resposta.status_code == 200
    (corpo,) = resposta.json()
    assert corpo["id"] == oferta.pk
    assert corpo["seats"] == 2
    # O deferido já ocupou uma das duas vagas.
    assert corpo["seats_available"] == 1
    assert corpo["needs_ranking"] is False


def test_ofertas_de_ciclo_de_outro_programa_sao_404(
    client_da_secretaria: Client, ciclo: IsolatedEnrollmentCycle
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGY")
    periodo = AcademicTerm.objects.get(pk=ciclo.term_id)
    alheio = IsolatedEnrollmentCycle.objects.create(
        program=outro,
        term=periodo,
        submission_opens_at=ciclo.submission_opens_at,
        submission_closes_at=ciclo.submission_closes_at,
        result_published_on=ciclo.result_published_on,
        appeal_opens_at=ciclo.appeal_opens_at,
        appeal_closes_at=ciclo.appeal_closes_at,
        final_result_on=ciclo.final_result_on,
        payment_closes_at=ciclo.payment_closes_at,
    )

    resposta = client_da_secretaria.get(OFERTAS, {"cycle_id": alheio.pk})

    assert resposta.status_code == 404


def test_candidato_nao_escolhe_o_ciclo_das_ofertas(
    client: Client, program: Program, ciclo: IsolatedEnrollmentCycle
):
    """Sem esta trava o candidato leria o edital de qualquer semestre a
    qualquer hora, driblando a janela que a rota impõe a ele.
    """
    candidato = criar_candidato(program=program, username="bia", nome="Bia Alves")

    resposta = logar(client, candidato).get(OFERTAS, {"cycle_id": ciclo.pk})

    assert resposta.status_code == 403
