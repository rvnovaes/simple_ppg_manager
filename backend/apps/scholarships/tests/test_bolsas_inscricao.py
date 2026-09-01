"""Invariantes da inscrição no edital de bolsas.

Nível (a) da pirâmide (Seção 9): objeto em memória sempre que possível —
`clean()` do questionário e `ensure_editable()` não tocam o banco. Os que
precisam da `UniqueConstraint` de verdade, ou de um `Student` gravado,
ficam no fim, marcados com `django_db`.

O caso que dá nome ao arquivo é o do nível congelado: a inscrição copia o
nível do `Student` no ato e **não** acompanha mudança posterior. É o que
impede um aluno que passou de mestrado a doutorado no meio da edição de
migrar de lista depois que a comissão já pontuou.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.academic.models import Student
from apps.core.exceptions import DomainError, InvalidStateTransition, NotAllowed
from apps.people.models import Person
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Program,
    ResearchLine,
)
from apps.scholarships.models import (
    PriorityBand,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

AGORA = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _inscricao(**kwargs) -> ScholarshipApplication:
    """Inscrição em memória, sem tocar o banco.

    A edição e o discente vão **sem pk** de propósito: com eles a
    checagem de duplicata de `clean()` faria uma consulta, e o que se
    quer aqui é o invariante do questionário, não a
    `UniqueConstraint` — essa tem os seus testes `django_db` no fim.
    """
    campos = {
        "program": Program(pk=1),
        "edition": ScholarshipEdition(program_id=1),
        "student": Student(program_id=1),
        "level": ScholarshipLevel.MASTERS,
    }
    return ScholarshipApplication(**{**campos, **kwargs})


# --- questionário: a atividade remunerada carrega renda e carga horária ----


def test_clean_passa_sem_atividade_remunerada_e_sem_renda():
    """Quem não declara atividade não precisa informar rendimento."""
    _inscricao(has_paid_activity=False).clean()


@pytest.mark.parametrize(
    "campos",
    [
        {},
        {"monthly_income": Decimal("2500.00")},
        {"weekly_hours": 20},
    ],
    ids=["nada", "so_renda", "so_carga_horaria"],
)
def test_clean_exige_renda_e_carga_horaria_de_quem_tem_atividade(campos):
    """As duas juntas: são elas que ordenam 2.4-V e 2.4-VI/VII/VIII."""
    with pytest.raises(DomainError) as exc:
        _inscricao(has_paid_activity=True, **campos).clean()

    assert exc.value.code == "income_required"
    assert exc.value.status_code == 400


def test_clean_passa_com_atividade_renda_e_carga_horaria():
    _inscricao(
        has_paid_activity=True,
        monthly_income=Decimal("2500.00"),
        weekly_hours=20,
    ).clean()


def test_renda_zerada_nao_e_ausencia_de_renda():
    """Rendimento 0,00 é declaração, não campo em branco — e ordena primeiro."""
    _inscricao(
        has_paid_activity=True,
        monthly_income=Decimal("0.00"),
        weekly_hours=4,
    ).clean()


# --- sobrescrita de faixa (B6) ---------------------------------------------


def test_clean_exige_justificativa_na_sobrescrita_de_faixa():
    with pytest.raises(DomainError) as exc:
        _inscricao(band_override=PriorityBand.B24_I).clean()

    assert exc.value.code == "override_reason_required"


def test_justificativa_so_de_espaco_em_branco_nao_conta():
    with pytest.raises(DomainError) as exc:
        _inscricao(band_override=PriorityBand.B24_I, band_override_reason="   ").clean()

    assert exc.value.code == "override_reason_required"


def test_clean_aceita_sobrescrita_com_justificativa():
    _inscricao(
        band_override=PriorityBand.B24_II,
        band_override_reason="Decisão do colegiado de 12/03, ata 04/2026.",
    ).clean()


def test_justificativa_sem_sobrescrita_nao_e_erro():
    """A justificativa sozinha não obriga a nada — só a sobrescrita obriga."""
    _inscricao(band_override_reason="Anotação da secretaria.").clean()


# --- band(): a sobrescrita vence; sem ela, a derivação vem depois ----------


def test_band_devolve_a_sobrescrita_quando_ha_uma():
    inscricao = _inscricao(
        band_override=PriorityBand.B24_I, band_override_reason="Caso omisso."
    )

    assert inscricao.band() == PriorityBand.B24_I


def test_band_sem_sobrescrita_e_none_e_nao_residual():
    """`None` é "ainda não derivada". Devolver `residual` aqui poria
    candidato do bloco 2.1 no fim da fila sem ninguém perceber."""
    assert _inscricao().band() is None


# --- ensure_editable: janela aberta e dono da inscrição --------------------


def _com_dono(status: str, user_pk: int | None = 7) -> ScholarshipApplication:
    """Inscrição cuja `student.person.user_id` é `user_pk`, sem banco.

    A cadeia `Student → Person → User` é montada em memória: o
    `person` atribuído fica em cache na instância, e `_user_is_owner`
    lê o `user_id` dele sem consulta nenhuma.
    """
    return _inscricao(
        edition=ScholarshipEdition(program_id=1, status=status),
        student=Student(program_id=1, person=Person(pk=5, user_id=user_pk)),
    )


def test_ensure_editable_passa_com_a_janela_aberta_e_o_proprio_aluno():
    _com_dono(ScholarshipEditionStatus.SUBMISSIONS_OPEN).ensure_editable(
        SimpleNamespace(pk=7)
    )


@pytest.mark.parametrize(
    "status",
    [s for s in ScholarshipEditionStatus.values if s != "submissions_open"],
)
def test_ensure_editable_recusa_fora_da_janela(status):
    """Fechada a janela, a inscrição some da mão do aluno: 409."""
    with pytest.raises(InvalidStateTransition) as exc:
        _com_dono(status).ensure_editable(SimpleNamespace(pk=7))

    assert exc.value.code == "submissions_closed"
    assert exc.value.status_code == 409


def test_ensure_editable_recusa_outro_usuario():
    """Pessoa errada é 403, e não 409: a janela está aberta, ele é que não é o dono."""
    with pytest.raises(NotAllowed) as exc:
        _com_dono(ScholarshipEditionStatus.SUBMISSIONS_OPEN).ensure_editable(
            SimpleNamespace(pk=99)
        )

    assert exc.value.code == "not_application_owner"
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "user", [None, SimpleNamespace(pk=None)], ids=["none", "sem_pk"]
)
def test_ensure_editable_recusa_usuario_anonimo(user):
    with pytest.raises(NotAllowed):
        _com_dono(ScholarshipEditionStatus.SUBMISSIONS_OPEN).ensure_editable(user)


def test_ensure_editable_recusa_aluno_sem_usuario_vinculado():
    with pytest.raises(NotAllowed):
        _com_dono(
            ScholarshipEditionStatus.SUBMISSIONS_OPEN, user_pk=None
        ).ensure_editable(SimpleNamespace(pk=7))


# --- o que precisa de banco ------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program, year=2026, title="Edital de Bolsas 2026"
    )


@pytest.fixture
def projeto(program: Program) -> CollectiveProject:
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    return CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto coletivo"
    )


@pytest.fixture
def discente(program: Program, projeto: CollectiveProject) -> Student:
    pessoa = Person.objects.create(
        program=program, full_name="João Souza", primary_email="joao@example.com"
    )
    return Student.objects.create(
        program=program,
        person=pessoa,
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2025, 3, 1),
    )


@pytest.mark.django_db
def test_for_student_copia_o_nivel_e_o_programa(edicao, discente):
    inscricao = ScholarshipApplication.for_student(edition=edicao, student=discente)

    assert inscricao.level == ScholarshipLevel.MASTERS
    assert inscricao.program_id == edicao.program_id
    assert inscricao.pk is None  # não salva: quem persiste é o router


@pytest.mark.django_db
def test_o_nivel_congela_e_nao_acompanha_mudanca_no_discente(edicao, discente):
    """O ponto do congelamento: mudar o `Student` depois não move a lista."""
    inscricao = ScholarshipApplication.for_student(edition=edicao, student=discente)
    inscricao.clean()
    inscricao.save()

    discente.level = Student.Level.DOCTORATE
    discente.save()
    inscricao.refresh_from_db()

    assert inscricao.level == ScholarshipLevel.MASTERS


@pytest.mark.django_db
def test_discente_sem_nivel_nao_se_inscreve(edicao, program):
    """Isolada e eletiva não têm nível — e sem nível não há barema."""
    pessoa = Person.objects.create(
        program=program, full_name="Maria Dias", primary_email="maria@example.com"
    )
    periodo = AcademicTerm.objects.create(
        year=2026, half=1, starts_on=date(2026, 3, 2), ends_on=date(2026, 7, 18)
    )
    isolada = Student.objects.create(
        program=program,
        person=pessoa,
        modality=Student.Modality.ISOLATED,
        term=periodo,
    )

    with pytest.raises(DomainError) as exc:
        ScholarshipApplication.for_student(edition=edicao, student=isolada)

    assert exc.value.code == "student_without_level"


@pytest.mark.django_db
def test_clean_rejeita_segunda_inscricao_do_mesmo_discente(edicao, discente):
    """A duplicata vira `duplicate_application` (400), não `IntegrityError`."""
    ScholarshipApplication.for_student(edition=edicao, student=discente).save()

    with pytest.raises(DomainError) as exc:
        ScholarshipApplication.for_student(edition=edicao, student=discente).clean()

    assert exc.value.code == "duplicate_application"
    assert exc.value.status_code == 400


@pytest.mark.django_db
def test_clean_aceita_a_propria_inscricao_na_edicao(edicao, discente):
    inscricao = ScholarshipApplication.for_student(edition=edicao, student=discente)
    inscricao.save()

    inscricao.fump_level = 1
    inscricao.clean()


@pytest.mark.django_db
def test_clean_rejeita_discente_de_outro_programa(edicao, discente):
    outro = Program.objects.create(acronym="PPGX", name="Outro programa")
    inscricao = ScholarshipApplication.for_student(edition=edicao, student=discente)
    inscricao.student.program_id = outro.pk

    with pytest.raises(DomainError) as exc:
        inscricao.clean()

    assert exc.value.code == "program_mismatch"


@pytest.mark.django_db
def test_for_program_e_o_primeiro_filtro_da_busca_de_inscricoes(edicao, discente):
    inscricao = ScholarshipApplication.for_student(edition=edicao, student=discente)
    inscricao.save()

    assert list(ScholarshipApplication.objects.for_program(edicao.program)) == [
        inscricao
    ]
    assert list(
        ScholarshipApplication.objects.for_program(edicao.program)
        .for_edition(edicao)
        .for_level(ScholarshipLevel.MASTERS)
        .for_student(discente)
    ) == [inscricao]


@pytest.mark.django_db
def test_snapshot_da_publicacao_nasce_todo_nulo(edicao, discente):
    inscricao = ScholarshipApplication.for_student(edition=edicao, student=discente)
    inscricao.save()

    assert inscricao.published_band is None
    assert inscricao.published_score is None
    assert inscricao.published_position is None
    assert inscricao.draw_order is None
    assert inscricao.published_at is None
    assert inscricao.fump_level == 0
