"""Invariantes da vida acadêmica.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
Os pks são atribuídos à mão só para as FKs terem id — nada é salvo.
"""

from datetime import UTC, date, datetime

import pytest

from apps.academic.models import (
    DisciplineOffering,
    EnrollmentAdjustmentRequest,
    IsolatedEnrollmentCycle,
    IsolatedEnrollmentRequest,
    Student,
    Teacher,
)
from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.people.models import Person
from apps.programs.models import AcademicTerm, Discipline, Program


def _professor(*, program: Program, person: Person) -> Teacher:
    return Teacher(
        program=program,
        person=person,
        category=Teacher.Category.PERMANENT,
        academic_degree=Teacher.AcademicDegree.DOCTORATE,
        accredited_since=date(2020, 3, 1),
    )


def test_clean_aceita_professor_no_mesmo_programa_da_pessoa():
    programa = Program(pk=1, acronym="PPGD")
    pessoa = Person(pk=1, program=programa, full_name="Ana Lima")

    _professor(program=programa, person=pessoa).clean()


def test_clean_rejeita_professor_em_programa_diferente_do_da_pessoa():
    pessoa = Person(pk=1, program=Program(pk=1, acronym="PPGD"), full_name="Ana Lima")
    outro = Program(pk=2, acronym="PPGA")

    with pytest.raises(DomainError) as exc:
        _professor(program=outro, person=pessoa).clean()

    assert exc.value.code == "program_mismatch"
    assert exc.value.status_code == 400


def test_clean_sem_pessoa_nao_levanta():
    """Obrigatoriedade da pessoa é da borda e do NOT NULL, não deste invariante."""
    professor = Teacher(
        program=Program(pk=1, acronym="PPGD"),
        category=Teacher.Category.VISITING,
        academic_degree=Teacher.AcademicDegree.HABILITATION,
        accredited_since=date(2020, 3, 1),
    )

    professor.clean()


def _aluno(**kwargs) -> Student:
    campos = {
        "program": Program(pk=1, acronym="PPGD"),
        "level": Student.Level.MASTERS,
        "admission_date": date(2026, 3, 2),
    }
    campos.update(kwargs)
    return Student(**campos)


def test_prazo_padrao_do_mestrado_e_de_dois_anos():
    assert _aluno().default_deadline() == date(2028, 3, 2)


def test_prazo_padrao_do_doutorado_e_de_quatro_anos():
    aluno = _aluno(level=Student.Level.DOCTORATE)

    assert aluno.default_deadline() == date(2030, 3, 2)


def test_prazo_a_partir_de_29_de_fevereiro_cai_em_28():
    """2024 é bissexto, 2026 não — o mestrado que entrou em 29/02/2024
    vence em 28/02/2026. Aritmética de ano, sem python-dateutil.
    """
    aluno = _aluno(admission_date=date(2024, 2, 29))

    assert aluno.default_deadline() == date(2026, 2, 28)


def test_prazo_a_partir_de_29_de_fevereiro_para_ano_bissexto_mantem_o_dia():
    aluno = _aluno(admission_date=date(2024, 2, 29), level=Student.Level.DOCTORATE)

    assert aluno.default_deadline() == date(2028, 2, 29)


def test_prazo_sem_ingresso_ou_nivel_e_none():
    assert _aluno(admission_date=None).default_deadline() is None
    assert _aluno(level=None).default_deadline() is None


def test_clean_rejeita_aluno_em_programa_diferente_do_da_pessoa():
    pessoa = Person(pk=1, program=Program(pk=1, acronym="PPGD"), full_name="Ana Lima")
    aluno = _aluno(program=Program(pk=2, acronym="PPGA"), person=pessoa)

    with pytest.raises(DomainError) as exc:
        aluno.clean()

    assert exc.value.code == "program_mismatch"


def _acerto(**kwargs) -> EnrollmentAdjustmentRequest:
    programa = Program(pk=1, acronym="PPGD")
    campos = {
        "program": programa,
        "student": _aluno(pk=1, program=programa),
        "term": AcademicTerm(pk=1, year=2026, half=1),
    }
    campos.update(kwargs)
    return EnrollmentAdjustmentRequest(**campos)


