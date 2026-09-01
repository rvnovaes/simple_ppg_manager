"""A secretaria monta as etapas e a grade de vagas do edital pela API.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. O conjunto canônico por recurso roda aqui — 201 + auditoria,
payload não escolhe tenant, duplicata com `code` estável, 403 sem
permissão, 401 sem sessão, 404 de outro programa, CSRF — mais o que é
próprio destes dois recursos: escrever com o edital publicado é 409
`process_not_editable`.

O dado é criado nos DOIS programas em todo teste de escopo: com um só
programa semeado, um vazamento de tenant passa despercebido.
"""

from datetime import UTC, datetime

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    QuotaCategory,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionStage,
    Vacancy,
)

pytestmark = pytest.mark.django_db


def etapas_de(process_id: int) -> str:
    return f"/api/v1/selection/processes/{process_id}/stages/"


def vagas_de(process_id: int) -> str:
    return f"/api/v1/selection/processes/{process_id}/vacancies/"


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


@pytest.fixture
def rascunho(program: Program) -> SelectionProcess:
    """Edital regular em rascunho — o estado em que etapa e vaga mudam."""
    return criar_edital(program)


def criar_edital(program: Program, **extra) -> SelectionProcess:
    campos = {
        "kind": SelectionKind.REGULAR,
        "year": 2029,
        "title": "Edital Regular 2029",
        "submission_opens_at": datetime(2028, 9, 1, tzinfo=UTC),
        "submission_closes_at": datetime(2028, 9, 30, tzinfo=UTC),
    }
    campos.update(extra)
    return SelectionProcess.objects.create(program=program, **campos)


def _post(client: Client, url: str, dados: dict):
    return client.post(url, data=dados, content_type="application/json")


def _patch(client: Client, url: str, dados: dict):
    return client.patch(url, data=dados, content_type="application/json")


def corpo_de_etapa(**extra) -> dict:
    dados = {"name": "Prova oral", "order": 1, "tiebreak_rank": 1}
    dados.update(extra)
    return dados


def corpo_de_vaga(projeto: CollectiveProject, **extra) -> dict:
    dados = {
        "level": SelectionLevel.MASTERS.value,
        "project_id": projeto.pk,
        "quota_category": QuotaCategory.OPEN.value,
        "quantity": 5,
    }
    dados.update(extra)
    return dados


# --- etapas: criação -------------------------------------------------------


def test_cria_a_etapa_e_registra_auditoria(
    client_da_secretaria: Client, rascunho: SelectionProcess, program: Program
):
    resposta = _post(
        client_da_secretaria,
        etapas_de(rascunho.pk),
        corpo_de_etapa(location="Auditório 1"),
    )

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["process_id"] == rascunho.pk
    assert dados["program_id"] == program.pk
    assert dados["location"] == "Auditório 1"
    assert dados["session_at"] is None
    assert dados["tiebreak_rank"] == 1
    registro = AuditLog.objects.get(event="selection.stage.create")
    assert registro.program_id == program.pk
    assert registro.target_id == str(dados["id"])
    assert registro.payload["order"] == 1


