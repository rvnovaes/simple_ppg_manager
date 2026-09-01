"""O PDF do resultado: bytes válidos, dez seções e a coluna que varia.

O papel é gerado a partir de `ScholarshipEdition.result(level)`, que lê o
banco — por isso este arquivo é `django_db` inteiro, e não nível (a) como
`test_pdf.py` do processo seletivo (lá a ata carrega o `content` congelado
e cabe em memória).

O que se prova aqui é o que o documento **tem de carregar**: as dez faixas
mesmo vazias, a coluna "Remuneração" só nas duas em que o rendimento
ordena, e bytes de PDF de verdade. Conferir posição de coluna no papel é
trabalho de olho humano, não de teste.
"""

import base64
import re
import zlib
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.academic.models import Student
from apps.programs.models import Program
from apps.scholarships.models import (
    ORDEM_DAS_FAIXAS,
    TITULO_DA_FAIXA,
    PriorityBand,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
)
from apps.scholarships.pdf import (
    RESULTADO_FINAL,
    RESULTADO_PRELIMINAR,
    montar_resultado,
    nome_do_arquivo,
    tipo_do_resultado,
)

from .test_bolsas_api_inscricao import criar_discente, logar
from .test_bolsas_api_lancamentos import usuario_com_papel

pytestmark = pytest.mark.django_db


# --- cenário ---------------------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )


@pytest.fixture
def aluno(program: Program) -> Student:
    return criar_discente(program=program, username="ana", nome="Ana Ribeiro")


@pytest.fixture
def inscricao(edicao: ScholarshipEdition, aluno: Student) -> ScholarshipApplication:
    """Faixa 2.1-I: sem atividade remunerada, ingresso por ação afirmativa."""
    inscricao = ScholarshipApplication.for_student(
        edition=edicao, student=aluno, affirmative_action=True
    )
    inscricao.save()
    return inscricao


@pytest.fixture
def inscricao_do_servico_publico(
    edicao: ScholarshipEdition, program: Program
) -> ScholarshipApplication:
    """Faixa 2.4-V — a que ordena por menor rendimento, e por isso imprime
    a coluna "Remuneração"."""
    bruno = criar_discente(program=program, username="bruno", nome="Bruno Silva")
    inscricao = ScholarshipApplication.for_student(
        edition=edicao,
        student=bruno,
        has_paid_activity=True,
        public_service=True,
        monthly_income=Decimal("3200.00"),
        weekly_hours=20,
    )
    inscricao.save()
    return inscricao


@pytest.fixture
def client_da_secretaria(client: Client, program: Program) -> Client:
    """Cliente próprio por papel: duas fixtures com `force_login` sobre o
    mesmo `client` do pytest-django disputam a MESMA sessão."""
    outro = Client()
    outro.force_login(usuario_com_papel(program, "Secretaria", "secretaria"))
    return outro


@pytest.fixture
def client_do_aluno(client: Client, aluno: Student) -> Client:
    return logar(client, aluno)


def url_pdf(edicao: ScholarshipEdition, nivel: str = "masters") -> str:
    return f"/api/v1/scholarships/editions/{edicao.pk}/result.pdf?level={nivel}"


def conteudo(resposta: Any) -> bytes:
    """`streaming_content` não está no tipo do cliente de teste."""
    return b"".join(resposta.streaming_content)


def publicar(client: Client, edicao: ScholarshipEdition, ato: str = "preliminary"):
    return client.post(f"/api/v1/scholarships/editions/{edicao.pk}/publish-{ato}")


def texto_do_pdf(pdf: bytes) -> str:
    """O texto que o papel carrega, para perguntar "este dado saiu?".

    O ReportLab comprime os fluxos de página (Flate) e ainda os passa por
    ASCII85, então ler os bytes crus não acha nada: cada `stream` precisa
    ser desfeito nessa ordem antes da busca. Latin-1 porque é assim que o
    operador de texto do PDF escreve com a Helvetica embutida.

    E **o acento vira escape octal** dentro do operador de texto (`\\351`
    para "é"): sem desfazer isso, procurar "décima" ou "Cumulação" no
    conteúdo falha mesmo com a palavra impressa no papel. É a armadilha
    deste tipo de teste — a asserção quebra por causa do encoding, não do
    documento.
    """
    partes = []
    for bruto in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        dados = bruto.strip()
        if dados.endswith(b"~>"):
            dados = base64.a85decode(dados, adobe=True)
        try:
            partes.append(zlib.decompress(dados))
        except zlib.error:
            partes.append(dados)
    conteudo = b"".join(partes).decode("latin-1")
    trechos = [
        re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), t)
        for t in re.findall(r"\((.*?)\) Tj", conteudo, re.DOTALL)
    ]
    return " ".join(trechos)


# --- bytes válidos ---------------------------------------------------------


def test_edicao_sem_nenhum_candidato_ainda_gera_pdf(edicao: ScholarshipEdition):
    pdf = montar_resultado(edicao, "masters", RESULTADO_PRELIMINAR)

    assert pdf.startswith(b"%PDF")
    assert pdf.rstrip().endswith(b"%%EOF")


