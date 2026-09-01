"""Invariantes de vaga e banca.

Mesma divisão de `test_models.py`: primeiro os testes em memória (pks à
mão, nada salvo), depois os que dependem de constraint ou de query,
marcados com `django_db`.
"""

from datetime import date

import pytest
from django.db import IntegrityError, transaction

from apps.academic.models import Teacher
from apps.core.exceptions import DomainError
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Board,
    QuotaCategory,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    Vacancy,
)

from .test_models import ABERTURA, ENCERRAMENTO

PROGRAMA = Program(pk=1, acronym="PPGD")
PROJETO = CollectiveProject(pk=1, name="Projeto A")
LINHA = ResearchLine(pk=1, name="Linha A")


def _edital(kind: str = SelectionKind.REGULAR) -> SelectionProcess:
    return SelectionProcess(
        pk=1,
        program=PROGRAMA,
        kind=kind,
        year=2027,
        title="Edital 2027",
        submission_opens_at=ABERTURA,
        submission_closes_at=ENCERRAMENTO,
    )


def _professor(pk: int, program_id: int = 1, descredenciado: bool = False) -> Teacher:
    return Teacher(
        pk=pk,
        program_id=program_id,
        category=Teacher.Category.PERMANENT,
        accredited_since=date(2020, 1, 1),
        accredited_until=date(2025, 1, 1) if descredenciado else None,
    )


PRESIDENTE, MEMBRO_1, MEMBRO_2, SUPLENTE = (_professor(i) for i in range(1, 5))


def _banca(**kwargs) -> Board:
    campos = {
        "program": PROGRAMA,
        "process": _edital(),
        "level": SelectionLevel.MASTERS,
        "project": PROJETO,
        "president": PRESIDENTE,
        "member_1": MEMBRO_1,
        "member_2": MEMBRO_2,
        "alternate": SUPLENTE,
    }
    return Board(**{**campos, **kwargs})


# --- vaga: alvo e cota (memória) --------------------------------------------


@pytest.mark.parametrize(
    ("projeto", "linha"), [(None, None), (PROJETO, LINHA)], ids=["nenhum", "ambos"]
)
def test_vacancy_clean_exige_exatamente_um_alvo(projeto, linha):
    with pytest.raises(DomainError) as exc:
        Vacancy(
            program=PROGRAMA,
            process=_edital(),
            level=SelectionLevel.MASTERS,
            project=projeto,
            research_line=linha,
            quota_category=QuotaCategory.OPEN,
            quantity=1,
        ).clean()

    assert exc.value.code == "target_mismatch"


def test_vacancy_clean_recusa_alvo_incompativel_com_o_tipo():
    with pytest.raises(DomainError) as exc:
        Vacancy(
            program=PROGRAMA,
            process=_edital(SelectionKind.SUPPLEMENTARY),
            level=SelectionLevel.MASTERS,
            project=PROJETO,
            quota_category=QuotaCategory.DISABILITY,
            quantity=1,
        ).clean()

    assert exc.value.code == "target_mismatch"


def test_vacancy_clean_recusa_cota_que_o_tipo_nao_tem():
    with pytest.raises(DomainError) as exc:
        Vacancy(
            program=PROGRAMA,
            process=_edital(),
            level=SelectionLevel.MASTERS,
            project=PROJETO,
            quota_category=QuotaCategory.TRANS,
            quantity=1,
        ).clean()

    assert exc.value.code == "quota_category_not_allowed"


def test_vacancy_target_key_e_nivel_mais_alvo():
    vaga = Vacancy(level=SelectionLevel.DOCTORATE, research_line=LINHA)

    assert vaga.target_key() == (SelectionLevel.DOCTORATE, None, 1)


# --- banca: composição (memória) --------------------------------------------


@pytest.mark.parametrize(
    "repetido",
    [{"member_1": PRESIDENTE}, {"alternate": MEMBRO_2}],
    ids=["titular-duas-vezes", "suplente-e-titular"],
)
def test_board_clean_recusa_professor_repetido(repetido):
    with pytest.raises(DomainError) as exc:
        _banca(**repetido).clean()

    assert exc.value.code == "duplicate_board_member"


def test_board_clean_recusa_docente_de_outro_programa():
    with pytest.raises(DomainError) as exc:
        _banca(member_2=_professor(9, program_id=2)).clean()

    assert exc.value.code == "teacher_from_other_program"


def test_board_clean_recusa_docente_descredenciado():
    with pytest.raises(DomainError) as exc:
        _banca(alternate=_professor(9, descredenciado=True)).clean()

    assert exc.value.code == "teacher_not_accredited"


