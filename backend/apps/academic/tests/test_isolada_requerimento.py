"""Fluxo do candidato pelos endpoints do requerimento de isolada.

Nível (b) da pirâmide (Seção 9): bate no endpoint de verdade, sem mock de
ORM. O que só existe aqui é o que a borda acrescenta ao model: o edital
resolvido pelo relógio, o requerimento que é sempre do próprio candidato e
a lista que não mostra o dos outros.
"""

import json
from collections.abc import Sequence

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import (
    DisciplineOffering,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
)
from apps.academic.tests.conftest import (
    SENHA,
    anexar_documentos_obrigatorios,
    criar_candidato,
    logar,
)
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program

pytestmark = pytest.mark.django_db

URL_OFERTAS = "/api/v1/academic/isolated/offerings/"
URL_REQUERIMENTOS = "/api/v1/academic/isolated/requests/"


@pytest.fixture
def candidata(program: Program) -> Person:
    return criar_candidato(program=program, username="marina", nome="Marina Alves")


@pytest.fixture
def client_candidata(client: Client, candidata: Person) -> Client:
    return logar(client, candidata)


@pytest.fixture
def secretaria_no_programa(secretaria: User, program: Program) -> Person:
    """`current_program` sai da Person ativa: usuário de papel sem cadastro
    no programa não passa nem da resolução do tenant.
    """
    return Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )


def _post(client: Client, url: str, payload: dict | None = None):
    return client.post(
        url, data=json.dumps(payload or {}), content_type="application/json"
    )


def _patch(client: Client, url: str, payload: dict):
    return client.patch(url, data=json.dumps(payload), content_type="application/json")


def _url(requerimento: IsolatedEnrollmentRequest, sufixo: str = "") -> str:
    return f"{URL_REQUERIMENTOS}{requerimento.id}/{sufixo}"


# --- ofertas ---------------------------------------------------------------


def test_ofertas_do_edital_aberto_trazem_o_saldo_de_vagas(
    client_candidata, program, ciclo_aberto, ofertas_abertas, candidata
):
    # Uma vaga da primeira oferta já foi comprometida por outro candidato
    # deferido — é isso que `seats_available` desconta.
    outro = IsolatedEnrollmentRequest.objects.create(
        program=program,
        cycle=ciclo_aberto,
        person=criar_candidato(program=program, username="joao", nome="João Dias"),
        status=IsolatedEnrollmentRequest.Status.DEFERRED,
    )
    IsolatedEnrollmentItem.objects.create(request=outro, offering=ofertas_abertas[0])

    resposta = client_candidata.get(URL_OFERTAS)

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert [o["discipline_code"] for o in corpo] == ["DIR010", "DIR011", "DIR012"]
    assert (corpo[0]["seats"], corpo[0]["seats_available"]) == (2, 1)
    assert (corpo[1]["seats"], corpo[1]["seats_available"]) == (3, 3)
    assert corpo[0]["teacher_name"] == "Bruno Reis"
    assert corpo[0]["cycle_id"] == ciclo_aberto.id


def test_ofertas_fora_da_janela_de_inscricao_devolvem_no_open_cycle(
    client_candidata, ciclo, oferta
):
    """O `ciclo` da fixture tem janela em fevereiro de 2026, já encerrada."""
    resposta = client_candidata.get(URL_OFERTAS)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_open_cycle"


def test_ofertas_de_outro_ciclo_do_mesmo_programa_ficam_de_fora(
    client_candidata, program, ciclo, oferta, ciclo_aberto, ofertas_abertas
):
    resposta = client_candidata.get(URL_OFERTAS)

    assert resposta.status_code == 200, resposta.content
    assert oferta.discipline.code not in [o["discipline_code"] for o in resposta.json()]


def test_ofertas_sem_permissao_devolvem_403(client, sem_permissao, ciclo_aberto):
    client.force_login(sem_permissao)

    resposta = client.get(URL_OFERTAS)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_ofertas_sem_sessao_devolvem_401(client, ciclo_aberto):
    assert client.get(URL_OFERTAS).status_code == 401


# --- criação ---------------------------------------------------------------


