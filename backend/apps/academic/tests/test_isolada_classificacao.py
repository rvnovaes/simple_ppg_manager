"""Classificação dos candidatos pelo docente responsável, pelos endpoints.

Nível (b) da pirâmide (Seção 9). O que só existe aqui é o que a borda
acrescenta ao model: a oferta que é sempre a do próprio docente, a lista
que só mostra inscrito e a gravação que troca duas posições sem esbarrar
na `unique_classificacao_por_oferta`.
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
    IsolatedRequestStatus,
    Teacher,
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
from apps.programs.models import Discipline, Program

pytestmark = pytest.mark.django_db

URL_OFERTAS = "/api/v1/academic/isolated/offerings/"


def _url_candidatos(oferta: DisciplineOffering) -> str:
    return f"{URL_OFERTAS}{oferta.id}/candidates"


def _url_rank(oferta: DisciplineOffering) -> str:
    return f"{URL_OFERTAS}{oferta.id}/rank"


def _classificar(client: Client, oferta: DisciplineOffering, ids: list[int]):
    return client.post(
        _url_rank(oferta),
        data=json.dumps({"item_ids": ids}),
        content_type="application/json",
    )


def _inscrever(
    *,
    program: Program,
    ciclo: IsolatedEnrollmentCycle,
    oferta: DisciplineOffering,
    nome: str,
    status: str = IsolatedRequestStatus.SUBMITTED,
) -> IsolatedEnrollmentItem:
    """Um candidato com requerimento naquele estado e item naquela oferta."""
    requerimento = criar_requerimento(
        program=program,
        ciclo=ciclo,
        nome=nome,
        status=status,
        submitted_at=timezone.now(),
    )
    return IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)


@pytest.fixture
def client_docente(client: Client, docente: Teacher) -> Client:
    """O docente responsável pela oferta, com conta e papel.

    A `Person` dele já existe e está ativa no programa — é dela que
    `current_program` tira o tenant da requisição.
    """
    user = User.objects.create_user(username="bruno", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    docente.person.user = user
    docente.person.save(update_fields=["user"])
    return logar(client, docente.person)


@pytest.fixture
def outro_docente(program: Program) -> Teacher:
    pessoa = Person.objects.create(
        program=program, full_name="Alice Prado", primary_email="alice@example.com"
    )
    user = User.objects.create_user(username="alice", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=timezone.now().date(),
    )


@pytest.fixture
def inscritos(
    program: Program, ciclo: IsolatedEnrollmentCycle, oferta: DisciplineOffering
) -> list[IsolatedEnrollmentItem]:
    return [
        _inscrever(program=program, ciclo=ciclo, oferta=oferta, nome=nome)
        for nome in ("Ana Souza", "Beto Lima", "Caio Melo")
    ]


# --- lista de candidatos ---------------------------------------------------


def test_lista_candidatos_traz_nome_e_rank(client_docente, oferta, inscritos):
    resposta = client_docente.get(_url_candidatos(oferta))

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert [linha["person_name"] for linha in corpo] == [
        "Ana Souza",
        "Beto Lima",
        "Caio Melo",
    ]
    assert [linha["rank"] for linha in corpo] == [None, None, None]
    assert {linha["item_id"] for linha in corpo} == {item.id for item in inscritos}
    assert all(linha["submitted_at"] is not None for linha in corpo)


def test_lista_candidatos_poe_classificados_no_topo(client_docente, oferta, inscritos):
    """Sem posição vai para o fim: a resposta do docente fica no topo."""
    ultimo = inscritos[2]
    ultimo.rank = 1
    ultimo.save(update_fields=["rank"])

    corpo = client_docente.get(_url_candidatos(oferta)).json()

    assert [linha["person_name"] for linha in corpo] == [
        "Caio Melo",
        "Ana Souza",
        "Beto Lima",
    ]


def test_lista_candidatos_ignora_quem_nao_enviou(
    client_docente, program, ciclo, oferta, inscritos
):
    _inscrever(
        program=program,
        ciclo=ciclo,
        oferta=oferta,
        nome="Dora Pinto",
        status=IsolatedRequestStatus.DRAFT,
    )

    corpo = client_docente.get(_url_candidatos(oferta)).json()

    assert "Dora Pinto" not in [linha["person_name"] for linha in corpo]


def test_lista_candidatos_de_outro_docente_devolve_403(
    client, oferta, outro_docente, inscritos
):
    logar(client, outro_docente.person)

    resposta = client.get(_url_candidatos(oferta))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_lista_candidatos_sem_permissao_devolve_403(client, program, oferta):
    candidata = criar_candidato(program=program, username="carla", nome="Carla Reis")
    logar(client, candidata)

    resposta = client.get(_url_candidatos(oferta))

    assert resposta.status_code == 403


def test_lista_candidatos_sem_sessao_devolve_401(client, oferta):
    assert client.get(_url_candidatos(oferta)).status_code == 401


def test_oferta_de_outro_programa_devolve_404(client_docente, docente, ciclo):
    """Escopo de tenant é 404, e não 403: a oferta não existe aqui."""
    outro = Program.objects.create(name="PPG Outro", acronym="PPGO")
    disciplina = Discipline.objects.create(program=outro, code="XXX1", name="Outra")
    alheia = DisciplineOffering.objects.create(
        program=outro,
        cycle=ciclo,
        discipline=disciplina,
        teacher=docente,
        seats=1,
    )

    assert client_docente.get(_url_candidatos(alheia)).status_code == 404


# --- gravação da classificação ---------------------------------------------


def test_classificar_grava_ranks_sequenciais_e_audita(
    client_docente, oferta, inscritos
):
    ordem = [inscritos[2].id, inscritos[0].id, inscritos[1].id]

    resposta = _classificar(client_docente, oferta, ordem)

    assert resposta.status_code == 200, resposta.content
    assert [linha["item_id"] for linha in resposta.json()] == ordem
    assert [linha["rank"] for linha in resposta.json()] == [1, 2, 3]
    assert [IsolatedEnrollmentItem.objects.get(pk=i).rank for i in ordem] == [1, 2, 3]
    registro = AuditLog.objects.get(event="academic.isolated.rank")
    assert registro.target_id == str(oferta.id)
    assert registro.program_id == oferta.program_id
    assert registro.payload["item_ids"] == ordem


def test_reclassificar_troca_posicoes_sem_violar_a_constraint(
    client_docente, oferta, inscritos
):
    """A troca de 1º e 2º é o caso que a escrita incremental quebraria."""
    primeiro, segundo, _ = inscritos
    _classificar(client_docente, oferta, [primeiro.id, segundo.id])

    resposta = _classificar(client_docente, oferta, [segundo.id, primeiro.id])

    assert resposta.status_code == 200, resposta.content
    primeiro.refresh_from_db()
    segundo.refresh_from_db()
    assert (segundo.rank, primeiro.rank) == (1, 2)


def test_classificacao_parcial_zera_quem_ficou_de_fora(
    client_docente, oferta, inscritos
):
    _classificar(client_docente, oferta, [item.id for item in inscritos])

    _classificar(client_docente, oferta, [inscritos[0].id])

    assert [
        IsolatedEnrollmentItem.objects.get(pk=item.pk).rank for item in inscritos
    ] == [1, None, None]


def test_lista_vazia_zera_a_classificacao(client_docente, oferta, inscritos):
    _classificar(client_docente, oferta, [item.id for item in inscritos])

    resposta = _classificar(client_docente, oferta, [])

    assert resposta.status_code == 200, resposta.content
    assert all(linha["rank"] is None for linha in resposta.json())


def test_item_de_outra_oferta_e_recusado(
    client_docente, program, ciclo, docente, oferta, inscritos
):
    disciplina = Discipline.objects.create(
        program=program, code="DIR099", name="Outra Isolada"
    )
    vizinha = DisciplineOffering.objects.create(
        program=program, cycle=ciclo, discipline=disciplina, teacher=docente, seats=1
    )
    forasteiro = _inscrever(
        program=program, ciclo=ciclo, oferta=vizinha, nome="Elis Rocha"
    )

    resposta = _classificar(client_docente, oferta, [inscritos[0].id, forasteiro.id])

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "item_not_in_offering"
    assert IsolatedEnrollmentItem.objects.get(pk=inscritos[0].pk).rank is None


def test_rascunho_nao_pode_ser_classificado(client_docente, program, ciclo, oferta):
    rascunho = _inscrever(
        program=program,
        ciclo=ciclo,
        oferta=oferta,
        nome="Dora Pinto",
        status=IsolatedRequestStatus.DRAFT,
    )

    resposta = _classificar(client_docente, oferta, [rascunho.id])

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "item_not_in_offering"


def test_candidato_repetido_na_ordem_e_422(client_docente, oferta, inscritos):
    resposta = _classificar(client_docente, oferta, [inscritos[0].id] * 2)

    assert resposta.status_code == 422


def test_classificar_oferta_de_outro_docente_devolve_403(
    client, oferta, outro_docente, inscritos
):
    logar(client, outro_docente.person)

    resposta = _classificar(client, oferta, [inscritos[0].id])

    assert resposta.status_code == 403
    assert IsolatedEnrollmentItem.objects.get(pk=inscritos[0].pk).rank is None


def test_classificar_sem_sessao_devolve_401(client, oferta, inscritos):
    assert _classificar(client, oferta, [inscritos[0].id]).status_code == 401


def test_classificar_sem_token_csrf_e_recusado(docente, oferta, inscritos):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    user = User.objects.create_user(username="bruno", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    docente.person.user = user
    docente.person.save(update_fields=["user"])
    client = logar(Client(enforce_csrf_checks=True), docente.person)

    resposta = _classificar(client, oferta, [inscritos[0].id])

    assert resposta.status_code == 403
    assert IsolatedEnrollmentItem.objects.get(pk=inscritos[0].pk).rank is None


# --- lista de ofertas do docente (?mine=true) ------------------------------


def test_mine_traz_as_ofertas_do_docente_com_marcador(
    client_docente, oferta, inscritos
):
    """Fora da janela de inscrição, que é justamente quando ele classifica."""
    corpo = client_docente.get(f"{URL_OFERTAS}?mine=true").json()

    assert [linha["id"] for linha in corpo] == [oferta.id]
    assert corpo[0]["needs_ranking"] is True

    _classificar(client_docente, oferta, [item.id for item in inscritos])

    corpo = client_docente.get(f"{URL_OFERTAS}?mine=true").json()
    assert corpo[0]["needs_ranking"] is False


def test_mine_nao_traz_oferta_de_outro_docente(client, oferta, outro_docente):
    logar(client, outro_docente.person)

    resposta = client.get(f"{URL_OFERTAS}?mine=true")

    assert resposta.status_code == 200, resposta.content
    assert resposta.json() == []


def test_oferta_sem_inscrito_nao_precisa_de_classificacao(client_docente, oferta):
    corpo = client_docente.get(f"{URL_OFERTAS}?mine=true").json()

    assert corpo[0]["needs_ranking"] is False
