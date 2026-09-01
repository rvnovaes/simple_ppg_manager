"""As três rotas públicas do processo seletivo.

Como o auto-registro da isolada (`test_isolada_signup.py`), a suíte cobre
menos o caminho feliz e mais o que substitui a sessão: janela do edital,
limite por IP, CSRF, tenant tirado do edital e resposta sem dado pessoal.

As datas do edital saem de `timezone.now()`, e não das constantes fixas do
conftest: quem decide se a inscrição está aberta é o relógio do servidor no
momento da chamada — a rota é pública e não recebe `at` de ninguém.
"""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Application,
    ApplicationDocument,
    ApplicationDocumentKind,
    ApplicationStatus,
    QuotaCategory,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    Vacancy,
)

pytestmark = pytest.mark.django_db

EDITAIS = "/api/v1/selection/public/processes"
INSCRICAO = "/api/v1/selection/public/applications"

# CPFs bem formados (mod-11 conferindo) — o suficiente para as cinco
# inscrições que o teste de limite por IP precisa fazer.
CPFS = [
    "52998224725",
    "11144477735",
    "12345678909",
    "10000000108",
    "10000013854",
    "10000027561",
]


def _anexo(nome: str = "rg.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        nome, b"%PDF-1.4 conteudo", content_type="application/pdf"
    )


def _formulario(edital: SelectionProcess, projeto: CollectiveProject, **extra):
    """Inscrição completa de mestrado × projeto, ampla concorrência.

    Os quatro anexos comuns mais o resumo expandido — que é o quinto
    documento exigido pelo edital regular.
    """
    dados = {
        "process_id": edital.pk,
        "full_name": "Marina Alves",
        "email": "marina@example.com",
        "cpf": CPFS[0],
        "birth_date": "1995-05-20",
        "phone_number": "31999990000",
        "level": SelectionLevel.MASTERS.value,
        "project_id": projeto.pk,
        "quota_category": QuotaCategory.OPEN.value,
        "identity": _anexo(),
        "diploma": _anexo("diploma.pdf"),
        "lattes": _anexo("lattes.pdf"),
        "payment_receipt": _anexo("gru.pdf"),
        "expanded_abstract": _anexo("resumo.pdf"),
    }
    dados.update(extra)
    return {campo: valor for campo, valor in dados.items() if valor is not None}


def _abrir(edital: SelectionProcess) -> SelectionProcess:
    """Põe a janela de inscrição em torno de agora."""
    agora = timezone.now()
    SelectionProcess.objects.filter(pk=edital.pk).update(
        submission_opens_at=agora - timedelta(days=1),
        submission_closes_at=agora + timedelta(days=1),
    )
    edital.refresh_from_db()
    return edital


@pytest.fixture
def edital_aberto(
    program: Program, edital_regular: SelectionProcess, projeto: CollectiveProject
) -> SelectionProcess:
    """Edital regular publicado, com a janela aberta e duas vagas de
    mestrado × projeto na ampla concorrência."""
    Vacancy.objects.create(
        program=program,
        process=edital_regular,
        level=SelectionLevel.MASTERS,
        project=projeto,
        quota_category=QuotaCategory.OPEN,
        quantity=2,
    )
    return _abrir(edital_regular)


# ---------------------------------------------------------------------------
# GET public/processes
# ---------------------------------------------------------------------------


def test_lista_publica_traz_edital_aberto_com_etapas_e_grade(
    edital_aberto, projeto, client
):
    resposta = client.get(EDITAIS)

    assert resposta.status_code == 200, resposta.content
    (edital,) = resposta.json()
    assert edital["id"] == edital_aberto.pk
    assert edital["title"] == "Edital Regular 2027"
    assert edital["kind_label"] == "Regular"
    assert edital["program_acronym"] == "PPGD"
    assert [etapa["name"] for etapa in edital["stages"]] == [
        "Resumo expandido",
        "Prova oral",
        "Entrevista",
    ]
    assert edital["levels"] == [{"value": "masters", "label": "Mestrado"}]
    assert edital["quota_categories"] == [
        {"value": "open", "label": "Ampla concorrência"}
    ]
    assert edital["targets"] == [
        {
            "project_id": projeto.pk,
            "research_line_id": None,
            "label": str(projeto),
        }
    ]
    assert edital["vacancies"][0]["quantity"] == 2


