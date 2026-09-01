"""Os papéis do processo seletivo saem da data migration com as permissões certas.

Mesmo espírito de `academic/tests/test_papeis.py`: testar o **resultado** da
migration, e não o dicionário do módulo, é o que pega uma migration que deixou
de rodar ou um grupo mexido à mão no banco.
"""

import pytest
from django.contrib.auth.models import Group

# Papéis que participam do processo seletivo. Discente e Candidato ficam de
# fora de propósito: aluno e candidato de isolada não têm nada a ver com o
# edital de seleção, e o teste de "não recebe nada" abaixo prova isso.
PAPEIS = ["Secretaria", "Coordenação", "Docente", "Comissão de Seleção"]

MODELS = [
    "selectionprocess",
    "selectionstage",
    "vacancy",
    "board",
    "application",
    "applicationdocument",
    "stagescore",
    "examinationrecord",
    "recordsignature",
    "vacancyreallocation",
    "convocation",
    "convocationemail",
]

# O que a secretaria monta enquanto o edital está em rascunho.
MONTAGEM_DO_EDITAL = ["selectionprocess", "selectionstage", "vacancy", "board"]


def _codenames(papel: str) -> set[str]:
    """Só as permissões do app `selection` — o resto é de outras migrations."""
    return set(
        Group.objects.get(name=papel)
        .permissions.filter(content_type__app_label="selection")
        .values_list("codename", flat=True)
    )


@pytest.mark.django_db
@pytest.mark.parametrize("papel", PAPEIS)
def test_papel_existe(papel: str) -> None:
    assert Group.objects.filter(name=papel).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("papel", ["Secretaria", "Coordenação", "Comissão de Seleção"])
@pytest.mark.parametrize("model", MODELS)
def test_papel_de_acompanhamento_le_todo_o_app(papel: str, model: str) -> None:
    assert f"view_{model}" in _codenames(papel)


@pytest.mark.django_db
@pytest.mark.parametrize("model", MONTAGEM_DO_EDITAL)
def test_so_a_secretaria_monta_o_edital(model: str) -> None:
    codenames = _codenames("Secretaria")
    for verbo in ("view", "add", "change"):
        assert f"{verbo}_{model}" in codenames
    for papel in ("Coordenação", "Docente", "Comissão de Seleção"):
        outros = _codenames(papel)
        assert f"add_{model}" not in outros
        assert f"change_{model}" not in outros


@pytest.mark.django_db
def test_so_a_secretaria_decide_a_inscricao() -> None:
    """Homologar e indeferir é `change_application`."""
    assert "change_application" in _codenames("Secretaria")
    for papel in ("Coordenação", "Docente", "Comissão de Seleção"):
        assert "change_application" not in _codenames(papel)


@pytest.mark.django_db
def test_so_a_secretaria_baixa_documento_da_inscricao() -> None:
    """Anexo é dado pessoal: nem a banca que avalia baixa identidade e diploma."""
    assert "download_applicationdocument" in _codenames("Secretaria")
    for papel in ("Coordenação", "Docente", "Comissão de Seleção"):
        assert "download_applicationdocument" not in _codenames(papel)


@pytest.mark.django_db
def test_so_a_secretaria_dispara_convocacao() -> None:
    assert "add_convocation" in _codenames("Secretaria")
    for papel in ("Coordenação", "Docente", "Comissão de Seleção"):
        assert "add_convocation" not in _codenames(papel)


@pytest.mark.django_db
def test_secretaria_nao_pontua_nem_assina() -> None:
    """Avaliar é da banca; a secretaria opera o edital, não julga candidato."""
    codenames = _codenames("Secretaria")
    for codename in (
        "add_stagescore",
        "change_stagescore",
        "add_examinationrecord",
        "change_examinationrecord",
        "sign_examinationrecord",
    ):
        assert codename not in codenames


@pytest.mark.django_db
@pytest.mark.parametrize("model", ["stagescore", "examinationrecord"])
def test_so_o_docente_lanca_nota_e_monta_a_ata(model: str) -> None:
    codenames = _codenames("Docente")
    for verbo in ("view", "add", "change"):
        assert f"{verbo}_{model}" in codenames
    for papel in ("Secretaria", "Coordenação", "Comissão de Seleção"):
        outros = _codenames(papel)
        assert f"add_{model}" not in outros
        assert f"change_{model}" not in outros


@pytest.mark.django_db
def test_so_o_docente_assina_a_ata() -> None:
    assert "sign_examinationrecord" in _codenames("Docente")
    for papel in ("Secretaria", "Coordenação", "Comissão de Seleção", "Discente"):
        assert "sign_examinationrecord" not in _codenames(papel)


@pytest.mark.django_db
def test_docente_le_o_que_precisa_para_avaliar_e_nada_mais() -> None:
    """A banca lê edital, banca, inscrição e ata — não a grade nem a convocação."""
    codenames = _codenames("Docente")
    for model in ("selectionprocess", "board", "application", "examinationrecord"):
        assert f"view_{model}" in codenames
    for model in ("vacancy", "applicationdocument", "convocation", "convocationemail"):
        assert f"view_{model}" not in codenames


@pytest.mark.django_db
def test_so_a_comissao_realoca_vaga() -> None:
    """Remanejar vaga entre alvos é decisão colegiada, não expediente."""
    assert "add_vacancyreallocation" in _codenames("Comissão de Seleção")
    for papel in ("Secretaria", "Coordenação", "Docente"):
        assert "add_vacancyreallocation" not in _codenames(papel)


@pytest.mark.django_db
def test_comissao_so_le_e_realoca() -> None:
    assert _codenames("Comissão de Seleção") == {
        *(f"view_{model}" for model in MODELS),
        "add_vacancyreallocation",
    }


@pytest.mark.django_db
def test_coordenacao_so_le_o_processo_seletivo() -> None:
    assert _codenames("Coordenação") == {f"view_{model}" for model in MODELS}


@pytest.mark.django_db
@pytest.mark.parametrize("papel", ["Discente", "Candidato"])
def test_papel_de_fora_do_edital_nao_recebe_nada(papel: str) -> None:
    assert _codenames(papel) == set()


@pytest.mark.django_db
@pytest.mark.parametrize("papel", [*PAPEIS, "Discente", "Candidato"])
def test_nenhum_papel_apaga_dado_da_selecao(papel: str) -> None:
    """Ata assinada não se apaga: retifica-se com versão nova (`supersedes`)."""
    assert not [c for c in _codenames(papel) if c.startswith("delete_")]


# --- Admin (ADR-006: quebra-vidro de sysadmin, sempre auditado) ---


def test_admin_registra_todos_os_models_do_app() -> None:
    """Model fora do Admin é dado que o sysadmin não consegue nem ler."""
    from django.apps import apps as django_apps
    from django.contrib import admin

    from apps.core.admin import AuditedModelAdmin

    for model in django_apps.get_app_config("selection").get_models():
        assert model in admin.site._registry, model.__name__
        # Sem AuditedModelAdmin a escrita pelo Admin sai sem AuditLog.
        assert isinstance(admin.site._registry[model], AuditedModelAdmin)
