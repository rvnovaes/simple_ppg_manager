"""Os lançamentos do barema: CRUD do candidato, com o comprovante junto.

Nível (b) da pirâmide (Seção 9). Os invariantes do lançamento (item de
outra edição, quantidade zero, divergência sem observação) ficam em
`test_bolsas_barema.py`; aqui só a borda — e a borda tem duas coisas
próprias que o model não vê:

1. **`candidate_score` é do servidor.** O schema de entrada não tem o
   campo, então mandá-lo no corpo não muda nada. É o teste que prova que
   o candidato não escolhe a própria nota.
2. **O comprovante vem no mesmo POST.** Sem arquivo é 422 do Ninja, e não
   um lançamento vazio esperando anexo.
"""

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.academic.models import Student
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.people.models import Person
from apps.programs.models import Program
from apps.scholarships.models import (
    TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA,
    BaremeEntry,
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

from .test_bolsas_api_inscricao import ESTADOS_FECHADOS, SENHA, criar_discente, logar

pytestmark = pytest.mark.django_db


# --- cenário ---------------------------------------------------------------


@pytest.fixture
def aluno(program: Program) -> Student:
    return criar_discente(program=program, username="ana", nome="Ana Ribeiro")


@pytest.fixture
def colega(program: Program) -> Student:
    return criar_discente(program=program, username="bruno", nome="Bruno Lima")


@pytest.fixture
def client_do_aluno(client: Client, aluno: Student) -> Client:
    return logar(client, aluno)


def usuario_com_papel(program: Program, papel: str, username: str) -> User:
    user = User.objects.create_user(username=username, password=SENHA)
    user.groups.add(Group.objects.get(name=papel))
    Person.objects.create(
        program=program,
        user=user,
        full_name=username.capitalize(),
        primary_email=f"{username}@exemplo.br",
    )
    return user


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.SUBMISSIONS_OPEN,
    )


def criar_item(
    edicao: ScholarshipEdition,
    *,
    code: str = "1.8",
    level: str = ScholarshipLevel.MASTERS,
    points: str = "3.00",
    cap: str = "18.00",
) -> BaremeItem:
    return BaremeItem.objects.create(
        edition=edicao,
        level=level,
        section=BaremeSection.PROFESSIONAL,
        code=code,
        text="Estágio em docência",
        unit=BaremeUnit.SEMESTER,
        points_per_unit=Decimal(points),
        cap=Decimal(cap),
    )


@pytest.fixture
def item(edicao: ScholarshipEdition) -> BaremeItem:
    return criar_item(edicao)


@pytest.fixture
def inscricao(edicao: ScholarshipEdition, aluno: Student) -> ScholarshipApplication:
    candidatura = ScholarshipApplication.for_student(edition=edicao, student=aluno)
    candidatura.save()
    return candidatura


def comprovante(nome: str = "certificado.pdf", conteudo: bytes = b"%PDF-1.4 cert"):
    return SimpleUploadedFile(nome, conteudo, content_type="application/pdf")


def url_lista(inscricao: ScholarshipApplication) -> str:
    return f"/api/v1/scholarships/applications/{inscricao.pk}/entries/"


def url_item(inscricao: ScholarshipApplication, lancamento: BaremeEntry) -> str:
    return f"{url_lista(inscricao)}{lancamento.pk}/"


def lancar(
    client: Client,
    inscricao: ScholarshipApplication,
    item: BaremeItem,
    **extra: Any,
):
    dados: dict[str, Any] = {
        "item_id": item.pk,
        "description": "Estágio em docência 2026/1",
        "quantity": "2",
        "proof": comprovante(),
    }
    dados.update(extra)
    dados = {chave: valor for chave, valor in dados.items() if valor is not None}
    return client.post(url_lista(inscricao), data=dados)


@pytest.fixture
def lancamento(inscricao: ScholarshipApplication, item: BaremeItem) -> BaremeEntry:
    """Gravado pelo ORM, e não pela rota: fixture que faz `force_login`
    disputa a sessão do `client` com o papel que o teste quer usar."""
    return BaremeEntry.objects.create(
        application=inscricao,
        item=item,
        description="Estágio em docência 2026/1",
        quantity=Decimal("2"),
        candidate_score=item.raw_score(Decimal("2")),
        proof=comprovante(),
    )