def test_lista_publica_nao_expoe_dado_pessoal(edital_aberto, inscricao, client):
    """A página é o cartaz do edital, não a lista de inscritos."""
    corpo = client.get(EDITAIS).content.decode()

    assert "Ana Lima" not in corpo
    assert inscricao.cpf not in corpo
    assert inscricao.protocol not in corpo


def test_vaga_zerada_nao_vira_opcao_do_formulario(
    program, edital_aberto, linha, projeto, client
):
    """Linha zerada existe na grade (a realocação conta com isso), mas não
    abre inscrição — então não aparece como escolha."""
    Vacancy.objects.create(
        program=program,
        process=edital_aberto,
        level=SelectionLevel.DOCTORATE,
        project=projeto,
        quota_category=QuotaCategory.RACIAL,
        quantity=0,
    )

    (edital,) = client.get(EDITAIS).json()

    assert [nivel["value"] for nivel in edital["levels"]] == ["masters"]
    assert [cota["value"] for cota in edital["quota_categories"]] == ["open"]


def test_edital_em_rascunho_ou_encerrado_nao_aparece(
    program, edital_regular, edital_suplementar, projeto, linha, client
):
    """Só o publicado e dentro da janela: rascunho é documento que o
    programa ainda não assinou, e encerrado não recebe inscrição."""
    _abrir(edital_regular)
    SelectionProcess.objects.filter(pk=edital_regular.pk).update(status="draft")
    _abrir(edital_suplementar)
    SelectionProcess.objects.filter(pk=edital_suplementar.pk).update(
        submission_closes_at=timezone.now() - timedelta(hours=1)
    )

    assert client.get(EDITAIS).json() == []


def test_edital_de_outro_programa_aparece_com_a_sigla_dele(
    edital_aberto, projeto, client
):
    """A listagem pública NÃO é escopada por tenant — não há sessão de onde
    tirar o programa, e edital publicado é documento público. O que separa
    os dois na tela é a sigla."""
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    outra_linha = ResearchLine.objects.create(program=outro, name="Macroeconomia")
    alheio = SelectionProcess(
        program=outro,
        kind=SelectionKind.SUPPLEMENTARY,
        year=2027,
        title="Edital Suplementar PPGE 2027",
        submission_opens_at=timezone.now() - timedelta(days=1),
        submission_closes_at=timezone.now() + timedelta(days=1),
    )
    alheio.publish(at=timezone.now())
    alheio.save()
    Vacancy.objects.create(
        program=outro,
        process=alheio,
        level=SelectionLevel.DOCTORATE,
        research_line=outra_linha,
        quota_category=QuotaCategory.INDIGENOUS,
        quantity=1,
    )

    siglas = {
        edital["program_acronym"]: edital["title"]
        for edital in client.get(EDITAIS).json()
    }

    assert siglas == {
        "PPGD": "Edital Regular 2027",
        "PPGE": "Edital Suplementar PPGE 2027",
    }


def test_limite_de_leitura_por_ip_dispara(edital_aberto, client):
    for _ in range(60):
        assert client.get(EDITAIS).status_code == 200

    excedente = client.get(EDITAIS)

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# POST public/applications
# ---------------------------------------------------------------------------


