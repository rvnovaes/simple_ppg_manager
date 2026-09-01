"""Invariantes da edição do edital de bolsas e da comissão.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
Os pks são atribuídos à mão só para as FKs terem id — nada é salvo. Os
testes que precisam da `UniqueConstraint` de verdade ficam no fim,
marcados com `django_db`.
"""

from datetime import UTC, date, datetime

import pytest

from apps.academic.models import Teacher
from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.people.models import Person
from apps.programs.models import Program
from apps.scholarships.models import (
    CommitteeMember,
    ScholarshipEdition,
    ScholarshipEditionStatus,
)

AGORA = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

# Cada transição, o estado que ela exige e o estado que ela produz.
TRANSICOES = (
    (
        "open_submissions",
        ScholarshipEditionStatus.DRAFT,
        ScholarshipEditionStatus.SUBMISSIONS_OPEN,
    ),
    (
        "start_review",
        ScholarshipEditionStatus.SUBMISSIONS_OPEN,
        ScholarshipEditionStatus.UNDER_REVIEW,
    ),
    (
        "publish_preliminary",
        ScholarshipEditionStatus.UNDER_REVIEW,
        ScholarshipEditionStatus.PRELIMINARY_RESULT,
    ),
    (
        "open_appeals",
        ScholarshipEditionStatus.PRELIMINARY_RESULT,
        ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
    ),
    (
        "publish_final",
        ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
        ScholarshipEditionStatus.FINAL_RESULT,
    ),
)

# As duas transições que carimbam instante recebem `at`; as outras três não.
CARIMBA_INSTANTE = {"publish_preliminary", "publish_final"}

TODOS_OS_ESTADOS = tuple(ScholarshipEditionStatus.values)


def _edicao(**kwargs) -> ScholarshipEdition:
    campos = {
        "program": Program(pk=1, acronym="PPGD"),
        "year": 2026,
        "title": "Edital de Bolsas 2026",
    }
    return ScholarshipEdition(**{**campos, **kwargs})


def _transicionar(edicao: ScholarshipEdition, nome: str) -> None:
    metodo = getattr(edicao, nome)
    if nome in CARIMBA_INSTANTE:
        metodo(at=AGORA)
    else:
        metodo()


# --- transições -------------------------------------------------------------


@pytest.mark.parametrize(("nome", "origem", "destino"), TRANSICOES)
def test_transicao_valida_muda_o_estado_sem_salvar(nome, origem, destino):
    edicao = _edicao(status=origem)

    _transicionar(edicao, nome)

    assert edicao.status == destino
    assert edicao.pk is None


@pytest.mark.parametrize(("nome", "origem", "_destino"), TRANSICOES)
@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_transicao_a_partir_de_estado_errado_e_409(nome, origem, _destino, estado):
    """Toda transição exige o estado anterior — inclusive o seu próprio
    destino: o caminho é de mão única e não há repetição."""
    if estado == origem:
        pytest.skip("estado de origem é justamente o caso válido")

    edicao = _edicao(status=estado)

    with pytest.raises(InvalidStateTransition) as exc:
        _transicionar(edicao, nome)

    assert exc.value.status_code == 409


def test_publicar_preliminar_e_final_carimbam_os_instantes():
    edicao = _edicao(status=ScholarshipEditionStatus.UNDER_REVIEW)

    edicao.publish_preliminary(at=AGORA)
    assert edicao.published_preliminary_at == AGORA
    assert edicao.published_final_at is None

    edicao.open_appeals()
    edicao.publish_final(at=AGORA)
    assert edicao.published_final_at == AGORA


def test_caminho_completo_do_rascunho_ao_resultado_final():
    edicao = _edicao()

    for nome, _origem, destino in TRANSICOES:
        _transicionar(edicao, nome)
        assert edicao.status == destino


# --- guardas de leitura -----------------------------------------------------


@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_bareme_editable_so_em_rascunho(estado):
    esperado = estado == ScholarshipEditionStatus.DRAFT

    assert _edicao(status=estado).bareme_editable() is esperado


@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_ensure_bareme_editable_e_a_versao_que_cobra(estado):
    """A leitura desenha a tela; `ensure_` é a guarda de escrita (409).

    O par existe porque o front precisa saber se mostra o botão, e o
    backend não pode confiar nisso — quem recusa a escrita é o model.
    """
    edicao = _edicao(status=estado)

    if edicao.bareme_editable():
        assert edicao.ensure_bareme_editable() is None
        return

    with pytest.raises(InvalidStateTransition) as erro:
        edicao.ensure_bareme_editable()
    assert erro.value.code == "bareme_frozen"
    assert erro.value.status_code == 409