def test_aprovar_solicitacao_aberta_muda_status_e_carimba_a_decisao():
    acerto = _acerto()

    acerto.approve(note="De acordo.")

    assert acerto.status == EnrollmentAdjustmentRequest.Status.APPROVED
    assert acerto.decision_note == "De acordo."
    assert acerto.decided_at is not None


def test_recusar_solicitacao_aberta_muda_status_e_carimba_a_decisao():
    acerto = _acerto()

    acerto.reject(note="Disciplina não é da linha do aluno.")

    assert acerto.status == EnrollmentAdjustmentRequest.Status.REJECTED
    assert acerto.decision_note == "Disciplina não é da linha do aluno."
    assert acerto.decided_at is not None


def test_aprovar_solicitacao_ja_decidida_levanta():
    acerto = _acerto(status=EnrollmentAdjustmentRequest.Status.REJECTED)

    with pytest.raises(InvalidStateTransition) as exc:
        acerto.approve()

    assert exc.value.status_code == 409


def test_recusar_solicitacao_ja_decidida_levanta():
    acerto = _acerto(status=EnrollmentAdjustmentRequest.Status.APPROVED)

    with pytest.raises(InvalidStateTransition):
        acerto.reject(note="Tarde demais.")


def test_recusar_sem_motivo_levanta():
    """Espaço em branco não é motivo — o aluno leria uma recusa vazia."""
    acerto = _acerto()

    with pytest.raises(DomainError) as exc:
        acerto.reject(note="   ")

    assert exc.value.code == "rejection_requires_note"
    assert acerto.status == EnrollmentAdjustmentRequest.Status.OPEN


def test_clean_rejeita_acerto_em_programa_diferente_do_do_aluno():
    acerto = _acerto(program=Program(pk=2, acronym="PPGA"))

    with pytest.raises(DomainError) as exc:
        acerto.clean()

    assert exc.value.code == "program_mismatch"


def _ciclo(**kwargs) -> IsolatedEnrollmentCycle:
    """Ciclo com o calendário em ordem; cada teste quebra uma data só."""
    padrao = {
        "program": Program(pk=1, acronym="PPGD"),
        "term": AcademicTerm(pk=1, year=2026, half=1),
        "submission_opens_at": datetime(2026, 2, 1, tzinfo=UTC),
        "submission_closes_at": datetime(2026, 2, 10, tzinfo=UTC),
        "result_published_on": date(2026, 2, 12),
        "appeal_opens_at": datetime(2026, 2, 12, tzinfo=UTC),
        "appeal_closes_at": datetime(2026, 2, 15, tzinfo=UTC),
        "final_result_on": date(2026, 2, 17),
        "payment_closes_at": datetime(2026, 2, 25, tzinfo=UTC),
    }
    return IsolatedEnrollmentCycle(**{**padrao, **kwargs})


def test_clean_aceita_ciclo_com_as_datas_em_ordem():
    _ciclo().clean()


def test_clean_aceita_recurso_comecando_no_instante_em_que_a_inscricao_fecha():
    """Encadear as duas fases no mesmo instante é o edital sem intervalo."""
    _ciclo(appeal_opens_at=datetime(2026, 2, 10, tzinfo=UTC)).clean()


def test_clean_rejeita_inscricao_que_fecha_antes_de_abrir():
    ciclo = _ciclo(submission_closes_at=datetime(2026, 1, 20, tzinfo=UTC))

    with pytest.raises(DomainError) as exc:
        ciclo.clean()

    assert exc.value.code == "invalid_cycle_dates"


def test_clean_rejeita_recurso_que_abre_antes_de_a_inscricao_fechar():
    ciclo = _ciclo(appeal_opens_at=datetime(2026, 2, 5, tzinfo=UTC))

    with pytest.raises(DomainError) as exc:
        ciclo.clean()

    assert exc.value.code == "invalid_cycle_dates"


