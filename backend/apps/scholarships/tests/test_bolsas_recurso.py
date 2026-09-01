"""O recurso contra o resultado preliminar: julgamento e recálculo.

Dois assuntos, e o segundo é o que mais importa no merge:

1. `judge()` só decide dentro da fase de recursos e só com fundamentação
   escrita — e não salva, como toda transição deste app.
2. **Não há rotina de recálculo, e o teste prova que não falta nenhuma.**
   Deferido o recurso, a comissão corrige o `committee_score` do
   lançamento atacado (pode, porque `committee_can_review()` vale em
   `appeals_under_review`) e a nota da inscrição muda sozinha na leitura
   seguinte, porque é derivada.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError

from apps.academic.models import Student
from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.scholarships.models import (
    AppealOutcome,
    BaremeEntry,
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    ScholarshipAppeal,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)

JULGADO_EM = datetime(2026, 5, 20, 14, 0, tzinfo=UTC)


# --- judge(): a fase, a fundamentação e o "só uma vez" ----------------------
#
# Em memória, sem banco: `clean()` do recurso só consulta o banco com
# `application_id` preenchido, e aqui a inscrição vai sem pk.


def _recurso(status: str = ScholarshipEditionStatus.APPEALS_UNDER_REVIEW, **kwargs):
    edicao = ScholarshipEdition(program_id=1, year=2026, title="Bolsas", status=status)
    inscricao = ScholarshipApplication(
        edition=edicao, level=ScholarshipLevel.MASTERS, program_id=1
    )
    campos = {"application": inscricao, "text": "Contesto o item 1.3."}
    return ScholarshipAppeal(**{**campos, **kwargs})


def test_julgamento_grava_resultado_fundamentacao_e_instante():
    recurso = _recurso()

    recurso.judge(
        outcome=AppealOutcome.GRANTED,
        reasoning="O certificado cobre o semestre inteiro.",
        at=JULGADO_EM,
    )

    assert recurso.outcome == AppealOutcome.GRANTED
    assert recurso.reasoning == "O certificado cobre o semestre inteiro."
    assert recurso.decided_at == JULGADO_EM
    assert recurso.judged() is True


def test_recurso_nasce_sem_resultado():
    assert _recurso().judged() is False


@pytest.mark.parametrize(
    "status",
    [s for s in ScholarshipEditionStatus.values if s != "appeals_under_review"],
)
def test_julgamento_fora_da_fase_de_recursos_e_recusado(status):
    """Matriz dos estados: o preliminar publicado ainda não abre a fase —
    quem abre é `open_appeals()`, e é o único estado que julga."""
    recurso = _recurso(status=status)

    with pytest.raises(InvalidStateTransition) as exc:
        recurso.judge(
            outcome=AppealOutcome.DENIED, reasoning="Sem razão.", at=JULGADO_EM
        )

    assert exc.value.code == "edition_not_appeals_under_review"
    assert exc.value.status_code == 409
    assert recurso.outcome is None


@pytest.mark.parametrize(
    "fundamentacao", ["", "   ", "\n\t"], ids=["vazia", "espaços", "brancos"]
)
def test_julgamento_sem_fundamentacao_e_recusado(fundamentacao):
    """Decisão sem fundamentação é exatamente o que o candidato recorreria."""
    recurso = _recurso()

    with pytest.raises(DomainError) as exc:
        recurso.judge(
            outcome=AppealOutcome.DENIED, reasoning=fundamentacao, at=JULGADO_EM
        )

    assert exc.value.code == "appeal_reasoning_required"
    assert exc.value.status_code == 400
    assert recurso.outcome is None
    assert recurso.decided_at is None


def test_julgamento_com_resultado_invalido_e_recusado():
    recurso = _recurso()

    with pytest.raises(DomainError) as exc:
        recurso.judge(outcome="talvez", reasoning="Fundamentado.", at=JULGADO_EM)

    assert exc.value.code == "invalid_appeal_outcome"


def test_recurso_julgado_nao_se_rejulga():
    recurso = _recurso()
    recurso.judge(
        outcome=AppealOutcome.DENIED, reasoning="Primeira decisão.", at=JULGADO_EM
    )

    with pytest.raises(InvalidStateTransition) as exc:
        recurso.judge(
            outcome=AppealOutcome.GRANTED, reasoning="Mudei de ideia.", at=JULGADO_EM
        )

    assert exc.value.code == "appeal_already_judged"
    assert recurso.outcome == AppealOutcome.DENIED
    assert recurso.reasoning == "Primeira decisão."


def test_julgamento_nao_salva():
    """Como toda transição deste app: quem persiste é o router, no mesmo
    `transaction.atomic()` do `AuditLog`."""
    recurso = _recurso()

    recurso.judge(
        outcome=AppealOutcome.PARTIALLY_GRANTED, reasoning="Em parte.", at=JULGADO_EM
    )

    assert recurso.pk is None


# --- um recurso por inscrição ----------------------------------------------


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
        program=program, full_name="Maria Lima", primary_email="maria@example.com"
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
    aplicacao = ScholarshipApplication.for_student(edition=edicao, student=discente)
    aplicacao.save()
    return aplicacao


@pytest.mark.django_db
def test_clean_recusa_segundo_recurso_na_mesma_inscricao(inscricao):
    ScholarshipAppeal.objects.create(application=inscricao, text="Primeiro.")

    with pytest.raises(DomainError) as exc:
        ScholarshipAppeal(application=inscricao, text="Segundo.").clean()

    assert exc.value.code == "duplicate_appeal"
    assert exc.value.status_code == 400


@pytest.mark.django_db
def test_banco_tambem_recusa_o_segundo_recurso(inscricao):
    """O espelho em `clean()` existe para dar 400 com código; a garantia
    dura é o `unique` do `OneToOneField`."""
    ScholarshipAppeal.objects.create(application=inscricao, text="Primeiro.")

    with pytest.raises(IntegrityError):
        ScholarshipAppeal.objects.create(application=inscricao, text="Segundo.")


@pytest.mark.django_db
def test_clean_aceita_o_proprio_recurso_na_edicao(inscricao):
    recurso = ScholarshipAppeal.objects.create(application=inscricao, text="Único.")

    recurso.clean()


@pytest.mark.django_db
def test_for_program_chega_ao_programa_pela_inscricao(inscricao, program):
    ScholarshipAppeal.objects.create(application=inscricao, text="Contesto.")

    assert ScholarshipAppeal.objects.for_program(program).count() == 1


@pytest.mark.django_db
def test_pending_lista_so_os_nao_julgados(inscricao):
    recurso = ScholarshipAppeal.objects.create(application=inscricao, text="Contesto.")

    assert ScholarshipAppeal.objects.pending().count() == 1

    recurso.outcome = AppealOutcome.DENIED
    recurso.save(update_fields=["outcome"])

    assert ScholarshipAppeal.objects.pending().count() == 0


# --- o deferimento não recalcula porque não há o que recalcular -------------


@pytest.mark.django_db
def test_deferido_o_recurso_a_nota_muda_sozinha_ao_corrigir_o_lancamento(
    inscricao, edicao
):
    """O ponto da story, e o motivo de `ScholarshipAppeal` não ter rotina
    de recálculo: com a edição em `appeals_under_review`, alterar o
    `committee_score` do lançamento atacado muda `committee_score()` da
    inscrição na leitura seguinte — a nota é derivada, não é campo."""
    item = BaremeItem.objects.create(
        edition=edicao,
        level=ScholarshipLevel.MASTERS,
        section=BaremeSection.FORMATION,
        code="1.3",
        text="Disciplina cursada",
        unit=BaremeUnit.SEMESTER,
        points_per_unit=Decimal("0.50"),
        cap=Decimal("3.00"),
    )
    lancamento = BaremeEntry.objects.create(
        application=inscricao,
        item=item,
        description="Dois semestres",
        quantity=Decimal("2"),
        candidate_score=item.raw_score(Decimal("2")),
        committee_score=Decimal("0.50"),
        committee_note="Só um semestre comprovado.",
        proof=SimpleUploadedFile("comprovante.pdf", b"%PDF-1.4"),
    )
    assert inscricao.committee_score() == Decimal("0.50")

    # A fase de recursos abre e o recurso é deferido.
    edicao.open_submissions()
    edicao.start_review()
    edicao.publish_preliminary(at=JULGADO_EM)
    edicao.open_appeals()
    edicao.save()
    recurso = ScholarshipAppeal.objects.create(
        application=inscricao, text="O certificado cobre os dois semestres."
    )
    recurso.judge(
        outcome=AppealOutcome.GRANTED,
        reasoning="Certificado confere: dois semestres.",
        at=JULGADO_EM,
    )
    recurso.save()

    # É a comissão que refaz o lançamento — pode, porque a edição em
    # `appeals_under_review` continua liberando a análise.
    assert edicao.committee_can_review() is True
    lancamento.committee_score = Decimal("1.00")
    lancamento.committee_note = ""
    lancamento.save(update_fields=["committee_score", "committee_note"])

    # Nenhuma rotina de recálculo foi chamada: a nota é derivada.
    inscricao.refresh_from_db()
    assert inscricao.committee_score() == Decimal("1.00")


def test_o_recurso_nao_tem_model_de_anexo():
    """Guarda contra o "conserto por simetria com as isoladas": o item 1.3
    do edital veta postagem de documento fora do prazo de inscrição."""
    relacoes = {r.get_accessor_name() for r in ScholarshipAppeal._meta.related_objects}

    assert relacoes == set()
