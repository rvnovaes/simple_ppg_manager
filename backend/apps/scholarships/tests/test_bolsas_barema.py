"""Aritmética do item do barema.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco. Os números
são os do edital citados no plano — teste que confere aritmética de
dinheiro/nota com valor inventado não confere nada.

O caso que dá nome ao arquivo é o último: **o teto é do item, aplicado
sobre a soma dos lançamentos**. Com um lançamento só, aplicar o teto em
`raw_score` daria a mesma resposta; é com dois que a diferença aparece.
"""

from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.programs.models import Program
from apps.scholarships.models import (
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    ScholarshipEdition,
    ScholarshipLevel,
)


def _item(**kwargs) -> BaremeItem:
    campos = {
        "edition": ScholarshipEdition(pk=1),
        "level": ScholarshipLevel.MASTERS,
        "section": BaremeSection.FORMATION,
        "code": "1.3",
        "text": "Item do barema",
        "unit": BaremeUnit.SEMESTER,
        "points_per_unit": Decimal("0.50"),
        "cap": Decimal("3.00"),
    }
    return BaremeItem(**{**campos, **kwargs})


# --- raw_score: pontuação de UM lançamento, sem teto ------------------------


def test_um_semestre_a_meio_ponto_vale_meio_ponto():
    item = _item(unit=BaremeUnit.SEMESTER, points_per_unit=Decimal("0.50"))

    assert item.raw_score(Decimal("1")) == Decimal("0.50")


def test_doze_meses_a_zero_virgula_vinte_e_cinco_batem_exatamente_no_teto():
    """3,00 contra limite de 3,00: o teto não corta o que apenas alcança."""
    item = _item(
        unit=BaremeUnit.MONTH, points_per_unit=Decimal("0.25"), cap=Decimal("3.00")
    )

    bruto = item.raw_score(Decimal("12"))

    assert bruto == Decimal("3.00")
    assert item.apply_cap(bruto) == Decimal("3.00")


def test_tres_horas_a_um_centesimo_valem_tres_centesimos():
    item = _item(unit=BaremeUnit.HOUR, points_per_unit=Decimal("0.01"))

    assert item.raw_score(Decimal("3")) == Decimal("0.03")


def test_raw_score_nao_corta_pelo_teto():
    """`raw_score` ignora o `cap` de propósito: quem corta é `apply_cap`."""
    item = _item(points_per_unit=Decimal("0.50"), cap=Decimal("3.00"))

    assert item.raw_score(Decimal("20")) == Decimal("10.00")


def test_quantidade_fracionaria_pontua_proporcional():
    item = _item(unit=BaremeUnit.SEMESTER, points_per_unit=Decimal("0.50"))

    assert item.raw_score(Decimal("2.50")) == Decimal("1.250")


# --- apply_cap: o teto é do ITEM, sobre a SOMA dos lançamentos -------------


def test_teto_do_item_corta_a_soma_dos_lancamentos_e_nao_cada_um():
    """Dois lançamentos de 3,00 no item 1.8 somam 6,00 contra o limite de
    18,00: nenhum é cortado sozinho, e a soma passa inteira. É este caso
    que separa `raw_score` de `apply_cap`."""
    item = _item(code="1.8", points_per_unit=Decimal("3.00"), cap=Decimal("18.00"))

    lancamentos = [item.raw_score(Decimal("1")), item.raw_score(Decimal("1"))]

    assert lancamentos == [Decimal("3.00"), Decimal("3.00")]
    assert item.apply_cap(sum(lancamentos, Decimal("0.00"))) == Decimal("6.00")


def test_soma_acima_do_teto_e_cortada_no_teto():
    item = _item(code="1.8", points_per_unit=Decimal("3.00"), cap=Decimal("18.00"))

    total = sum((item.raw_score(Decimal("1")) for _ in range(10)), Decimal("0.00"))

    assert total == Decimal("30.00")
    assert item.apply_cap(total) == Decimal("18.00")


def test_apply_cap_nao_altera_soma_abaixo_do_teto():
    item = _item(cap=Decimal("3.00"))

    assert item.apply_cap(Decimal("0.50")) == Decimal("0.50")


# --- dinheiro/nota nunca é float -------------------------------------------


def test_pontuacao_e_sempre_decimal():
    """CLAUDE.md Seção 8: nota é `Decimal`, nunca `float` — 0,1 + 0,2 em
    binário não é 0,3, e o barema soma centésimos."""
    item = _item()

    assert isinstance(item.raw_score(Decimal("3")), Decimal)
    assert isinstance(item.apply_cap(Decimal("3.00")), Decimal)


# --- clean sem banco --------------------------------------------------------


def test_clean_sem_edicao_nao_consulta_o_banco():
    _item(edition=None, code="").clean()


# --- com banco --------------------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program, year=2026, title="Edital de Bolsas 2026"
    )


def _salvar_item(edicao: ScholarshipEdition, **kwargs) -> BaremeItem:
    item = _item(edition=edicao, **kwargs)
    item.clean()
    item.save()
    return item


@pytest.mark.django_db
def test_clean_rejeita_codigo_repetido_no_mesmo_nivel_da_edicao(edicao):
    """A duplicata vira `duplicate_bareme_item` (400), não `IntegrityError`."""
    _salvar_item(edicao, code="1.3")

    with pytest.raises(DomainError) as exc:
        _item(edition=edicao, code="1.3").clean()

    assert exc.value.code == "duplicate_bareme_item"
    assert exc.value.status_code == 400


@pytest.mark.django_db
def test_mesmo_codigo_no_outro_nivel_e_item_independente(edicao):
    """O barema é por (edição, nível): o 1.3 do mestrado e o do doutorado
    são itens diferentes, e podem valer pontos diferentes."""
    _salvar_item(edicao, code="1.3", level=ScholarshipLevel.MASTERS)

    doutorado = _salvar_item(
        edicao,
        code="1.3",
        level=ScholarshipLevel.DOCTORATE,
        points_per_unit=Decimal("1.00"),
    )

    assert BaremeItem.objects.for_edition(edicao).count() == 2
    assert doutorado.raw_score(Decimal("1")) == Decimal("1.00")


@pytest.mark.django_db
def test_clean_aceita_o_proprio_item_na_edicao(edicao):
    item = _salvar_item(edicao, code="1.3")

    item.text = "Descrição retificada"
    item.clean()


@pytest.mark.django_db
def test_for_program_chega_ao_programa_pela_edicao(edicao, program):
    _salvar_item(edicao, code="1.3")

    assert BaremeItem.objects.for_program(program).count() == 1


@pytest.mark.django_db
def test_for_level_separa_os_dois_baremas(edicao):
    _salvar_item(edicao, code="1.3", level=ScholarshipLevel.MASTERS)
    _salvar_item(edicao, code="1.3", level=ScholarshipLevel.DOCTORATE)

    itens = BaremeItem.objects.for_edition(edicao).for_level(ScholarshipLevel.MASTERS)

    assert [i.level for i in itens] == [ScholarshipLevel.MASTERS]
