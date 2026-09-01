"""A realocação de vaga: a única escrita do edital que a secretaria não faz.

Nível (b) da pirâmide (Seção 9). As regras de espécie, cota e saldo já são
exercidas em memória em `test_reallocation_convocation.py`; aqui guarda-se
a borda:

- **quem pode** — só o grupo Comissão de Seleção
  (`selection.add_vacancyreallocation`); secretaria, que opera todo o
  resto do edital, recebe 403.
- **o efeito** — as duas vagas mudam de quantidade e a linha imutável
  guarda o ofício.
- **o efeito colateral** — a classificação já calculada dos alvos
  envolvidos é zerada: as posições saíram de uma grade que acabou de
  mudar, e a secretaria precisa recalcular antes de publicar de novo.
- **o tenant** — edital de outro programa é 404, e vaga de outro edital
  também.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import Student
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Application,
    ApplicationStatus,
    QuotaCategory,
    RankingOutcome,
    ReallocationKind,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    Vacancy,
    VacancyReallocation,
    gerar_protocolo,
)

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"
OFICIO = "Ofício 12/2027 da Comissão de Seleção"


def url(process_id: int) -> str:
    return f"/api/v1/selection/processes/{process_id}/reallocations/"


@pytest.fixture
def comissao(program: Program) -> User:
    """Usuário do grupo Comissão de Seleção, com pessoa no programa.

    A pessoa é o que dá tenant à sessão (`current_program`); sem ela toda
    rota escopada devolveria erro antes da permissão.
    """
    user = User.objects.create_user(username="comissao", password=SENHA)
    user.groups.add(Group.objects.get(name="Comissão de Seleção"))
    Person.objects.create(
        program=program,
        user=user,
        full_name="Dora Prado",
        primary_email="dora@exemplo.br",
    )
    return user


@pytest.fixture
def client_comissao(client: Client, comissao: User) -> Client:
    client.force_login(comissao)
    return client


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


def vaga(
    program: Program,
    edital: SelectionProcess,
    *,
    quantidade: int,
    categoria: str = QuotaCategory.OPEN,
    level: str = SelectionLevel.MASTERS,
    projeto: CollectiveProject | None = None,
    linha: ResearchLine | None = None,
) -> Vacancy:
    vaga = Vacancy(
        program=program,
        process=edital,
        level=level,
        project=projeto,
        research_line=linha,
        quota_category=categoria,
        quantity=quantidade,
    )
    vaga.clean()
    vaga.save()
    return vaga


def classificada(
    program: Program,
    edital: SelectionProcess,
    *,
    nome: str,
    cpf: str,
    projeto: CollectiveProject | None = None,
    level: str = SelectionLevel.MASTERS,
) -> Application:
    """Inscrição aprovada e já com posição carimbada."""
    return Application.objects.create(
        program=program,
        process=edital,
        protocol=gerar_protocolo(edital),
        full_name=nome,
        email=f"{cpf}@exemplo.br",
        cpf=cpf,
        birth_date=date(1995, 5, 20),
        level=level,
        project=projeto,
        quota_category=QuotaCategory.OPEN,
        status=ApplicationStatus.APPROVED,
        final_score=Decimal("90.00"),
        final_rank=1,
        final_outcome=RankingOutcome.CLASSIFIED_OPEN,
        ranked_at=datetime(2026, 6, 10, 10, 0, tzinfo=UTC),
        submitted_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
    )


def matriculada(
    program: Program, inscricao: Application, projeto: CollectiveProject
) -> Application:
    """Converte a inscrição classificada em aluno.

    O caminho de verdade é `convert_to_student` (f5); aqui interessa só o
    status `enrolled`, que a CheckConstraint
    `application_enrolled_requires_student` obriga a vir com aluno.
    """
    pessoa = Person.objects.create(
        program=program,
        full_name=inscricao.full_name,
        primary_email=inscricao.email,
    )
    aluno = Student.objects.create(
        program=program,
        person=pessoa,
        registration_number="2027000001",
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2027, 3, 1),
        deadline=date(2029, 3, 1),
    )
    inscricao.enroll(aluno)
    inscricao.save(update_fields=["status", "student"])
    return inscricao


def corpo(
    origem: Vacancy,
    destino: Vacancy,
    *,
    quantidade: int = 1,
    kind: str = ReallocationKind.LEVEL_TRANSFER,
) -> dict:
    return {
        "kind": kind,
        "from_vacancy_id": origem.pk,
        "to_vacancy_id": destino.pk,
        "quantity": quantidade,
        "reason": "Vaga ociosa no mestrado e demanda no doutorado.",
        "decided_on": "2027-02-10",
        "decided_by_note": OFICIO,
    }


# --- o efeito ---------------------------------------------------------------


def test_transferencia_entre_niveis_move_a_vaga_e_audita(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    mestrado = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    doutorado = vaga(
        program,
        edital_regular,
        quantidade=1,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )

    resposta = client_comissao.post(
        url(edital_regular.pk),
        corpo(mestrado, doutorado),
        content_type="application/json",
    )

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["kind"] == ReallocationKind.LEVEL_TRANSFER
    assert dados["decided_by_note"] == OFICIO
    assert dados["from_vacancy"]["quantity"] == 1
    assert dados["to_vacancy"]["quantity"] == 2

    mestrado.refresh_from_db()
    doutorado.refresh_from_db()
    assert (mestrado.quantity, doutorado.quantity) == (1, 2)
    assert VacancyReallocation.objects.count() == 1
    assert AuditLog.objects.filter(event="selection.vacancy.reallocate").count() == 1


def test_retificacao_do_edital_move_entre_alvos_do_mesmo_nivel(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    linha: ResearchLine,
):
    """A grade saiu errada no edital: a vaga era do outro projeto."""
    outro_projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Outro projeto"
    )
    origem = vaga(program, edital_regular, quantidade=3, projeto=projeto)
    destino = vaga(program, edital_regular, quantidade=0, projeto=outro_projeto)

    resposta = client_comissao.post(
        url(edital_regular.pk),
        corpo(
            origem, destino, quantidade=2, kind=ReallocationKind.NOTICE_RECTIFICATION
        ),
        content_type="application/json",
    )

    assert resposta.status_code == 201, resposta.content
    origem.refresh_from_db()
    destino.refresh_from_db()
    assert (origem.quantity, destino.quantity) == (1, 2)


def test_classificacao_dos_alvos_afetados_e_zerada(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    linha: ResearchLine,
):
    """A posição saiu de uma grade que acabou de mudar: quem estava
    classificado nos dois alvos volta para o limbo até o recálculo. Quem
    concorre a alvo não envolvido não é tocado."""
    de_fora_projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto alheio"
    )
    mestrado = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    doutorado = vaga(
        program,
        edital_regular,
        quantidade=1,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )
    vaga(program, edital_regular, quantidade=1, projeto=de_fora_projeto)

    daqui = classificada(
        program, edital_regular, nome="Ana Lima", cpf="52998224725", projeto=projeto
    )
    do_doutorado = classificada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf="11144477735",
        projeto=projeto,
        level=SelectionLevel.DOCTORATE,
    )
    de_fora = classificada(
        program,
        edital_regular,
        nome="Célia Nunes",
        cpf="12345678909",
        projeto=de_fora_projeto,
    )

    resposta = client_comissao.post(
        url(edital_regular.pk),
        corpo(mestrado, doutorado),
        content_type="application/json",
    )

    assert resposta.status_code == 201, resposta.content
    for inscricao in (daqui, do_doutorado):
        inscricao.refresh_from_db()
        assert inscricao.final_rank is None
        assert inscricao.final_outcome == ""
        assert inscricao.ranked_at is None
    de_fora.refresh_from_db()
    assert de_fora.final_rank == 1
    assert de_fora.ranked_at is not None
    assert (
        AuditLog.objects.get(event="selection.vacancy.reallocate").payload[
            "rankings_invalidated"
        ]
        == 2
    )


def test_matriculado_nao_perde_a_posicao(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """Quem já virou aluno não é `approved`: a realocação não reescreve a
    classificação que já produziu matrícula."""
    mestrado = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    doutorado = vaga(
        program,
        edital_regular,
        quantidade=1,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )
    aluna = matriculada(
        program,
        classificada(
            program, edital_regular, nome="Ana Lima", cpf="52998224725", projeto=projeto
        ),
        projeto,
    )

    resposta = client_comissao.post(
        url(edital_regular.pk),
        corpo(mestrado, doutorado),
        content_type="application/json",
    )

    assert resposta.status_code == 201, resposta.content
    aluna.refresh_from_db()
    assert aluna.status == ApplicationStatus.ENROLLED
    assert aluna.final_rank == 1
    assert aluna.ranked_at is not None


# --- o que a realocação recusa ----------------------------------------------


def test_saldo_insuficiente_e_recusado(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    mestrado = vaga(program, edital_regular, quantidade=1, projeto=projeto)
    doutorado = vaga(
        program,
        edital_regular,
        quantidade=0,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )

    resposta = client_comissao.post(
        url(edital_regular.pk),
        corpo(mestrado, doutorado, quantidade=2),
        content_type="application/json",
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "insufficient_vacancies"
    mestrado.refresh_from_db()
    assert mestrado.quantity == 1
    assert not VacancyReallocation.objects.exists()


def test_categoria_de_cota_diferente_e_recusada(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """Vaga de cota racial não vira ampla concorrência por decisão da
    comissão — a realocação preserva a categoria."""
    ampla = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    racial = vaga(
        program,
        edital_regular,
        quantidade=1,
        categoria=QuotaCategory.RACIAL,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )

    resposta = client_comissao.post(
        url(edital_regular.pk),
        corpo(ampla, racial),
        content_type="application/json",
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "quota_category_must_be_preserved"


def test_transferencia_de_nivel_exige_alvo_igual(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    linha: ResearchLine,
):
    outro_projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Outro projeto"
    )
    origem = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    destino = vaga(
        program,
        edital_regular,
        quantidade=0,
        level=SelectionLevel.DOCTORATE,
        projeto=outro_projeto,
    )

    resposta = client_comissao.post(
        url(edital_regular.pk), corpo(origem, destino), content_type="application/json"
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "same_target_required"


def test_mesma_vaga_na_origem_e_no_destino_e_recusada(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """Sem esta trava a CheckConstraint do banco devolveria 500."""
    unica = vaga(program, edital_regular, quantidade=2, projeto=projeto)

    resposta = client_comissao.post(
        url(edital_regular.pk), corpo(unica, unica), content_type="application/json"
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "same_vacancy"


def test_edital_em_rascunho_corrige_a_grade_em_vez_de_realocar(
    client_comissao: Client, program: Program, projeto: CollectiveProject
):
    rascunho = SelectionProcess.objects.create(
        program=program,
        kind=SelectionKind.REGULAR,
        year=2028,
        title="Edital Regular 2028",
        submission_opens_at=datetime(2027, 1, 1, tzinfo=UTC),
        submission_closes_at=datetime(2027, 12, 31, tzinfo=UTC),
        convocation_subject="Assunto",
        convocation_body="Corpo",
    )
    origem = vaga(program, rascunho, quantidade=2, projeto=projeto)
    destino = vaga(
        program,
        rascunho,
        quantidade=0,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )

    resposta = client_comissao.post(
        url(rascunho.pk), corpo(origem, destino), content_type="application/json"
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "process_still_draft"


# --- a leitura --------------------------------------------------------------


def test_lista_traz_o_historico_do_edital(
    client_da_secretaria: Client,
    comissao: User,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    """A secretaria não realoca, mas lê: o histórico aparece na tela de
    resultado, que é dela.

    A comissão entra por uma `Client` própria: o `client` do pytest-django
    é um só, e o último `force_login` venceria.
    """
    client_comissao = Client()
    client_comissao.force_login(comissao)
    mestrado = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    doutorado = vaga(
        program,
        edital_regular,
        quantidade=0,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )
    client_comissao.post(
        url(edital_regular.pk),
        corpo(mestrado, doutorado),
        content_type="application/json",
    )

    resposta = client_da_secretaria.get(url(edital_regular.pk))

    assert resposta.status_code == 200, resposta.content
    linhas = resposta.json()
    assert len(linhas) == 1
    assert linhas[0]["quantity"] == 1
    assert linhas[0]["kind_label"] == "Transferência entre níveis"
    assert linhas[0]["from_vacancy"]["target_label"] == str(projeto)


# --- tenant, permissão e CSRF -----------------------------------------------


def test_secretaria_nao_realoca(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    mestrado = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    doutorado = vaga(
        program,
        edital_regular,
        quantidade=0,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )

    resposta = client_da_secretaria.post(
        url(edital_regular.pk),
        corpo(mestrado, doutorado),
        content_type="application/json",
    )

    assert resposta.status_code == 403, resposta.content
    assert not VacancyReallocation.objects.exists()


def test_edital_de_outro_programa_e_404(
    client_comissao: Client, edital_regular: SelectionProcess
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGY")
    alheio = SelectionProcess.objects.create(
        program=outro,
        kind=SelectionKind.REGULAR,
        year=2027,
        title="Edital de outro programa",
        submission_opens_at=edital_regular.submission_opens_at,
        submission_closes_at=edital_regular.submission_closes_at,
        convocation_subject="Assunto",
        convocation_body="Corpo",
    )

    resposta = client_comissao.get(url(alheio.pk))

    assert resposta.status_code == 404, resposta.content


def test_vaga_de_outro_edital_e_404(
    client_comissao: Client,
    program: Program,
    edital_regular: SelectionProcess,
    edital_suplementar: SelectionProcess,
    projeto: CollectiveProject,
    linha: ResearchLine,
):
    daqui = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    de_outro_edital = vaga(
        program,
        edital_suplementar,
        quantidade=0,
        categoria=QuotaCategory.DISABILITY,
        level=SelectionLevel.DOCTORATE,
        linha=linha,
    )

    resposta = client_comissao.post(
        url(edital_regular.pk),
        corpo(daqui, de_outro_edital),
        content_type="application/json",
    )

    assert resposta.status_code == 404, resposta.content


def test_sem_sessao_e_401(edital_regular: SelectionProcess):
    sessao = Client()

    resposta = sessao.get(url(edital_regular.pk))

    assert resposta.status_code == 401, resposta.content


def test_sem_csrf_a_realocacao_e_recusada(
    comissao: User,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
):
    mestrado = vaga(program, edital_regular, quantidade=2, projeto=projeto)
    doutorado = vaga(
        program,
        edital_regular,
        quantidade=0,
        level=SelectionLevel.DOCTORATE,
        projeto=projeto,
    )
    sessao = Client(enforce_csrf_checks=True)
    sessao.force_login(comissao)

    resposta = sessao.post(
        url(edital_regular.pk),
        corpo(mestrado, doutorado),
        content_type="application/json",
    )

    assert resposta.status_code == 403, resposta.content
