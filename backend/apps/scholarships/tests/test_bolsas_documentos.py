"""Comprovantes do questionário da inscrição de bolsas.

Dois níveis da pirâmide (Seção 9), nesta ordem: `validate_upload()` e a
parte de `pending_docs()` que só lê os booleanos são invariantes em
memória, sem banco; a substituição, a `UniqueConstraint` e a permissão
própria de download precisam de linhas gravadas e vêm depois, marcadas
com `django_db`.

O caso que dá nome ao arquivo é o do reenvio: mandar de novo o
comprovante de ação afirmativa **substitui** o anterior. Duas versões da
mesma prova deixariam a comissão adivinhar qual vale.
"""

from datetime import date

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.academic.models import Student
from apps.core.exceptions import DomainError
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.scholarships.models import (
    RESPOSTA_QUE_EXIGE_DOCUMENTO,
    TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO,
    ApplicationDocument,
    ApplicationDocumentKind,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipLevel,
)


def _inscricao(**kwargs) -> ScholarshipApplication:
    """Inscrição em memória, sem tocar o banco — o molde é o de
    `test_bolsas_inscricao.py`: FKs **sem pk**, senão o espelho da
    `UniqueConstraint` dentro de `clean()` consulta o banco."""
    campos = {
        "program": Program(pk=1),
        "edition": ScholarshipEdition(program_id=1),
        "student": Student(program_id=1),
        "level": ScholarshipLevel.MASTERS,
    }
    return ScholarshipApplication(**{**campos, **kwargs})


# --- validate_upload: o que o edital aceita como comprovante ---------------


@pytest.mark.parametrize(
    "filename",
    ["laudo.pdf", "LAUDO.PDF", "foto.jpg", "foto.jpeg", "print.png"],
)
def test_validate_upload_aceita_pdf_e_imagem(filename):
    """Imagem entra porque comprovante quase sempre chega como foto de
    celular; a extensão é lida sem distinguir caixa."""
    ApplicationDocument.validate_upload(filename=filename, size=1024)


@pytest.mark.parametrize(
    "filename",
    ["", "laudo", "laudo.exe", "laudo.docx", "laudo.pdf.exe", "laudo.zip"],
    ids=["vazio", "sem_extensao", "exe", "docx", "dupla", "zip"],
)
def test_validate_upload_recusa_o_que_nao_e_pdf_nem_imagem(filename):
    """Documento de candidato é lido pela secretaria, não executado."""
    with pytest.raises(DomainError) as exc:
        ApplicationDocument.validate_upload(filename=filename, size=1024)

    assert exc.value.code == "invalid_document"
    assert exc.value.status_code == 400


def test_validate_upload_aceita_exatamente_o_limite():
    """O limite é o maior tamanho aceito, não o primeiro recusado."""
    ApplicationDocument.validate_upload(
        filename="laudo.pdf", size=TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO
    )


def test_validate_upload_recusa_acima_do_limite():
    with pytest.raises(DomainError) as exc:
        ApplicationDocument.validate_upload(
            filename="laudo.pdf", size=TAMANHO_MAXIMO_DO_DOCUMENTO_DA_INSCRICAO + 1
        )

    assert exc.value.code == "invalid_document"


# --- pending_docs(): o "Sim - Não enviado" do export -----------------------


def test_questionario_todo_negativo_nao_pede_documento():
    assert _inscricao().pending_docs() == []


@pytest.mark.parametrize(("kind", "campo"), list(RESPOSTA_QUE_EXIGE_DOCUMENTO.items()))
def test_cada_sim_do_questionario_cobra_o_seu_comprovante(kind, campo):
    assert _inscricao(**{campo: True}).pending_docs() == [kind]


@pytest.mark.parametrize(
    "campo",
    ["has_paid_activity", "cadastro_unico"],
)
def test_os_dois_sim_que_nao_pedem_comprovante(campo):
    """`has_paid_activity` é a chave que joga do bloco 2.1 para o 2.4 —
    quem comprova são os incisos abaixo dela; `cadastro_unico` é critério
    de desempate, e o edital não cobra anexo por ele.

    A atividade remunerada vem com renda e carga horária porque o
    `clean()` as exige; aqui só interessa que nenhuma das duas respostas
    entra na lista de pendências.
    """
    extras = (
        {"monthly_income": 2500, "weekly_hours": 20}
        if campo == "has_paid_activity"
        else {}
    )

    assert _inscricao(**{campo: True}, **extras).pending_docs() == []


def test_pending_docs_segue_a_ordem_do_questionario():
    """A ordem é a de declaração do enum, que é a da tela — a comissão lê
    a lista de pendências ao lado do questionário."""
    inscricao = _inscricao(
        other_non_public_scholarship=True,
        affirmative_action=True,
        public_service=True,
    )

    assert inscricao.pending_docs() == [
        ApplicationDocumentKind.AFFIRMATIVE_ACTION,
        ApplicationDocumentKind.PUBLIC_SERVICE,
        ApplicationDocumentKind.OTHER_NON_PUBLIC_SCHOLARSHIP,
    ]


# --- o que precisa de banco ------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program, year=2026, title="Edital de Bolsas 2026"
    )


@pytest.fixture
def discente(program: Program) -> Student:
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto coletivo"
    )
    pessoa = Person.objects.create(
        program=program, full_name="João Souza", primary_email="joao@example.com"
    )
    return Student.objects.create(
        program=program,
        person=pessoa,
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2025, 3, 1),
    )


@pytest.fixture
def inscricao(edicao, discente) -> ScholarshipApplication:
    aplicacao = ScholarshipApplication.for_student(
        edition=edicao,
        student=discente,
        affirmative_action=True,
        socioeconomic_vulnerability=True,
    )
    aplicacao.save()
    return aplicacao