def test_etapa_com_ordem_zero_e_400(
    client_da_secretaria: Client, rascunho: SelectionProcess
):
    resposta = _post(
        client_da_secretaria, etapas_de(rascunho.pk), corpo_de_etapa(order=0)
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_stage_order"


@pytest.mark.parametrize(
    "repetido", [{"order": 1}, {"name": "Prova oral"}, {"tiebreak_rank": 1}]
)
def test_etapa_que_repete_ordem_nome_ou_desempate_e_400(
    client_da_secretaria: Client, rascunho: SelectionProcess, repetido: dict
):
    _post(client_da_secretaria, etapas_de(rascunho.pk), corpo_de_etapa())
    # Os campos que não estão sendo testados mudam, para que a única
    # colisão seja a do parâmetro.
    segunda = corpo_de_etapa(name="Entrevista", order=2, tiebreak_rank=2)
    segunda.update(repetido)

    resposta = _post(client_da_secretaria, etapas_de(rascunho.pk), segunda)

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_stage"
    assert rascunho.stages.count() == 1


def test_a_mesma_etapa_em_outro_edital_nao_e_duplicata(
    client_da_secretaria: Client, program: Program, rascunho: SelectionProcess
):
    outro = criar_edital(program, kind=SelectionKind.SUPPLEMENTARY)
    _post(client_da_secretaria, etapas_de(rascunho.pk), corpo_de_etapa())

    resposta = _post(client_da_secretaria, etapas_de(outro.pk), corpo_de_etapa())

    assert resposta.status_code == 201, resposta.content


def test_criar_etapa_em_edital_publicado_e_409(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    resposta = _post(
        client_da_secretaria,
        etapas_de(edital_regular.pk),
        corpo_de_etapa(name="Etapa extra", order=9, tiebreak_rank=None),
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_editable"
    assert edital_regular.stages.count() == 3


def test_criar_etapa_sem_permissao_e_403(
    client_sem_permissao: Client, rascunho: SelectionProcess
):
    resposta = _post(client_sem_permissao, etapas_de(rascunho.pk), corpo_de_etapa())

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_etapa_sem_sessao_e_401(client: Client, rascunho: SelectionProcess):
    assert _post(client, etapas_de(rascunho.pk), corpo_de_etapa()).status_code == 401


def test_criar_etapa_sem_token_csrf_e_recusada(secretaria: User, program: Program):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    edital = criar_edital(program)
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    assert _post(client, etapas_de(edital.pk), corpo_de_etapa()).status_code == 403
    assert not SelectionStage.objects.exists()


def test_criar_etapa_em_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio = criar_edital(outro_programa)

    resposta = _post(client_da_secretaria, etapas_de(alheio.pk), corpo_de_etapa())

    assert resposta.status_code == 404
    assert not SelectionStage.objects.exists()


# --- etapas: leitura -------------------------------------------------------


def test_lista_as_etapas_na_ordem(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    resposta = client_da_secretaria.get(etapas_de(edital_regular.pk))

    assert resposta.status_code == 200
    assert [item["order"] for item in resposta.json()] == [1, 2, 3]
    assert [item["name"] for item in resposta.json()] == [
        "Resumo expandido",
        "Prova oral",
        "Entrevista",
    ]


def test_listar_etapas_de_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheio = criar_edital(outro_programa)
    SelectionStage.objects.create(process=alheio, name="Prova oral", order=1)

    assert client_da_secretaria.get(etapas_de(alheio.pk)).status_code == 404


# --- etapas: edição e remoção ----------------------------------------------


def test_altera_a_etapa_em_rascunho(
    client_da_secretaria: Client, rascunho: SelectionProcess
):
    etapa = SelectionStage.objects.create(
        process=rascunho, name="Prova oral", order=1, tiebreak_rank=1
    )

    resposta = _patch(
        client_da_secretaria,
        f"{etapas_de(rascunho.pk)}{etapa.pk}/",
        {"location": "Sala 3", "session_at": "2028-10-01T13:00:00Z"},
    )

    assert resposta.status_code == 200, resposta.content
    etapa.refresh_from_db()
    assert etapa.location == "Sala 3"
    assert etapa.session_at == datetime(2028, 10, 1, 13, 0, tzinfo=UTC)
    registro = AuditLog.objects.get(event="selection.stage.update")
    assert registro.payload["fields"] == ["location", "session_at"]
    assert registro.program_id == rascunho.program_id


def test_patch_tira_a_etapa_do_desempate_com_nulo_explicito(
    client_da_secretaria: Client, rascunho: SelectionProcess
):
    """`exclude_unset` sem `exclude_none`: `null` desmarca de verdade."""
    etapa = SelectionStage.objects.create(
        process=rascunho, name="Entrevista", order=1, tiebreak_rank=1
    )

    resposta = _patch(
        client_da_secretaria,
        f"{etapas_de(rascunho.pk)}{etapa.pk}/",
        {"tiebreak_rank": None},
    )

    assert resposta.status_code == 200, resposta.content
    etapa.refresh_from_db()
    assert etapa.tiebreak_rank is None


def test_alterar_etapa_para_ordem_ja_usada_e_400(
    client_da_secretaria: Client, rascunho: SelectionProcess
):
    SelectionStage.objects.create(process=rascunho, name="Prova oral", order=1)
    segunda = SelectionStage.objects.create(
        process=rascunho, name="Entrevista", order=2
    )

    resposta = _patch(
        client_da_secretaria, f"{etapas_de(rascunho.pk)}{segunda.pk}/", {"order": 1}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_stage"
    segunda.refresh_from_db()
    assert segunda.order == 2


def test_alterar_etapa_de_edital_publicado_e_409(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    etapa = edital_regular.stages.get(order=1)

    resposta = _patch(
        client_da_secretaria,
        f"{etapas_de(edital_regular.pk)}{etapa.pk}/",
        {"location": "Sala 3"},
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_editable"


def test_apaga_a_etapa_em_rascunho_e_registra_auditoria(
    client_da_secretaria: Client, rascunho: SelectionProcess
):
    etapa = SelectionStage.objects.create(process=rascunho, name="Prova oral", order=1)

    resposta = client_da_secretaria.delete(f"{etapas_de(rascunho.pk)}{etapa.pk}/")

    assert resposta.status_code == 204, resposta.content
    assert not SelectionStage.objects.filter(pk=etapa.pk).exists()
    registro = AuditLog.objects.get(event="selection.stage.delete")
    assert registro.target_id == str(etapa.pk)
    assert registro.payload["name"] == "Prova oral"
    assert registro.program_id == rascunho.program_id


def test_apagar_etapa_de_edital_publicado_e_409(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    etapa = edital_regular.stages.get(order=1)

    resposta = client_da_secretaria.delete(f"{etapas_de(edital_regular.pk)}{etapa.pk}/")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_editable"
    assert edital_regular.stages.filter(pk=etapa.pk).exists()


def test_apagar_etapa_sem_permissao_e_403(
    client_sem_permissao: Client, rascunho: SelectionProcess
):
    """A permissão do DELETE é `change_selectionstage` — nenhum papel de
    domínio recebe `delete_*` (ver docstring da rota)."""
    etapa = SelectionStage.objects.create(process=rascunho, name="Prova oral", order=1)

    resposta = client_sem_permissao.delete(f"{etapas_de(rascunho.pk)}{etapa.pk}/")

    assert resposta.status_code == 403
    assert SelectionStage.objects.filter(pk=etapa.pk).exists()


def test_apagar_etapa_de_outro_edital_e_404(
    client_da_secretaria: Client, program: Program, rascunho: SelectionProcess
):
    """A etapa é buscada dentro do edital da URL: id de outro edital não
    existe aqui, mesmo sendo do mesmo programa."""
    outro = criar_edital(program, kind=SelectionKind.SUPPLEMENTARY)
    etapa = SelectionStage.objects.create(process=outro, name="Memorial", order=1)

    resposta = client_da_secretaria.delete(f"{etapas_de(rascunho.pk)}{etapa.pk}/")

    assert resposta.status_code == 404
    assert SelectionStage.objects.filter(pk=etapa.pk).exists()


# --- vagas: criação --------------------------------------------------------


def test_cria_a_vaga_e_registra_auditoria(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    program: Program,
    projeto: CollectiveProject,
):
    resposta = _post(
        client_da_secretaria, vagas_de(rascunho.pk), corpo_de_vaga(projeto)
    )

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["program_id"] == program.pk
    assert dados["process_id"] == rascunho.pk
    assert dados["project_id"] == projeto.pk
    assert dados["research_line_id"] is None
    assert dados["target_label"] == str(projeto)
    assert dados["level_label"] == "Mestrado"
    assert dados["quota_category_label"] == "Ampla concorrência"
    registro = AuditLog.objects.get(event="selection.vacancy.create")
    assert registro.program_id == program.pk
    assert registro.payload["quantity"] == 5


def test_payload_nao_escolhe_o_programa_da_vaga(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    program: Program,
    outro_programa: Program,
    projeto: CollectiveProject,
):
    resposta = _post(
        client_da_secretaria,
        vagas_de(rascunho.pk),
        corpo_de_vaga(projeto, program_id=outro_programa.pk),
    )

    assert resposta.status_code == 201, resposta.content
    assert Vacancy.objects.get(pk=resposta.json()["id"]).program_id == program.pk


def test_vaga_duplicada_com_alvo_nulo_e_400(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    """A `research_line` nula das duas linhas não as torna distintas — é o
    que a unique com `nulls_distinct=False` garante no banco e o `clean()`
    antecipa com `code` estável."""
    _post(client_da_secretaria, vagas_de(rascunho.pk), corpo_de_vaga(projeto))

    resposta = _post(
        client_da_secretaria,
        vagas_de(rascunho.pk),
        corpo_de_vaga(projeto, quantity=2),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_vacancy"
    assert rascunho.vacancies.count() == 1


def test_vaga_com_linha_de_pesquisa_no_edital_regular_e_400(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
    linha: ResearchLine,
):
    resposta = _post(
        client_da_secretaria,
        vagas_de(rascunho.pk),
        corpo_de_vaga(projeto, research_line_id=linha.pk),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "target_mismatch"


def test_vaga_sem_alvo_e_400(
    client_da_secretaria: Client, rascunho: SelectionProcess, projeto: CollectiveProject
):
    resposta = _post(
        client_da_secretaria,
        vagas_de(rascunho.pk),
        corpo_de_vaga(projeto, project_id=None),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "target_mismatch"


def test_cota_de_outro_tipo_de_edital_e_400(
    client_da_secretaria: Client, program: Program, linha: ResearchLine
):
    """Ampla concorrência não existe no Suplementar."""
    suplementar = criar_edital(program, kind=SelectionKind.SUPPLEMENTARY)

    resposta = _post(
        client_da_secretaria,
        vagas_de(suplementar.pk),
        {
            "level": SelectionLevel.MASTERS.value,
            "research_line_id": linha.pk,
            "quota_category": QuotaCategory.OPEN.value,
            "quantity": 3,
        },
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "quota_category_not_allowed"


def test_projeto_de_outro_programa_e_404(
    client_da_secretaria: Client, rascunho: SelectionProcess, outro_programa: Program
):
    linha_alheia = ResearchLine.objects.create(
        program=outro_programa, name="Linha alheia"
    )
    projeto_alheio = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha_alheia, name="Projeto alheio"
    )

    resposta = _post(
        client_da_secretaria,
        vagas_de(rascunho.pk),
        corpo_de_vaga(projeto_alheio),
    )

    assert resposta.status_code == 404
    assert not Vacancy.objects.exists()


def test_criar_vaga_em_edital_publicado_e_409(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    resposta = _post(
        client_da_secretaria, vagas_de(edital_regular.pk), corpo_de_vaga(projeto)
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_editable"
    assert not Vacancy.objects.exists()


def test_criar_vaga_sem_permissao_e_403(
    client_sem_permissao: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    resposta = _post(
        client_sem_permissao, vagas_de(rascunho.pk), corpo_de_vaga(projeto)
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_vaga_sem_sessao_e_401(
    client: Client, rascunho: SelectionProcess, projeto: CollectiveProject
):
    assert (
        _post(client, vagas_de(rascunho.pk), corpo_de_vaga(projeto)).status_code == 401
    )


def test_criar_vaga_sem_token_csrf_e_recusada(
    secretaria: User,
    program: Program,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    resposta = _post(client, vagas_de(rascunho.pk), corpo_de_vaga(projeto))

    assert resposta.status_code == 403
    assert not Vacancy.objects.exists()


def test_criar_vaga_em_edital_de_outro_programa_e_404(
    client_da_secretaria: Client,
    outro_programa: Program,
    projeto: CollectiveProject,
):
    alheio = criar_edital(outro_programa)

    resposta = _post(client_da_secretaria, vagas_de(alheio.pk), corpo_de_vaga(projeto))

    assert resposta.status_code == 404


# --- vagas: leitura e edição -----------------------------------------------


def criar_vaga(
    edital: SelectionProcess, projeto: CollectiveProject, **extra
) -> Vacancy:
    campos = {
        "level": SelectionLevel.MASTERS,
        "project": projeto,
        "quota_category": QuotaCategory.OPEN,
        "quantity": 5,
    }
    campos.update(extra)
    return Vacancy.objects.create(program=edital.program, process=edital, **campos)


def test_lista_as_vagas_do_edital_e_filtra_por_nivel(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    mestrado = criar_vaga(rascunho, projeto)
    criar_vaga(rascunho, projeto, level=SelectionLevel.DOCTORATE)

    resposta = client_da_secretaria.get(f"{vagas_de(rascunho.pk)}?level=masters")

    assert resposta.status_code == 200
    assert [item["id"] for item in resposta.json()] == [mestrado.pk]


def test_lista_nao_vaza_vaga_de_outro_edital(
    client_da_secretaria: Client,
    program: Program,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    outro = criar_edital(program, kind=SelectionKind.SUPPLEMENTARY)
    minha = criar_vaga(rascunho, projeto)
    criar_vaga(
        outro,
        projeto,
        project=None,
        research_line=projeto.research_line,
        quota_category=QuotaCategory.RACIAL,
    )

    dados = client_da_secretaria.get(vagas_de(rascunho.pk)).json()

    assert [item["id"] for item in dados] == [minha.pk]


def test_altera_a_quantidade_da_vaga(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    vaga = criar_vaga(rascunho, projeto)

    resposta = _patch(
        client_da_secretaria, f"{vagas_de(rascunho.pk)}{vaga.pk}/", {"quantity": 8}
    )

    assert resposta.status_code == 200, resposta.content
    vaga.refresh_from_db()
    assert vaga.quantity == 8
    registro = AuditLog.objects.get(event="selection.vacancy.update")
    assert registro.payload["fields"] == ["quantity"]


def test_alterar_vaga_para_combinacao_ja_existente_e_400(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    criar_vaga(rascunho, projeto)
    outra = criar_vaga(rascunho, projeto, level=SelectionLevel.DOCTORATE)

    resposta = _patch(
        client_da_secretaria,
        f"{vagas_de(rascunho.pk)}{outra.pk}/",
        {"level": SelectionLevel.MASTERS.value},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_vacancy"
    outra.refresh_from_db()
    assert outra.level == SelectionLevel.DOCTORATE


def test_alterar_vaga_para_projeto_de_outro_programa_e_404(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
    outro_programa: Program,
):
    vaga = criar_vaga(rascunho, projeto)
    linha_alheia = ResearchLine.objects.create(
        program=outro_programa, name="Linha alheia"
    )
    alheio = CollectiveProject.objects.create(
        program=outro_programa, research_line=linha_alheia, name="Projeto alheio"
    )

    resposta = _patch(
        client_da_secretaria,
        f"{vagas_de(rascunho.pk)}{vaga.pk}/",
        {"project_id": alheio.pk},
    )

    assert resposta.status_code == 404
    vaga.refresh_from_db()
    assert vaga.project_id == projeto.pk


def test_alterar_vaga_de_edital_publicado_e_409(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    vaga = criar_vaga(edital_regular, projeto)

    resposta = _patch(
        client_da_secretaria,
        f"{vagas_de(edital_regular.pk)}{vaga.pk}/",
        {"quantity": 9},
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "process_not_editable"
    vaga.refresh_from_db()
    assert vaga.quantity == 5


def test_zerar_a_vaga_e_permitido(
    client_da_secretaria: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    """Não existe DELETE de vaga: a linha zerada é o histórico."""
    vaga = criar_vaga(rascunho, projeto)

    resposta = _patch(
        client_da_secretaria, f"{vagas_de(rascunho.pk)}{vaga.pk}/", {"quantity": 0}
    )

    assert resposta.status_code == 200, resposta.content
    vaga.refresh_from_db()
    assert vaga.quantity == 0


def test_alterar_vaga_sem_permissao_e_403(
    client_sem_permissao: Client,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    vaga = criar_vaga(rascunho, projeto)

    resposta = _patch(
        client_sem_permissao, f"{vagas_de(rascunho.pk)}{vaga.pk}/", {"quantity": 9}
    )

    assert resposta.status_code == 403


def test_alterar_vaga_de_outro_edital_e_404(
    client_da_secretaria: Client,
    program: Program,
    rascunho: SelectionProcess,
    projeto: CollectiveProject,
):
    outro = criar_edital(program, kind=SelectionKind.SUPPLEMENTARY)
    vaga = criar_vaga(
        outro,
        projeto,
        project=None,
        research_line=projeto.research_line,
        quota_category=QuotaCategory.RACIAL,
    )

    resposta = _patch(
        client_da_secretaria, f"{vagas_de(rascunho.pk)}{vaga.pk}/", {"quantity": 9}
    )

    assert resposta.status_code == 404
