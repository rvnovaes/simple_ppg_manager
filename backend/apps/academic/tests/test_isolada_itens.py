"""Itens do requerimento de isolada — nível (b) da pirâmide, com banco.

As duas UniqueConstraint e a contagem de vagas não têm como ser exercitadas
em memória: uma barra o INSERT, a outra conta linhas relacionadas. Por isso
este módulo existe separado de `test_models.py`, que é todo sem banco.
"""

from datetime import UTC, date, datetime

import pytest
from django.db import IntegrityError, transaction

from apps.academic.models import (
    DisciplineOffering,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentItem,
    IsolatedEnrollmentRequest,
)
from apps.academic.tests.conftest import (
    DENTRO_DA_INSCRICAO,
    anexar_documentos_obrigatorios,
    criar_requerimento,
)
from apps.core.exceptions import DomainError
from apps.programs.models import AcademicTerm, Discipline


def test_item_duplicado_na_mesma_oferta_e_rejeitado(requerimento, oferta):
    """Pedir duas vezes a mesma disciplina consumiria duas vagas do mesmo
    candidato — e o edital dá até duas disciplinas, não duas cópias de uma.
    """
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)

    with pytest.raises(IntegrityError), transaction.atomic():
        IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)


def test_duas_pessoas_no_mesmo_rank_da_mesma_oferta_e_rejeitado(program, ciclo, oferta):
    outro = criar_requerimento(program=program, ciclo=ciclo, nome="Davi Melo")
    requerimento = criar_requerimento(program=program, ciclo=ciclo, nome="Elisa Nunes")
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta, rank=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        IsolatedEnrollmentItem.objects.create(request=outro, offering=oferta, rank=1)


def test_varios_itens_sem_classificacao_convivem_na_mesma_oferta(
    program, ciclo, oferta
):
    """Antes de o docente classificar, todo mundo empata em `rank` nulo —
    é o estado normal, e a condição da constraint deixa isso de fora.
    """
    for nome in ("Davi Melo", "Elisa Nunes", "Felipe Cruz"):
        IsolatedEnrollmentItem.objects.create(
            request=criar_requerimento(program=program, ciclo=ciclo, nome=nome),
            offering=oferta,
        )

    assert oferta.items.count() == 3


def test_vagas_contam_deferido_e_matriculado_e_ignoram_inscrito(program, ciclo, oferta):
    situacoes = (
        IsolatedEnrollmentRequest.Status.SUBMITTED,
        IsolatedEnrollmentRequest.Status.DEFERRED,
        IsolatedEnrollmentRequest.Status.ENROLLED,
        IsolatedEnrollmentRequest.Status.CANCELLED,
    )
    for indice, situacao in enumerate(situacoes):
        pedido = criar_requerimento(
            program=program, ciclo=ciclo, nome=f"Pessoa{indice} Silva"
        )
        pedido.status = situacao
        pedido.save(update_fields=["status"])
        IsolatedEnrollmentItem.objects.create(
            request=pedido, offering=oferta, rank=indice + 1
        )

    assert oferta.seats_taken() == 2
    assert oferta.seats_available() == 0


def test_vagas_disponiveis_nunca_ficam_negativas(program, ciclo, oferta):
    """Reduzir `seats` depois dos deferimentos não pode devolver -1: vaga
    negativa não significa nada para quem lê a tela.
    """
    for indice in range(3):
        pedido = criar_requerimento(
            program=program, ciclo=ciclo, nome=f"Pessoa{indice} Souza"
        )
        pedido.status = IsolatedEnrollmentRequest.Status.DEFERRED
        pedido.save(update_fields=["status"])
        IsolatedEnrollmentItem.objects.create(
            request=pedido, offering=oferta, rank=indice + 1
        )

    assert oferta.seats_taken() == 3
    assert oferta.seats_available() == 0


def test_inscrever_com_uma_disciplina_muda_status_e_carimba(requerimento, oferta):
    IsolatedEnrollmentItem.objects.create(request=requerimento, offering=oferta)
    anexar_documentos_obrigatorios(requerimento)

    requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert requerimento.status == IsolatedEnrollmentRequest.Status.SUBMITTED
    assert requerimento.submitted_at == DENTRO_DA_INSCRICAO


def test_inscrever_sem_nenhuma_disciplina_levanta(requerimento):
    with pytest.raises(DomainError) as exc:
        requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert exc.value.code == "invalid_item_count"
    assert exc.value.status_code == 400
    assert requerimento.status == IsolatedEnrollmentRequest.Status.DRAFT


def test_inscrever_com_tres_disciplinas_levanta(requerimento, program, ciclo, docente):
    for codigo in ("DIR002", "DIR003", "DIR004"):
        disciplina = Discipline.objects.create(
            program=program, code=codigo, name=f"Disciplina {codigo}"
        )
        IsolatedEnrollmentItem.objects.create(
            request=requerimento,
            offering=DisciplineOffering.objects.create(
                program=program,
                cycle=ciclo,
                discipline=disciplina,
                teacher=docente,
                seats=5,
            ),
        )

    with pytest.raises(DomainError) as exc:
        requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert exc.value.code == "invalid_item_count"


def test_clean_do_item_rejeita_oferta_de_outro_ciclo(
    program, periodo, requerimento, docente
):
    outro_periodo = AcademicTerm.objects.create(
        year=2026, half=2, starts_on=date(2026, 8, 3), ends_on=date(2026, 12, 19)
    )
    outro_ciclo = IsolatedEnrollmentCycle.objects.create(
        program=program,
        term=outro_periodo,
        submission_opens_at=datetime(2026, 7, 1, tzinfo=UTC),
        submission_closes_at=datetime(2026, 7, 10, tzinfo=UTC),
        result_published_on=date(2026, 7, 12),
        appeal_opens_at=datetime(2026, 7, 12, tzinfo=UTC),
        appeal_closes_at=datetime(2026, 7, 15, tzinfo=UTC),
        final_result_on=date(2026, 7, 17),
        payment_closes_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    disciplina = Discipline.objects.create(program=program, code="DIR009", name="Outra")
    item = IsolatedEnrollmentItem(
        request=requerimento,
        offering=DisciplineOffering.objects.create(
            program=program,
            cycle=outro_ciclo,
            discipline=disciplina,
            teacher=docente,
            seats=3,
        ),
    )

    with pytest.raises(DomainError) as exc:
        item.clean()

    assert exc.value.code == "cycle_mismatch"
