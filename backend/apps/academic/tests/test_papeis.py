"""Os papéis do domínio saem das data migrations com as permissões certas.

Testar o resultado da migration (e não o dicionário do módulo) é o que pega
uma migration que deixou de rodar ou um grupo removido à mão no banco.
"""

import pytest
from django.contrib.auth.models import Group

PAPEIS = ["Secretaria", "Coordenação", "Docente", "Discente"]

# Candidato não é papel dos cadastros nem do acerto: ele só existe no fluxo da
# isolada. Fica fora de PAPEIS para não contaminar os testes desses módulos, e
# entra aqui para os invariantes que valem para todo grupo.
TODOS_OS_PAPEIS = [*PAPEIS, "Candidato"]

CADASTROS = ["researchline", "collectiveproject", "academicterm", "teacher", "student"]


def _codenames(papel: str) -> set[str]:
    return set(
        Group.objects.get(name=papel).permissions.values_list("codename", flat=True)
    )


@pytest.mark.django_db
@pytest.mark.parametrize("papel", PAPEIS)
def test_papel_existe(papel: str) -> None:
    assert Group.objects.filter(name=papel).exists()


@pytest.mark.django_db
def test_secretaria_cria_e_altera_os_cadastros() -> None:
    codenames = _codenames("Secretaria")
    for model in CADASTROS:
        for verbo in ("view", "add", "change"):
            assert f"{verbo}_{model}" in codenames


@pytest.mark.django_db
def test_secretaria_define_senha_de_primeiro_acesso() -> None:
    assert "change_user" in _codenames("Secretaria")


@pytest.mark.django_db
def test_coordenacao_so_le_os_cadastros() -> None:
    codenames = _codenames("Coordenação")
    for model in CADASTROS:
        assert f"view_{model}" in codenames
        assert f"add_{model}" not in codenames
        assert f"change_{model}" not in codenames


@pytest.mark.django_db
@pytest.mark.parametrize("papel", ["Docente", "Discente"])
def test_papel_de_leitura_ve_a_estrutura_do_programa(papel: str) -> None:
    codenames = _codenames(papel)
    for model in ("researchline", "collectiveproject", "academicterm"):
        assert f"view_{model}" in codenames


@pytest.mark.django_db
def test_discente_nao_lista_professores_nem_alunos() -> None:
    codenames = _codenames("Discente")
    assert "view_teacher" not in codenames
    assert "view_student" not in codenames


@pytest.mark.django_db
@pytest.mark.parametrize("papel", PAPEIS)
def test_todo_papel_le_o_catalogo_de_disciplinas(papel: str) -> None:
    assert "view_discipline" in _codenames(papel)


@pytest.mark.django_db
def test_so_a_secretaria_mantem_o_catalogo() -> None:
    assert {"add_discipline", "change_discipline"} <= _codenames("Secretaria")
    for papel in ("Coordenação", "Docente", "Discente"):
        codenames = _codenames(papel)
        assert "add_discipline" not in codenames
        assert "change_discipline" not in codenames


@pytest.mark.django_db
@pytest.mark.parametrize("papel", PAPEIS)
def test_todo_papel_acompanha_o_acerto_de_matricula(papel: str) -> None:
    assert "view_enrollmentadjustmentrequest" in _codenames(papel)


@pytest.mark.django_db
def test_so_o_discente_abre_solicitacao_de_acerto() -> None:
    assert "add_enrollmentadjustmentrequest" in _codenames("Discente")
    for papel in ("Secretaria", "Coordenação", "Docente"):
        assert "add_enrollmentadjustmentrequest" not in _codenames(papel)


@pytest.mark.django_db
def test_so_o_docente_decide_a_solicitacao_de_acerto() -> None:
    """Decidir é `change_`: quem não orienta não muda o status da solicitação."""
    assert "change_enrollmentadjustmentrequest" in _codenames("Docente")
    for papel in ("Secretaria", "Coordenação", "Discente"):
        assert "change_enrollmentadjustmentrequest" not in _codenames(papel)


@pytest.mark.django_db
@pytest.mark.parametrize("papel", TODOS_OS_PAPEIS)
def test_nenhum_papel_apaga_dado(papel: str) -> None:
    assert not [c for c in _codenames(papel) if c.startswith("delete_")]