def test_clean_rejeita_pagamento_que_fecha_antes_do_fim_do_recurso():
    ciclo = _ciclo(payment_closes_at=datetime(2026, 2, 13, tzinfo=UTC))

    with pytest.raises(DomainError) as exc:
        ciclo.clean()

    assert exc.value.code == "invalid_cycle_dates"


def test_clean_sem_data_obrigatoria_nao_levanta():
    """Data ausente é cobrança do schema Ninja e do NOT NULL, não daqui."""
    _ciclo(appeal_closes_at=None).clean()


def test_janela_de_inscricao_inclui_a_abertura_e_exclui_o_fechamento():
    ciclo = _ciclo()

    assert ciclo.submission_open(datetime(2026, 2, 1, tzinfo=UTC))
    assert ciclo.submission_open(datetime(2026, 2, 5, tzinfo=UTC))
    assert not ciclo.submission_open(datetime(2026, 2, 10, tzinfo=UTC))


def test_janela_de_inscricao_recusa_instante_anterior_a_abertura():
    assert not _ciclo().submission_open(datetime(2026, 1, 31, tzinfo=UTC))


def test_janela_de_recurso_responde_dentro_e_fora():
    ciclo = _ciclo()

    assert ciclo.appeal_open(datetime(2026, 2, 13, tzinfo=UTC))
    assert not ciclo.appeal_open(datetime(2026, 2, 11, tzinfo=UTC))
    assert not ciclo.appeal_open(datetime(2026, 2, 15, tzinfo=UTC))


def _oferta(**kwargs) -> DisciplineOffering:
    """Oferta coerente; cada teste troca um relacionado de programa."""
    programa = kwargs.pop("program", None) or Program(pk=1, acronym="PPGD")
    padrao = {
        "program": programa,
        "cycle": _ciclo(pk=1, program=programa),
        "discipline": Discipline(pk=1, program=programa, code="DIR001", name="Teoria"),
        "teacher": _professor(
            program=programa,
            person=Person(pk=1, program=programa, full_name="Ana Lima"),
        ),
        "seats": 10,
    }
    return DisciplineOffering(**{**padrao, **kwargs})


def test_clean_aceita_oferta_com_tudo_no_mesmo_programa():
    _oferta().clean()


def test_clean_rejeita_docente_de_outro_programa():
    outro = Program(pk=2, acronym="PPGA")
    oferta = _oferta(
        teacher=_professor(
            program=outro,
            person=Person(pk=2, program=outro, full_name="Bruno Sá"),
        ),
    )

    with pytest.raises(DomainError) as exc:
        oferta.clean()

    assert exc.value.code == "program_mismatch"
    assert exc.value.status_code == 400


def test_clean_rejeita_disciplina_de_outro_programa():
    outro = Program(pk=2, acronym="PPGA")
    oferta = _oferta(
        discipline=Discipline(pk=2, program=outro, code="ADM001", name="Gestão"),
    )

    with pytest.raises(DomainError) as exc:
        oferta.clean()

    assert exc.value.code == "program_mismatch"


def test_clean_rejeita_ciclo_de_outro_programa():
    outro = Program(pk=2, acronym="PPGA")
    oferta = _oferta(cycle=_ciclo(pk=2, program=outro))

    with pytest.raises(DomainError) as exc:
        oferta.clean()

    assert exc.value.code == "program_mismatch"


def test_clean_sem_relacionado_obrigatorio_nao_levanta():
    """Obrigatoriedade é da borda e do NOT NULL, não deste invariante."""
    programa = Program(pk=1, acronym="PPGD")

    DisciplineOffering(program=programa, seats=5).clean()


def _requerimento(**kwargs) -> IsolatedEnrollmentRequest:
    programa = kwargs.pop("program", None) or Program(pk=1, acronym="PPGD")
    padrao = {
        "program": programa,
        "cycle": _ciclo(pk=1, program=programa),
        "person": Person(pk=1, program=programa, full_name="Carla Reis"),
    }
    return IsolatedEnrollmentRequest(**{**padrao, **kwargs})


