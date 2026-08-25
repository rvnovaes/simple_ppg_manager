"""Invariantes da inscrição e dos seus documentos.

Mesma divisão de `test_vacancy_board.py`: primeiro os testes em memória
(pks à mão, nada salvo), depois os que dependem de constraint ou de
query, marcados com `django_db`.
"""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.academic.models import TAMANHO_MAXIMO_DO_DOCUMENTO, Student
from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    Application,
    ApplicationDocument,
    ApplicationDocumentKind,
    ApplicationStatus,
    QuotaCategory,
    RankingOutcome,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionStage,
    cpf_valido,
    gerar_protocolo,
)

from .test_models import ABERTURA, ENCERRAMENTO

PROGRAMA = Program(pk=1, acronym="PPGD")
PROJETO = CollectiveProject(pk=1, name="Projeto A")
LINHA = ResearchLine(pk=1, name="Linha A")
AGORA = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
CPF_VALIDO = "52998224725"


def _edital(kind: str = SelectionKind.REGULAR, pk: int = 1) -> SelectionProcess:
    return SelectionProcess(
        pk=pk,
        program=PROGRAMA,
        kind=kind,
        year=2027,
        title="Edital 2027",
        submission_opens_at=ABERTURA,
        submission_closes_at=ENCERRAMENTO,
    )


def _inscricao(**kwargs) -> Application:
    campos = {
        "program": PROGRAMA,
        "process": _edital(),
        "protocol": "PS2027R-ABCDEF01",
        "full_name": "Ana Lima",
        "email": "ana@example.com",
        "cpf": CPF_VALIDO,
        "birth_date": date(1995, 5, 20),
        "level": SelectionLevel.MASTERS,
        "project": PROJETO,
        "quota_category": QuotaCategory.OPEN,
        "submitted_at": AGORA,
    }
    return Application(**{**campos, **kwargs})


def _etapa(process: SelectionProcess, order: int = 1, pk: int = 1) -> SelectionStage:
    return SelectionStage(pk=pk, process=process, name=f"Etapa {order}", order=order)


# --- CPF e protocolo --------------------------------------------------------


@pytest.mark.parametrize("cpf", ["52998224725", "11144477735", "12345678909"])
def test_cpf_valido_aceita_digitos_verificadores_corretos(cpf):
    assert cpf_valido(cpf)


@pytest.mark.parametrize(
    "cpf",
    [
        "52998224726",  # segundo dígito errado
        "52998224735",  # primeiro dígito errado
        "11111111111",  # sequência repetida passa no mod-11, barrada à parte
        "5299822472",  # 10 dígitos
        "529982247250",  # 12 dígitos
        "529.982.247-25",  # com máscara: quem normaliza é a borda
        "",
    ],
)
def test_cpf_valido_rejeita_mal_formados(cpf):
    assert not cpf_valido(cpf)


def test_clean_rejeita_cpf_invalido():
    with pytest.raises(DomainError) as exc:
        _inscricao(process=None, cpf="52998224726").clean()

    assert exc.value.code == "invalid_cpf"
    assert exc.value.status_code == 400


def test_clean_aceita_cpf_valido_e_nascimento_no_passado():
    _inscricao(process=None).clean()


@pytest.mark.parametrize("deslocamento", [0, 1, 365])
def test_clean_rejeita_nascimento_hoje_ou_no_futuro(deslocamento):
    nascimento = date.today() + timedelta(days=deslocamento)

    with pytest.raises(DomainError) as exc:
        _inscricao(process=None, birth_date=nascimento).clean()

    assert exc.value.code == "invalid_birth_date"


def test_clean_exige_alvo_compativel_com_o_tipo_do_edital():
    with pytest.raises(DomainError) as exc:
        _inscricao(project=None, research_line=LINHA).clean()

    assert exc.value.code == "target_mismatch"


def test_clean_exige_cota_permitida_no_tipo_do_edital():
    with pytest.raises(DomainError) as exc:
        _inscricao(quota_category=QuotaCategory.DISABILITY).clean()

    assert exc.value.code == "quota_category_not_allowed"


@pytest.mark.parametrize(
    ("kind", "letra"),
    [(SelectionKind.REGULAR, "R"), (SelectionKind.SUPPLEMENTARY, "S")],
)
def test_gerar_protocolo_segue_o_formato_ps_ano_tipo_hex(kind, letra):
    protocolo = gerar_protocolo(_edital(kind))

    assert re.fullmatch(rf"PS2027{letra}-[0-9A-F]{{8}}", protocolo), protocolo


