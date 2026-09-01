"""Os papéis do edital de bolsas saem da data migration com as permissões certas.

Mesmo espírito de `selection/tests/test_papeis.py`: testar o **resultado** da
migration, e não o dicionário do módulo, é o que pega uma migration que deixou
de rodar ou um grupo mexido à mão no banco.
"""

import pytest
from django.contrib.auth.models import Group

# Papéis que participam do edital de bolsas. Candidato fica de fora de
# propósito: bolsa é do aluno matriculado, e o teste de "não recebe nada"
# abaixo prova que ele não vê o edital.
PAPEIS = ["Secretaria", "Coordenação", "Comissão de Bolsas", "Discente"]

MODELS = [
    "scholarshipedition",
    "committeemember",
    "baremeitem",
    "scholarshipapplication",
    "applicationdocument",
    "baremeentry",
    "itemreview",
    "scholarshipappeal",
]

# O que a secretaria monta enquanto a edição está em rascunho.
MONTAGEM_DO_EDITAL = ["scholarshipedition", "baremeitem", "committeemember"]

# As três permissões próprias desta story (migration 0007), somadas às duas
# que vieram com os models: nenhuma delas deriva do codename padrão.
PERMISSOES_PROPRIAS = [
    "publish_scholarshipedition",
    "set_fump_level",
    "override_band",
    "download_applicationdocument",
    "review_baremeentry",
]


def _codenames(papel: str) -> set[str]:
    """Só as permissões do app `scholarships` — o resto é de outras migrations."""
    return set(
        Group.objects.get(name=papel)
        .permissions.filter(content_type__app_label="scholarships")
        .values_list("codename", flat=True)
    )


@pytest.mark.django_db
@pytest.mark.parametrize("papel", PAPEIS)
def test_papel_existe(papel: str) -> None:
    assert Group.objects.filter(name=papel).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("codename", PERMISSOES_PROPRIAS)
def test_permissao_propria_existe_no_content_type_certo(codename: str) -> None:
    """O `criar` da migration deriva o model do codename, e estas cinco não
    seguem o padrão `verbo_model` — sem o mapa explícito elas nasceriam
    penduradas num content type fantasma ("fump_level")."""
    from django.contrib.auth.models import Permission

    permissoes = Permission.objects.filter(
        codename=codename, content_type__app_label="scholarships"
    )
    assert permissoes.count() == 1
    assert permissoes.get().content_type.model in MODELS


# --- Secretaria -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("model", MONTAGEM_DO_EDITAL)
def test_so_a_secretaria_monta_o_edital(model: str) -> None:
    codenames = _codenames("Secretaria")
    for verbo in ("view", "add", "change"):
        assert f"{verbo}_{model}" in codenames
    for papel in ("Coordenação", "Comissão de Bolsas", "Discente"):
        outros = _codenames(papel)
        assert f"add_{model}" not in outros
        assert f"change_{model}" not in outros


@pytest.mark.django_db
@pytest.mark.parametrize("codename", ["publish_scholarshipedition"])
def test_so_a_secretaria_publica(codename: str) -> None:
    """Publicar congela o ano: é ato da secretaria, não da comissão."""
    assert codename in _codenames("Secretaria")
    for papel in ("Coordenação", "Comissão de Bolsas", "Discente"):
        assert codename not in _codenames(papel)


@pytest.mark.django_db
@pytest.mark.parametrize("codename", ["set_fump_level", "override_band"])
def test_so_a_secretaria_escreve_na_inscricao_alheia(codename: str) -> None:
    """Os dois campos que ela lança **sem** ter `change` sobre a inscrição."""
    codenames = _codenames("Secretaria")
    assert codename in codenames
    assert "change_scholarshipapplication" not in codenames
    for papel in ("Coordenação", "Comissão de Bolsas", "Discente"):
        assert codename not in _codenames(papel)


@pytest.mark.django_db
def test_secretaria_nao_pontua_nem_julga_recurso() -> None:
    """Avaliar e julgar é da comissão; a secretaria opera o edital."""
    codenames = _codenames("Secretaria")
    for codename in (
        "review_baremeentry",
        "change_baremeentry",
        "add_baremeentry",
        "change_scholarshipappeal",
    ):
        assert codename not in codenames


