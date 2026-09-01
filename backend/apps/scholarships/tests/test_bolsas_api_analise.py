"""A fila de análise da comissão e a avaliação lançamento a lançamento.

Nível (b) da pirâmide (Seção 9). Os invariantes (divergência sem
observação, item de outro nível, observação vazia) ficam em
`test_bolsas_barema.py`, e a janela da edição em `test_bolsas_edital.py`;
aqui é a borda, que tem três coisas próprias:

1. **O nível é obrigatório na fila.** A classificação corre por nível, e
   uma lista que mistura mestrado e doutorado não é a fila de ninguém.
2. **A comissão não mexe no que o aluno digitou.** O schema de entrada da
   avaliação tem dois campos; mandar `quantity` ou `description` no corpo
   não muda nada — e é o teste que prova que isso é código, e não
   combinado.
3. **`view_scholarshipapplication` não é porteiro da fila.** O Discente
   também a tem (é com ela que lê a própria inscrição), então quem recorta
   é `visible_to`.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.academic.models import Student, Teacher
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.scholarships.models import (
    AppealOutcome,
    AppealState,
    BaremeEntry,
    BaremeItem,
    ItemReview,
    PriorityBand,
    ScholarshipAppeal,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

from .test_bolsas_api_edital import criar_docente
from .test_bolsas_api_inscricao import criar_discente
from .test_bolsas_api_lancamentos import (
    comprovante,
    criar_item,
    usuario_com_papel,
)

pytestmark = pytest.mark.django_db

# As oito respostas do questionário que a fila filtra. `cadastro_unico`
# fica de fora porque é critério de desempate, e não pergunta de faixa —
# a mesma razão pela qual ele não tem comprovante próprio.
RESPOSTAS_DO_QUESTIONARIO = (
    "has_paid_activity",
    "affirmative_action",
    "socioeconomic_vulnerability",
    "substitute_teacher",
    "basic_education_or_collective_health",
    "public_service",
    "private_service",
    "other_non_public_scholarship",
)

# Os dois estados em que a comissão avalia, e os três em que não avalia.
ESTADOS_DE_ANALISE = (
    ScholarshipEditionStatus.UNDER_REVIEW,
    ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
)
ESTADOS_SEM_ANALISE = tuple(
    estado
    for estado in ScholarshipEditionStatus.values
    if estado not in ESTADOS_DE_ANALISE
)


# --- cenário ---------------------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )


@pytest.fixture
def orientador(program: Program) -> Teacher:
    return criar_docente(program, "Otávio Prado", "otavio@exemplo.br")


def outro_projeto(program: Program) -> CollectiveProject:
    linha = ResearchLine.objects.create(program=program, name="Direito e Trabalho")
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name="Reforma trabalhista"
    )


@pytest.fixture
def ana(program: Program, orientador: Teacher) -> Student:
    """Mestranda, com orientador, ingresso em 2026 e questionário todo "não"."""
    return criar_discente(
        program=program,
        username="ana",
        nome="Ana Ribeiro",
        advisor=orientador,
        admission_date=date(2026, 3, 2),
    )


@pytest.fixture
def bruno(program: Program) -> Student:
    """Mestrando de outra linha, sem orientador, ingresso em 2025."""
    return criar_discente(
        program=program,
        username="bruno",
        nome="Bruno Lima",
        project=outro_projeto(program),
        admission_date=date(2025, 3, 3),
    )


@pytest.fixture
def carla(program: Program) -> Student:
    """Doutoranda: existe para provar que a fila não mistura os níveis."""
    return criar_discente(
        program=program,
        username="carla",
        nome="Carla Dias",
        level=Student.Level.DOCTORATE,
    )


def criar_inscricao(
    edicao: ScholarshipEdition, aluno: Student, **campos: Any
) -> ScholarshipApplication:
    inscricao = ScholarshipApplication.for_student(
        edition=edicao, student=aluno, **campos
    )
    inscricao.save()
    return inscricao


@pytest.fixture
def inscricao_ana(edicao: ScholarshipEdition, ana: Student) -> ScholarshipApplication:
    return criar_inscricao(edicao, ana)


@pytest.fixture
def inscricao_bruno(
    edicao: ScholarshipEdition, bruno: Student
) -> ScholarshipApplication:
    """Todos os "sim" do questionário — é contra ela que cada filtro corre."""
    return criar_inscricao(
        edicao,
        bruno,
        monthly_income=Decimal("3000.00"),
        weekly_hours=20,
        **dict.fromkeys(RESPOSTAS_DO_QUESTIONARIO, True),
    )


@pytest.fixture
def inscricao_carla(
    edicao: ScholarshipEdition, carla: Student
) -> ScholarshipApplication:
    return criar_inscricao(edicao, carla)


@pytest.fixture
def item(edicao: ScholarshipEdition) -> BaremeItem:
    return criar_item(edicao)


def criar_lancamento(
    inscricao: ScholarshipApplication,
    item: BaremeItem,
    *,
    quantidade: str = "2",
    **campos: Any,
) -> BaremeEntry:
    """Gravado pelo ORM: fixture que faz `force_login` disputa a sessão do
    `client` com o papel que o teste quer usar."""
    return BaremeEntry.objects.create(
        application=inscricao,
        item=item,
        description="Estágio em docência 2026/1",
        quantity=Decimal(quantidade),
        candidate_score=item.raw_score(Decimal(quantidade)),
        proof=comprovante(),
        **campos,
    )


@pytest.fixture
def lancamento(inscricao_ana: ScholarshipApplication, item: BaremeItem) -> BaremeEntry:
    return criar_lancamento(inscricao_ana, item)


def logar_papel(client: Client, program: Program, papel: str, username: str) -> Client:
    client.force_login(usuario_com_papel(program, papel, username))
    return client


@pytest.fixture
def client_da_comissao(client: Client, program: Program) -> Client:
    return logar_papel(client, program, "Comissão de Bolsas", "comissao")


@pytest.fixture
def client_da_secretaria(client: Client, program: Program) -> Client:
    return logar_papel(client, program, "Secretaria", "secretaria")


@pytest.fixture
def client_da_coordenacao(client: Client, program: Program) -> Client:
    return logar_papel(client, program, "Coordenação", "coordenacao")


@pytest.fixture
def client_da_ana(client: Client, ana: Student) -> Client:
    user = ana.person.user
    assert user is not None
    client.force_login(user)
    return client


def url_fila(edicao: ScholarshipEdition) -> str:
    return f"/api/v1/scholarships/editions/{edicao.pk}/applications/"


def url_review(lancamento: BaremeEntry) -> str:
    return f"/api/v1/scholarships/entries/{lancamento.pk}/review"


def url_item_review(inscricao: ScholarshipApplication) -> str:
    return f"/api/v1/scholarships/applications/{inscricao.pk}/item-review"


def url_item_reviews(inscricao: ScholarshipApplication) -> str:
    return f"/api/v1/scholarships/applications/{inscricao.pk}/item-reviews/"


def fila(client: Client, edicao: ScholarshipEdition, **filtros: Any):
    consulta = {"level": ScholarshipLevel.MASTERS}
    consulta.update(filtros)
    return client.get(url_fila(edicao), data=consulta)


def ids(resposta) -> list[int]:
    return [linha["id"] for linha in resposta.json()["items"]]


def _patch(client: Client, url: str, dados: dict):
    return client.patch(url, data=dados, content_type="application/json")


def _put(client: Client, url: str, dados: dict):
    return client.put(url, data=dados, content_type="application/json")


# --- a fila: nível e escopo ------------------------------------------------


def test_o_nivel_e_obrigatorio_na_fila(
    client_da_comissao: Client, edicao: ScholarshipEdition
):
    """Sem nível não há fila: a classificação corre por lista, e uma lista
    com os dois níveis juntos precisaria ser separada à mão."""
    resposta = client_da_comissao.get(url_fila(edicao))

    assert resposta.status_code == 422, resposta.content


def test_a_fila_traz_so_as_inscricoes_do_nivel_pedido(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    inscricao_ana: ScholarshipApplication,
    inscricao_carla: ScholarshipApplication,
):
    resposta = fila(client_da_comissao, edicao)

    assert resposta.status_code == 200, resposta.content
    assert ids(resposta) == [inscricao_ana.pk]


def test_a_fila_de_outro_programa_nao_existe(
    client_da_comissao: Client, db: None
) -> None:
    """404, e não 403: 403 revelaria que a edição existe."""
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    alheia = ScholarshipEdition.objects.create(
        program=outro,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )

    assert fila(client_da_comissao, alheia).status_code == 404


@pytest.mark.parametrize("papel", ["Comissão de Bolsas", "Secretaria", "Coordenação"])
def test_comissao_secretaria_e_coordenacao_enxergam_a_fila_inteira(
    client: Client,
    program: Program,
    papel: str,
    edicao: ScholarshipEdition,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    logado = logar_papel(client, program, papel, "operador")

    assert sorted(ids(fila(logado, edicao))) == sorted(
        [inscricao_ana.pk, inscricao_bruno.pk]
    )


def test_o_discente_so_enxerga_a_propria_inscricao_na_fila(
    client_da_ana: Client,
    edicao: ScholarshipEdition,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    """`view_scholarshipapplication` diz que ele acompanha inscrição, não
    QUAIS inscrições — sem `visible_to` a fila entregaria o questionário de
    todo mundo a qualquer candidato."""
    resposta = fila(client_da_ana, edicao)

    assert ids(resposta) == [inscricao_ana.pk]


# --- a fila: os filtros do legado ------------------------------------------


def test_filtro_por_linha_de_pesquisa(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    projeto = inscricao_bruno.student.project
    assert projeto is not None
    linha = projeto.research_line

    resposta = fila(client_da_comissao, edicao, research_line_id=linha.pk)

    assert ids(resposta) == [inscricao_bruno.pk]
    assert resposta.json()["items"][0]["research_line"] == linha.name


def test_filtro_por_orientador(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    orientador: Teacher,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    resposta = fila(client_da_comissao, edicao, advisor_id=orientador.pk)

    assert ids(resposta) == [inscricao_ana.pk]
    assert resposta.json()["items"][0]["advisor_name"] == "Otávio Prado"


def test_filtro_por_ano_de_entrada(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    resposta = fila(client_da_comissao, edicao, admission_year=2025)

    assert ids(resposta) == [inscricao_bruno.pk]
    assert resposta.json()["items"][0]["admission_year"] == 2025


@pytest.mark.parametrize("resposta_do_questionario", RESPOSTAS_DO_QUESTIONARIO)
def test_filtro_por_cada_resposta_do_questionario(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    resposta_do_questionario: str,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    """Bruno respondeu "sim" a tudo, Ana a nada: cada filtro tem que separar
    os dois nos dois sentidos."""
    sim = fila(client_da_comissao, edicao, **{resposta_do_questionario: "true"})
    nao = fila(client_da_comissao, edicao, **{resposta_do_questionario: "false"})

    assert ids(sim) == [inscricao_bruno.pk]
    assert ids(nao) == [inscricao_ana.pk]


def test_sem_filtro_de_questionario_a_fila_traz_os_dois(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    assert len(ids(fila(client_da_comissao, edicao))) == 2


@pytest.mark.parametrize(
    ("estado", "esperado"),
    [
        (AppealState.NONE, "ana"),
        (AppealState.PENDING, "bruno"),
        (AppealState.JUDGED, "carla"),
    ],
)
def test_filtro_por_estado_do_recurso(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    program: Program,
    estado: str,
    esperado: str,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    """Sem recurso e recurso pendente têm os dois `outcome` nulo — um filtro
    por `outcome` sozinho não os separaria."""
    terceira = criar_inscricao(
        edicao,
        criar_discente(program=program, username="dani", nome="Dani Souza"),
    )
    ScholarshipAppeal.objects.create(application=inscricao_bruno, text="Reconsiderem.")
    ScholarshipAppeal.objects.create(
        application=terceira,
        text="Reconsiderem.",
        outcome=AppealOutcome.DENIED,
        reasoning="Mantida a pontuação.",
    )
    esperados = {
        "ana": inscricao_ana.pk,
        "bruno": inscricao_bruno.pk,
        "carla": terceira.pk,
    }

    resposta = fila(client_da_comissao, edicao, appeal=estado)

    assert ids(resposta) == [esperados[esperado]]


def test_pending_review_traz_so_quem_tem_lancamento_sem_nota(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    item: BaremeItem,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
):
    """O "somente candidatos com itens a analisar" do legado, derivado de
    `fully_reviewed()` — não há botão de "concluí a análise"."""
    criar_lancamento(inscricao_ana, item)
    criar_lancamento(
        inscricao_bruno,
        item,
        committee_score=Decimal("6.00"),
        reviewed_at=None,
    )

    pendentes = fila(client_da_comissao, edicao, pending_review="true")
    analisados = fila(client_da_comissao, edicao, pending_review="false")

    assert ids(pendentes) == [inscricao_ana.pk]
    assert ids(analisados) == [inscricao_bruno.pk]


def test_quem_nao_lancou_nada_conta_como_analisado(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    inscricao_ana: ScholarshipApplication,
):
    """Inscrição sem lançamento é vacuamente analisada: não há o que
    avaliar nela, e ela não pode ficar presa na fila para sempre."""
    assert ids(fila(client_da_comissao, edicao, pending_review="true")) == []
    assert ids(fila(client_da_comissao, edicao, pending_review="false")) == [
        inscricao_ana.pk
    ]


def test_a_fila_nao_repete_a_inscricao_com_dois_itens_pendentes(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    item: BaremeItem,
    inscricao_ana: ScholarshipApplication,
):
    criar_lancamento(inscricao_ana, item)
    criar_lancamento(inscricao_ana, item)

    assert ids(fila(client_da_comissao, edicao, pending_review="true")) == [
        inscricao_ana.pk
    ]


# --- a fila: o que cada linha mostra ---------------------------------------


def test_a_linha_da_fila_traz_as_duas_notas_lado_a_lado(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    item: BaremeItem,
    inscricao_ana: ScholarshipApplication,
):
    """A comissão decide vendo o que foi pedido e o que foi concedido."""
    criar_lancamento(inscricao_ana, item, quantidade="2")
    criar_lancamento(
        inscricao_ana,
        item,
        quantidade="1",
        committee_score=Decimal("0.00"),
        committee_note="Certificado ilegível.",
    )

    linha = fila(client_da_comissao, edicao).json()["items"][0]

    assert Decimal(linha["candidate_score"]) == Decimal("9.00")
    assert Decimal(linha["committee_score"]) == Decimal("0.00")
    assert linha["fully_reviewed"] is False
    assert linha["appeal_state"] == AppealState.NONE
    assert linha["appeal_outcome"] is None
    assert linha["student_name"] == "Ana Ribeiro"


def test_a_linha_da_fila_traz_as_pendencias_de_documento(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    inscricao_bruno: ScholarshipApplication,
    inscricao_ana: ScholarshipApplication,
):
    """O "Sim - Não enviado" do legado: o que ele afirmou e não provou."""
    linha = next(
        linha
        for linha in fila(client_da_comissao, edicao).json()["items"]
        if linha["id"] == inscricao_bruno.pk
    )

    assert {pendencia["kind"] for pendencia in linha["pending_docs"]} == {
        "affirmative_action",
        "socioeconomic_vulnerability",
        "substitute_teacher",
        "basic_education_or_collective_health",
        "public_service",
        "private_service",
        "other_non_public_scholarship",
    }


# --- avaliação do lançamento -----------------------------------------------


def test_a_comissao_avalia_o_lancamento_e_a_avaliacao_e_auditada(
    client_da_comissao: Client, lancamento: BaremeEntry, program: Program
):
    resposta = _patch(
        client_da_comissao,
        url_review(lancamento),
        {"committee_score": "3.00", "committee_note": "Só um semestre comprovado."},
    )

    assert resposta.status_code == 200, resposta.content
    lancamento.refresh_from_db()
    assert lancamento.committee_score == Decimal("3.00")
    assert lancamento.committee_note == "Só um semestre comprovado."
    assert lancamento.reviewed_at is not None
    registro = AuditLog.objects.get(event="scholarships.entry.review")
    assert registro.program_id == program.pk
    assert registro.payload["committee_score"] == "3.00"


def test_a_comissao_nao_altera_o_que_o_aluno_digitou(
    client_da_comissao: Client, lancamento: BaremeEntry
):
    """Os campos do candidato não existem no schema de entrada, então o
    corpo os ignora — é o contrato, e não uma checagem, que segura isso."""
    resposta = _patch(
        client_da_comissao,
        url_review(lancamento),
        {
            "committee_score": "6.00",
            "quantity": "99",
            "description": "Reescrito pela comissão",
            "candidate_score": "999.00",
        },
    )

    assert resposta.status_code == 200, resposta.content
    lancamento.refresh_from_db()
    assert lancamento.quantity == Decimal("2")
    assert lancamento.description == "Estágio em docência 2026/1"
    assert lancamento.candidate_score == Decimal("6.00")


def test_nota_divergente_sem_observacao_e_recusada(
    client_da_comissao: Client, lancamento: BaremeEntry
):
    resposta = _patch(
        client_da_comissao, url_review(lancamento), {"committee_score": "1.00"}
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "note_required"
    lancamento.refresh_from_db()
    assert lancamento.committee_score is None


def test_nota_igual_a_do_candidato_dispensa_observacao(
    client_da_comissao: Client, lancamento: BaremeEntry
):
    resposta = _patch(
        client_da_comissao, url_review(lancamento), {"committee_score": "6.00"}
    )

    assert resposta.status_code == 200, resposta.content


def test_zero_e_a_comissao_negando_o_ponto_e_nao_ausencia_de_analise(
    client_da_comissao: Client, lancamento: BaremeEntry
):
    resposta = _patch(
        client_da_comissao,
        url_review(lancamento),
        {"committee_score": "0.00", "committee_note": "Sem comprovante válido."},
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["committee_score"] == "0.00"
    assert lancamento.application.fully_reviewed() is True


@pytest.mark.parametrize("estado", ESTADOS_SEM_ANALISE)
def test_avaliar_fora_da_janela_da_comissao_e_409(
    client_da_comissao: Client,
    lancamento: BaremeEntry,
    edicao: ScholarshipEdition,
    estado: str,
):
    edicao.status = estado
    edicao.save(update_fields=["status"])

    resposta = _patch(
        client_da_comissao, url_review(lancamento), {"committee_score": "6.00"}
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "review_closed"


@pytest.mark.parametrize("estado", ESTADOS_DE_ANALISE)
def test_avaliar_passa_em_analise_e_em_recursos(
    client_da_comissao: Client,
    lancamento: BaremeEntry,
    edicao: ScholarshipEdition,
    estado: str,
):
    """`appeals_under_review` não é sobra: é o recurso deferido reabrindo o
    lançamento antes do resultado final."""
    edicao.status = estado
    edicao.save(update_fields=["status"])

    resposta = _patch(
        client_da_comissao, url_review(lancamento), {"committee_score": "6.00"}
    )

    assert resposta.status_code == 200, resposta.content


@pytest.mark.parametrize("papel", ["Secretaria", "Coordenação"])
def test_quem_nao_e_da_comissao_nao_avalia(
    client: Client, program: Program, lancamento: BaremeEntry, papel: str
):
    """A secretaria opera o edital e não pontua; a coordenação acompanha."""
    logado = logar_papel(client, program, papel, "operador")

    resposta = _patch(logado, url_review(lancamento), {"committee_score": "6.00"})

    assert resposta.status_code == 403, resposta.content


def test_o_candidato_nao_avalia_o_proprio_lancamento(
    client_da_ana: Client, lancamento: BaremeEntry
):
    """Ele tem `change_baremeentry` sobre a própria linha — e é por isso que
    avaliar é permissão separada."""
    resposta = _patch(
        client_da_ana, url_review(lancamento), {"committee_score": "6.00"}
    )

    assert resposta.status_code == 403, resposta.content


def test_lancamento_de_outro_programa_nao_existe_para_a_comissao(
    client_da_comissao: Client, program: Program
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    edicao_alheia = ScholarshipEdition.objects.create(
        program=outro,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )
    pessoa = Person.objects.create(
        program=outro, full_name="Elis Alheia", primary_email="elis@exemplo.br"
    )
    aluno = Student.objects.create(
        program=outro,
        person=pessoa,
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=outro_projeto(outro),
        admission_date=date(2026, 3, 2),
    )
    alheio = criar_lancamento(
        criar_inscricao(edicao_alheia, aluno), criar_item(edicao_alheia)
    )

    resposta = _patch(
        client_da_comissao, url_review(alheio), {"committee_score": "6.00"}
    )

    assert resposta.status_code == 404, resposta.content


# --- observação por item ---------------------------------------------------


def test_a_comissao_grava_a_observacao_do_item(
    client_da_comissao: Client,
    inscricao_ana: ScholarshipApplication,
    item: BaremeItem,
    program: Program,
):
    resposta = _put(
        client_da_comissao,
        url_item_review(inscricao_ana),
        {"item_id": item.pk, "note": "Produção reclassificada em bloco."},
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["item_code"] == item.code
    assert ItemReview.objects.get(application=inscricao_ana, item=item).note == (
        "Produção reclassificada em bloco."
    )
    registro = AuditLog.objects.get(event="scholarships.item_review.set")
    assert registro.program_id == program.pk
    assert registro.payload["item_id"] == item.pk


def test_reenviar_a_observacao_sobrescreve_em_vez_de_empilhar(
    client_da_comissao: Client, inscricao_ana: ScholarshipApplication, item: BaremeItem
):
    """Uma por (inscrição, item): duas versões deixariam o candidato
    adivinhando qual vale."""
    _put(
        client_da_comissao,
        url_item_review(inscricao_ana),
        {"item_id": item.pk, "note": "Primeira leitura."},
    )

    resposta = _put(
        client_da_comissao,
        url_item_review(inscricao_ana),
        {"item_id": item.pk, "note": "Revista após o recurso."},
    )

    assert resposta.status_code == 200, resposta.content
    assert ItemReview.objects.filter(application=inscricao_ana).count() == 1
    assert ItemReview.objects.get(application=inscricao_ana).note == (
        "Revista após o recurso."
    )


def test_observacao_vazia_e_recusada(
    client_da_comissao: Client, inscricao_ana: ScholarshipApplication, item: BaremeItem
):
    resposta = _put(
        client_da_comissao,
        url_item_review(inscricao_ana),
        {"item_id": item.pk, "note": "   "},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "item_review_note_required"


def test_observacao_em_item_de_outro_nivel_e_recusada(
    client_da_comissao: Client,
    inscricao_ana: ScholarshipApplication,
    edicao: ScholarshipEdition,
):
    """O item existe no programa — quem recusa é o `clean()`, com código, e
    não um 404 que faria parecer id inexistente."""
    do_doutorado = criar_item(edicao, code="1.3", level=ScholarshipLevel.DOCTORATE)

    resposta = _put(
        client_da_comissao,
        url_item_review(inscricao_ana),
        {"item_id": do_doutorado.pk, "note": "Comentário."},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "bareme_item_mismatch"


def test_observacao_fora_da_janela_da_comissao_e_409(
    client_da_comissao: Client,
    inscricao_ana: ScholarshipApplication,
    item: BaremeItem,
    edicao: ScholarshipEdition,
):
    edicao.status = ScholarshipEditionStatus.PRELIMINARY_RESULT
    edicao.save(update_fields=["status"])

    resposta = _put(
        client_da_comissao,
        url_item_review(inscricao_ana),
        {"item_id": item.pk, "note": "Tarde demais."},
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "review_closed"


def test_o_candidato_nao_escreve_a_observacao_do_item(
    client_da_ana: Client, inscricao_ana: ScholarshipApplication, item: BaremeItem
):
    resposta = _put(
        client_da_ana,
        url_item_review(inscricao_ana),
        {"item_id": item.pk, "note": "Me dá o ponto."},
    )

    assert resposta.status_code == 403, resposta.content


def test_o_candidato_le_a_observacao_do_proprio_item(
    client: Client,
    program: Program,
    inscricao_ana: ScholarshipApplication,
    item: BaremeItem,
    ana: Student,
):
    """É dela que sai o recurso: sem ler o comentário, ele ataca um número
    sem fundamento."""
    ItemReview.objects.create(
        application=inscricao_ana, item=item, note="Reclassificado."
    )
    user = ana.person.user
    assert user is not None
    client.force_login(user)

    resposta = client.get(url_item_reviews(inscricao_ana))

    assert resposta.status_code == 200, resposta.content
    assert [linha["note"] for linha in resposta.json()] == ["Reclassificado."]


def test_o_colega_nao_le_a_observacao_alheia(
    client: Client,
    program: Program,
    inscricao_ana: ScholarshipApplication,
    inscricao_bruno: ScholarshipApplication,
    item: BaremeItem,
    bruno: Student,
):
    """Mesma porta do comprovante: posse primeiro, e quem não é dono precisa
    de `download_applicationdocument` — que o Discente não tem."""
    ItemReview.objects.create(
        application=inscricao_ana, item=item, note="Reclassificado."
    )
    user = bruno.person.user
    assert user is not None
    client.force_login(user)

    assert client.get(url_item_reviews(inscricao_ana)).status_code == 403


# --- FUMP e sobrescrita de faixa (os dois campos da Secretaria) ------------
#
# O que estas rotas provam, e nenhuma outra prova: quem escreve nelas é a
# Secretaria, e só ela. A Comissão tem `view_scholarshipapplication` e
# `review_baremeentry` e mesmo assim leva 403 — as permissões são próprias
# (`set_fump_level`, `override_band`), e é isso que separa "decidir a nota"
# de "transcrever a FUMP e sobrescrever a faixa".


def url_fump(inscricao: ScholarshipApplication) -> str:
    return f"/api/v1/scholarships/applications/{inscricao.pk}/fump"


def url_band(inscricao: ScholarshipApplication) -> str:
    return f"/api/v1/scholarships/applications/{inscricao.pk}/band"


JUSTIFICATIVA = "Caso omisso decidido pelo colegiado em 12/03, ata 04/2026."


def test_a_secretaria_lanca_o_nivel_da_fump(
    client_da_secretaria: Client, inscricao_ana: ScholarshipApplication
):
    resposta = _patch(client_da_secretaria, url_fump(inscricao_ana), {"fump_level": 2})

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["fump_level"] == 2
    inscricao_ana.refresh_from_db()
    assert inscricao_ana.fump_level == 2


def test_o_lancamento_da_fump_audita_o_valor_anterior_e_o_novo(
    client_da_secretaria: Client, inscricao_ana: ScholarshipApplication
):
    """Decisão sobre a vida acadêmica: sem o valor anterior o rastro não
    responde "qual era o nível antes de a secretaria mexer"."""
    inscricao_ana.fump_level = 1
    inscricao_ana.save(update_fields=["fump_level"])

    _patch(client_da_secretaria, url_fump(inscricao_ana), {"fump_level": 2})

    registro = AuditLog.objects.get(event="scholarships.application.set_fump_level")
    assert registro.payload["previous_fump_level"] == 1
    assert registro.payload["fump_level"] == 2


@pytest.mark.parametrize("nivel", [3, -1])
def test_nivel_de_fump_fora_da_tabela_para_na_borda(
    client_da_secretaria: Client, inscricao_ana: ScholarshipApplication, nivel: int
):
    """A FUMP tem três níveis (`NIVEIS_DA_FUMP`); um quarto viraria linha
    gravada que ninguém sabe ler."""
    resposta = _patch(
        client_da_secretaria, url_fump(inscricao_ana), {"fump_level": nivel}
    )

    assert resposta.status_code == 422, resposta.content


def test_a_secretaria_sobrescreve_a_faixa_com_justificativa(
    client_da_secretaria: Client, inscricao_ana: ScholarshipApplication
):
    """2.4-I não tem pergunta no questionário: só chega por esta rota."""
    resposta = _patch(
        client_da_secretaria,
        url_band(inscricao_ana),
        {"band_override": "b24_i", "band_override_reason": JUSTIFICATIVA},
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["band_override"] == "b24_i"
    assert corpo["band"] == "b24_i"
    inscricao_ana.refresh_from_db()
    assert inscricao_ana.band() == "b24_i"


def test_a_sobrescrita_sem_justificativa_e_recusada(
    client_da_secretaria: Client, inscricao_ana: ScholarshipApplication
):
    resposta = _patch(
        client_da_secretaria,
        url_band(inscricao_ana),
        {"band_override": "b24_ii", "band_override_reason": "   "},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "override_reason_required"
    inscricao_ana.refresh_from_db()
    assert inscricao_ana.band_override is None


def test_a_sobrescrita_pode_ser_desfeita(
    client_da_secretaria: Client, inscricao_ana: ScholarshipApplication
):
    """Nulo devolve a inscrição à faixa derivada do questionário."""
    inscricao_ana.band_override = PriorityBand.B24_I
    inscricao_ana.band_override_reason = JUSTIFICATIVA
    inscricao_ana.save(update_fields=["band_override", "band_override_reason"])

    resposta = _patch(client_da_secretaria, url_band(inscricao_ana), {})

    assert resposta.status_code == 200, resposta.content
    # Ana não exerce atividade remunerada e não marcou nenhum dos dois
    # critérios do 2.1: desfeita a sobrescrita, a derivação a devolve ao
    # 2.1-II. O `band` da resposta é a faixa efetiva, não a sobrescrita.
    assert resposta.json()["band"] == PriorityBand.B21_II
    inscricao_ana.refresh_from_db()
    assert inscricao_ana.band_override is None
    registro = AuditLog.objects.get(event="scholarships.application.override_band")
    assert registro.payload["previous_band"] == PriorityBand.B24_I
    assert registro.payload["band"] is None


def test_a_sobrescrita_audita_a_faixa_anterior_e_a_justificativa(
    client_da_secretaria: Client, inscricao_ana: ScholarshipApplication
):
    _patch(
        client_da_secretaria,
        url_band(inscricao_ana),
        {"band_override": "b24_ii", "band_override_reason": JUSTIFICATIVA},
    )

    registro = AuditLog.objects.get(event="scholarships.application.override_band")
    assert registro.payload["previous_band"] is None
    assert registro.payload["band"] == "b24_ii"
    assert registro.payload["reason"] == JUSTIFICATIVA


@pytest.mark.parametrize(
    ("url", "corpo"),
    [
        ("fump", {"fump_level": 1}),
        ("band", {"band_override": "b24_i", "band_override_reason": JUSTIFICATIVA}),
    ],
)
def test_a_comissao_nao_lanca_fump_nem_sobrescreve_faixa(
    client_da_comissao: Client,
    inscricao_ana: ScholarshipApplication,
    url: str,
    corpo: dict,
):
    """Ela pontua o barema; transcrever a FUMP e mexer na faixa é da
    Secretaria, e as permissões são próprias justamente por isso."""
    resposta = _patch(
        client_da_comissao,
        f"/api/v1/scholarships/applications/{inscricao_ana.pk}/{url}",
        corpo,
    )

    assert resposta.status_code == 403, resposta.content
    inscricao_ana.refresh_from_db()
    assert inscricao_ana.fump_level == 0
    assert inscricao_ana.band_override is None


@pytest.mark.parametrize(
    ("url", "corpo"),
    [
        ("fump", {"fump_level": 2}),
        ("band", {"band_override": "b21_i", "band_override_reason": JUSTIFICATIVA}),
    ],
)
def test_o_proprio_candidato_nao_lanca_a_fump_nem_a_faixa(
    client_da_ana: Client,
    inscricao_ana: ScholarshipApplication,
    url: str,
    corpo: dict,
):
    """Os dois campos valem na classificação: o candidato não escolhe nem
    o bônus da FUMP nem a faixa em que compete."""
    resposta = _patch(
        client_da_ana,
        f"/api/v1/scholarships/applications/{inscricao_ana.pk}/{url}",
        corpo,
    )

    assert resposta.status_code == 403, resposta.content


def test_inscricao_de_outro_programa_nao_existe_para_a_secretaria(
    client_da_secretaria: Client, db: None
) -> None:
    outro = Program.objects.create(name="Outro programa", acronym="PPGY")
    edicao_alheia = ScholarshipEdition.objects.create(
        program=outro,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )
    aluno_alheio = criar_discente(program=outro, username="daniel", nome="Daniel Rocha")
    alheia = criar_inscricao(edicao_alheia, aluno_alheio)

    resposta = _patch(client_da_secretaria, url_fump(alheia), {"fump_level": 1})

    assert resposta.status_code == 404, resposta.content