def test_gerar_protocolo_nao_repete():
    edital = _edital()

    assert len({gerar_protocolo(edital) for _ in range(50)}) == 50


# --- documentos exigidos ----------------------------------------------------

BASE = ["identity", "diploma", "lattes", "payment_receipt"]


def test_regular_ampla_concorrencia_exige_resumo_expandido_sem_comprovacao():
    assert _inscricao().required_document_kinds() == [*BASE, "expanded_abstract"]


def test_regular_com_cota_exige_comprovacao_da_cota():
    candidata = _inscricao(quota_category=QuotaCategory.RACIAL)

    assert candidata.required_document_kinds() == [
        *BASE,
        "expanded_abstract",
        "quota_proof",
    ]


def test_suplementar_exige_memorial_e_comprovacao_da_cota():
    candidata = _inscricao(
        process=_edital(SelectionKind.SUPPLEMENTARY),
        project=None,
        research_line=LINHA,
        quota_category=QuotaCategory.INDIGENOUS,
    )

    assert candidata.required_document_kinds() == [*BASE, "memorial", "quota_proof"]


def test_missing_documents_com_lote_em_maos_nao_consulta_o_banco():
    candidata = _inscricao(quota_category=QuotaCategory.RACIAL)

    faltam = candidata.missing_documents(present=["identity", "lattes", "quota_proof"])

    assert faltam == ["diploma", "payment_receipt", "expanded_abstract"]
    assert (
        candidata.missing_documents(present=candidata.required_document_kinds()) == []
    )


# --- transições -------------------------------------------------------------


def test_homologate_carimba_status_nota_e_instante_sem_salvar():
    candidata = _inscricao()

    candidata.homologate(at=AGORA, note="Documentação completa.")

    assert candidata.status == ApplicationStatus.HOMOLOGATED
    assert candidata.decision_note == "Documentação completa."
    assert candidata.decided_at == AGORA


def test_reject_exige_justificativa():
    candidata = _inscricao()

    with pytest.raises(DomainError) as exc:
        candidata.reject(at=AGORA, note="   ")

    assert exc.value.code == "rejection_requires_note"
    assert candidata.status == ApplicationStatus.SUBMITTED


def test_reject_com_justificativa():
    candidata = _inscricao()

    candidata.reject(at=AGORA, note="Diploma ilegível.")

    assert candidata.status == ApplicationStatus.REJECTED
    assert candidata.decision_note == "Diploma ilegível."
    assert candidata.decided_at == AGORA


@pytest.mark.parametrize(
    "status",
    [s for s in ApplicationStatus if s != ApplicationStatus.SUBMITTED],
)
def test_homologate_e_reject_so_a_partir_de_inscrita(status):
    for operacao in (
        lambda c: c.homologate(at=AGORA),
        lambda c: c.reject(at=AGORA, note="x"),
    ):
        candidata = _inscricao(status=status)
        with pytest.raises(InvalidStateTransition) as exc:
            operacao(candidata)
        assert exc.value.code == "application_not_submitted"
        assert exc.value.status_code == 409
        assert candidata.status == status


def test_eliminate_carimba_a_etapa():
    edital = _edital()
    candidata = _inscricao(process=edital, status=ApplicationStatus.HOMOLOGATED)
    etapa = _etapa(edital)

    candidata.eliminate(etapa)

    assert candidata.status == ApplicationStatus.ELIMINATED
    assert candidata.eliminated_at_stage is etapa


def test_eliminate_rejeita_etapa_de_outro_edital():
    candidata = _inscricao(status=ApplicationStatus.HOMOLOGATED)

    with pytest.raises(DomainError) as exc:
        candidata.eliminate(_etapa(_edital(pk=2), pk=9))

    assert exc.value.code == "stage_mismatch"
    assert candidata.status == ApplicationStatus.HOMOLOGATED


def test_approve_carimba_nota_final():
    candidata = _inscricao(status=ApplicationStatus.HOMOLOGATED)

    candidata.approve(Decimal("87.50"))

    assert candidata.status == ApplicationStatus.APPROVED
    assert candidata.final_score == Decimal("87.50")


@pytest.mark.parametrize("nota", [Decimal("-0.01"), Decimal("100.01")])
def test_approve_rejeita_nota_fora_de_0_a_100(nota):
    candidata = _inscricao(status=ApplicationStatus.HOMOLOGATED)

    with pytest.raises(DomainError) as exc:
        candidata.approve(nota)

    assert exc.value.code == "invalid_score"