# --- criação ---------------------------------------------------------------


def test_o_candidato_lanca_com_o_comprovante_no_mesmo_post(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    item: BaremeItem,
    program: Program,
):
    resposta = lancar(client_do_aluno, inscricao, item)

    assert resposta.status_code == 201, resposta.content
    dados = resposta.json()
    assert dados["item_code"] == "1.8"
    assert dados["item_section_label"] == item.get_section_display()
    assert dados["proof_filename"] == "certificado.pdf"
    assert dados["proof_size"] > 0
    assert dados["committee_score"] is None
    # Nem o caminho nem a URL do arquivo saem no contrato.
    assert "proof" not in dados and "url" not in dados
    registro = AuditLog.objects.get(event="scholarships.entry.create")
    assert registro.program_id == program.pk
    assert registro.payload["item_id"] == item.pk


def test_a_nota_do_candidato_e_calculada_pelo_servidor(
    client_do_aluno: Client, inscricao: ScholarshipApplication, item: BaremeItem
):
    """2 semestres × 3,00 = 6,00 — sem teto, que é do item e se aplica à
    soma dos lançamentos, não a um deles."""
    resposta = lancar(client_do_aluno, inscricao, item, quantity="2")

    assert Decimal(resposta.json()["candidate_score"]) == Decimal("6.00")


def test_mandar_a_propria_nota_no_corpo_nao_muda_o_que_e_gravado(
    client_do_aluno: Client, inscricao: ScholarshipApplication, item: BaremeItem
):
    """O campo não existe no schema de entrada, então é ignorado — e é
    esta a diferença entre "o candidato não escolhe a nota" ser código e
    ser combinado."""
    resposta = lancar(
        client_do_aluno,
        inscricao,
        item,
        candidate_score="99.00",
        committee_score="99.00",
        committee_note="dei nota a mim mesmo",
    )

    assert resposta.status_code == 201, resposta.content
    lancado = BaremeEntry.objects.get()
    assert lancado.candidate_score == Decimal("6.00")
    assert lancado.committee_score is None
    assert lancado.committee_note == ""


def test_lancamento_sem_comprovante_e_recusado(
    client_do_aluno: Client, inscricao: ScholarshipApplication, item: BaremeItem
):
    resposta = lancar(client_do_aluno, inscricao, item, proof=None)

    assert resposta.status_code == 422, resposta.content
    assert not BaremeEntry.objects.exists()