def test_criar_requerimento_devolve_201_em_rascunho_e_grava_auditoria(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    resposta = _post(
        client_candidata,
        URL_REQUERIMENTOS,
        {
            "is_ufmg_staff": True,
            "items": [
                {"offering_id": ofertas_abertas[0].id},
                {"offering_id": ofertas_abertas[1].id},
            ],
        },
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == "draft"
    assert corpo["payment_status"] == "pending"
    assert corpo["person_id"] == candidata.id
    assert corpo["person_name"] == "Marina Alves"
    assert corpo["cycle_id"] == ciclo_aberto.id
    assert corpo["program_id"] == program.id
    assert corpo["submitted_at"] is None
    assert [item["discipline_code"] for item in corpo["items"]] == ["DIR010", "DIR011"]
    assert [item["rank"] for item in corpo["items"]] == [None, None]
    # Servidor da UFMG junta contracheque e autorização da chefia: a tela
    # do candidato precisa da lista antes de ele tentar enviar.
    assert corpo["missing_documents"] == [
        "identity",
        "diploma",
        "lattes",
        "address",
        "payslip",
        "supervisor_auth",
    ]

    log = AuditLog.objects.get(event="academic.isolated.create")
    assert log.actor.username == "marina"
    assert log.program_id == program.id
    assert log.target_id == str(corpo["id"])
    assert log.payload["cycle_id"] == ciclo_aberto.id


def test_criar_requerimento_ignora_programa_e_ciclo_do_payload(
    client_candidata, program, ciclo_aberto, ofertas_abertas
):
    """Payload não escolhe tenant nem edital: campo extra é descartado."""
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")

    resposta = _post(
        client_candidata,
        URL_REQUERIMENTOS,
        {
            "program_id": outro.id,
            "cycle_id": 999,
            "items": [{"offering_id": ofertas_abertas[0].id}],
        },
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["program_id"] == program.id
    assert corpo["cycle_id"] == ciclo_aberto.id


def test_criar_requerimento_em_nome_de_outra_pessoa_devolve_403(
    client_candidata, program, ciclo_aberto, ofertas_abertas
):
    outra = criar_candidato(program=program, username="joao", nome="João Dias")

    resposta = _post(
        client_candidata,
        URL_REQUERIMENTOS,
        {"person_id": outra.id, "items": [{"offering_id": ofertas_abertas[0].id}]},
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    assert not IsolatedEnrollmentRequest.objects.exists()


def test_criar_requerimento_com_tres_disciplinas_e_recusado_na_borda(
    client_candidata, ciclo_aberto, ofertas_abertas
):
    resposta = _post(
        client_candidata,
        URL_REQUERIMENTOS,
        {"items": [{"offering_id": oferta.id} for oferta in ofertas_abertas]},
    )

    assert resposta.status_code == 422, resposta.content
    assert not IsolatedEnrollmentRequest.objects.exists()


def test_criar_requerimento_com_a_mesma_disciplina_duas_vezes_e_recusado(
    client_candidata, ciclo_aberto, ofertas_abertas
):
    resposta = _post(
        client_candidata,
        URL_REQUERIMENTOS,
        {
            "items": [
                {"offering_id": ofertas_abertas[0].id},
                {"offering_id": ofertas_abertas[0].id},
            ]
        },
    )

    assert resposta.status_code == 422, resposta.content
    assert not IsolatedEnrollmentRequest.objects.exists()


def test_criar_requerimento_com_oferta_de_outro_ciclo_devolve_404(
    client_candidata, ciclo_aberto, ofertas_abertas, ciclo, oferta
):
    resposta = _post(
        client_candidata, URL_REQUERIMENTOS, {"items": [{"offering_id": oferta.id}]}
    )

    assert resposta.status_code == 404
    assert not IsolatedEnrollmentRequest.objects.exists()


def test_criar_requerimento_fora_da_janela_devolve_no_open_cycle(
    client_candidata, ciclo, oferta
):
    resposta = _post(client_candidata, URL_REQUERIMENTOS, {"items": []})

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_open_cycle"


def test_criar_requerimento_sem_permissao_devolve_403(
    client, sem_permissao, ciclo_aberto
):
    client.force_login(sem_permissao)

    resposta = _post(client, URL_REQUERIMENTOS, {"items": []})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_requerimento_sem_sessao_devolve_401(client, ciclo_aberto):
    assert _post(client, URL_REQUERIMENTOS, {"items": []}).status_code == 401


def test_escrita_sem_token_csrf_e_recusada(candidata, ciclo_aberto, ofertas_abertas):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    client = Client(enforce_csrf_checks=True)
    logar(client, candidata)

    resposta = _post(
        client, URL_REQUERIMENTOS, {"items": [{"offering_id": ofertas_abertas[0].id}]}
    )

    assert resposta.status_code == 403
    assert not IsolatedEnrollmentRequest.objects.exists()


# --- alteração do rascunho -------------------------------------------------


def _rascunho(
    *,
    program: Program,
    cycle: IsolatedEnrollmentCycle,
    person: Person,
    ofertas: Sequence[DisciplineOffering] = (),
    **campos,
) -> IsolatedEnrollmentRequest:
    requerimento = IsolatedEnrollmentRequest.objects.create(
        program=program, cycle=cycle, person=person, **campos
    )
    for oferta in ofertas:
        IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)
    return requerimento


def test_patch_troca_as_disciplinas_e_o_vinculo_e_grava_auditoria(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    requerimento = _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=candidata,
        ofertas=[ofertas_abertas[0]],
    )

    resposta = _patch(
        client_candidata,
        _url(requerimento),
        {"is_ufmg_staff": True, "items": [{"offering_id": ofertas_abertas[2].id}]},
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["is_ufmg_staff"] is True
    assert [item["discipline_code"] for item in corpo["items"]] == ["DIR012"]
    # Substituição, e não acréscimo: a escolha antiga não fica pendurada.
    assert requerimento.items.count() == 1

    log = AuditLog.objects.get(event="academic.isolated.update")
    assert log.payload["fields"] == ["is_ufmg_staff", "items"]


def test_patch_com_lista_vazia_apaga_as_disciplinas(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    requerimento = _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=candidata,
        ofertas=[ofertas_abertas[0]],
    )

    resposta = _patch(client_candidata, _url(requerimento), {"items": []})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["items"] == []


def test_patch_sem_items_mantem_as_disciplinas(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    requerimento = _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=candidata,
        ofertas=[ofertas_abertas[0]],
    )

    resposta = _patch(client_candidata, _url(requerimento), {"is_ufmg_staff": True})

    assert resposta.status_code == 200, resposta.content
    assert [item["discipline_code"] for item in resposta.json()["items"]] == ["DIR010"]


def test_patch_depois_de_submetido_devolve_409(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    requerimento = _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=candidata,
        ofertas=[ofertas_abertas[0]],
        status=IsolatedEnrollmentRequest.Status.SUBMITTED,
    )

    resposta = _patch(client_candidata, _url(requerimento), {"items": []})

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "invalid_state_transition"
    assert requerimento.items.count() == 1


def test_patch_no_requerimento_de_outro_candidato_devolve_403(
    client_candidata, program, ciclo_aberto, ofertas_abertas
):
    outra = criar_candidato(program=program, username="joao", nome="João Dias")
    requerimento = _rascunho(program=program, cycle=ciclo_aberto, person=outra)

    resposta = _patch(client_candidata, _url(requerimento), {"is_ufmg_staff": True})

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
    requerimento.refresh_from_db()
    assert requerimento.is_ufmg_staff is False


def test_patch_de_outro_programa_devolve_404(client_candidata, ciclo_aberto):
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    pessoa = Person.objects.create(
        program=outro, full_name="Rui Lima", primary_email="rui@exemplo.br"
    )
    ciclo = IsolatedEnrollmentCycle.objects.create(
        program=outro,
        term=ciclo_aberto.term,
        submission_opens_at=ciclo_aberto.submission_opens_at,
        submission_closes_at=ciclo_aberto.submission_closes_at,
        result_published_on=ciclo_aberto.result_published_on,
        appeal_opens_at=ciclo_aberto.appeal_opens_at,
        appeal_closes_at=ciclo_aberto.appeal_closes_at,
        final_result_on=ciclo_aberto.final_result_on,
        payment_closes_at=ciclo_aberto.payment_closes_at,
    )
    requerimento = _rascunho(program=outro, cycle=ciclo, person=pessoa)

    resposta = _patch(client_candidata, _url(requerimento), {"is_ufmg_staff": True})

    assert resposta.status_code == 404


# --- envio -----------------------------------------------------------------


def test_submit_inscreve_o_candidato_e_grava_auditoria(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    requerimento = _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=candidata,
        ofertas=[ofertas_abertas[0]],
    )
    anexar_documentos_obrigatorios(requerimento)

    resposta = _post(client_candidata, _url(requerimento, "submit"))

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["status"] == "submitted"
    assert corpo["submitted_at"] is not None
    assert corpo["missing_documents"] == []

    log = AuditLog.objects.get(event="academic.isolated.submit")
    assert log.program_id == program.id
    assert log.payload["person_id"] == candidata.id


def test_submit_sem_documentacao_completa_devolve_400(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    requerimento = _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=candidata,
        ofertas=[ofertas_abertas[0]],
    )

    resposta = _post(client_candidata, _url(requerimento, "submit"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "missing_documents"
    requerimento.refresh_from_db()
    assert requerimento.status == IsolatedEnrollmentRequest.Status.DRAFT


def test_submit_sem_disciplina_devolve_400(
    client_candidata, candidata, program, ciclo_aberto
):
    requerimento = _rascunho(program=program, cycle=ciclo_aberto, person=candidata)
    anexar_documentos_obrigatorios(requerimento)

    resposta = _post(client_candidata, _url(requerimento, "submit"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_item_count"


def test_submit_fora_da_janela_devolve_400(
    client_candidata, candidata, program, ciclo, oferta
):
    """O `ciclo` da fixture já encerrou as inscrições: o rascunho ficou
    para trás e o candidato só descobre ao tentar enviar.
    """
    requerimento = _rascunho(
        program=program, cycle=ciclo, person=candidata, ofertas=[oferta]
    )
    anexar_documentos_obrigatorios(requerimento)

    resposta = _post(client_candidata, _url(requerimento, "submit"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "submission_window_closed"
    requerimento.refresh_from_db()
    assert requerimento.status == IsolatedEnrollmentRequest.Status.DRAFT


def test_submit_do_requerimento_de_outro_candidato_devolve_403(
    client_candidata, program, ciclo_aberto, ofertas_abertas
):
    outra = criar_candidato(program=program, username="joao", nome="João Dias")
    requerimento = _rascunho(
        program=program, cycle=ciclo_aberto, person=outra, ofertas=[ofertas_abertas[0]]
    )
    anexar_documentos_obrigatorios(requerimento)

    resposta = _post(client_candidata, _url(requerimento, "submit"))

    assert resposta.status_code == 403
    requerimento.refresh_from_db()
    assert requerimento.status == IsolatedEnrollmentRequest.Status.DRAFT


# --- listagem --------------------------------------------------------------


def test_candidato_lista_so_o_proprio_requerimento(
    client_candidata, candidata, program, ciclo_aberto, ofertas_abertas
):
    meu = _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=candidata,
        ofertas=[ofertas_abertas[0]],
    )
    outra = criar_candidato(program=program, username="joao", nome="João Dias")
    _rascunho(program=program, cycle=ciclo_aberto, person=outra)

    resposta = client_candidata.get(URL_REQUERIMENTOS)

    assert resposta.status_code == 200, resposta.content
    assert [r["id"] for r in resposta.json()["items"]] == [meu.id]


def test_secretaria_lista_o_edital_inteiro(
    client_secretaria, secretaria_no_programa, program, ciclo_aberto, ofertas_abertas
):
    for username, nome in (("marina", "Marina Alves"), ("joao", "João Dias")):
        pessoa = criar_candidato(program=program, username=username, nome=nome)
        _rascunho(
            program=program,
            cycle=ciclo_aberto,
            person=pessoa,
            ofertas=[ofertas_abertas[0]],
        )

    resposta = client_secretaria.get(URL_REQUERIMENTOS)

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["count"] == 2


def test_docente_lista_so_quem_pediu_a_oferta_dele_sem_repetir(
    client, program, ciclo_aberto, ofertas_abertas, docente
):
    """Duas disciplinas do mesmo docente no mesmo requerimento não podem
    duplicar a linha na fila dele — é o `distinct` de `visible_to`.
    """
    user = User.objects.create_user(username="bruno", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    docente.person.user = user
    docente.person.save(update_fields=["user"])
    client.force_login(user)

    pessoa = criar_candidato(program=program, username="marina", nome="Marina Alves")
    _rascunho(
        program=program,
        cycle=ciclo_aberto,
        person=pessoa,
        ofertas=[ofertas_abertas[0], ofertas_abertas[1]],
    )

    resposta = client.get(URL_REQUERIMENTOS)

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["count"] == 1


def test_listagem_nao_atravessa_o_programa(
    client_secretaria, secretaria_no_programa, program, ciclo_aberto, ofertas_abertas
):
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    pessoa = Person.objects.create(
        program=outro, full_name="Rui Lima", primary_email="rui@exemplo.br"
    )
    ciclo = IsolatedEnrollmentCycle.objects.create(
        program=outro,
        term=ciclo_aberto.term,
        submission_opens_at=ciclo_aberto.submission_opens_at,
        submission_closes_at=ciclo_aberto.submission_closes_at,
        result_published_on=ciclo_aberto.result_published_on,
        appeal_opens_at=ciclo_aberto.appeal_opens_at,
        appeal_closes_at=ciclo_aberto.appeal_closes_at,
        final_result_on=ciclo_aberto.final_result_on,
        payment_closes_at=ciclo_aberto.payment_closes_at,
    )
    _rascunho(program=outro, cycle=ciclo, person=pessoa)

    resposta = client_secretaria.get(URL_REQUERIMENTOS)

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["count"] == 0


def test_listagem_sem_sessao_devolve_401(client, ciclo_aberto):
    assert client.get(URL_REQUERIMENTOS).status_code == 401