def _anexar(
    aplicacao: ScholarshipApplication, kind: str, conteudo: bytes = b"comprovante"
) -> ApplicationDocument:
    documento, _ = ApplicationDocument.replace_for(
        application=aplicacao,
        kind=kind,
        file=SimpleUploadedFile(f"{kind}.pdf", conteudo),
    )
    return documento


@pytest.mark.django_db
def test_reenviar_o_mesmo_tipo_substitui_e_nao_empilha(inscricao):
    """O caso que dá nome ao arquivo: uma linha por tipo, sempre."""
    primeiro = _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION, b"v1")

    segundo, substituiu = ApplicationDocument.replace_for(
        application=inscricao,
        kind=ApplicationDocumentKind.AFFIRMATIVE_ACTION,
        file=SimpleUploadedFile("novo.pdf", b"v2"),
    )

    assert substituiu is True
    assert segundo.pk != primeiro.pk
    assert ApplicationDocument.objects.for_application(inscricao).count() == 1
    assert segundo.file.read() == b"v2"


@pytest.mark.django_db
def test_primeiro_envio_nao_e_substituicao(inscricao):
    _, substituiu = ApplicationDocument.replace_for(
        application=inscricao,
        kind=ApplicationDocumentKind.AFFIRMATIVE_ACTION,
        file=SimpleUploadedFile("laudo.pdf", b"v1"),
    )

    assert substituiu is False


@pytest.mark.django_db
def test_substituicao_apaga_o_arquivo_anterior_do_storage(inscricao):
    """Sem a remoção explícita, cada reenvio deixaria um órfão no
    MEDIA_ROOT — o `delete()` do model não apaga o arquivo."""
    primeiro, _ = ApplicationDocument.replace_for(
        application=inscricao,
        kind=ApplicationDocumentKind.AFFIRMATIVE_ACTION,
        file=SimpleUploadedFile("primeiro.pdf", b"v1"),
    )
    caminho = primeiro.file.name

    ApplicationDocument.replace_for(
        application=inscricao,
        kind=ApplicationDocumentKind.AFFIRMATIVE_ACTION,
        file=SimpleUploadedFile("segundo.pdf", b"v2"),
    )

    assert not primeiro.file.storage.exists(caminho)


@pytest.mark.django_db
def test_clean_rejeita_segundo_documento_do_mesmo_tipo(inscricao):
    """A duplicata vira `duplicate_application_document` (400), não
    `IntegrityError` — quem chama `replace_for()` nunca chega aqui."""
    _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION)

    with pytest.raises(DomainError) as exc:
        ApplicationDocument(
            application=inscricao,
            kind=ApplicationDocumentKind.AFFIRMATIVE_ACTION,
            file=SimpleUploadedFile("outro.pdf", b"x"),
        ).clean()

    assert exc.value.code == "duplicate_application_document"
    assert exc.value.status_code == 400


@pytest.mark.django_db
def test_o_proprio_documento_nao_e_duplicata_de_si_mesmo(inscricao):
    documento = _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION)

    documento.clean()


@pytest.mark.django_db
def test_dois_tipos_diferentes_convivem_na_mesma_inscricao(inscricao):
    _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION)
    _anexar(inscricao, ApplicationDocumentKind.SOCIOECONOMIC_VULNERABILITY)

    assert ApplicationDocument.objects.for_application(inscricao).count() == 2


@pytest.mark.django_db
def test_pending_docs_desconta_o_que_ja_foi_enviado(inscricao):
    _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION)

    assert inscricao.pending_docs() == [
        ApplicationDocumentKind.SOCIOECONOMIC_VULNERABILITY
    ]

    _anexar(inscricao, ApplicationDocumentKind.SOCIOECONOMIC_VULNERABILITY)

    assert inscricao.pending_docs() == []


@pytest.mark.django_db
def test_documento_de_resposta_nao_declarada_nao_vira_pendencia(inscricao):
    """Anexo a mais não é pendência nem erro: quem manda na lista é o
    questionário."""
    _anexar(inscricao, ApplicationDocumentKind.PUBLIC_SERVICE)

    assert ApplicationDocumentKind.PUBLIC_SERVICE not in inscricao.pending_docs()


@pytest.mark.django_db
def test_arquivo_e_gravado_particionado_por_edicao_e_inscricao(inscricao):
    documento = _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION)

    assert documento.file.name.startswith(
        f"bolsas/edicao-{inscricao.edition_id}/inscricao-{inscricao.pk}/questionario/"
    )


@pytest.mark.django_db
def test_apagar_a_inscricao_leva_os_documentos_junto(inscricao):
    _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION)

    inscricao.delete()

    assert not ApplicationDocument.objects.exists()


@pytest.mark.django_db
def test_for_program_e_o_primeiro_filtro_da_busca_de_documentos(inscricao):
    documento = _anexar(inscricao, ApplicationDocumentKind.AFFIRMATIVE_ACTION)
    outro = Program.objects.create(acronym="PPGX", name="Outro programa")

    assert list(ApplicationDocument.objects.for_program(inscricao.program)) == [
        documento
    ]
    assert not ApplicationDocument.objects.for_program(outro).exists()


@pytest.mark.django_db
def test_a_permissao_propria_de_download_existe():
    """Baixar o anexo é mais do que ver a inscrição: são dados pessoais do
    candidato, e a permissão é separada por isso."""
    assert Permission.objects.filter(
        codename="download_applicationdocument",
        content_type__app_label="scholarships",
    ).exists()