@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_submission_open_so_com_inscricoes_abertas(estado):
    esperado = estado == ScholarshipEditionStatus.SUBMISSIONS_OPEN

    assert _edicao(status=estado).submission_open() is esperado


@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_committee_can_review_em_analise_e_em_recursos(estado):
    """Os dois estados: `appeals_under_review` é o deferimento reabrindo o
    lançamento antes do resultado final."""
    esperado = estado in {
        ScholarshipEditionStatus.UNDER_REVIEW,
        ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
    }

    assert _edicao(status=estado).committee_can_review() is esperado


@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_appeal_open_so_com_a_fase_de_recursos_aberta(estado):
    esperado = estado == ScholarshipEditionStatus.APPEALS_UNDER_REVIEW

    assert _edicao(status=estado).appeal_open() is esperado


@pytest.mark.parametrize("estado", TODOS_OS_ESTADOS)
def test_results_visible_a_partir_do_preliminar(estado):
    esperado = estado in {
        ScholarshipEditionStatus.PRELIMINARY_RESULT,
        ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
        ScholarshipEditionStatus.FINAL_RESULT,
    }

    assert _edicao(status=estado).results_visible_to_student() is esperado


# --- clean sem banco --------------------------------------------------------


def test_clean_da_edicao_sem_programa_nao_consulta_o_banco():
    """Obrigatoriedade é cobrança do schema Ninja e do NOT NULL."""
    _edicao(program=None).clean()


def test_clean_do_membro_sem_edicao_nao_consulta_o_banco():
    CommitteeMember(edition=None, teacher=None).clean()


# --- com banco --------------------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    edicao = ScholarshipEdition(
        program=program, year=2026, title="Edital de Bolsas 2026"
    )
    edicao.clean()
    edicao.save()
    return edicao


@pytest.fixture
def docente(program: Program) -> Teacher:
    pessoa = Person.objects.create(
        program=program, full_name="Ana Lima", primary_email="ana@example.com"
    )
    return Teacher.objects.create(
        program=program,
        person=pessoa,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 3, 1),
    )


@pytest.mark.django_db
def test_clean_rejeita_segunda_edicao_no_mesmo_ano_do_programa(edicao, program):
    """A duplicata vira `duplicate_edition` (400), não `IntegrityError`."""
    with pytest.raises(DomainError) as exc:
        ScholarshipEdition(program=program, year=2026, title="Outra").clean()

    assert exc.value.code == "duplicate_edition"
    assert exc.value.status_code == 400


@pytest.mark.django_db
def test_clean_aceita_outro_ano_no_mesmo_programa(edicao, program):
    ScholarshipEdition(program=program, year=2027, title="Bolsas 2027").clean()


@pytest.mark.django_db
def test_clean_aceita_a_propria_edicao_na_edicao(edicao):
    edicao.title = "Edital de Bolsas 2026 (retificado)"
    edicao.clean()


@pytest.mark.django_db
def test_membro_da_comissao_chega_ao_programa_pela_edicao(edicao, docente):
    membro = CommitteeMember(
        edition=edicao, teacher=docente, appointed_on=date(2026, 2, 1)
    )
    membro.clean()
    membro.save()

    assert CommitteeMember.objects.for_program(edicao.program).get() == membro


@pytest.mark.django_db
def test_clean_rejeita_o_mesmo_professor_duas_vezes_na_comissao(edicao, docente):
    CommitteeMember.objects.create(edition=edicao, teacher=docente)

    with pytest.raises(DomainError) as exc:
        CommitteeMember(edition=edicao, teacher=docente).clean()

    assert exc.value.code == "duplicate_committee_member"


@pytest.mark.django_db
def test_clean_rejeita_professor_de_outro_programa(edicao, docente):
    outro = Program.objects.create(acronym="PPGX", name="Outro programa")
    docente.program = outro
    docente.save()

    with pytest.raises(DomainError) as exc:
        CommitteeMember(edition=edicao, teacher=docente).clean()

    assert exc.value.code == "program_mismatch"


@pytest.mark.django_db
def test_for_program_e_o_primeiro_filtro_da_busca_de_edicoes(edicao):
    outro = Program.objects.create(acronym="PPGX", name="Outro programa")
    ScholarshipEdition.objects.create(program=outro, year=2026, title="Bolsas 2026")

    assert list(ScholarshipEdition.objects.for_program(edicao.program)) == [edicao]