@pytest.mark.parametrize(
    "status",
    [s for s in ApplicationStatus if s != ApplicationStatus.HOMOLOGATED],
)
def test_eliminate_e_approve_so_a_partir_de_homologada(status):
    edital = _edital()
    for operacao in (
        lambda c: c.eliminate(_etapa(edital)),
        lambda c: c.approve(Decimal("80")),
    ):
        candidata = _inscricao(process=edital, status=status)
        with pytest.raises(InvalidStateTransition) as exc:
            operacao(candidata)
        assert exc.value.code == "application_not_homologated"
        assert exc.value.status_code == 409


def test_reinstate_volta_eliminada_a_homologada_e_limpa_a_etapa():
    edital = _edital()
    candidata = _inscricao(
        process=edital,
        status=ApplicationStatus.ELIMINATED,
        eliminated_at_stage=_etapa(edital),
    )

    candidata.reinstate()

    assert candidata.status == ApplicationStatus.HOMOLOGATED
    assert candidata.eliminated_at_stage is None


@pytest.mark.parametrize(
    "status",
    [s for s in ApplicationStatus if s != ApplicationStatus.ELIMINATED],
)
def test_reinstate_so_a_partir_de_eliminada(status):
    with pytest.raises(InvalidStateTransition) as exc:
        _inscricao(status=status).reinstate()

    assert exc.value.code == "application_not_eliminated"
    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    "outcome",
    [RankingOutcome.CLASSIFIED_OPEN, RankingOutcome.CLASSIFIED_QUOTA],
)
def test_enroll_classificada_vira_matriculada(outcome):
    candidata = _inscricao(status=ApplicationStatus.APPROVED, final_outcome=outcome)
    aluno = Student(pk=1)

    candidata.enroll(aluno)

    assert candidata.status == ApplicationStatus.ENROLLED
    assert candidata.student is aluno


@pytest.mark.parametrize("outcome", ["", RankingOutcome.NOT_CLASSIFIED])
def test_enroll_sem_classificacao_e_409_not_classified(outcome):
    candidata = _inscricao(status=ApplicationStatus.APPROVED, final_outcome=outcome)

    with pytest.raises(InvalidStateTransition) as exc:
        candidata.enroll(Student(pk=1))

    assert exc.value.code == "not_classified"
    assert exc.value.status_code == 409
    assert candidata.status == ApplicationStatus.APPROVED


@pytest.mark.parametrize(
    "status",
    [s for s in ApplicationStatus if s != ApplicationStatus.APPROVED],
)
def test_enroll_so_a_partir_de_aprovada(status):
    candidata = _inscricao(status=status, final_outcome=RankingOutcome.CLASSIFIED_OPEN)

    with pytest.raises(InvalidStateTransition) as exc:
        candidata.enroll(Student(pk=1))

    assert exc.value.code == "application_not_approved"


# --- validate_upload --------------------------------------------------------


@pytest.mark.parametrize("nome", ["lattes.pdf", "RG.JPG", "foto.jpeg", "diploma.png"])
def test_validate_upload_aceita_extensoes_do_edital(nome):
    ApplicationDocument.validate_upload(filename=nome, size=1024)


@pytest.mark.parametrize("nome", ["lattes.docx", "script.exe", "semextensao", ""])
def test_validate_upload_rejeita_extensao_fora_da_lista(nome):
    with pytest.raises(DomainError) as exc:
        ApplicationDocument.validate_upload(filename=nome, size=1024)

    assert exc.value.code == "invalid_document"


def test_validate_upload_rejeita_arquivo_acima_do_limite():
    ApplicationDocument.validate_upload(
        filename="ok.pdf", size=TAMANHO_MAXIMO_DO_DOCUMENTO
    )
    with pytest.raises(DomainError) as exc:
        ApplicationDocument.validate_upload(
            filename="grande.pdf", size=TAMANHO_MAXIMO_DO_DOCUMENTO + 1
        )

    assert exc.value.code == "invalid_document"


# --- com banco: uniques, checks e queries -----------------------------------


def _nova(program, edital, **kwargs) -> Application:
    campos = {
        "program": program,
        "process": edital,
        "protocol": gerar_protocolo(edital),
        "full_name": "Beatriz Melo",
        "email": "bia@example.com",
        "cpf": "11144477735",
        "birth_date": date(1992, 1, 10),
        "level": SelectionLevel.MASTERS,
        "quota_category": QuotaCategory.OPEN,
        "submitted_at": AGORA,
    }
    return Application(**{**campos, **kwargs})