def test_o_documento_carrega_o_cabecalho_da_edicao(
    edicao: ScholarshipEdition, inscricao: ScholarshipApplication
):
    texto = texto_do_pdf(montar_resultado(edicao, "masters", RESULTADO_PRELIMINAR))

    assert "RESULTADO PRELIMINAR" in texto
    assert "Edital de Bolsas 2026" in texto
    assert "Mestrado" in texto
    assert "Ana Ribeiro" in texto


def test_o_final_publicado_muda_o_titulo_do_documento(edicao: ScholarshipEdition):
    texto = texto_do_pdf(montar_resultado(edicao, "masters", RESULTADO_FINAL))

    assert "RESULTADO FINAL" in texto


# --- as dez seções ---------------------------------------------------------


def test_as_dez_faixas_saem_no_papel_mesmo_vazias(edicao: ScholarshipEdition):
    """Faixa sem candidato que sumisse viraria uma prioridade a menos na
    lista publicada (decisão Q8): ela sai só com o cabeçalho."""
    texto = texto_do_pdf(montar_resultado(edicao, "masters", RESULTADO_PRELIMINAR))

    assert len(ORDEM_DAS_FAIXAS) == 10
    for faixa in ORDEM_DAS_FAIXAS:
        assert TITULO_DA_FAIXA[faixa] in texto, faixa
    assert "Nenhum candidato nesta faixa." in texto


def test_cada_secao_publica_a_ordem_de_prioridade_e_a_regra(
    edicao: ScholarshipEdition,
):
    texto = texto_do_pdf(montar_resultado(edicao, "masters", RESULTADO_PRELIMINAR))

    assert "Ordem de prioridade: primeira" in texto
    assert "Ordem de prioridade: décima" in texto
    assert "Nota do barema, em ordem decrescente." in texto
    assert "Menor rendimento mensal" in texto


# --- a coluna que varia ----------------------------------------------------


def test_a_coluna_remuneracao_so_aparece_nas_duas_faixas_previstas(
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
    inscricao_do_servico_publico: ScholarshipApplication,
):
    """Duas seções da mesma lista, duas composições de coluna: o papel
    publica a coluna que decidiu a ordem, e só ela."""
    faixas = {faixa.band: faixa for faixa in edicao.result("masters")}

    assert {b for b, f in faixas.items() if f.shows_income} == {
        PriorityBand.B24_V,
        PriorityBand.B24_VI_VII_VIII,
    }
    texto = texto_do_pdf(montar_resultado(edicao, "masters", RESULTADO_PRELIMINAR))
    # Uma ocorrência por faixa com `shows_income`, e nenhuma nas outras oito.
    assert texto.count("Remunera") == 2
    assert "3.200,00" in texto


# --- o tipo e o nome do arquivo -------------------------------------------


def test_o_tipo_do_documento_sai_do_carimbo_de_publicacao(
    client_da_secretaria: Client, edicao: ScholarshipEdition
):
    assert tipo_do_resultado(edicao) == RESULTADO_PRELIMINAR

    publicar(client_da_secretaria, edicao)
    edicao.refresh_from_db()
    assert tipo_do_resultado(edicao) == RESULTADO_PRELIMINAR

    edicao.open_appeals()
    edicao.save(update_fields=["status"])
    publicar(client_da_secretaria, edicao, "final")
    edicao.refresh_from_db()
    assert tipo_do_resultado(edicao) == RESULTADO_FINAL


def test_o_nome_do_arquivo_distingue_nivel_e_edicao(edicao: ScholarshipEdition):
    nome = nome_do_arquivo(edicao, "doctorate", RESULTADO_FINAL)

    assert nome == f"resultado-final-2026-doctorate-edicao-{edicao.pk}.pdf"


# --- a rota ----------------------------------------------------------------


def test_a_rota_devolve_um_pdf_para_quem_trabalha_o_edital(
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    resposta = client_da_secretaria.get(url_pdf(edicao))

    assert resposta.status_code == 200, resposta.content
    assert resposta["Content-Type"] == "application/pdf"
    assert "attachment" in resposta["Content-Disposition"]
    assert conteudo(resposta).startswith(b"%PDF")


def test_a_rota_recusa_quem_nao_tem_a_permissao(
    client_sem_permissao: Client, edicao: ScholarshipEdition
):
    assert client_sem_permissao.get(url_pdf(edicao)).status_code == 403


def test_o_candidato_nao_baixa_o_pdf_antes_de_publicado(
    client_do_aluno: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    """Mesma regra de visibilidade do JSON — é a mesma função."""
    resposta = client_do_aluno.get(url_pdf(edicao))

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "result_not_published"


def test_o_candidato_baixa_o_pdf_depois_de_publicado(
    client_do_aluno: Client,
    client_da_secretaria: Client,
    edicao: ScholarshipEdition,
    inscricao: ScholarshipApplication,
):
    publicar(client_da_secretaria, edicao)

    resposta = client_do_aluno.get(url_pdf(edicao))

    assert resposta.status_code == 200, resposta.content
    assert conteudo(resposta).startswith(b"%PDF")


def test_edicao_de_outro_programa_nao_existe_aqui(client_da_secretaria: Client, db):
    alheia = ScholarshipEdition.objects.create(
        program=Program.objects.create(name="Outro programa", acronym="PPGX"),
        year=2026,
        title="Edital alheio",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )

    assert client_da_secretaria.get(url_pdf(alheia)).status_code == 404