@pytest.mark.django_db
@pytest.mark.parametrize("papel", TODOS_OS_PAPEIS)
def test_papel_nao_abre_o_admin(papel: str) -> None:
    """is_staff/is_superuser são flags de User; papel de domínio não os concede.

    O que se verifica aqui é que nenhum grupo carrega permissão sobre o
    próprio model User além do change_user da Secretaria — nada de add/delete
    de conta, que é o caminho por onde alguém se daria acesso.
    """
    permitido = {"change_user"} if papel == "Secretaria" else set()
    sobre_user = {c for c in _codenames(papel) if c.endswith("_user")}
    assert sobre_user == permitido


# --- Matrícula em disciplina isolada (academic.0011_papeis_da_isolada) ---


@pytest.mark.django_db
def test_candidato_existe() -> None:
    assert Group.objects.filter(name="Candidato").exists()


@pytest.mark.django_db
def test_candidato_so_mexe_no_proprio_requerimento() -> None:
    """O escopo "só o meu" é do QuerySet; a permissão só abre o verbo."""
    assert _codenames("Candidato") == {
        "add_isolatedenrollmentrequest",
        "view_isolatedenrollmentrequest",
        "change_isolatedenrollmentrequest",
        "view_disciplineoffering",
    }


@pytest.mark.django_db
def test_candidato_nao_toca_em_dado_de_negocio() -> None:
    codenames = _codenames("Candidato")
    for model in CADASTROS:
        for verbo in ("view", "add", "change"):
            assert f"{verbo}_{model}" not in codenames


@pytest.mark.django_db
def test_so_a_secretaria_monta_o_edital() -> None:
    codenames = _codenames("Secretaria")
    for model in ("isolatedenrollmentcycle", "disciplineoffering"):
        for verbo in ("view", "add", "change"):
            assert f"{verbo}_{model}" in codenames
    for papel in ("Coordenação", "Docente", "Candidato"):
        outros = _codenames(papel)
        assert "add_isolatedenrollmentcycle" not in outros
        assert "change_isolatedenrollmentcycle" not in outros
        assert "add_disciplineoffering" not in outros
        assert "change_disciplineoffering" not in outros


@pytest.mark.django_db
@pytest.mark.parametrize("papel", ["Secretaria", "Coordenação", "Docente", "Candidato"])
def test_todo_papel_do_fluxo_acompanha_o_requerimento(papel: str) -> None:
    assert "view_isolatedenrollmentrequest" in _codenames(papel)


@pytest.mark.django_db
def test_so_secretaria_e_candidato_alteram_o_requerimento() -> None:
    """Candidato monta e envia; secretaria defere, indefere e cancela."""
    for papel in ("Secretaria", "Candidato"):
        assert "change_isolatedenrollmentrequest" in _codenames(papel)
    for papel in ("Coordenação", "Docente"):
        assert "change_isolatedenrollmentrequest" not in _codenames(papel)


@pytest.mark.django_db
def test_so_o_docente_classifica_a_oferta() -> None:
    assert "rank_disciplineoffering" in _codenames("Docente")
    for papel in ("Secretaria", "Coordenação", "Candidato", "Discente"):
        assert "rank_disciplineoffering" not in _codenames(papel)


@pytest.mark.django_db
def test_so_a_secretaria_baixa_documento_do_requerimento() -> None:
    """Anexo é dado pessoal: nem quem classifica, nem quem acompanha, baixa."""
    assert "download_requestdocument" in _codenames("Secretaria")
    for papel in ("Coordenação", "Docente", "Candidato", "Discente"):
        assert "download_requestdocument" not in _codenames(papel)


@pytest.mark.django_db
def test_coordenacao_so_le_o_fluxo_da_isolada() -> None:
    codenames = _codenames("Coordenação")
    for model in (
        "isolatedenrollmentrequest",
        "isolatedenrollmentcycle",
        "disciplineoffering",
    ):
        assert f"view_{model}" in codenames
        assert f"add_{model}" not in codenames
        assert f"change_{model}" not in codenames