def test_requerimento_nasce_em_rascunho_e_com_pagamento_pendente():
    requerimento = _requerimento()

    assert requerimento.status == IsolatedEnrollmentRequest.Status.DRAFT
    assert (
        requerimento.payment_status == IsolatedEnrollmentRequest.PaymentStatus.PENDING
    )
    assert requerimento.is_ufmg_staff is False


def test_clean_aceita_requerimento_com_tudo_no_mesmo_programa():
    _requerimento().clean()


def test_clean_rejeita_candidato_de_outro_programa():
    outro = Program(pk=2, acronym="PPGA")
    requerimento = _requerimento(
        person=Person(pk=2, program=outro, full_name="Davi Melo"),
    )

    with pytest.raises(DomainError) as exc:
        requerimento.clean()

    assert exc.value.code == "program_mismatch"
    assert exc.value.status_code == 400


def test_clean_rejeita_ciclo_de_outro_programa_no_requerimento():
    outro = Program(pk=2, acronym="PPGA")
    requerimento = _requerimento(cycle=_ciclo(pk=2, program=outro))

    with pytest.raises(DomainError) as exc:
        requerimento.clean()

    assert exc.value.code == "program_mismatch"


def test_clean_do_requerimento_sem_relacionado_obrigatorio_nao_levanta():
    """Obrigatoriedade é da borda e do NOT NULL, não deste invariante."""
    IsolatedEnrollmentRequest(program=Program(pk=1, acronym="PPGD")).clean()


# Transições do requerimento de isolada (US-004). O instante entra por
# parâmetro em submit()/appeal(), então a janela é exercitada sem
# congelar o relógio: DENTRO_DA_INSCRICAO e DENTRO_DO_RECURSO são
# coerentes com o calendário de `_ciclo()`.
DENTRO_DA_INSCRICAO = datetime(2026, 2, 5, tzinfo=UTC)
FORA_DA_INSCRICAO = datetime(2026, 2, 20, tzinfo=UTC)
DENTRO_DO_RECURSO = datetime(2026, 2, 13, tzinfo=UTC)
FORA_DO_RECURSO = datetime(2026, 2, 20, tzinfo=UTC)


def test_inscrever_rascunho_dentro_da_janela_carimba_e_muda_status():
    requerimento = _requerimento()

    requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert requerimento.status == IsolatedEnrollmentRequest.Status.SUBMITTED
    assert requerimento.submitted_at == DENTRO_DA_INSCRICAO


def test_inscrever_fora_da_janela_levanta():
    requerimento = _requerimento()

    with pytest.raises(DomainError) as exc:
        requerimento.submit(at=FORA_DA_INSCRICAO)

    assert exc.value.code == "submission_window_closed"
    assert exc.value.status_code == 400
    assert requerimento.status == IsolatedEnrollmentRequest.Status.DRAFT


def test_inscrever_requerimento_ja_inscrito_levanta():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.SUBMITTED)

    with pytest.raises(InvalidStateTransition) as exc:
        requerimento.submit(at=DENTRO_DA_INSCRICAO)

    assert exc.value.status_code == 409


def test_deferir_inscrito_carimba_a_decisao_e_mantem_pagamento_pendente():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.SUBMITTED)

    requerimento.defer(note="Documentação em ordem.")

    assert requerimento.status == IsolatedEnrollmentRequest.Status.DEFERRED
    assert requerimento.decision_note == "Documentação em ordem."
    assert requerimento.decided_at is not None
    assert (
        requerimento.payment_status == IsolatedEnrollmentRequest.PaymentStatus.PENDING
    )


def test_deferir_servidor_da_ufmg_nasce_isento():
    """A isenção é consequência do vínculo, não uma segunda decisão."""
    requerimento = _requerimento(
        status=IsolatedEnrollmentRequest.Status.SUBMITTED,
        is_ufmg_staff=True,
    )

    requerimento.defer()

    assert requerimento.payment_status == IsolatedEnrollmentRequest.PaymentStatus.EXEMPT


