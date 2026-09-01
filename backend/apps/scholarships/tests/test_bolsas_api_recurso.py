"""A interposição e o julgamento do recurso, pela borda HTTP.

Nível (b) da pirâmide (Seção 9). Os invariantes do recurso — fase,
fundamentação, "só se julga uma vez", um recurso por inscrição — ficam em
`test_bolsas_recurso.py`; aqui é a borda, que tem três coisas próprias:

1. **O aluno não julga o próprio recurso, e isso é permissão.** O
   Discente tem `add`/`view_scholarshipappeal` e não tem `change_`; a
   Comissão tem o `change_` e não o `add_`. Nenhuma das duas rotas checa
   "quem você é" à mão para isso — quem recusa é o `require_perm`.
2. **A janela é o estado, não a data.** Publicado o preliminar ainda não
   se recorre: quem abre a fase é `open_appeals()`, e antes dela a rota
   devolve 409 `appeals_closed`.
3. **O deferimento não recalcula nada**, e o teste do fluxo inteiro
   prova por que não precisa: corrigido o `committee_score` do lançamento
   atacado — pela mesma rota de avaliação de sempre, porque
   `committee_can_review()` vale em `appeals_under_review` —, a nota da
   inscrição muda sozinha na leitura seguinte.
"""

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.academic.models import Student
from apps.audit.models import AuditLog
from apps.programs.models import Program
from apps.scholarships.models import (
    AppealOutcome,
    BaremeEntry,
    BaremeItem,
    ScholarshipAppeal,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
)

from .test_bolsas_api_inscricao import criar_discente, logar
from .test_bolsas_api_lancamentos import comprovante, criar_item, usuario_com_papel

pytestmark = pytest.mark.django_db

# Os quatro estados em que **não** se recorre. A fase é uma só, e é a que
# `open_appeals()` abre: `preliminary_result` está na lista de propósito —
# publicar o preliminar não abre a janela.
ESTADOS_SEM_RECURSO = tuple(
    estado
    for estado in ScholarshipEditionStatus.values
    if estado != ScholarshipEditionStatus.APPEALS_UNDER_REVIEW
)


# --- cenário ---------------------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
    )


@pytest.fixture
def aluno(program: Program) -> Student:
    return criar_discente(program=program, username="ana", nome="Ana Ribeiro")


@pytest.fixture
def colega(program: Program) -> Student:
    return criar_discente(program=program, username="bruno", nome="Bruno Lima")


def criar_inscricao(
    edicao: ScholarshipEdition, aluno: Student, **campos: Any
) -> ScholarshipApplication:
    inscricao = ScholarshipApplication.for_student(
        edition=edicao, student=aluno, **campos
    )
    inscricao.save()
    return inscricao


@pytest.fixture
def inscricao(edicao: ScholarshipEdition, aluno: Student) -> ScholarshipApplication:
    return criar_inscricao(edicao, aluno)


@pytest.fixture
def inscricao_do_colega(
    edicao: ScholarshipEdition, colega: Student
) -> ScholarshipApplication:
    return criar_inscricao(edicao, colega)


@pytest.fixture
def client_do_aluno(client: Client, aluno: Student) -> Client:
    return logar(client, aluno)


@pytest.fixture
def client_da_comissao(client: Client, program: Program) -> Client:
    """Cliente próprio: duas fixtures com `force_login` sobre o mesmo
    `client` do pytest-django disputam a MESMA sessão, e a última vence em
    silêncio — o teste de "este papel não pode" passaria como o outro."""
    outro = Client()
    outro.force_login(usuario_com_papel(program, "Comissão de Bolsas", "comissao"))
    return outro


@pytest.fixture
def client_da_secretaria(client: Client, program: Program) -> Client:
    outro = Client()
    outro.force_login(usuario_com_papel(program, "Secretaria", "secretaria"))
    return outro


def url_recurso(inscricao: ScholarshipApplication) -> str:
    return f"/api/v1/scholarships/applications/{inscricao.pk}/appeal"


def url_julgamento(recurso: ScholarshipAppeal) -> str:
    return f"/api/v1/scholarships/appeals/{recurso.pk}/judge"


