"""Invariantes da estrutura acadêmica do programa.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
Os pks são atribuídos à mão só para as FKs terem id — nada é salvo.
"""

from datetime import date

import pytest

from apps.core.exceptions import DomainError
from apps.programs.models import (
    AcademicTerm,
    CollectiveProject,
    Program,
    ResearchLine,
)


def _linha() -> ResearchLine:
    return ResearchLine(
        pk=1, program=Program(pk=1, acronym="PPGD"), name="Direito e Estado"
    )


def test_clean_aceita_projeto_no_mesmo_programa_da_linha():
    linha = _linha()
    projeto = CollectiveProject(
        program=linha.program, research_line=linha, name="Projeto A"
    )

    projeto.clean()


def test_clean_rejeita_projeto_em_programa_diferente_do_da_linha():
    linha = _linha()
    outro = Program(pk=2, acronym="PPGA")
    projeto = CollectiveProject(program=outro, research_line=linha, name="Projeto A")

    with pytest.raises(DomainError) as exc:
        projeto.clean()

    assert exc.value.code == "program_mismatch"
    assert exc.value.status_code == 400


def test_clean_sem_linha_nao_levanta():
    """Obrigatoriedade da linha é da borda e do NOT NULL, não deste invariante."""
    CollectiveProject(program=Program(pk=1, acronym="PPGD"), name="Projeto A").clean()


def _periodo(**kwargs) -> AcademicTerm:
    campos = {
        "year": 2026,
        "half": 1,
        "starts_on": date(2026, 3, 2),
        "ends_on": date(2026, 7, 18),
    }
    campos.update(kwargs)
    return AcademicTerm(**campos)


def test_str_do_periodo_usa_o_rotulo_canonico():
    assert str(_periodo()) == "2026/1"
    assert str(_periodo(half=2)) == "2026/2"


@pytest.mark.django_db
def test_clean_aceita_periodo_com_fim_posterior_ao_inicio():
    """Único teste com banco neste arquivo: passando pela validação de
    intervalo, o clean segue para a checagem de ano/semestre duplicado, que
    consulta a tabela. Os testes de rejeição acima levantam antes disso e
    continuam sem banco."""
    _periodo().clean()


def test_clean_rejeita_periodo_com_fim_anterior_ao_inicio():
    periodo = _periodo(ends_on=date(2026, 2, 1))

    with pytest.raises(DomainError) as exc:
        periodo.clean()

    assert exc.value.code == "invalid_term_range"


def test_clean_rejeita_periodo_de_um_dia_so():
    """Fim igual ao início não é intervalo — o critério é ends_on > starts_on."""
    with pytest.raises(DomainError):
        _periodo(ends_on=date(2026, 3, 2)).clean()
