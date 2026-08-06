"""Decisão da secretaria sobre o requerimento de isolada, pelos endpoints.

Nível (b) da pirâmide (Seção 9). O que só existe aqui é o que a borda
acrescenta ao model: a posse invertida (quem julga é quem NÃO é o
candidato), o corte de vagas que só se enxerga com a oferta cheia, e o
cancelamento que devolve a vaga para o próximo caber.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from apps.academic.models import (
    DisciplineOffering,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
    IsolatedPaymentStatus,
    IsolatedRequestStatus,
)
from apps.academic.tests.conftest import (
    SENHA,
    criar_candidato,
    criar_requerimento,
    logar,
)
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program

pytestmark = pytest.mark.django_db

URL = "/api/v1/academic/isolated/requests/"


def _url(requerimento: IsolatedEnrollmentRequest, acao: str) -> str:
    return f"{URL}{requerimento.id}/{acao}"


def _post(client: Client, url: str, payload: dict | None = None):
    return client.post(
        url, data=json.dumps(payload or {}), content_type="application/json"
    )


@pytest.fixture
def secretaria_no_programa(secretaria: User, program: Program) -> Person:
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


@pytest.fixture
def inscrito(
    program: Program, ciclo: IsolatedEnrollmentCycle, oferta: DisciplineOffering
) -> IsolatedEnrollmentRequest:
    """Requerimento inscrito, com a oferta já classificada pelo docente.

    Classificado porque é o estado normal na mesa da secretaria: ela
    julga depois que o docente ordenou a fila.
    """
    requerimento = criar_requerimento(
        program=program,
        ciclo=ciclo,
        nome="Ana Souza",
        status=IsolatedRequestStatus.SUBMITTED,
        submitted_at=timezone.now(),
    )
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta, rank=1)
    return requerimento


def _outro_inscrito(
    *,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
    nome: str,
    rank: int,
    status: str = IsolatedRequestStatus.SUBMITTED,
) -> IsolatedEnrollmentRequest:
    requerimento = criar_requerimento(
        program=program,
        ciclo=ciclo,
        nome=nome,
        status=status,
        submitted_at=timezone.now(),
    )
    IsolatedEnrollmentItem.objects.create(
        request=requerimento, offering=oferta, rank=rank
    )
    return requerimento


# --- deferimento -----------------------------------------------------


def test_deferir_muda_o_status_grava_a_gru_e_audita(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    resposta = _post(
        client_secretaria,
        _url(inscrito, "defer"),
        {"note": "Documentação em ordem.", "gru_url": "https://gru.ufmg.br/1234"},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == IsolatedRequestStatus.DEFERRED
    assert corpo["gru_url"] == "https://gru.ufmg.br/1234"
    assert corpo["decision_note"] == "Documentação em ordem."
    assert corpo["decided_at"] is not None
    inscrito.refresh_from_db()
    assert inscrito.status == IsolatedRequestStatus.DEFERRED
    assert AuditLog.objects.filter(
        event="academic.isolated.defer", target_id=inscrito.pk
    ).exists()


def test_deferir_sem_gru_mantem_o_campo_vazio(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    """A guia pode vir depois — o que não pode é o link chegar torto."""
    resposta = _post(client_secretaria, _url(inscrito, "defer"))

    assert resposta.status_code == 200
    assert resposta.json()["gru_url"] == ""


def test_deferir_com_gru_malformada_e_recusado_na_borda(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    resposta = _post(
        client_secretaria, _url(inscrito, "defer"), {"gru_url": "gru.ufmg.br"}
    )

    assert resposta.status_code == 422


def test_deferir_servidor_da_ufmg_nasce_isento(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    """A isenção é consequência do vínculo declarado, não uma segunda
    decisão que a secretaria poderia esquecer de tomar.
    """
    inscrito.is_ufmg_staff = True
    inscrito.save(update_fields=["is_ufmg_staff"])

    resposta = _post(client_secretaria, _url(inscrito, "defer"))

    assert resposta.status_code == 200
    assert resposta.json()["payment_status"] == IsolatedPaymentStatus.EXEMPT


def test_deferir_sem_vaga_na_oferta_e_recusado(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
    inscrito: IsolatedEnrollmentRequest,
):
    """`oferta` tem duas vagas; dois deferidos as esgotam."""
    for posicao, nome in ((2, "Bia Lima"), (3, "Caio Melo")):
        _outro_inscrito(
            program=program,
            ciclo=ciclo,
            oferta=oferta,
            nome=nome,
            rank=posicao,
            status=IsolatedRequestStatus.DEFERRED,
        )

    resposta = _post(client_secretaria, _url(inscrito, "defer"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_seats_available"
    inscrito.refresh_from_db()
    assert inscrito.status == IsolatedRequestStatus.SUBMITTED


def test_deferir_oferta_nao_classificada_e_recusado(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    """Sem a lista do docente ninguém é matriculado."""
    inscrito.items.update(rank=None)

    resposta = _post(client_secretaria, _url(inscrito, "defer"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "offering_not_ranked"


def test_deferir_recusa_a_falta_de_classificacao_antes_da_falta_de_vaga(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
    inscrito: IsolatedEnrollmentRequest,
):
    """Recusar por vaga uma oferta que sequer foi ordenada diria à
    secretaria a coisa errada: o que falta ali é o docente.
    """
    for posicao, nome in ((2, "Bia Lima"), (3, "Caio Melo")):
        _outro_inscrito(
            program=program,
            ciclo=ciclo,
            oferta=oferta,
            nome=nome,
            rank=posicao,
            status=IsolatedRequestStatus.DEFERRED,
        )
    inscrito.items.update(rank=None)

    resposta = _post(client_secretaria, _url(inscrito, "defer"))

    assert resposta.json()["code"] == "offering_not_ranked"


def test_deferir_requerimento_ja_decidido_e_conflito(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    inscrito.status = IsolatedRequestStatus.REJECTED
    inscrito.save(update_fields=["status"])

    resposta = _post(client_secretaria, _url(inscrito, "defer"))

    assert resposta.status_code == 409


def test_deferir_rascunho_nao_esbarra_na_classificacao_antes_do_estado(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    """Rascunho não é candidato, então `needs_ranking` é falso — quem
    barra é o estado, com 409, e não um 400 confuso de classificação.
    """
    inscrito.status = IsolatedRequestStatus.DRAFT
    inscrito.items.update(rank=None)
    inscrito.save(update_fields=["status"])

    resposta = _post(client_secretaria, _url(inscrito, "defer"))

    assert resposta.status_code == 409


# --- indeferimento ---------------------------------------------------


def test_indeferir_com_motivo_muda_o_status_e_audita(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    resposta = _post(
        client_secretaria, _url(inscrito, "reject"), {"note": "Falta o diploma."}
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == IsolatedRequestStatus.REJECTED
    assert resposta.json()["decision_note"] == "Falta o diploma."
    assert AuditLog.objects.filter(
        event="academic.isolated.reject", target_id=inscrito.pk
    ).exists()


def test_indeferir_sem_o_campo_note_e_recusado_na_borda(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    resposta = _post(client_secretaria, _url(inscrito, "reject"))

    assert resposta.status_code == 422


def test_indeferir_com_motivo_em_branco_e_recusado_pelo_model(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    resposta = _post(client_secretaria, _url(inscrito, "reject"), {"note": "   "})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "rejection_requires_note"


def test_indeferir_nao_olha_vaga_nem_classificacao(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    """Negar não consome vaga: a fila do docente não é pré-requisito."""
    inscrito.items.update(rank=None)

    resposta = _post(
        client_secretaria, _url(inscrito, "reject"), {"note": "Fora do edital."}
    )

    assert resposta.status_code == 200


# --- cancelamento ----------------------------------------------------


def test_cancelar_deferido_libera_a_vaga_e_o_proximo_passa_a_caber(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
    inscrito: IsolatedEnrollmentRequest,
):
    ocupantes = [
        _outro_inscrito(
            program=program,
            ciclo=ciclo,
            oferta=oferta,
            nome=nome,
            rank=posicao,
            status=IsolatedRequestStatus.DEFERRED,
        )
        for posicao, nome in ((2, "Bia Lima"), (3, "Caio Melo"))
    ]
    assert _post(client_secretaria, _url(inscrito, "defer")).status_code == 400

    cancelamento = _post(
        client_secretaria,
        _url(ocupantes[0], "cancel"),
        {"note": "Não pagou a GRU no prazo."},
    )

    assert cancelamento.status_code == 200
    assert cancelamento.json()["status"] == IsolatedRequestStatus.CANCELLED
    assert AuditLog.objects.filter(
        event="academic.isolated.cancel", target_id=ocupantes[0].pk
    ).exists()
    assert _post(client_secretaria, _url(inscrito, "defer")).status_code == 200


def test_cancelar_inscrito_e_a_desistencia_antes_da_decisao(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    resposta = _post(client_secretaria, _url(inscrito, "cancel"))

    assert resposta.status_code == 200
    assert resposta.json()["status"] == IsolatedRequestStatus.CANCELLED


def test_cancelar_rascunho_e_conflito(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    inscrito.status = IsolatedRequestStatus.DRAFT
    inscrito.save(update_fields=["status"])

    resposta = _post(client_secretaria, _url(inscrito, "cancel"))

    assert resposta.status_code == 409


# --- quem decide -----------------------------------------------------


def test_candidato_nao_defere_o_proprio_requerimento(
    client: Client,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
):
    """A permissão `change` tem duas faces: montar e decidir. É a posse
    que separa os papéis — e o candidato tem a permissão.
    """
    pessoa = criar_candidato(program=program, username="ana", nome="Ana Souza")
    requerimento = IsolatedEnrollmentRequest.objects.create(
        program=program,
        cycle=ciclo,
        person=pessoa,
        status=IsolatedRequestStatus.SUBMITTED,
        submitted_at=timezone.now(),
    )
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta, rank=1)

    resposta = _post(logar(client, pessoa), _url(requerimento, "defer"))

    assert resposta.status_code == 403
    requerimento.refresh_from_db()
    assert requerimento.status == IsolatedRequestStatus.SUBMITTED


def test_docente_nao_decide_requerimento(
    client: Client,
    program: Program,
    inscrito: IsolatedEnrollmentRequest,
):
    """Docente classifica; quem defere é a secretaria. Ele só tem `view`."""
    pessoa = Person.objects.create(
        program=program, full_name="Bruno Reis", primary_email="b@exemplo.br"
    )
    user = User.objects.create_user(username="bruno-decide", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    pessoa.user = user
    pessoa.save(update_fields=["user"])

    resposta = _post(logar(client, pessoa), _url(inscrito, "defer"))

    assert resposta.status_code == 403


def test_sem_sessao_nao_defere(inscrito: IsolatedEnrollmentRequest, client: Client):
    assert _post(client, _url(inscrito, "defer")).status_code == 401


def test_requerimento_de_outro_programa_e_404(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    inscrito: IsolatedEnrollmentRequest,
):
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    IsolatedEnrollmentRequest.objects.filter(pk=inscrito.pk).update(program=outro)

    assert _post(client_secretaria, _url(inscrito, "defer")).status_code == 404


def test_deferir_sem_csrf_e_recusado(
    secretaria_no_programa: Person,
    secretaria: User,
    inscrito: IsolatedEnrollmentRequest,
):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(secretaria)

    resposta = strict.post(
        _url(inscrito, "defer"), data="{}", content_type="application/json"
    )

    assert resposta.status_code == 403


# --- listagem da secretaria ------------------------------------------


def test_listagem_filtra_por_situacao(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
    inscrito: IsolatedEnrollmentRequest,
):
    _outro_inscrito(
        program=program,
        ciclo=ciclo,
        oferta=oferta,
        nome="Bia Lima",
        rank=2,
        status=IsolatedRequestStatus.DEFERRED,
    )

    resposta = client_secretaria.get(URL, {"status": IsolatedRequestStatus.SUBMITTED})

    assert resposta.status_code == 200
    itens = resposta.json()["items"]
    assert [item["id"] for item in itens] == [inscrito.pk]


def test_listagem_com_situacao_fora_do_enum_e_recusada(
    client_secretaria: Client, secretaria_no_programa: Person
):
    assert client_secretaria.get(URL, {"status": "inventado"}).status_code == 422


def test_secretaria_ve_o_edital_inteiro(
    client_secretaria: Client,
    secretaria_no_programa: Person,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
    inscrito: IsolatedEnrollmentRequest,
):
    _outro_inscrito(
        program=program,
        ciclo=ciclo,
        oferta=oferta,
        nome="Bia Lima",
        rank=2,
        status=IsolatedRequestStatus.DEFERRED,
    )

    resposta = client_secretaria.get(URL, {"cycle_id": ciclo.pk})

    assert resposta.status_code == 200
    assert resposta.json()["count"] == 2