def interpor(
    client: Client, inscricao: ScholarshipApplication, texto: str = "Contesto"
):
    return client.post(
        url_recurso(inscricao),
        data={"text": texto},
        content_type="application/json",
    )


def julgar(
    client: Client,
    recurso: ScholarshipAppeal,
    *,
    outcome: str = AppealOutcome.GRANTED,
    reasoning: str = "O certificado cobre os dois semestres.",
):
    return client.patch(
        url_julgamento(recurso),
        data={"outcome": outcome, "reasoning": reasoning},
        content_type="application/json",
    )


def recurso_gravado(
    inscricao: ScholarshipApplication, texto: str = "Contesto."
) -> ScholarshipAppeal:
    """Gravado pelo ORM: fixture que faz `force_login` disputaria a sessão
    do `client` com o papel que o teste quer usar."""
    return ScholarshipAppeal.objects.create(application=inscricao, text=texto)


# --- a interposição --------------------------------------------------------


def test_o_aluno_interpoe_recurso_na_fase_aberta(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    resposta = interpor(client_do_aluno, inscricao, "A nota do item 1.8 está errada.")

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["text"] == "A nota do item 1.8 está errada."
    assert corpo["outcome"] is None
    assert corpo["judged"] is False
    assert corpo["submitted_at"] is not None
    assert ScholarshipAppeal.objects.get(application=inscricao).text == corpo["text"]


def test_a_interposicao_registra_auditoria(
    client_do_aluno: Client, inscricao: ScholarshipApplication, program: Program
):
    interpor(client_do_aluno, inscricao)

    registro = AuditLog.objects.get(event="scholarships.appeal.create")
    assert registro.program_id == program.pk
    assert registro.payload["application_id"] == inscricao.pk
    assert registro.payload["edition_id"] == inscricao.edition_id


@pytest.mark.parametrize("status", ESTADOS_SEM_RECURSO)
def test_recurso_fora_da_janela_e_recusado(
    client_do_aluno: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
    status: str,
):
    """409, e não 403: a fase abre para todo mundo ao mesmo tempo.

    `preliminary_result` está na lista — publicar o preliminar dá ao
    candidato o que contestar, mas quem abre o prazo é a secretaria.
    """
    edicao.status = status
    edicao.save(update_fields=["status"])

    resposta = interpor(client_do_aluno, inscricao)

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "appeals_closed"
    assert not ScholarshipAppeal.objects.exists()


def test_ninguem_recorre_da_inscricao_alheia(
    client_do_aluno: Client, inscricao_do_colega: ScholarshipApplication
):
    """403 e não 404: a inscrição do colega existe e é do mesmo programa —
    o que falta é ser dele."""
    resposta = interpor(client_do_aluno, inscricao_do_colega)

    assert resposta.status_code == 403, resposta.content
    assert resposta.json()["code"] == "not_application_owner"


def test_o_segundo_recurso_e_recusado(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    """Um por inscrição (Q14): a réplica do indeferimento não é recurso
    novo."""
    recurso_gravado(inscricao, "Primeiro.")

    resposta = interpor(client_do_aluno, inscricao, "Segundo.")

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "duplicate_appeal"
    assert ScholarshipAppeal.objects.count() == 1


@pytest.mark.parametrize("texto", ["", "   "])
def test_recurso_sem_razoes_e_recusado(
    client_do_aluno: Client, inscricao: ScholarshipApplication, texto: str
):
    resposta = interpor(client_do_aluno, inscricao, texto)

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "appeal_text_required"


def test_a_comissao_nao_interpoe_recurso(
    client_da_comissao: Client, inscricao: ScholarshipApplication
):
    """`add_scholarshipappeal` é só do Discente: recorrer é ato do
    candidato, e a comissão que o julga não o escreve por ele."""
    assert interpor(client_da_comissao, inscricao).status_code == 403


def test_inscricao_de_outro_programa_nao_existe(
    client_do_aluno: Client, aluno: Student
):
    """404, e não 403: 403 revelaria que a inscrição existe."""
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    edicao_alheia = ScholarshipEdition.objects.create(
        program=outro,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
    )
    alheia = criar_inscricao(
        edicao_alheia,
        criar_discente(program=outro, username="dora", nome="Dora Melo"),
    )

    assert interpor(client_do_aluno, alheia).status_code == 404


# --- a leitura -------------------------------------------------------------


def test_o_dono_le_o_proprio_recurso(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    recurso = recurso_gravado(inscricao)

    resposta = client_do_aluno.get(url_recurso(inscricao))

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["id"] == recurso.pk


def test_a_comissao_le_o_recurso_do_candidato(
    client_da_comissao: Client, inscricao: ScholarshipApplication
):
    recurso = recurso_gravado(inscricao)

    resposta = client_da_comissao.get(url_recurso(inscricao))

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["id"] == recurso.pk


def test_o_aluno_nao_le_o_recurso_do_colega(
    client_do_aluno: Client, inscricao_do_colega: ScholarshipApplication
):
    """`view_scholarshipappeal` não é porteiro: o Discente também a tem, é
    com ela que lê o próprio. Quem separa é a permissão ampla."""
    recurso_gravado(inscricao_do_colega)

    assert client_do_aluno.get(url_recurso(inscricao_do_colega)).status_code == 403


def test_inscricao_sem_recurso_devolve_404(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    """ "Não recorreu" é o caso normal, e é assim que a tela sabe que deve
    oferecer o formulário em branco."""
    assert client_do_aluno.get(url_recurso(inscricao)).status_code == 404


def test_a_inscricao_carrega_o_recurso_e_o_bool_de_recorrer(
    client_do_aluno: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    """Um pedido só: a tela do candidato desenha o botão por `can_appeal`
    e o histórico por `appeal`. Duas chamadas deixariam o botão aparecer
    para quem já recorreu, no intervalo entre elas."""
    url = f"/api/v1/scholarships/editions/{edicao.pk}/my-application"

    antes = client_do_aluno.get(url).json()
    assert antes["can_appeal"] is True
    assert antes["appeal"] is None

    interpor(client_do_aluno, inscricao)

    depois = client_do_aluno.get(url).json()
    assert depois["can_appeal"] is False
    assert depois["appeal"]["text"] == "Contesto"


# --- o julgamento ----------------------------------------------------------


def test_a_comissao_julga_com_fundamentacao(
    client_da_comissao: Client, inscricao: ScholarshipApplication
):
    recurso = recurso_gravado(inscricao)

    resposta = julgar(client_da_comissao, recurso, outcome=AppealOutcome.DENIED)

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["outcome"] == AppealOutcome.DENIED
    assert corpo["outcome_label"] == "Indeferido"
    assert corpo["judged"] is True
    assert corpo["decided_at"] is not None
    recurso.refresh_from_db()
    assert recurso.outcome == AppealOutcome.DENIED
    assert recurso.decided_at is not None


def test_o_julgamento_registra_auditoria(
    client_da_comissao: Client, inscricao: ScholarshipApplication, program: Program
):
    recurso = recurso_gravado(inscricao)

    julgar(client_da_comissao, recurso)

    registro = AuditLog.objects.get(event="scholarships.appeal.judge")
    assert registro.program_id == program.pk
    assert registro.payload["outcome"] == AppealOutcome.GRANTED
    assert registro.payload["application_id"] == inscricao.pk


@pytest.mark.parametrize("fundamentacao", ["", "   "])
def test_julgamento_sem_fundamentacao_e_recusado(
    client_da_comissao: Client, inscricao: ScholarshipApplication, fundamentacao: str
):
    """A regra é do model: decisão sem fundamentação é o que o próprio
    candidato recorreria."""
    recurso = recurso_gravado(inscricao)

    resposta = julgar(client_da_comissao, recurso, reasoning=fundamentacao)

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "appeal_reasoning_required"
    recurso.refresh_from_db()
    assert recurso.outcome is None


def test_resultado_invalido_para_na_borda(
    client_da_comissao: Client, inscricao: ScholarshipApplication
):
    recurso = recurso_gravado(inscricao)

    resposta = julgar(client_da_comissao, recurso, outcome="talvez")

    assert resposta.status_code == 422, resposta.content


def test_recurso_julgado_nao_se_rejulga(
    client_da_comissao: Client, inscricao: ScholarshipApplication
):
    recurso = recurso_gravado(inscricao)
    assert julgar(client_da_comissao, recurso).status_code == 200

    resposta = julgar(client_da_comissao, recurso, outcome=AppealOutcome.DENIED)

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "appeal_already_judged"


def test_julgamento_fora_da_fase_e_recusado(
    client_da_comissao: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    recurso = recurso_gravado(inscricao)
    edicao.status = ScholarshipEditionStatus.FINAL_RESULT
    edicao.save(update_fields=["status"])

    resposta = julgar(client_da_comissao, recurso)

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "edition_not_appeals_under_review"


def test_o_aluno_nao_julga_o_proprio_recurso(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    """403 de permissão, e não checagem escrita à mão: o Discente não tem
    `change_scholarshipappeal`, e é só a comissão que o tem."""
    recurso = recurso_gravado(inscricao)

    assert julgar(client_do_aluno, recurso).status_code == 403
    recurso.refresh_from_db()
    assert recurso.outcome is None


def test_a_secretaria_nao_julga_recurso(
    client_da_secretaria: Client, inscricao: ScholarshipApplication
):
    """Ela opera o edital; quem decide o mérito é a comissão."""
    assert julgar(client_da_secretaria, recurso_gravado(inscricao)).status_code == 403


def test_recurso_de_outro_programa_nao_existe(client_da_comissao: Client, db: None):
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    edicao_alheia = ScholarshipEdition.objects.create(
        program=outro,
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
    )
    alheio = recurso_gravado(
        criar_inscricao(
            edicao_alheia,
            criar_discente(program=outro, username="dora", nome="Dora Melo"),
        )
    )

    assert julgar(client_da_comissao, alheio).status_code == 404


# --- o fluxo inteiro -------------------------------------------------------


@pytest.fixture
def item(edicao: ScholarshipEdition) -> BaremeItem:
    return criar_item(edicao)


def test_deferido_o_recurso_a_nota_muda_ao_refazer_o_lancamento(
    client: Client,
    program: Program,
    aluno: Student,
    edicao: ScholarshipEdition,
    item: BaremeItem,
):
    """O fluxo do passo 9, ponta a ponta e sempre pela API.

    Preliminar publicado → a secretaria abre a fase → o aluno recorre →
    a comissão defere → a comissão refaz o lançamento atacado **pela rota
    de avaliação de sempre**, porque `committee_can_review()` já vale em
    `appeals_under_review` → a nota da inscrição muda sozinha, sem rotina
    de recálculo nenhuma.
    """
    edicao.status = ScholarshipEditionStatus.PRELIMINARY_RESULT
    edicao.save(update_fields=["status"])
    inscricao = criar_inscricao(edicao, aluno)
    lancamento = BaremeEntry.objects.create(
        application=inscricao,
        item=item,
        description="Estágio em docência 2026",
        quantity=Decimal("2"),
        candidate_score=item.raw_score(Decimal("2")),
        committee_score=Decimal("3.00"),
        committee_note="Só um semestre comprovado.",
        proof=comprovante(),
    )
    assert inscricao.committee_score() == Decimal("3.00")

    secretaria = Client()
    secretaria.force_login(usuario_com_papel(program, "Secretaria", "secretaria"))
    abertura = secretaria.post(
        f"/api/v1/scholarships/editions/{edicao.pk}/open-appeals"
    )
    assert abertura.status_code == 200, abertura.content

    do_aluno = logar(client, aluno)
    interposicao = interpor(do_aluno, inscricao, "O certificado cobre os dois.")
    assert interposicao.status_code == 201, interposicao.content
    recurso = ScholarshipAppeal.objects.get(pk=interposicao.json()["id"])

    comissao = Client()
    comissao.force_login(usuario_com_papel(program, "Comissão de Bolsas", "comissao"))
    assert julgar(comissao, recurso).status_code == 200

    correcao = comissao.patch(
        f"/api/v1/scholarships/entries/{lancamento.pk}/review",
        data={"committee_score": "6.00", "committee_note": "Recurso deferido."},
        content_type="application/json",
    )
    assert correcao.status_code == 200, correcao.content

    inscricao.refresh_from_db()
    assert inscricao.committee_score() == Decimal("6.00")