@pytest.mark.django_db
def test_clean_barra_segundo_cpf_no_mesmo_edital(inscricao, program, projeto):
    repetida = _nova(program, inscricao.process, cpf=inscricao.cpf, project=projeto)

    with pytest.raises(DomainError) as exc:
        repetida.clean()

    assert exc.value.code == "duplicate_application"


@pytest.mark.django_db
def test_mesmo_cpf_pode_se_inscrever_no_outro_edital(
    inscricao, program, edital_suplementar, linha
):
    outra = _nova(
        program,
        edital_suplementar,
        cpf=inscricao.cpf,
        research_line=linha,
        quota_category=QuotaCategory.QUILOMBOLA,
    )

    outra.clean()
    outra.save()

    assert Application.objects.filter(cpf=inscricao.cpf).count() == 2


@pytest.mark.django_db
def test_unique_de_cpf_por_edital_vale_no_banco(inscricao, program, projeto):
    repetida = _nova(program, inscricao.process, cpf=inscricao.cpf, project=projeto)

    with pytest.raises(IntegrityError), transaction.atomic():
        repetida.save()


@pytest.mark.django_db
def test_check_de_eliminada_exige_etapa_no_banco(inscricao):
    inscricao.status = ApplicationStatus.ELIMINATED

    with pytest.raises(IntegrityError), transaction.atomic():
        inscricao.save()


@pytest.mark.django_db
def test_check_de_matriculada_exige_aluno_no_banco(inscricao):
    inscricao.status = ApplicationStatus.ENROLLED

    with pytest.raises(IntegrityError), transaction.atomic():
        inscricao.save()


@pytest.mark.django_db
def test_check_de_nota_final_fora_do_intervalo_no_banco(inscricao):
    inscricao.final_score = Decimal("100.50")

    with pytest.raises(IntegrityError), transaction.atomic():
        inscricao.save()


@pytest.mark.django_db
def test_querysets_alive_approved_for_target_e_convocable(
    inscricao, program, projeto, linha
):
    edital = inscricao.process
    aprovada = _nova(
        program, edital, project=projeto, status=ApplicationStatus.APPROVED
    )
    aprovada.save()
    outro_alvo = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto B"
    )
    doutorado = _nova(
        program,
        edital,
        cpf="12345678909",
        project=outro_alvo,
        level=SelectionLevel.DOCTORATE,
        status=ApplicationStatus.HOMOLOGATED,
    )
    doutorado.save()
    etapa = edital.stages.first()

    assert set(Application.objects.for_process(edital).alive()) == {
        inscricao,
        doutorado,
    }
    assert list(Application.objects.approved()) == [aprovada]
    assert list(
        Application.objects.for_process(edital).for_target(
            SelectionLevel.MASTERS, projeto, None
        )
    ) == [inscricao, aprovada]
    assert set(Application.objects.convocable_for(etapa)) == {inscricao, doutorado}


@pytest.mark.django_db
def test_missing_documents_consulta_os_anexos_e_grava_no_caminho_do_edital(inscricao):
    doc = ApplicationDocument(
        application=inscricao,
        kind=ApplicationDocumentKind.LATTES,
        file=SimpleUploadedFile("lattes.pdf", b"%PDF-1.4"),
    )
    doc.clean()
    doc.save()

    assert doc.file.name == (
        f"selecao/edital-{inscricao.process_id}/inscricao-{inscricao.pk}/lattes.pdf"
    )
    assert inscricao.missing_documents() == [
        "identity",
        "diploma",
        "payment_receipt",
        "expanded_abstract",
    ]


@pytest.mark.django_db
def test_clean_barra_segundo_documento_do_mesmo_tipo(inscricao):
    ApplicationDocument.objects.create(
        application=inscricao,
        kind=ApplicationDocumentKind.IDENTITY,
        file=SimpleUploadedFile("rg.pdf", b"%PDF-1.4"),
    )
    repetido = ApplicationDocument(
        application=inscricao,
        kind=ApplicationDocumentKind.IDENTITY,
        file=SimpleUploadedFile("rg2.pdf", b"%PDF-1.4"),
    )

    with pytest.raises(DomainError) as exc:
        repetido.clean()

    assert exc.value.code == "duplicate_document"
    with pytest.raises(IntegrityError), transaction.atomic():
        repetido.save()


@pytest.mark.django_db
def test_apagar_inscricao_leva_os_documentos_junto(inscricao):
    ApplicationDocument.objects.create(
        application=inscricao,
        kind=ApplicationDocumentKind.IDENTITY,
        file=SimpleUploadedFile("rg.pdf", b"%PDF-1.4"),
    )

    inscricao.delete()

    assert not ApplicationDocument.objects.exists()