@pytest.mark.parametrize(
    ("kind", "projeto", "linha"),
    [
        (SelectionKind.REGULAR, None, LINHA),
        (SelectionKind.SUPPLEMENTARY, PROJETO, None),
        (SelectionKind.REGULAR, None, None),
        (SelectionKind.REGULAR, PROJETO, LINHA),
    ],
    ids=["regular-com-linha", "suplementar-com-projeto", "nenhum", "ambos"],
)
def test_board_clean_recusa_alvo_incompativel(kind, projeto, linha):
    with pytest.raises(DomainError) as exc:
        _banca(process=_edital(kind), project=projeto, research_line=linha).clean()

    assert exc.value.code == "target_mismatch"


def test_titular_members_e_is_member():
    banca = _banca()

    assert banca.titular_members() == [PRESIDENTE, MEMBRO_1, MEMBRO_2]
    assert banca.is_member(SUPLENTE)
    assert not banca.is_member(_professor(9))


def test_expected_signers_sem_impedido_sao_os_titulares():
    assert _banca().expected_signers() == [PRESIDENTE, MEMBRO_1, MEMBRO_2]


def test_expected_signers_com_impedido_poe_o_suplente_no_lugar():
    signatarios = _banca().expected_signers(replaced_member=MEMBRO_1)

    assert signatarios == [PRESIDENTE, SUPLENTE, MEMBRO_2]


@pytest.mark.parametrize(
    "impedido", [SUPLENTE, _professor(9)], ids=["suplente", "estranho"]
)
def test_expected_signers_so_substitui_titular(impedido):
    with pytest.raises(DomainError) as exc:
        _banca().expected_signers(replaced_member=impedido)

    assert exc.value.code == "not_a_titular_member"


# --- com banco: constraints e queries ----------------------------------------


def _vaga(edital, projeto, quantidade=2, **kwargs) -> Vacancy:
    campos = {
        "program": edital.program,
        "process": edital,
        "level": SelectionLevel.MASTERS,
        "project": projeto,
        "quota_category": QuotaCategory.OPEN,
        "quantity": quantidade,
    }
    return Vacancy(**{**campos, **kwargs})


@pytest.mark.django_db
def test_vacancy_aceita_quantidade_zero(edital_regular, projeto):
    vaga = _vaga(edital_regular, projeto, quantidade=0)
    vaga.clean()
    vaga.save()

    assert edital_regular.vacancies.get().quantity == 0


@pytest.mark.django_db
def test_vacancy_clean_rejeita_duplicata_com_linha_nula(edital_regular, projeto):
    primeira = _vaga(edital_regular, projeto)
    primeira.clean()
    primeira.save()

    with pytest.raises(DomainError) as exc:
        _vaga(edital_regular, projeto).clean()

    assert exc.value.code == "duplicate_vacancy"
    # Outro nível ou outra cota é outra linha da grade.
    _vaga(edital_regular, projeto, level=SelectionLevel.DOCTORATE).clean()
    _vaga(edital_regular, projeto, quota_category=QuotaCategory.RACIAL).clean()


@pytest.mark.django_db
def test_vacancy_unique_no_banco_trata_nulos_como_iguais(edital_regular, projeto):
    """`nulls_distinct=False`: a segunda vaga colide mesmo sem passar pelo
    `clean()` — a constraint é a última linha de defesa."""
    _vaga(edital_regular, projeto).save()

    with pytest.raises(IntegrityError), transaction.atomic():
        _vaga(edital_regular, projeto).save()


@pytest.mark.django_db
@pytest.mark.parametrize("com_projeto", [False, True], ids=["nenhum", "ambos"])
def test_vacancy_check_no_banco_exige_um_alvo(
    edital_regular, projeto, linha, com_projeto
):
    vaga = _vaga(edital_regular, projeto if com_projeto else None, research_line=linha)
    if not com_projeto:
        vaga.research_line = None

    with pytest.raises(IntegrityError), transaction.atomic():
        vaga.save()


@pytest.mark.django_db
def test_board_clean_rejeita_segunda_banca_para_o_mesmo_alvo(
    banca_regular, professores
):
    presidente, membro_1, membro_2, suplente = professores
    with pytest.raises(DomainError) as exc:
        Board(
            program=banca_regular.program,
            process=banca_regular.process,
            level=banca_regular.level,
            project=banca_regular.project,
            president=membro_1,
            member_1=presidente,
            member_2=membro_2,
            alternate=suplente,
        ).clean()

    assert exc.value.code == "duplicate_board"


@pytest.mark.django_db
def test_board_queryset_with_teacher_cobre_os_quatro_papeis(
    banca_regular, professores, program
):
    for professor in professores:
        assert list(Board.objects.with_teacher(professor)) == [banca_regular]
    assert list(Board.objects.for_process(banca_regular.process)) == [banca_regular]

    outro = Teacher.objects.create(
        program=program,
        person=Person.objects.create(
            program=program, full_name="Fora", primary_email="fora@example.com"
        ),
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 1, 1),
    )
    assert not Board.objects.with_teacher(outro).exists()
