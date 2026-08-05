"""Invariantes da estrutura acadêmica do programa.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
Os pks são atribuídos à mão só para as FKs terem id — nada é salvo.
"""

import pytest

from apps.core.exceptions import DomainError
from apps.programs.models import CollectiveProject, Program, ResearchLine


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
