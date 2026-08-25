"""A classificação: o cálculo que transforma nota final em posição.

Nível (b) da pirâmide (Seção 9). A regra pura já é exercida sem banco em
`test_ranking.py`; o que este arquivo guarda é a borda dela:

- **sem a ata da última etapa assinada não há classificação.** Enquanto a
  banca pode retificar a ata, `approved` é resultado provisório.
- **recalcular é o fluxo normal**, e é idempotente: a segunda chamada
  reescreve as mesmas posições, sem duplicar nada.
- **o primeiro matriculado tranca a chave** (`ranking_locked`): a lista
  virou matrícula e não se reescreve mais.
- **o recorte é nível × alvo**, e o alvo é escopado no programa da sessão:
  edital de outro tenant é 404 antes de qualquer conta.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.academic.models import Student, Teacher
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    ExaminationRecord,
    QuotaCategory,
    RankingOutcome,
    RecordStatus,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionStage,
    StageScore,
    Vacancy,
    gerar_protocolo,
)

pytestmark = pytest.mark.django_db

SENHA = "senha-de-teste-123"

# CPFs válidos (mod-11) para as inscrições dos cenários.
CPFS = [
    "52998224725",
    "11144477735",
    "12345678909",
    "39053344705",
    "16899535009",
    "40442820135",
]


def ranking_de(process_id: int) -> str:
    return f"/api/v1/selection/processes/{process_id}/ranking"


def consulta(project_id: int, level: str = SelectionLevel.MASTERS) -> dict[str, str]:
    """A query string do GET — tudo texto, como chega do navegador."""
    return {"level": level, "project_id": str(project_id)}


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


def aprovada(
    program: Program,
    edital: SelectionProcess,
    *,
    nome: str,
    cpf: str,
    nota: str,
    categoria: str = QuotaCategory.OPEN,
    nascimento: date = date(1995, 5, 20),
    projeto: CollectiveProject | None = None,
    linha: ResearchLine | None = None,
    level: str = SelectionLevel.MASTERS,
) -> Application:
    """Inscrição já aprovada na última etapa, com nota final carimbada."""
    return Application.objects.create(
        program=program,
        process=edital,
        protocol=gerar_protocolo(edital),
        full_name=nome,
        email=f"{cpf}@exemplo.br",
        cpf=cpf,
        birth_date=nascimento,
        level=level,
        project=projeto,
        research_line=linha,
        quota_category=categoria,
        status=ApplicationStatus.APPROVED,
        final_score=Decimal(nota),
        submitted_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
    )


def com_desempate(
    program: Program, inscricao: Application, etapa: SelectionStage, nota: str
) -> StageScore:
    return StageScore.objects.create(
        program=program, application=inscricao, stage=etapa, score=Decimal(nota)
    )


def vaga(
    program: Program,
    edital: SelectionProcess,
    *,
    categoria: str,
    quantidade: int,
    projeto: CollectiveProject | None = None,
    linha: ResearchLine | None = None,
    level: str = SelectionLevel.MASTERS,
) -> Vacancy:
    return Vacancy.objects.create(
        program=program,
        process=edital,
        level=level,
        project=projeto,
        research_line=linha,
        quota_category=categoria,
        quantity=quantidade,
    )


def ata_final_assinada(
    edital: SelectionProcess,
    *,
    banca: Board,
    level: str = SelectionLevel.MASTERS,
    projeto: CollectiveProject | None = None,
    linha: ResearchLine | None = None,
) -> ExaminationRecord:
    """Ata assinada da última etapa, gravada direto.

    O caminho pela banca (congelar, assinar, fechar) é exercido em
    `test_fechamento_de_etapa.py`; aqui interessa só o efeito dela sobre
    a classificação.
    """
    ultima = edital.stages.order_by("-order").first()
    assert ultima is not None
    return ExaminationRecord.objects.create(
        program=edital.program,
        process=edital,
        stage=ultima,
        level=level,
        project=projeto,
        research_line=linha,
        board=banca,
        status=RecordStatus.SIGNED,
        content=[],
        signed_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
    )


@pytest.fixture
def chave_regular(
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    banca_regular: Board,
) -> dict:
    """Uma vaga de ampla, uma de cota racial e a ata final assinada."""
    vaga(
        program,
        edital_regular,
        categoria=QuotaCategory.OPEN,
        quantidade=1,
        projeto=projeto,
    )
    vaga(
        program,
        edital_regular,
        categoria=QuotaCategory.RACIAL,
        quantidade=1,
        projeto=projeto,
    )
    ata_final_assinada(edital_regular, banca=banca_regular, projeto=projeto)
    return {"level": SelectionLevel.MASTERS, "project_id": projeto.pk}


def aluna_matriculada(
    program: Program,
    inscricao: Application,
    projeto: CollectiveProject,
    matricula: str,
) -> Student:
    """Converte a inscrição em aluno na marra.

    O caminho de verdade é `convert_to_student` (f5), que ainda não
    existe; aqui interessa só o efeito da matrícula sobre o recálculo.
    Aluno regular exige nível, projeto, ingresso e prazo — a
    CheckConstraint `student_regular_requires_degree_fields`.
    """
    pessoa = Person.objects.create(
        program=program,
        full_name=inscricao.full_name,
        primary_email=inscricao.email,
    )
    aluno = Student.objects.create(
        program=program,
        person=pessoa,
        registration_number=matricula,
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2027, 3, 1),
        deadline=date(2029, 3, 1),
    )
    inscricao.refresh_from_db()
    inscricao.enroll(aluno)
    inscricao.save(update_fields=["status", "student"])
    return aluno


# --- o cálculo --------------------------------------------------------------


def test_calculo_grava_posicao_desfecho_e_auditoria(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    primeira = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )
    cotista = aprovada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="80.00",
        categoria=QuotaCategory.RACIAL,
        projeto=projeto,
    )
    ultima = aprovada(
        program,
        edital_regular,
        nome="Célia Nunes",
        cpf=CPFS[2],
        nota="75.00",
        projeto=projeto,
    )

    resposta = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["total_seats"] == 2
    assert corpo["locked"] is False
    assert corpo["computed_at"] is not None
    posicoes = [
        (c["id"], c["final_rank"], c["final_outcome"]) for c in corpo["applications"]
    ]
    assert posicoes == [
        (primeira.pk, 1, RankingOutcome.CLASSIFIED_OPEN),
        (cotista.pk, 2, RankingOutcome.CLASSIFIED_QUOTA),
        (ultima.pk, 3, RankingOutcome.NOT_CLASSIFIED),
    ]

    primeira.refresh_from_db()
    assert (primeira.final_rank, primeira.final_outcome) == (
        1,
        RankingOutcome.CLASSIFIED_OPEN,
    )
    assert primeira.ranked_at is not None
    assert AuditLog.objects.filter(event="selection.ranking.compute").count() == 1


def test_cotista_classificado_na_ampla_libera_a_reserva(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    """A política inteira em um teste: a reserva não é consumida por quem
    já entrou pela ampla, e reserva ociosa volta para a ampla."""
    lider = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="95.00",
        categoria=QuotaCategory.RACIAL,
        projeto=projeto,
    )
    segundo = aprovada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="90.00",
        projeto=projeto,
    )
    terceiro = aprovada(
        program,
        edital_regular,
        nome="Célia Nunes",
        cpf=CPFS[2],
        nota="85.00",
        projeto=projeto,
    )

    corpo = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    ).json()

    por_id = {c["id"]: c for c in corpo["applications"]}
    assert por_id[lider.pk]["final_outcome"] == RankingOutcome.CLASSIFIED_OPEN
    assert por_id[segundo.pk]["final_outcome"] == RankingOutcome.CLASSIFIED_OPEN
    assert por_id[terceiro.pk]["final_outcome"] == RankingOutcome.NOT_CLASSIFIED


def test_desempate_usa_as_etapas_na_ordem_do_edital_e_marca_o_empate_total(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    primeira_etapa = edital_regular.stages.get(order=1)
    vencedor = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )
    perdedor = aprovada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="90.00",
        projeto=projeto,
    )
    com_desempate(program, vencedor, primeira_etapa, "80.00")
    com_desempate(program, perdedor, primeira_etapa, "70.00")
    # Sem nenhuma nota de desempate e com a mesma data de nascimento: o
    # sistema não desempata, e diz isso.
    empatada_a = aprovada(
        program,
        edital_regular,
        nome="Célia Nunes",
        cpf=CPFS[2],
        nota="60.00",
        projeto=projeto,
    )
    empatada_b = aprovada(
        program,
        edital_regular,
        nome="Dario Reis",
        cpf=CPFS[3],
        nota="60.00",
        projeto=projeto,
    )

    corpo = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    ).json()

    por_id = {c["id"]: c for c in corpo["applications"]}
    assert por_id[vencedor.pk]["final_rank"] < por_id[perdedor.pk]["final_rank"]
    assert por_id[vencedor.pk]["tie_unresolved"] is False
    assert por_id[empatada_a.pk]["tie_unresolved"] is True
    assert por_id[empatada_b.pk]["tie_unresolved"] is True


def test_recalcular_e_idempotente(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )
    aprovada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="80.00",
        projeto=projeto,
    )

    primeiro = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    ).json()
    segundo = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    ).json()

    def posicoes(corpo: dict) -> list[tuple]:
        return [
            (c["id"], c["final_rank"], c["final_outcome"])
            for c in corpo["applications"]
        ]

    assert posicoes(primeiro) == posicoes(segundo)
    assert Application.objects.filter(ranked_at__isnull=False).count() == 2
    assert AuditLog.objects.filter(event="selection.ranking.compute").count() == 2


def test_nota_nova_muda_a_posicao_no_recalculo(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    """Retificação de ata mexe na nota final; a classificação seguinte
    tem que enxergar isso — é o motivo de recalcular existir."""
    primeira = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )
    segunda = aprovada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="80.00",
        projeto=projeto,
    )
    client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    )

    segunda.final_score = Decimal("99.00")
    segunda.save(update_fields=["final_score"])
    corpo = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    ).json()

    assert [c["id"] for c in corpo["applications"]] == [segunda.pk, primeira.pk]


# --- as travas --------------------------------------------------------------


def test_sem_ata_final_assinada_o_calculo_e_recusado(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    banca_regular: Board,
):
    vaga(
        program,
        edital_regular,
        categoria=QuotaCategory.OPEN,
        quantidade=1,
        projeto=projeto,
    )
    inscricao = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )

    resposta = client_da_secretaria.post(
        ranking_de(edital_regular.pk),
        {"level": SelectionLevel.MASTERS, "project_id": projeto.pk},
        content_type="application/json",
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "final_record_not_signed"
    inscricao.refresh_from_db()
    assert inscricao.final_rank is None
    assert inscricao.ranked_at is None


def test_ata_assinada_de_outra_etapa_nao_serve(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    banca_regular: Board,
):
    """A exigência é da **última** etapa: assinar a primeira não classifica
    ninguém, porque as seguintes ainda podem eliminar."""
    vaga(
        program,
        edital_regular,
        categoria=QuotaCategory.OPEN,
        quantidade=1,
        projeto=projeto,
    )
    aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )
    ExaminationRecord.objects.create(
        program=program,
        process=edital_regular,
        stage=edital_regular.stages.get(order=1),
        level=SelectionLevel.MASTERS,
        project=projeto,
        board=banca_regular,
        status=RecordStatus.SIGNED,
        content=[],
        signed_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
    )

    resposta = client_da_secretaria.post(
        ranking_de(edital_regular.pk),
        {"level": SelectionLevel.MASTERS, "project_id": projeto.pk},
        content_type="application/json",
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "final_record_not_signed"


def test_matriculado_na_chave_tranca_o_recalculo(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    classificada = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )
    client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    )

    aluna_matriculada(program, classificada, projeto, "2027000001")

    resposta = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "ranking_locked"


def test_alvo_incompativel_com_o_tipo_do_edital_e_recusado(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    linha: ResearchLine,
):
    resposta = client_da_secretaria.post(
        ranking_de(edital_regular.pk),
        {"level": SelectionLevel.MASTERS, "research_line_id": linha.pk},
        content_type="application/json",
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "target_mismatch"


# --- o suplementar ----------------------------------------------------------


def test_suplementar_classifica_por_categoria(
    client_da_secretaria: Client,
    program: Program,
    edital_suplementar: SelectionProcess,
    linha: ResearchLine,
    professores: list[Teacher],
):
    """No Suplementar cada ação afirmativa disputa só entre os seus, e a
    posição é dentro da categoria — não há ordem geral."""
    vaga(
        program,
        edital_suplementar,
        categoria=QuotaCategory.RACIAL,
        quantidade=1,
        linha=linha,
    )
    vaga(
        program,
        edital_suplementar,
        categoria=QuotaCategory.INDIGENOUS,
        quantidade=1,
        linha=linha,
    )
    banca = Board(
        program=program,
        process=edital_suplementar,
        level=SelectionLevel.MASTERS,
        research_line=linha,
        president=professores[0],
        member_1=professores[1],
        member_2=professores[2],
        alternate=professores[3],
    )
    banca.clean()
    banca.save()
    ata_final_assinada(edital_suplementar, banca=banca, linha=linha)
    racial_1 = aprovada(
        program,
        edital_suplementar,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="70.00",
        categoria=QuotaCategory.RACIAL,
        linha=linha,
    )
    racial_2 = aprovada(
        program,
        edital_suplementar,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="95.00",
        categoria=QuotaCategory.RACIAL,
        linha=linha,
    )
    indigena = aprovada(
        program,
        edital_suplementar,
        nome="Célia Nunes",
        cpf=CPFS[2],
        nota="72.00",
        categoria=QuotaCategory.INDIGENOUS,
        linha=linha,
    )

    resposta = client_da_secretaria.post(
        ranking_de(edital_suplementar.pk),
        {"level": SelectionLevel.MASTERS, "research_line_id": linha.pk},
        content_type="application/json",
    )

    assert resposta.status_code == 200, resposta.content
    por_id = {c["id"]: c for c in resposta.json()["applications"]}
    assert por_id[racial_2.pk]["final_rank"] == 1
    assert por_id[racial_2.pk]["final_outcome"] == RankingOutcome.CLASSIFIED_QUOTA
    assert por_id[racial_1.pk]["final_rank"] == 2
    assert por_id[racial_1.pk]["final_outcome"] == RankingOutcome.NOT_CLASSIFIED
    # A nota mais baixa da indígena classifica: a disputa é só dela.
    assert por_id[indigena.pk]["final_rank"] == 1
    assert por_id[indigena.pk]["final_outcome"] == RankingOutcome.CLASSIFIED_QUOTA


# --- a leitura --------------------------------------------------------------


def test_get_devolve_a_grade_de_vagas_e_lista_vazia_antes_do_calculo(
    client_da_secretaria: Client,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    resposta = client_da_secretaria.get(
        ranking_de(edital_regular.pk), consulta(projeto.pk)
    )

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo["applications"] == []
    assert corpo["computed_at"] is None
    assert corpo["total_seats"] == 2
    assert [(s["quota_category"], s["quantity"]) for s in corpo["seats"]] == [
        (QuotaCategory.OPEN, 1),
        (QuotaCategory.RACIAL, 1),
    ]


def test_get_traz_quem_ja_virou_aluno_e_marca_a_trava(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    """Matriculado não some da lista publicada — ele é o primeiro colocado."""
    classificada = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="90.00",
        projeto=projeto,
    )
    client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    )
    aluna = aluna_matriculada(program, classificada, projeto, "2027000002")

    corpo = client_da_secretaria.get(
        ranking_de(edital_regular.pk), consulta(projeto.pk)
    ).json()

    assert [c["id"] for c in corpo["applications"]] == [classificada.pk]
    assert corpo["applications"][0]["status"] == ApplicationStatus.ENROLLED
    assert corpo["applications"][0]["student_id"] == aluna.pk
    assert corpo["locked"] is True


def test_outro_alvo_nao_entra_na_classificacao(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    linha: ResearchLine,
    chave_regular: dict,
):
    """Cada projeto tem a sua grade e a sua lista: quem concorre a outro
    alvo não disputa estas vagas."""
    outro_projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Outro projeto"
    )
    daqui = aprovada(
        program,
        edital_regular,
        nome="Ana Lima",
        cpf=CPFS[0],
        nota="80.00",
        projeto=projeto,
    )
    de_la = aprovada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="99.00",
        projeto=outro_projeto,
    )

    corpo = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    ).json()

    assert [c["id"] for c in corpo["applications"]] == [daqui.pk]
    de_la.refresh_from_db()
    assert de_la.ranked_at is None


def test_nao_aprovada_fica_de_fora(
    client_da_secretaria: Client,
    program: Program,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
    inscricao: Application,
):
    """`inscricao` é homologada, não aprovada: ela não entra na lista."""
    classificada = aprovada(
        program,
        edital_regular,
        nome="Bento Melo",
        cpf=CPFS[1],
        nota="80.00",
        projeto=projeto,
    )

    corpo = client_da_secretaria.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    ).json()

    assert [c["id"] for c in corpo["applications"]] == [classificada.pk]


# --- tenant, permissão e CSRF -----------------------------------------------


def test_edital_de_outro_programa_e_404(
    client_da_secretaria: Client, edital_regular: SelectionProcess
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

    resposta = client_da_secretaria.post(
        ranking_de(alheio.pk),
        {"level": SelectionLevel.MASTERS, "project_id": None},
        content_type="application/json",
    )

    assert resposta.status_code == 404, resposta.content


def test_alvo_de_outro_programa_e_404(
    client_da_secretaria: Client, edital_regular: SelectionProcess
):
    outro = Program.objects.create(name="Outro programa", acronym="PPGZ")
    linha_alheia = ResearchLine.objects.create(program=outro, name="Linha de fora")
    projeto_alheio = CollectiveProject.objects.create(
        program=outro, research_line=linha_alheia, name="Projeto de fora"
    )

    resposta = client_da_secretaria.post(
        ranking_de(edital_regular.pk),
        {"level": SelectionLevel.MASTERS, "project_id": projeto_alheio.pk},
        content_type="application/json",
    )

    assert resposta.status_code == 404, resposta.content


def test_docente_nao_calcula_classificacao(
    client: Client,
    program: Program,
    docente: Teacher,
    edital_regular: SelectionProcess,
    projeto: CollectiveProject,
    chave_regular: dict,
):
    user = User.objects.create_user(username="docente", password=SENHA)
    user.groups.add(Group.objects.get(name="Docente"))
    pessoa = docente.person
    pessoa.user = user
    pessoa.save(update_fields=["user"])
    client.force_login(user)

    resposta = client.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    )

    assert resposta.status_code == 403, resposta.content


def test_sem_sessao_e_401(edital_regular: SelectionProcess, projeto: CollectiveProject):
    sessao = Client()

    resposta = sessao.get(ranking_de(edital_regular.pk), consulta(projeto.pk))

    assert resposta.status_code == 401, resposta.content


def test_sem_csrf_o_calculo_e_recusado(
    secretaria: User,
    program: Program,
    edital_regular: SelectionProcess,
    chave_regular: dict,
):
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    sessao = Client(enforce_csrf_checks=True)
    sessao.force_login(secretaria)

    resposta = sessao.post(
        ranking_de(edital_regular.pk), chave_regular, content_type="application/json"
    )

    assert resposta.status_code == 403, resposta.content
