"""A publicação e a leitura do resultado, pela borda HTTP.

Nível (b) da pirâmide (Seção 9). O algoritmo da lista está em
`test_bolsas_classificacao.py` — aqui é a borda, que tem três coisas
próprias:

1. **Publicar é permissão à parte.** `publish_scholarshipedition` é só da
   Secretaria: a Comissão avalia e julga, mas não assina a lista, e o
   403 dela é o caso que prova que publicar não caiu junto do `change_`.
2. **A prévia não é o resultado.** Antes do preliminar publicado a rota
   entrega a lista a quem trabalha o edital (Secretaria, Coordenação e
   Comissão, o mesmo recorte de `visible_to`) e devolve 403
   `result_not_published` ao candidato. Publicado, o candidato lê.
3. **A resposta tem sempre as dez faixas**, na ordem canônica e com o
   cabeçalho de cada uma — é o mesmo objeto que a tela e o PDF consomem,
   e faixa vazia que sumisse viraria uma prioridade a menos no documento.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.academic.models import Student
from apps.audit.models import AuditLog
from apps.programs.models import Program
from apps.scholarships.models import (
    ORDEM_DAS_FAIXAS,
    PriorityBand,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

from .test_bolsas_api_inscricao import criar_discente, logar
from .test_bolsas_api_lancamentos import usuario_com_papel

pytestmark = pytest.mark.django_db


# --- cenário ---------------------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    """No estado de onde se publica o preliminar."""
    return ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Outro programa", acronym="PPGX")


@pytest.fixture
def aluno(program: Program) -> Student:
    return criar_discente(program=program, username="ana", nome="Ana Ribeiro")


@pytest.fixture
def inscricao(edicao: ScholarshipEdition, aluno: Student) -> ScholarshipApplication:
    inscricao = ScholarshipApplication.for_student(
        edition=edicao, student=aluno, affirmative_action=True
    )
    inscricao.save()
    return inscricao


@pytest.fixture
def client_do_aluno(client: Client, aluno: Student) -> Client:
    return logar(client, aluno)


@pytest.fixture
def client_da_secretaria(client: Client, program: Program) -> Client:
    """Cliente próprio por papel: duas fixtures com `force_login` sobre o
    mesmo `client` do pytest-django disputam a MESMA sessão."""
    outro = Client()
    outro.force_login(usuario_com_papel(program, "Secretaria", "secretaria"))
    return outro


@pytest.fixture
def client_da_comissao(client: Client, program: Program) -> Client:
    outro = Client()
    outro.force_login(usuario_com_papel(program, "Comissão de Bolsas", "comissao"))
    return outro


@pytest.fixture
def client_da_coordenacao(client: Client, program: Program) -> Client:
    outro = Client()
    outro.force_login(usuario_com_papel(program, "Coordenação", "coordenacao"))
    return outro


def url_resultado(edicao: ScholarshipEdition, nivel: str = "masters") -> str:
    return f"/api/v1/scholarships/editions/{edicao.pk}/result?level={nivel}"


def url_publicacao(edicao: ScholarshipEdition, ato: str) -> str:
    return f"/api/v1/scholarships/editions/{edicao.pk}/{ato}"


def publicar(client: Client, edicao: ScholarshipEdition, ato: str = "preliminary"):
    return client.post(url_publicacao(edicao, f"publish-{ato}"))


# --- publicar --------------------------------------------------------------


def test_a_secretaria_publica_o_preliminar_e_o_snapshot_fica_gravado(
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    resposta = publicar(client_da_secretaria, edicao)

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["status"] == ScholarshipEditionStatus.PRELIMINARY_RESULT
    inscricao.refresh_from_db()
    edicao.refresh_from_db()
    assert inscricao.published_band == PriorityBand.B21_I
    assert inscricao.published_position == 1
    assert inscricao.published_at == edicao.published_preliminary_at
    assert edicao.draw_seed is not None


def test_a_publicacao_escreve_um_auditlog_com_as_contagens(
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    publicar(client_da_secretaria, edicao)

    registro = AuditLog.objects.get(event="scholarships.edition.publish_preliminary")
    assert registro.actor is not None
    assert registro.payload["published"] == 1
    assert registro.payload["by_level"] == {"masters": 1, "doctorate": 0}


def test_a_comissao_nao_publica(client_da_comissao: Client, edicao: ScholarshipEdition):
    """Avaliar e julgar não é assinar a lista: `publish_` é da Secretaria."""
    assert publicar(client_da_comissao, edicao).status_code == 403


def test_o_discente_nao_publica(client_do_aluno: Client, edicao: ScholarshipEdition):
    assert publicar(client_do_aluno, edicao).status_code == 403


def test_publicar_fora_do_estado_e_409(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    resposta = publicar(client_da_secretaria, edicao, "final")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "edition_not_appeals_under_review"


def test_edicao_de_outro_programa_nao_existe_aqui(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = ScholarshipEdition.objects.create(
        program=outro_programa,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )

    assert publicar(client_da_secretaria, alheia).status_code == 404
    assert client_da_secretaria.get(url_resultado(alheia)).status_code == 404


# --- ler o resultado -------------------------------------------------------


def test_o_candidato_nao_le_o_resultado_antes_de_publicado(
    client_do_aluno: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    resposta = client_do_aluno.get(url_resultado(edicao))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "result_not_published"


def test_o_candidato_le_o_resultado_depois_de_publicado(
    client_do_aluno: Client,
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    publicar(client_da_secretaria, edicao)

    resposta = client_do_aluno.get(url_resultado(edicao))

    assert resposta.status_code == 200, resposta.content
    (faixa,) = [f for f in resposta.json() if f["band"] == PriorityBand.B21_I]
    assert [linha["name"] for linha in faixa["rows"]] == ["Ana Ribeiro"]


@pytest.mark.parametrize(
    "papel", ["client_da_secretaria", "client_da_comissao", "client_da_coordenacao"]
)
def test_quem_trabalha_o_edital_ve_a_previa(
    request: pytest.FixtureRequest,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
    papel: str,
):
    """A lista antes de congelada é de quem acompanha a edição inteira —
    mesmo recorte de `ScholarshipApplicationQuerySet.visible_to`."""
    resposta = request.getfixturevalue(papel).get(url_resultado(edicao))

    assert resposta.status_code == 200, resposta.content
    (faixa,) = [f for f in resposta.json() if f["band"] == PriorityBand.B21_I]
    assert len(faixa["rows"]) == 1


def test_o_resultado_traz_as_dez_faixas_com_cabecalho(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    resposta = client_da_secretaria.get(url_resultado(edicao))

    faixas = resposta.json()
    assert [faixa["band"] for faixa in faixas] == ORDEM_DAS_FAIXAS
    primeira = faixas[0]
    assert primeira["priority_label"] == "Ordem de prioridade: primeira"
    assert primeira["ordering_rule"]
    assert primeira["title"]
    assert primeira["rows"] == []
    assert {faixa["band"] for faixa in faixas if faixa["shows_income"]} == {
        PriorityBand.B24_V,
        PriorityBand.B24_VI_VII_VIII,
    }


def test_a_linha_publica_o_que_a_tela_e_o_pdf_imprimem(
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
    aluno: Student,
):
    publicar(client_da_secretaria, edicao)

    resposta = client_da_secretaria.get(url_resultado(edicao))

    (faixa,) = [f for f in resposta.json() if f["band"] == PriorityBand.B21_I]
    (linha,) = faixa["rows"]
    assert linha == {
        "application_id": inscricao.pk,
        "student_id": aluno.pk,
        "name": "Ana Ribeiro",
        "score": "0.00",
        "position": 1,
        "income": None,
        "weekly_hours": None,
        "draw_order": None,
    }


def test_o_nivel_e_obrigatorio(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    """Um nível por documento: mestrado e doutorado correm independentes,
    e uma lista dos dois juntos não existe no edital."""
    resposta = client_da_secretaria.get(
        f"/api/v1/scholarships/editions/{edicao.pk}/result"
    )

    assert resposta.status_code == 422


def test_o_outro_nivel_sai_vazio(
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    resposta = client_da_secretaria.get(
        url_resultado(edicao, ScholarshipLevel.DOCTORATE)
    )

    assert resposta.status_code == 200, resposta.content
    assert all(faixa["rows"] == [] for faixa in resposta.json())


def test_a_nota_publicada_e_a_congelada(
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    """Depois de publicado, a resposta vem do snapshot: mexer no nível da
    FUMP (que entra na nota final) não muda a lista já lida."""
    publicar(client_da_secretaria, edicao)

    inscricao.fump_level = 1
    inscricao.save(update_fields=["fump_level", "updated_at"])

    resposta = client_da_secretaria.get(url_resultado(edicao))
    (faixa,) = [f for f in resposta.json() if f["band"] == PriorityBand.B21_I]
    assert faixa["rows"][0]["score"] == "0.00"
    assert inscricao.final_score() == Decimal("15.00")