def test_deferir_requerimento_ja_decidido_levanta():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.DEFERRED)

    with pytest.raises(InvalidStateTransition):
        requerimento.defer()


def test_indeferir_inscrito_com_motivo_carimba_a_decisao():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.SUBMITTED)

    requerimento.reject(note="Falta o diploma.")

    assert requerimento.status == IsolatedEnrollmentRequest.Status.REJECTED
    assert requerimento.decision_note == "Falta o diploma."
    assert requerimento.decided_at is not None


def test_indeferir_sem_motivo_levanta():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.SUBMITTED)

    with pytest.raises(DomainError) as exc:
        requerimento.reject(note="   ")

    assert exc.value.code == "rejection_requires_note"
    assert requerimento.status == IsolatedEnrollmentRequest.Status.SUBMITTED


def test_cancelar_deferido_devolve_a_vaga():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.DEFERRED)

    requerimento.cancel(note="Não pagou a GRU no prazo.")

    assert requerimento.status == IsolatedEnrollmentRequest.Status.CANCELLED
    assert requerimento.decided_at is not None


def test_cancelar_rascunho_levanta():
    with pytest.raises(InvalidStateTransition):
        _requerimento().cancel()


def test_recorrer_de_indeferido_na_janela_nao_muda_o_status():
    """Recurso é pedido de rejulgamento, não deferimento automático."""
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.REJECTED)

    requerimento.appeal(note="Anexo o diploma que faltava.", at=DENTRO_DO_RECURSO)

    assert requerimento.status == IsolatedEnrollmentRequest.Status.REJECTED
    assert requerimento.appeal_note == "Anexo o diploma que faltava."
    assert requerimento.appealed_at == DENTRO_DO_RECURSO


def test_recorrer_fora_da_janela_levanta():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.REJECTED)

    with pytest.raises(DomainError) as exc:
        requerimento.appeal(note="Anexo o diploma.", at=FORA_DO_RECURSO)

    assert exc.value.code == "appeal_window_closed"


def test_recorrer_de_requerimento_deferido_levanta():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.DEFERRED)

    with pytest.raises(InvalidStateTransition):
        requerimento.appeal(note="Quero mais uma disciplina.", at=DENTRO_DO_RECURSO)


def test_recorrer_sem_razoes_levanta():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.REJECTED)

    with pytest.raises(DomainError) as exc:
        requerimento.appeal(note="", at=DENTRO_DO_RECURSO)

    assert exc.value.code == "appeal_requires_note"


def test_efetivar_deferido_e_pago_vira_matriculado():
    requerimento = _requerimento(
        status=IsolatedEnrollmentRequest.Status.DEFERRED,
        payment_status=IsolatedEnrollmentRequest.PaymentStatus.PAID,
    )

    requerimento.enroll()

    assert requerimento.status == IsolatedEnrollmentRequest.Status.ENROLLED


def test_efetivar_deferido_isento_passa_sem_comprovante():
    requerimento = _requerimento(
        status=IsolatedEnrollmentRequest.Status.DEFERRED,
        payment_status=IsolatedEnrollmentRequest.PaymentStatus.EXEMPT,
    )

    requerimento.enroll()

    assert requerimento.status == IsolatedEnrollmentRequest.Status.ENROLLED


def test_efetivar_sem_pagamento_levanta():
    requerimento = _requerimento(status=IsolatedEnrollmentRequest.Status.DEFERRED)

    with pytest.raises(DomainError) as exc:
        requerimento.enroll()

    assert exc.value.code == "payment_required"
    assert requerimento.status == IsolatedEnrollmentRequest.Status.DEFERRED


def test_efetivar_requerimento_inscrito_levanta():
    requerimento = _requerimento(
        status=IsolatedEnrollmentRequest.Status.SUBMITTED,
        payment_status=IsolatedEnrollmentRequest.PaymentStatus.PAID,
    )

    with pytest.raises(InvalidStateTransition):
        requerimento.enroll()