def test_inscricao_cria_candidatura_com_anexos_e_protocolo(
    edital_aberto, projeto, client
):
    resposta = client.post(INSCRICAO, data=_formulario(edital_aberto, projeto))

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.json()
    assert corpo["protocol"].startswith("PS2027R-")
    assert corpo["submitted_at"]
    # O comprovante não devolve mais nada: o resto o candidato já digitou.
    assert set(corpo) == {"protocol", "submitted_at"}

    inscricao = Application.objects.get(protocol=corpo["protocol"])
    assert inscricao.program_id == edital_aberto.program_id
    assert inscricao.status == ApplicationStatus.SUBMITTED
    assert inscricao.cpf == CPFS[0]
    assert sorted(inscricao.documents.values_list("kind", flat=True)) == sorted(
        [
            ApplicationDocumentKind.IDENTITY,
            ApplicationDocumentKind.DIPLOMA,
            ApplicationDocumentKind.LATTES,
            ApplicationDocumentKind.PAYMENT_RECEIPT,
            ApplicationDocumentKind.EXPANDED_ABSTRACT,
        ]
    )


def test_auditoria_registra_a_inscricao_sem_cpf(edital_aberto, projeto, client):
    resposta = client.post(INSCRICAO, data=_formulario(edital_aberto, projeto))

    registro = AuditLog.objects.get(event="selection.application.submit")
    assert registro.program_id == edital_aberto.program_id
    # Sem sessão não há ator — é justamente o que o protocolo substitui.
    assert registro.actor is None
    assert registro.payload["protocol"] == resposta.json()["protocol"]
    serializado = str(registro.payload)
    assert CPFS[0] not in serializado
    assert "Marina" not in serializado
    assert "marina@example.com" not in serializado


def test_cpf_com_mascara_e_normalizado(edital_aberto, projeto, client):
    resposta = client.post(
        INSCRICAO, data=_formulario(edital_aberto, projeto, cpf="529.982.247-25")
    )

    assert resposta.status_code == 201, resposta.content
    assert Application.objects.get().cpf == "52998224725"