def test_comprovante_que_nao_e_pdf_e_recusado(
    client_do_aluno: Client, inscricao: ScholarshipApplication, item: BaremeItem
):
    """O comprovante do barema é mais estrito que o do questionário: aqui
    não entra imagem."""
    resposta = lancar(
        client_do_aluno, inscricao, item, proof=comprovante("foto.jpg", b"\xff\xd8")
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_document"
    assert not BaremeEntry.objects.exists()


def test_comprovante_acima_do_limite_e_recusado(
    client_do_aluno: Client, inscricao: ScholarshipApplication, item: BaremeItem
):
    grande = comprovante(
        "certificado.pdf", b"x" * (TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA + 1)
    )

    resposta = lancar(client_do_aluno, inscricao, item, proof=grande)

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_document"


def test_item_de_outro_nivel_e_recusado_pelo_dominio(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    edicao: ScholarshipEdition,
):
    """O item existe no programa, e é o `clean()` que recusa: o "1.3" do
    doutorado não é o "1.3" do mestrado, e sem esta checagem um candidato
    de mestrado pontuaria pela tabela do doutorado."""
    do_doutorado = criar_item(edicao, code="1.9", level=ScholarshipLevel.DOCTORATE)

    resposta = lancar(client_do_aluno, inscricao, do_doutorado)

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "bareme_item_mismatch"
    assert not BaremeEntry.objects.exists()


def test_item_de_outra_edicao_e_recusado_pelo_dominio(
    client_do_aluno: Client, inscricao: ScholarshipApplication, program: Program
):
    outra = ScholarshipEdition.objects.create(
        program=program, year=2025, title="Edital de Bolsas 2025"
    )

    resposta = lancar(client_do_aluno, inscricao, criar_item(outra))

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "bareme_item_mismatch"


def test_item_de_outro_programa_nao_existe(
    client_do_aluno: Client, inscricao: ScholarshipApplication
):
    """404, e não `bareme_item_mismatch`: responder com o código do
    domínio confirmaria que o id existe em algum lugar."""
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    de_fora = criar_item(
        ScholarshipEdition.objects.create(
            program=outro, year=2026, title="Edital alheio"
        )
    )

    resposta = lancar(client_do_aluno, inscricao, de_fora)

    assert resposta.status_code == 404, resposta.content


def test_quantidade_zero_e_recusada(
    client_do_aluno: Client, inscricao: ScholarshipApplication, item: BaremeItem
):
    resposta = lancar(client_do_aluno, inscricao, item, quantity="0")

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_quantity"


def test_dois_lancamentos_no_mesmo_item_convivem(
    client_do_aluno: Client, inscricao: ScholarshipApplication, item: BaremeItem
):
    """Dois semestres de docência são duas linhas, e não duplicata — é a
    soma delas que enfrenta o teto do item."""
    lancar(client_do_aluno, inscricao, item, description="2026/1")
    resposta = lancar(client_do_aluno, inscricao, item, description="2026/2")

    assert resposta.status_code == 201, resposta.content
    assert BaremeEntry.objects.count() == 2


def test_o_colega_nao_lanca_na_inscricao_alheia(
    client: Client, inscricao: ScholarshipApplication, item: BaremeItem, colega: Student
):
    resposta = lancar(logar(client, colega), inscricao, item)

    assert resposta.status_code == 403, resposta.content
    assert resposta.json()["code"] == "not_application_owner"
    assert not BaremeEntry.objects.exists()


def test_a_secretaria_nao_lanca_no_lugar_do_candidato(
    client: Client,
    program: Program,
    inscricao: ScholarshipApplication,
    item: BaremeItem,
):
    """Não tem `add_baremeentry`: montar o barema do candidato é do
    candidato."""
    client.force_login(usuario_com_papel(program, "Secretaria", "carla"))

    assert lancar(client, inscricao, item).status_code == 403


@pytest.mark.parametrize("estado", ESTADOS_FECHADOS)
def test_fora_da_janela_o_lancamento_e_recusado(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    item: BaremeItem,
    edicao: ScholarshipEdition,
    estado: str,
):
    edicao.status = estado
    edicao.save(update_fields=["status"])

    resposta = lancar(client_do_aluno, inscricao, item)

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "submissions_closed"


# --- leitura ---------------------------------------------------------------


def test_o_candidato_lista_os_proprios_lancamentos(
    client_do_aluno: Client, inscricao: ScholarshipApplication, lancamento: BaremeEntry
):
    resposta = client_do_aluno.get(url_lista(inscricao))

    assert resposta.status_code == 200, resposta.content
    dados = resposta.json()
    assert [linha["id"] for linha in dados] == [lancamento.pk]
    assert dados[0]["item_code"] == "1.8"


def test_a_comissao_lista_para_analisar(
    client: Client,
    program: Program,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
):
    client.force_login(usuario_com_papel(program, "Comissão de Bolsas", "elisa"))

    resposta = client.get(url_lista(inscricao))

    assert resposta.status_code == 200, resposta.content
    assert len(resposta.json()) == 1


def test_o_colega_nao_le_o_barema_alheio(
    client: Client,
    colega: Student,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
):
    """`view_baremeentry` sozinha não abre a inscrição do vizinho: o
    papel Discente também a tem."""
    resposta = logar(client, colega).get(url_lista(inscricao))

    assert resposta.status_code == 403, resposta.content


def test_a_coordenacao_nao_le_o_barema_do_candidato(
    client: Client,
    program: Program,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
):
    """Mesma linha do download do comprovante do questionário: acompanhar
    o edital não é ler a papelada de cada candidato."""
    client.force_login(usuario_com_papel(program, "Coordenação", "denise"))

    assert client.get(url_lista(inscricao)).status_code == 403


def test_inscricao_de_outro_programa_nao_existe(
    client: Client, program: Program, inscricao: ScholarshipApplication
):
    client.force_login(usuario_com_papel(program, "Secretaria", "carla"))
    outro = Program.objects.create(name="Outro programa", acronym="PPGX")
    inscricao.edition.program = outro
    inscricao.edition.save(update_fields=["program"])
    inscricao.program = outro
    inscricao.save(update_fields=["program"])

    assert client.get(url_lista(inscricao)).status_code == 404


# --- retificação -----------------------------------------------------------


def test_mudar_a_quantidade_recalcula_a_nota(
    client_do_aluno: Client, inscricao: ScholarshipApplication, lancamento: BaremeEntry
):
    resposta = client_do_aluno.patch(
        url_item(inscricao, lancamento),
        data={"quantity": "3"},
        content_type="application/json",
    )

    assert resposta.status_code == 200, resposta.content
    assert Decimal(resposta.json()["candidate_score"]) == Decimal("9.00")
    registro = AuditLog.objects.get(event="scholarships.entry.update")
    assert "candidate_score" in registro.payload["fields"]


def test_mudar_so_a_descricao_nao_mexe_na_nota(
    client_do_aluno: Client, inscricao: ScholarshipApplication, lancamento: BaremeEntry
):
    resposta = client_do_aluno.patch(
        url_item(inscricao, lancamento),
        data={"description": "Estágio em docência 2026/2"},
        content_type="application/json",
    )

    assert resposta.status_code == 200, resposta.content
    lancamento.refresh_from_db()
    assert lancamento.description == "Estágio em docência 2026/2"
    assert lancamento.candidate_score == Decimal("6.00")


def test_trocar_para_item_de_outro_nivel_e_recusado(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
    edicao: ScholarshipEdition,
):
    do_doutorado = criar_item(edicao, code="1.9", level=ScholarshipLevel.DOCTORATE)

    resposta = client_do_aluno.patch(
        url_item(inscricao, lancamento),
        data={"item_id": do_doutorado.pk},
        content_type="application/json",
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "bareme_item_mismatch"
    lancamento.refresh_from_db()
    assert lancamento.item_id != do_doutorado.pk


def test_o_colega_nao_retifica_o_lancamento_alheio(
    client: Client,
    colega: Student,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
):
    resposta = logar(client, colega).patch(
        url_item(inscricao, lancamento),
        data={"quantity": "9"},
        content_type="application/json",
    )

    assert resposta.status_code == 403, resposta.content
    assert resposta.json()["code"] == "not_application_owner"


def test_fora_da_janela_a_retificacao_e_recusada(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
    edicao: ScholarshipEdition,
):
    edicao.status = ScholarshipEditionStatus.UNDER_REVIEW
    edicao.save(update_fields=["status"])

    resposta = client_do_aluno.patch(
        url_item(inscricao, lancamento),
        data={"quantity": "3"},
        content_type="application/json",
    )

    assert resposta.status_code == 409, resposta.content
    assert resposta.json()["code"] == "submissions_closed"


# --- troca do comprovante --------------------------------------------------


def url_proof(inscricao: ScholarshipApplication, lancamento: BaremeEntry) -> str:
    return f"{url_item(inscricao, lancamento)}proof"


def test_trocar_o_comprovante_apaga_o_antigo(
    client_do_aluno: Client, inscricao: ScholarshipApplication, lancamento: BaremeEntry
):
    """Nomes diferentes de propósito: com o mesmo nome o caminho seria
    liberado e reocupado, e o teste passaria sem provar nada."""
    antigo = lancamento.proof.name

    resposta = client_do_aluno.post(
        url_proof(inscricao, lancamento),
        data={"proof": comprovante("corrigido.pdf")},
    )

    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["proof_filename"] == "corrigido.pdf"
    assert not default_storage.exists(antigo or "")
    assert AuditLog.objects.filter(event="scholarships.entry.proof_replace").exists()


def test_a_troca_do_comprovante_recusa_arquivo_invalido(
    client_do_aluno: Client, inscricao: ScholarshipApplication, lancamento: BaremeEntry
):
    resposta = client_do_aluno.post(
        url_proof(inscricao, lancamento),
        data={"proof": comprovante("foto.jpg", b"\xff\xd8")},
    )

    assert resposta.status_code == 400, resposta.content
    assert resposta.json()["code"] == "invalid_document"


def test_fora_da_janela_o_comprovante_nao_e_trocado(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
    edicao: ScholarshipEdition,
):
    edicao.status = ScholarshipEditionStatus.UNDER_REVIEW
    edicao.save(update_fields=["status"])

    resposta = client_do_aluno.post(
        url_proof(inscricao, lancamento), data={"proof": comprovante("outro.pdf")}
    )

    assert resposta.status_code == 409, resposta.content


# --- exclusão --------------------------------------------------------------


def test_o_candidato_apaga_o_proprio_lancamento(
    client_do_aluno: Client, inscricao: ScholarshipApplication, lancamento: BaremeEntry
):
    caminho = lancamento.proof.name

    resposta = client_do_aluno.delete(url_item(inscricao, lancamento))

    assert resposta.status_code == 204, resposta.content
    assert not BaremeEntry.objects.exists()
    assert not default_storage.exists(caminho or "")
    registro = AuditLog.objects.get(event="scholarships.entry.remove")
    assert registro.payload["application_id"] == inscricao.pk


def test_fora_da_janela_o_lancamento_nao_e_apagado(
    client_do_aluno: Client,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
    edicao: ScholarshipEdition,
):
    edicao.status = ScholarshipEditionStatus.UNDER_REVIEW
    edicao.save(update_fields=["status"])

    resposta = client_do_aluno.delete(url_item(inscricao, lancamento))

    assert resposta.status_code == 409, resposta.content
    assert BaremeEntry.objects.exists()


def test_o_colega_nao_apaga_o_lancamento_alheio(
    client: Client,
    colega: Student,
    inscricao: ScholarshipApplication,
    lancamento: BaremeEntry,
):
    resposta = logar(client, colega).delete(url_item(inscricao, lancamento))

    assert resposta.status_code == 403, resposta.content
    assert BaremeEntry.objects.exists()


# --- download do comprovante -----------------------------------------------


def conteudo(resposta: Any) -> bytes:
    """`streaming_content` não está no tipo do cliente de teste."""
    return b"".join(resposta.streaming_content)


def url_download(lancamento: BaremeEntry) -> str:
    return f"/api/v1/scholarships/entries/{lancamento.pk}/proof/download"


def test_o_candidato_baixa_o_proprio_comprovante(
    client_do_aluno: Client, lancamento: BaremeEntry
):
    resposta = client_do_aluno.get(url_download(lancamento))

    assert resposta.status_code == 200, resposta.content
    assert conteudo(resposta) == b"%PDF-1.4 cert"


def test_a_comissao_baixa_o_comprovante_e_o_acesso_fica_registrado(
    client: Client, program: Program, lancamento: BaremeEntry
):
    """É o comprovante que a comissão lê para decidir a nota."""
    client.force_login(usuario_com_papel(program, "Comissão de Bolsas", "elisa"))

    resposta = client.get(url_download(lancamento))

    assert resposta.status_code == 200, resposta.content
    registro = AuditLog.objects.get(event="scholarships.entry.proof_download")
    assert registro.target_id == str(lancamento.pk)


def test_a_coordenacao_nao_baixa_o_comprovante(
    client: Client, program: Program, lancamento: BaremeEntry
):
    client.force_login(usuario_com_papel(program, "Coordenação", "denise"))

    assert client.get(url_download(lancamento)).status_code == 403