@pytest.mark.django_db
def test_secretaria_recebe_exatamente_o_que_opera_o_edital() -> None:
    assert _codenames("Secretaria") == {
        *(
            f"{verbo}_{model}"
            for model in MONTAGEM_DO_EDITAL
            for verbo in ("view", "add", "change")
        ),
        "view_scholarshipapplication",
        "view_baremeentry",
        "download_applicationdocument",
        "publish_scholarshipedition",
        "set_fump_level",
        "override_band",
    }


# --- Comissão de Bolsas -----------------------------------------------


@pytest.mark.django_db
def test_so_a_comissao_avalia_lancamento() -> None:
    """`review_baremeentry` é separada de `change_baremeentry` de propósito:
    o candidato tem `change` sobre o próprio lançamento e não pode encostar
    na nota da comissão."""
    assert "review_baremeentry" in _codenames("Comissão de Bolsas")
    for papel in ("Secretaria", "Coordenação", "Discente"):
        assert "review_baremeentry" not in _codenames(papel)


@pytest.mark.django_db
def test_so_a_comissao_julga_o_recurso() -> None:
    assert "change_scholarshipappeal" in _codenames("Comissão de Bolsas")
    for papel in ("Secretaria", "Coordenação", "Discente"):
        assert "change_scholarshipappeal" not in _codenames(papel)


@pytest.mark.django_db
def test_comissao_le_o_que_precisa_para_avaliar_e_nada_mais() -> None:
    assert _codenames("Comissão de Bolsas") == {
        "view_scholarshipedition",
        "view_baremeitem",
        "view_scholarshipapplication",
        "view_baremeentry",
        "review_baremeentry",
        "download_applicationdocument",
        "change_scholarshipappeal",
    }


# --- Discente ---------------------------------------------------------


@pytest.mark.django_db
def test_discente_se_inscreve_lanca_e_recorre() -> None:
    """Anexar comprovante do questionário é `change` da própria inscrição —
    não há permissão de `add_applicationdocument`, exatamente como no
    requerimento de isolada."""
    assert _codenames("Discente") == {
        "view_scholarshipedition",
        "view_baremeitem",
        "add_scholarshipapplication",
        "view_scholarshipapplication",
        "change_scholarshipapplication",
        "add_baremeentry",
        "view_baremeentry",
        "change_baremeentry",
        "add_scholarshipappeal",
        "view_scholarshipappeal",
    }


@pytest.mark.django_db
def test_discente_nao_baixa_documento_alheio() -> None:
    """`download_applicationdocument` é leitura de dado pessoal de terceiro;
    o próprio anexo o candidato alcança pela inscrição dele."""
    assert "download_applicationdocument" not in _codenames("Discente")


# --- Coordenação ------------------------------------------------------


@pytest.mark.django_db
def test_coordenacao_so_le_o_edital_de_bolsas() -> None:
    assert _codenames("Coordenação") == {f"view_{model}" for model in MODELS}


# --- O que nenhum papel recebe ----------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("papel", ["Candidato", "Docente"])
def test_papel_de_fora_do_edital_nao_recebe_nada(papel: str) -> None:
    """Docente avalia processo seletivo; bolsa é da Comissão de Bolsas, que é
    grupo próprio — quem entra nela ganha o papel, não o cargo."""
    assert _codenames(papel) == set()


@pytest.mark.django_db
@pytest.mark.parametrize("papel", [*PAPEIS, "Candidato", "Docente"])
def test_nenhum_papel_apaga_dado_da_bolsa(papel: str) -> None:
    """Apagar é quebra-vidro de sysadmin no Admin, e sempre auditado."""
    assert not [c for c in _codenames(papel) if c.startswith("delete_")]


@pytest.mark.django_db
@pytest.mark.parametrize("papel", [*PAPEIS, "Candidato", "Docente"])
def test_nenhum_papel_de_dominio_abre_o_admin(papel: str) -> None:
    """`is_staff`/`is_superuser` é de quem opera a plataforma (CLAUDE.md
    Seção 5). Papel de domínio é Group, e Group não carrega flag de Admin —
    o que este teste trava é alguém dar a flag por meio das contas do grupo."""
    grupo = Group.objects.get(name=papel)
    assert not grupo.user_set.filter(is_staff=True).exists()
    assert not grupo.user_set.filter(is_superuser=True).exists()