def test_cpf_invalido_e_recusado(edital_aberto, projeto, client):
    resposta = client.post(
        INSCRICAO, data=_formulario(edital_aberto, projeto, cpf="11111111111")
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_cpf"
    assert not Application.objects.exists()


def test_cpf_duplicado_no_mesmo_edital_e_recusado(edital_aberto, projeto, client):
    assert (
        client.post(INSCRICAO, data=_formulario(edital_aberto, projeto)).status_code
        == 201
    )

    repetida = client.post(
        INSCRICAO,
        data=_formulario(edital_aberto, projeto, email="outra@example.com"),
    )

    assert repetida.status_code == 400
    assert repetida.json()["code"] == "duplicate_application"
    assert Application.objects.count() == 1


def test_fora_da_janela_de_inscricao_e_recusado(
    program, edital_regular, projeto, client
):
    Vacancy.objects.create(
        program=program,
        process=edital_regular,
        level=SelectionLevel.MASTERS,
        project=projeto,
        quota_category=QuotaCategory.OPEN,
        quantity=1,
    )
    SelectionProcess.objects.filter(pk=edital_regular.pk).update(
        submission_opens_at=timezone.now() - timedelta(days=30),
        submission_closes_at=timezone.now() - timedelta(days=20),
    )
    edital_regular.refresh_from_db()

    resposta = client.post(INSCRICAO, data=_formulario(edital_regular, projeto))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "submission_window_closed"
    assert not Application.objects.exists()


def test_edital_em_rascunho_e_recusado_como_janela_fechada(
    program, edital_regular, projeto, client
):
    """Rascunho, encerrado e inexistente dão a mesma resposta: distinguir
    transformaria a rota num inventário dos editais não publicados."""
    _abrir(edital_regular)
    SelectionProcess.objects.filter(pk=edital_regular.pk).update(status="draft")

    resposta = client.post(INSCRICAO, data=_formulario(edital_regular, projeto))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "submission_window_closed"


def test_edital_inexistente_e_recusado_como_janela_fechada(
    edital_aberto, projeto, client
):
    resposta = client.post(
        INSCRICAO, data=_formulario(edital_aberto, projeto, process_id=999999)
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "submission_window_closed"


def test_alvo_de_outro_programa_e_404(edital_aberto, client):
    """O alvo é escopado no programa DO EDITAL: projeto alheio não existe
    aqui, e responder 400 confirmaria que o id existe em algum lugar."""
    outro = Program.objects.create(name="Pós em Economia", acronym="PPGE")
    outra_linha = ResearchLine.objects.create(program=outro, name="Macroeconomia")
    projeto_alheio = CollectiveProject.objects.create(
        program=outro, research_line=outra_linha, name="Inflação"
    )

    resposta = client.post(
        INSCRICAO,
        data=_formulario(edital_aberto, projeto_alheio, project_id=projeto_alheio.pk),
    )

    assert resposta.status_code == 404
    assert not Application.objects.exists()


def test_cota_fora_do_tipo_do_edital_e_recusada(edital_aberto, projeto, client):
    """Cota de deficiência é do Suplementar; no Regular só existem ampla e
    racial (`CATEGORIAS_POR_TIPO`)."""
    resposta = client.post(
        INSCRICAO,
        data=_formulario(
            edital_aberto,
            projeto,
            quota_category=QuotaCategory.DISABILITY.value,
            quota_proof=_anexo("cota.pdf"),
        ),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "quota_category_not_allowed"


def test_alvo_incompativel_com_o_tipo_do_edital_e_recusado(
    edital_aberto, linha, projeto, client
):
    """No Regular o alvo é projeto coletivo; mandar a linha é
    `target_mismatch`, e não um 500 da CheckConstraint."""
    resposta = client.post(
        INSCRICAO,
        data=_formulario(
            edital_aberto, projeto, project_id=None, research_line_id=linha.pk
        ),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "target_mismatch"


def test_combinacao_sem_vaga_e_recusada(edital_aberto, projeto, client):
    """Existe vaga de mestrado × ampla, mas nenhuma de doutorado."""
    resposta = client.post(
        INSCRICAO,
        data=_formulario(edital_aberto, projeto, level=SelectionLevel.DOCTORATE.value),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_vacancy_for_choice"
    assert not Application.objects.exists()


def test_vaga_zerada_nao_abre_inscricao(program, edital_aberto, projeto, client):
    Vacancy.objects.filter(process=edital_aberto).update(quantity=0)

    resposta = client.post(INSCRICAO, data=_formulario(edital_aberto, projeto))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "no_vacancy_for_choice"


def test_documento_obrigatorio_faltando_e_recusado(edital_aberto, projeto, client):
    """O resumo expandido é exigido no edital regular, e vai no campo
    opcional da assinatura — quem cobra é o model, pelo tipo do edital."""
    resposta = client.post(
        INSCRICAO, data=_formulario(edital_aberto, projeto, expanded_abstract=None)
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "missing_documents"
    assert not Application.objects.exists()
    assert not ApplicationDocument.objects.exists()


def test_cota_racial_exige_a_comprovacao(program, edital_aberto, projeto, client):
    Vacancy.objects.create(
        program=program,
        process=edital_aberto,
        level=SelectionLevel.MASTERS,
        project=projeto,
        quota_category=QuotaCategory.RACIAL,
        quantity=1,
    )
    formulario = _formulario(
        edital_aberto, projeto, quota_category=QuotaCategory.RACIAL.value
    )

    sem_comprovacao = client.post(INSCRICAO, data=formulario)
    assert sem_comprovacao.status_code == 400
    assert sem_comprovacao.json()["code"] == "missing_documents"

    completa = client.post(
        INSCRICAO,
        data=_formulario(
            edital_aberto,
            projeto,
            quota_category=QuotaCategory.RACIAL.value,
            quota_proof=_anexo("cota.pdf"),
        ),
    )
    assert completa.status_code == 201, completa.content
    inscricao = Application.objects.get()
    assert ApplicationDocumentKind.QUOTA_PROOF in set(
        inscricao.documents.values_list("kind", flat=True)
    )


def test_documento_que_o_edital_nao_exige_e_ignorado(edital_aberto, projeto, client):
    """Memorial é do Suplementar. Mandado ao Regular, não vira anexo — é
    campo que a tela deixou sobrar, não documento da inscrição."""
    resposta = client.post(
        INSCRICAO,
        data=_formulario(edital_aberto, projeto, memorial=_anexo("memorial.pdf")),
    )

    assert resposta.status_code == 201, resposta.content
    kinds = set(Application.objects.get().documents.values_list("kind", flat=True))
    assert ApplicationDocumentKind.MEMORIAL not in kinds


def test_arquivo_de_formato_invalido_e_recusado(edital_aberto, projeto, client):
    resposta = client.post(
        INSCRICAO,
        data=_formulario(
            edital_aberto,
            projeto,
            diploma=SimpleUploadedFile("diploma.exe", b"MZ", content_type="x"),
        ),
    )

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "invalid_document"
    # Nenhuma escrita parcial: nem inscrição, nem os anexos válidos do lote.
    assert not Application.objects.exists()
    assert not ApplicationDocument.objects.exists()


def test_inscricao_sem_token_csrf_e_recusada(edital_aberto, projeto):
    """auth=None desliga o CSRF do SessionAuth; o csrf_protect explícito da
    rota é o que segura — mesma trava do login e do signup da isolada."""
    client = Client(enforce_csrf_checks=True)

    resposta = client.post(INSCRICAO, data=_formulario(edital_aberto, projeto))

    assert resposta.status_code == 403
    assert not Application.objects.exists()


def test_limite_de_inscricoes_por_ip_dispara(edital_aberto, projeto, client):
    for cpf in CPFS[:5]:
        resposta = client.post(
            INSCRICAO,
            data=_formulario(
                edital_aberto, projeto, cpf=cpf, email=f"c{cpf}@example.com"
            ),
        )
        assert resposta.status_code == 201, resposta.content

    excedente = client.post(
        INSCRICAO,
        data=_formulario(
            edital_aberto, projeto, cpf=CPFS[5], email="excedente@example.com"
        ),
    )

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"
    assert Application.objects.count() == 5


# ---------------------------------------------------------------------------
# GET public/applications/{protocol}
# ---------------------------------------------------------------------------


def test_consulta_de_protocolo_devolve_situacao_sem_dado_pessoal(inscricao, client):
    resposta = client.get(f"{INSCRICAO}/{inscricao.protocol}")

    assert resposta.status_code == 200, resposta.content
    corpo = resposta.json()
    assert corpo == {
        "protocol": inscricao.protocol,
        "status": "homologated",
        "status_label": "Homologada",
        "submitted_at": corpo["submitted_at"],
        "process_title": "Edital Regular 2027",
    }
    assert "Ana Lima" not in resposta.content.decode()
    assert inscricao.cpf not in resposta.content.decode()


def test_protocolo_aceita_minusculas(inscricao, client):
    resposta = client.get(f"{INSCRICAO}/{inscricao.protocol.lower()}")

    assert resposta.status_code == 200, resposta.content


def test_protocolo_inexistente_e_404_generico(inscricao, client):
    resposta = client.get(f"{INSCRICAO}/PS2027R-DEADBEEF")

    assert resposta.status_code == 404
    assert "PS2027R-DEADBEEF" not in resposta.content.decode()


def test_limite_de_consulta_de_protocolo_dispara(inscricao, client):
    url = f"{INSCRICAO}/{inscricao.protocol}"
    for _ in range(20):
        assert client.get(url).status_code == 200

    excedente = client.get(url)

    assert excedente.status_code == 429
    assert excedente.json()["code"] == "rate_limited"
