"""A secretaria monta o barema da edição pela API, e clona o do ano anterior.

Nível (b) da pirâmide (Seção 9): a rota real, com sessão, CSRF e
permissão. O caso que dá nome ao arquivo é o **congelamento**: as três
escritas (POST, PATCH, DELETE) e a clonagem só valem com a edição em
rascunho, e a matriz roda contra os cinco estados seguintes — depois de
abertas as inscrições o candidato lança contra os pontos que leu.

Os invariantes do item (aritmética do teto, duplicata de código em
memória) ficam em `test_bolsas_barema.py`. Aqui só o que é da borda.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program
from apps.scholarships.models import (
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

pytestmark = pytest.mark.django_db

# Os cinco estados em que o barema já está congelado.
ESTADOS_CONGELADOS = tuple(
    estado
    for estado in ScholarshipEditionStatus.values
    if estado != ScholarshipEditionStatus.DRAFT
)


@pytest.fixture
def client_da_secretaria(client: Client, secretaria, program: Program) -> Client:
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client.force_login(secretaria)
    return client


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Outro programa", acronym="PPGX")


def criar_edicao(program: Program, **extra) -> ScholarshipEdition:
    campos = {"year": 2026, "title": "Edital de Bolsas 2026"}
    campos.update(extra)
    return ScholarshipEdition.objects.create(program=program, **campos)


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return criar_edicao(program)


def criar_item(edicao: ScholarshipEdition, **extra) -> BaremeItem:
    campos = {
        "level": ScholarshipLevel.MASTERS,
        "section": BaremeSection.FORMATION,
        "code": "1.1",
        "text": "Curso de especialização concluído",
        "unit": BaremeUnit.UNIT,
        "points_per_unit": Decimal("1.00"),
        "cap": Decimal("2.00"),
    }
    campos.update(extra)
    return BaremeItem.objects.create(edition=edicao, **campos)


def corpo(**extra) -> dict:
    dados = {
        "level": ScholarshipLevel.MASTERS.value,
        "section": BaremeSection.BIBLIOGRAPHIC.value,
        "code": "2.1",
        "text": "Artigo publicado em periódico Qualis A",
        "unit": BaremeUnit.UNIT.value,
        "points_per_unit": "3.00",
        "cap": "18.00",
    }
    dados.update(extra)
    return dados


def url(edicao: ScholarshipEdition) -> str:
    return f"/api/v1/scholarships/editions/{edicao.pk}/bareme/"


def _post(client: Client, endereco: str, dados: dict | None = None):
    if dados is None:
        return client.post(endereco)
    return client.post(endereco, data=dados, content_type="application/json")


def _patch(client: Client, endereco: str, dados: dict):
    return client.patch(endereco, data=dados, content_type="application/json")


# --- criação ---------------------------------------------------------------


def test_cria_o_item_do_barema_e_registra_auditoria(
    client_da_secretaria: Client, edicao: ScholarshipEdition, program: Program
):
    resposta = _post(client_da_secretaria, url(edicao), corpo())

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["code"] == "2.1"
    assert dados["level"] == ScholarshipLevel.MASTERS.value
    assert dados["level_label"] == "Mestrado"
    assert dados["section_label"] == "II - Produção Bibliográfica"
    assert dados["unit_label"] == "Unidade"
    assert Decimal(dados["points_per_unit"]) == Decimal("3.00")
    assert Decimal(dados["cap"]) == Decimal("18.00")
    item = BaremeItem.objects.get(pk=dados["id"])
    assert item.edition_id == edicao.pk
    registro = AuditLog.objects.get(event="scholarships.bareme.add")
    assert registro.program_id == program.pk
    assert registro.target_id == str(item.pk)
    assert registro.payload["code"] == "2.1"


def test_o_mesmo_codigo_no_outro_nivel_e_item_independente(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    criar_item(edicao, code="2.1", level=ScholarshipLevel.MASTERS)

    resposta = _post(
        client_da_secretaria,
        url(edicao),
        corpo(level=ScholarshipLevel.DOCTORATE.value),
    )

    assert resposta.status_code == 201, resposta.content


def test_codigo_repetido_no_mesmo_nivel_e_400_com_code_estavel(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    criar_item(edicao, code="2.1", level=ScholarshipLevel.MASTERS)

    resposta = _post(client_da_secretaria, url(edicao), corpo(code="2.1"))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_bareme_item"


def test_criar_item_sem_permissao_e_403(
    client_sem_permissao: Client, edicao: ScholarshipEdition
):
    resposta = _post(client_sem_permissao, url(edicao), corpo())

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"


def test_criar_item_sem_sessao_e_401(client: Client, edicao: ScholarshipEdition):
    assert _post(client, url(edicao), corpo()).status_code == 401


def test_escrita_sem_token_csrf_e_recusada(secretaria, program: Program):
    """Guarda o ADR-003/004: sessão sem CSRF não escreve."""
    edicao = criar_edicao(program)
    Person.objects.create(
        program=program,
        user=secretaria,
        full_name="Carla Dias",
        primary_email="carla@exemplo.br",
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(secretaria)

    assert _post(client, url(edicao), corpo()).status_code == 403
    assert not BaremeItem.objects.exists()


def test_criar_item_em_edicao_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = criar_edicao(outro_programa)

    assert _post(client_da_secretaria, url(alheia), corpo()).status_code == 404
    assert not BaremeItem.objects.exists()


# --- leitura ---------------------------------------------------------------


def test_lista_o_barema_da_edicao_na_ordem_do_edital(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    criar_item(edicao, code="1.2", level=ScholarshipLevel.MASTERS)
    criar_item(edicao, code="1.1", level=ScholarshipLevel.MASTERS)
    criar_item(edicao, code="1.1", level=ScholarshipLevel.DOCTORATE)

    resposta = client_da_secretaria.get(url(edicao))

    assert resposta.status_code == 200
    assert [(item["level"], item["code"]) for item in resposta.json()] == [
        ("doctorate", "1.1"),
        ("masters", "1.1"),
        ("masters", "1.2"),
    ]


def test_lista_filtra_por_nivel(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    mestrado = criar_item(edicao, code="1.1", level=ScholarshipLevel.MASTERS)
    criar_item(edicao, code="1.1", level=ScholarshipLevel.DOCTORATE)

    resposta = client_da_secretaria.get(f"{url(edicao)}?level=masters")

    assert [item["id"] for item in resposta.json()] == [mestrado.pk]


def test_lista_nao_mistura_o_barema_de_outra_edicao(
    client_da_secretaria: Client, program: Program, edicao: ScholarshipEdition
):
    outra = criar_edicao(program, year=2025)
    meu = criar_item(edicao)
    criar_item(outra)

    resposta = client_da_secretaria.get(url(edicao))

    assert [item["id"] for item in resposta.json()] == [meu.pk]


def test_ler_o_barema_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = criar_edicao(outro_programa)
    criar_item(alheia)

    assert client_da_secretaria.get(url(alheia)).status_code == 404


def test_a_leitura_continua_aberta_com_a_edicao_congelada(
    client_da_secretaria: Client, program: Program
):
    """O barema publicado é o que o candidato lê para lançar."""
    edicao = criar_edicao(program, status=ScholarshipEditionStatus.SUBMISSIONS_OPEN)
    criar_item(edicao)

    resposta = client_da_secretaria.get(url(edicao))

    assert resposta.status_code == 200
    assert len(resposta.json()) == 1


# --- retificação e remoção -------------------------------------------------


def test_patch_altera_so_os_campos_enviados(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    item = criar_item(edicao, text="Texto antigo", cap=Decimal("2.00"))

    resposta = _patch(client_da_secretaria, f"{url(edicao)}{item.pk}/", {"cap": "9.00"})

    assert resposta.status_code == 200, resposta.content
    item.refresh_from_db()
    assert item.cap == Decimal("9.00")
    assert item.text == "Texto antigo"
    assert AuditLog.objects.get(event="scholarships.bareme.update").payload[
        "fields"
    ] == ["cap"]


def test_patch_que_repete_codigo_do_nivel_e_400(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    criar_item(edicao, code="1.1")
    outro = criar_item(edicao, code="1.2")

    resposta = _patch(
        client_da_secretaria, f"{url(edicao)}{outro.pk}/", {"code": "1.1"}
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_bareme_item"


def test_patch_de_item_de_outra_edicao_e_404(
    client_da_secretaria: Client, program: Program, edicao: ScholarshipEdition
):
    outra = criar_edicao(program, year=2025)
    alheio = criar_item(outra)

    resposta = _patch(
        client_da_secretaria, f"{url(edicao)}{alheio.pk}/", {"cap": "9.00"}
    )

    assert resposta.status_code == 404


def test_delete_remove_o_item_e_audita_antes(
    client_da_secretaria: Client, edicao: ScholarshipEdition, program: Program
):
    item = criar_item(edicao)

    resposta = client_da_secretaria.delete(f"{url(edicao)}{item.pk}/")

    assert resposta.status_code == 204
    assert not BaremeItem.objects.filter(pk=item.pk).exists()
    registro = AuditLog.objects.get(event="scholarships.bareme.remove")
    assert registro.target_id == str(item.pk)
    assert registro.program_id == program.pk


def test_delete_de_item_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program
):
    alheia = criar_edicao(outro_programa)
    item = criar_item(alheia)

    resposta = client_da_secretaria.delete(f"{url(alheia)}{item.pk}/")

    assert resposta.status_code == 404
    assert BaremeItem.objects.filter(pk=item.pk).exists()


# --- congelamento ----------------------------------------------------------


@pytest.mark.parametrize("estado", ESTADOS_CONGELADOS)
def test_criar_item_fora_do_rascunho_e_409(
    client_da_secretaria: Client, program: Program, estado: str
):
    congelada = criar_edicao(program, status=estado)

    resposta = _post(client_da_secretaria, url(congelada), corpo())

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "bareme_frozen"
    assert not BaremeItem.objects.exists()


@pytest.mark.parametrize("estado", ESTADOS_CONGELADOS)
def test_alterar_item_fora_do_rascunho_e_409(
    client_da_secretaria: Client, program: Program, estado: str
):
    congelada = criar_edicao(program, status=estado)
    item = criar_item(congelada, points_per_unit=Decimal("1.00"))

    resposta = _patch(
        client_da_secretaria,
        f"{url(congelada)}{item.pk}/",
        {"points_per_unit": "9.00"},
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "bareme_frozen"
    item.refresh_from_db()
    assert item.points_per_unit == Decimal("1.00")


@pytest.mark.parametrize("estado", ESTADOS_CONGELADOS)
def test_remover_item_fora_do_rascunho_e_409(
    client_da_secretaria: Client, program: Program, estado: str
):
    congelada = criar_edicao(program, status=estado)
    item = criar_item(congelada)

    resposta = client_da_secretaria.delete(f"{url(congelada)}{item.pk}/")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "bareme_frozen"
    assert BaremeItem.objects.filter(pk=item.pk).exists()


# --- clonagem --------------------------------------------------------------


def test_clone_copia_os_dois_niveis_preservando_os_campos(
    client_da_secretaria: Client, program: Program, edicao: ScholarshipEdition
):
    anterior = criar_edicao(
        program, year=2025, status=ScholarshipEditionStatus.FINAL_RESULT
    )
    criar_item(
        anterior,
        level=ScholarshipLevel.MASTERS,
        code="1.1",
        unit=BaremeUnit.SEMESTER,
        points_per_unit=Decimal("0.50"),
        cap=Decimal("2.00"),
    )
    criar_item(
        anterior,
        level=ScholarshipLevel.DOCTORATE,
        code="2.3",
        unit=BaremeUnit.HOUR,
        points_per_unit=Decimal("0.01"),
        cap=Decimal("5.00"),
    )

    resposta = _post(
        client_da_secretaria,
        f"{url(edicao)}clone",
        {"source_edition_id": anterior.pk},
    )

    assert resposta.status_code == 200, resposta.content
    dados = resposta.json()
    assert dados["created"] == 2
    assert dados["source_edition_id"] == anterior.pk
    assert len(dados["items"]) == 2
    copiado = BaremeItem.objects.get(edition=edicao, code="1.1")
    assert copiado.level == ScholarshipLevel.MASTERS
    assert copiado.unit == BaremeUnit.SEMESTER
    assert copiado.points_per_unit == Decimal("0.50")
    assert copiado.cap == Decimal("2.00")
    doutorado = BaremeItem.objects.get(edition=edicao, code="2.3")
    assert doutorado.level == ScholarshipLevel.DOCTORATE
    # A origem continua intacta: clonar é copiar, não mover.
    assert anterior.bareme_items.count() == 2


def test_clone_grava_um_unico_auditlog(
    client_da_secretaria: Client, program: Program, edicao: ScholarshipEdition
):
    """O ato é "clonei o barema de 2025", não N criações soltas."""
    anterior = criar_edicao(program, year=2025)
    criar_item(anterior, code="1.1")
    criar_item(anterior, code="1.2")
    criar_item(anterior, code="1.3")

    _post(
        client_da_secretaria,
        f"{url(edicao)}clone",
        {"source_edition_id": anterior.pk},
    )

    registros = AuditLog.objects.filter(event="scholarships.bareme.clone")
    assert registros.count() == 1
    registro = registros.get()
    assert registro.payload == {"source_edition_id": anterior.pk, "created": 3}
    assert registro.program_id == program.pk
    assert registro.target_id == str(edicao.pk)
    assert not AuditLog.objects.filter(event="scholarships.bareme.add").exists()


@pytest.mark.parametrize("estado", ESTADOS_CONGELADOS)
def test_clone_para_destino_fora_do_rascunho_e_409(
    client_da_secretaria: Client, program: Program, estado: str
):
    anterior = criar_edicao(program, year=2025)
    criar_item(anterior)
    destino = criar_edicao(program, status=estado)

    resposta = _post(
        client_da_secretaria,
        f"{url(destino)}clone",
        {"source_edition_id": anterior.pk},
    )

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "bareme_frozen"
    assert not destino.bareme_items.exists()


def test_clone_aceita_origem_ja_publicada(
    client_da_secretaria: Client, program: Program, edicao: ScholarshipEdition
):
    """O caso normal: a origem é o edital do ano anterior, já encerrado."""
    anterior = criar_edicao(
        program, year=2025, status=ScholarshipEditionStatus.FINAL_RESULT
    )
    criar_item(anterior)

    resposta = _post(
        client_da_secretaria,
        f"{url(edicao)}clone",
        {"source_edition_id": anterior.pk},
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["created"] == 1


def test_clone_da_propria_edicao_e_400(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    criar_item(edicao)

    resposta = _post(
        client_da_secretaria,
        f"{url(edicao)}clone",
        {"source_edition_id": edicao.pk},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "same_edition"
    assert edicao.bareme_items.count() == 1


def test_clone_sobre_codigo_ja_existente_e_400_e_nao_escreve_nada(
    client_da_secretaria: Client, program: Program, edicao: ScholarshipEdition
):
    anterior = criar_edicao(program, year=2025)
    criar_item(anterior, code="1.1")
    criar_item(anterior, code="1.2")
    criar_item(edicao, code="1.2")

    resposta = _post(
        client_da_secretaria,
        f"{url(edicao)}clone",
        {"source_edition_id": anterior.pk},
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "duplicate_bareme_item"
    # Ou o barema inteiro entra, ou nada entra.
    assert [item.code for item in edicao.bareme_items.all()] == ["1.2"]


def test_clone_de_origem_de_outro_programa_e_404(
    client_da_secretaria: Client, outro_programa: Program, edicao: ScholarshipEdition
):
    alheia = criar_edicao(outro_programa)
    criar_item(alheia)

    resposta = _post(
        client_da_secretaria,
        f"{url(edicao)}clone",
        {"source_edition_id": alheia.pk},
    )

    assert resposta.status_code == 404
    assert not edicao.bareme_items.exists()


def test_clone_sem_permissao_e_403(
    client_sem_permissao: Client, program: Program, edicao: ScholarshipEdition
):
    anterior = criar_edicao(program, year=2025)

    resposta = _post(
        client_sem_permissao,
        f"{url(edicao)}clone",
        {"source_edition_id": anterior.pk},
    )

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "not_allowed"
