"""Realocação de vaga e convocação de etapa.

A maior parte roda em memória (`clean()` e transições não tocam o
banco); os testes com `django_db` são os que provam constraint ou
consulta — unique do e-mail, check de `sent_at` e a recusa de `save()`
em realocação já gravada.
"""

from datetime import UTC, date, datetime

import pytest
from django.db import IntegrityError, transaction

from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.selection.models import (
    Application,
    Convocation,
    ConvocationEmail,
    EmailDeliveryStatus,
    QuotaCategory,
    ReallocationKind,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionProcessStatus,
    SelectionStage,
    Vacancy,
    VacancyReallocation,
    gerar_protocolo,
)

DECISAO = date(2026, 3, 10)
ENVIO = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)


def _edital_publicado(pk: int = 1) -> SelectionProcess:
    return SelectionProcess(
        pk=pk,
        kind=SelectionKind.REGULAR,
        year=2027,
        title="Edital Regular 2027",
        status=SelectionProcessStatus.PUBLISHED,
        convocation_subject="Convocação — {etapa}",
        convocation_body="{nome} ({protocolo}) em {data_hora}, no {local}.",
    )


def _vaga(
    edital: SelectionProcess,
    pk: int,
    *,
    level: str = SelectionLevel.MASTERS,
    project_id: int | None = 7,
    research_line_id: int | None = None,
    quota: str = QuotaCategory.OPEN,
    quantity: int = 5,
) -> Vacancy:
    return Vacancy(
        pk=pk,
        process=edital,
        level=level,
        project_id=project_id,
        research_line_id=research_line_id,
        quota_category=quota,
        quantity=quantity,
    )


def _realocacao(
    edital: SelectionProcess,
    origem: Vacancy,
    destino: Vacancy,
    *,
    kind: str = ReallocationKind.LEVEL_TRANSFER,
    quantity: int = 1,
) -> VacancyReallocation:
    return VacancyReallocation(
        program_id=1,
        process=edital,
        kind=kind,
        from_vacancy=origem,
        to_vacancy=destino,
        quantity=quantity,
        reason="Sobrou vaga de mestrado.",
        decided_on=DECISAO,
        decided_by_note="Ofício 12/2026",
    )


# ---------------------------------------------------------------------------
# VacancyReallocation.clean()
# ---------------------------------------------------------------------------


def test_transferencia_entre_niveis_no_mesmo_alvo_passa():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE)

    _realocacao(edital, origem, destino).clean()


def test_retificacao_no_mesmo_nivel_com_alvo_diferente_passa():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, project_id=7)
    destino = _vaga(edital, 2, project_id=8)

    _realocacao(
        edital, origem, destino, kind=ReallocationKind.NOTICE_RECTIFICATION
    ).clean()


def test_vagas_de_editais_diferentes_dao_process_mismatch():
    edital = _edital_publicado()
    outro = _edital_publicado(pk=2)
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS)
    destino = _vaga(outro, 2, level=SelectionLevel.DOCTORATE)

    with pytest.raises(DomainError) as erro:
        _realocacao(edital, origem, destino).clean()
    assert erro.value.code == "process_mismatch"


def test_edital_em_rascunho_nao_realoca():
    edital = _edital_publicado()
    edital.status = SelectionProcessStatus.DRAFT
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE)

    with pytest.raises(DomainError) as erro:
        _realocacao(edital, origem, destino).clean()
    assert erro.value.code == "process_still_draft"


def test_transferencia_entre_niveis_exige_alvo_igual():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS, project_id=7)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE, project_id=8)

    with pytest.raises(DomainError) as erro:
        _realocacao(edital, origem, destino).clean()
    assert erro.value.code == "same_target_required"


def test_transferencia_entre_niveis_exige_niveis_diferentes():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS)
    destino = _vaga(edital, 2, level=SelectionLevel.MASTERS)

    with pytest.raises(DomainError) as erro:
        _realocacao(edital, origem, destino).clean()
    assert erro.value.code == "same_target_required"


def test_retificacao_exige_mesmo_nivel():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE)

    with pytest.raises(DomainError) as erro:
        _realocacao(
            edital, origem, destino, kind=ReallocationKind.NOTICE_RECTIFICATION
        ).clean()
    assert erro.value.code == "same_level_required"


def test_categoria_de_cota_e_preservada():
    """Assunção do plano: a comissão não converte cota em ampla."""
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS, quota=QuotaCategory.OPEN)
    destino = _vaga(
        edital, 2, level=SelectionLevel.DOCTORATE, quota=QuotaCategory.RACIAL
    )

    with pytest.raises(DomainError) as erro:
        _realocacao(edital, origem, destino).clean()
    assert erro.value.code == "quota_category_must_be_preserved"


def test_saldo_insuficiente_na_origem():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS, quantity=2)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE)

    with pytest.raises(DomainError) as erro:
        _realocacao(edital, origem, destino, quantity=3).clean()
    assert erro.value.code == "insufficient_vacancies"


def test_esvaziar_a_origem_e_permitido():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS, quantity=2)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE)

    _realocacao(edital, origem, destino, quantity=2).clean()


def test_clean_sem_vagas_atribuidas_nao_estoura():
    VacancyReallocation(kind=ReallocationKind.LEVEL_TRANSFER).clean()


# ---------------------------------------------------------------------------
# VacancyReallocation.apply_to_vacancies()
# ---------------------------------------------------------------------------


def test_apply_move_a_quantidade_entre_as_vagas():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS, quantity=5)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE, quantity=1)

    _realocacao(edital, origem, destino, quantity=2).apply_to_vacancies()

    assert (origem.quantity, destino.quantity) == (3, 3)


def test_apply_recusa_saldo_insuficiente():
    edital = _edital_publicado()
    origem = _vaga(edital, 1, level=SelectionLevel.MASTERS, quantity=1)
    destino = _vaga(edital, 2, level=SelectionLevel.DOCTORATE, quantity=0)

    with pytest.raises(DomainError) as erro:
        _realocacao(edital, origem, destino, quantity=2).apply_to_vacancies()
    assert erro.value.code == "insufficient_vacancies"
    assert (origem.quantity, destino.quantity) == (1, 0)


# ---------------------------------------------------------------------------
# Convocation
# ---------------------------------------------------------------------------


def _etapa(edital: SelectionProcess, pk: int = 3) -> SelectionStage:
    return SelectionStage(
        pk=pk,
        process=edital,
        name="Prova oral",
        order=2,
        session_at=datetime(2026, 4, 1, 17, 30, tzinfo=UTC),
        location="Sala 200",
    )


class _CandidatoFalso:
    """Duck typing do que `renderizar_convocacao` precisa."""

    full_name = "Ana Lima"
    protocol = "PS2027R-ABCD1234"
    email = "ana@example.com"


def _inscricao_em_memoria(process_id: int) -> Application:
    """`ConvocationEmail.application` é FK: o Django recusa qualquer
    objeto que não seja `Application`, mesmo sem banco."""
    return Application(
        process_id=process_id,
        full_name=_CandidatoFalso.full_name,
        protocol=_CandidatoFalso.protocol,
        email=_CandidatoFalso.email,
    )


def test_from_process_copia_o_template_do_edital():
    edital = _edital_publicado()
    lote = Convocation.from_process(edital, _etapa(edital))

    assert lote.subject == edital.convocation_subject
    assert lote.body_template == edital.convocation_body


def test_render_for_usa_a_copia_e_nao_o_template_atual():
    edital = _edital_publicado()
    lote = Convocation.from_process(edital, _etapa(edital))
    edital.convocation_subject = "Assunto novo"

    assunto, corpo = lote.render_for(_CandidatoFalso())

    assert assunto == "Convocação — Prova oral"
    # 17:30 UTC no fuso do projeto (America/Sao_Paulo) é 14:30.
    assert corpo == "Ana Lima (PS2027R-ABCD1234) em 01/04/2026 14:30, no Sala 200."


def test_render_convocation_do_edital_delega_ao_helper():
    edital = _edital_publicado()
    etapa = _etapa(edital)

    assert edital.render_convocation(_CandidatoFalso(), etapa) == Convocation(
        process=edital,
        stage=etapa,
        subject=edital.convocation_subject,
        body_template=edital.convocation_body,
    ).render_for(_CandidatoFalso())


def test_email_for_nasce_pendente_com_texto_congelado():
    edital = _edital_publicado()
    lote = Convocation.from_process(edital, _etapa(edital))

    email = lote.email_for(_inscricao_em_memoria(edital.pk))

    assert email.status == EmailDeliveryStatus.PENDING
    assert email.attempts == 0
    assert email.sent_at is None
    assert email.to_email == "ana@example.com"
    assert email.rendered_subject == "Convocação — Prova oral"


def test_convocacao_com_etapa_de_outro_edital():
    edital = _edital_publicado()
    outro = _edital_publicado(pk=2)
    lote = Convocation.from_process(edital, _etapa(outro))

    with pytest.raises(DomainError) as erro:
        lote.clean()
    assert erro.value.code == "stage_mismatch"


@pytest.mark.parametrize(("assunto", "corpo"), [("", "corpo"), ("assunto", "   ")])
def test_convocacao_sem_template_no_edital(assunto: str, corpo: str):
    edital = _edital_publicado()
    edital.convocation_subject = assunto
    edital.convocation_body = corpo
    lote = Convocation.from_process(edital, _etapa(edital))

    with pytest.raises(DomainError) as erro:
        lote.clean()
    assert erro.value.code == "convocation_template_missing"


# ---------------------------------------------------------------------------
# ConvocationEmail — transições
# ---------------------------------------------------------------------------


def test_mark_sent_carimba_conta_tentativa_e_limpa_o_erro():
    email = ConvocationEmail(status=EmailDeliveryStatus.FAILED, error="timeout")
    email.attempts = 1

    email.mark_sent(ENVIO)

    assert email.status == EmailDeliveryStatus.SENT
    assert email.sent_at == ENVIO
    assert email.attempts == 2
    assert email.error == ""


def test_mark_failed_guarda_o_motivo_e_conta_tentativa():
    email = ConvocationEmail()

    email.mark_failed("SMTPRecipientsRefused")

    assert email.status == EmailDeliveryStatus.FAILED
    assert email.error == "SMTPRecipientsRefused"
    assert email.attempts == 1
    assert email.sent_at is None


def test_tentativas_acumulam_entre_falhas():
    email = ConvocationEmail()
    email.mark_failed("um")
    email.mark_failed("dois")

    assert email.attempts == 2
    assert email.error == "dois"


def test_email_ja_enviado_nao_e_reenviado():
    email = ConvocationEmail()
    email.mark_sent(ENVIO)

    with pytest.raises(InvalidStateTransition) as erro:
        email.mark_sent(ENVIO)
    assert erro.value.code == "email_already_sent"


def test_email_ja_enviado_nao_vira_falha():
    email = ConvocationEmail()
    email.mark_sent(ENVIO)

    with pytest.raises(InvalidStateTransition) as erro:
        email.mark_failed("tarde demais")
    assert erro.value.code == "email_already_sent"


def test_email_de_inscricao_de_outro_edital():
    edital = _edital_publicado()
    lote = Convocation.from_process(edital, _etapa(edital))
    email = ConvocationEmail(
        convocation=lote,
        application=_inscricao_em_memoria(process_id=99),
        to_email="x@y.z",
    )

    with pytest.raises(DomainError) as erro:
        email.clean()
    assert erro.value.code == "application_from_other_process"


# ---------------------------------------------------------------------------
# Com banco: constraints e consultas
# ---------------------------------------------------------------------------


@pytest.fixture
def vagas(program, edital_regular, projeto) -> tuple[Vacancy, Vacancy]:
    """Mestrado (5) e doutorado (1) no mesmo projeto, ampla concorrência."""

    def criar(level: str, quantidade: int) -> Vacancy:
        vaga = Vacancy(
            program=program,
            process=edital_regular,
            level=level,
            project=projeto,
            quota_category=QuotaCategory.OPEN,
            quantity=quantidade,
        )
        vaga.clean()
        vaga.save()
        return vaga

    return criar(SelectionLevel.MASTERS, 5), criar(SelectionLevel.DOCTORATE, 1)


@pytest.mark.django_db
def test_realocacao_gravada_nao_pode_ser_alterada(program, edital_regular, vagas):
    origem, destino = vagas
    realocacao = _realocacao(edital_regular, origem, destino, quantity=2)
    realocacao.program = program
    realocacao.clean()
    realocacao.save()

    realocacao.quantity = 3
    with pytest.raises(InvalidStateTransition) as erro:
        realocacao.save()
    assert erro.value.code == "reallocation_is_immutable"
    assert VacancyReallocation.objects.get(pk=realocacao.pk).quantity == 2


@pytest.mark.django_db
def test_realocacao_para_a_propria_vaga_bate_na_constraint(
    program, edital_regular, vagas
):
    origem, _ = vagas
    with pytest.raises(IntegrityError), transaction.atomic():
        VacancyReallocation.objects.create(
            program=program,
            process=edital_regular,
            kind=ReallocationKind.NOTICE_RECTIFICATION,
            from_vacancy=origem,
            to_vacancy=origem,
            quantity=1,
            reason="—",
            decided_on=DECISAO,
            decided_by_note="Ofício 1/2026",
        )


@pytest.mark.django_db
def test_realocacao_de_quantidade_zero_bate_na_constraint(
    program, edital_regular, vagas
):
    origem, destino = vagas
    with pytest.raises(IntegrityError), transaction.atomic():
        VacancyReallocation.objects.create(
            program=program,
            process=edital_regular,
            kind=ReallocationKind.LEVEL_TRANSFER,
            from_vacancy=origem,
            to_vacancy=destino,
            quantity=0,
            reason="—",
            decided_on=DECISAO,
            decided_by_note="Ofício 1/2026",
        )


@pytest.fixture
def convocacao(program, edital_regular) -> Convocation:
    lote = Convocation.from_process(
        edital_regular, edital_regular.stages.get(order=1), program=program
    )
    lote.clean()
    lote.save()
    return lote


@pytest.mark.django_db
def test_mesma_inscricao_uma_vez_por_lote(convocacao, inscricao):
    email = convocacao.email_for(inscricao)
    email.clean()
    email.save()

    repetido = convocacao.email_for(inscricao)
    with pytest.raises(DomainError) as erro:
        repetido.clean()
    assert erro.value.code == "duplicate_convocation_email"

    with pytest.raises(IntegrityError), transaction.atomic():
        repetido.save()


@pytest.mark.django_db
def test_enviado_sem_carimbo_bate_na_constraint(convocacao, inscricao):
    email = convocacao.email_for(inscricao)
    email.status = EmailDeliveryStatus.SENT

    with pytest.raises(IntegrityError), transaction.atomic():
        email.save()


@pytest.mark.django_db
def test_pendente_com_carimbo_bate_na_constraint(convocacao, inscricao):
    email = convocacao.email_for(inscricao)
    email.sent_at = ENVIO

    with pytest.raises(IntegrityError), transaction.atomic():
        email.save()


@pytest.mark.django_db
def test_to_send_pega_pendente_e_falhado_mas_nao_enviado(
    program, convocacao, inscricao, edital_regular, projeto
):
    def outra_inscricao(nome: str, cpf: str, email: str) -> Application:
        candidato = Application(
            program=program,
            process=edital_regular,
            protocol=gerar_protocolo(edital_regular),
            full_name=nome,
            email=email,
            cpf=cpf,
            birth_date=date(1990, 1, 1),
            level=SelectionLevel.MASTERS,
            project=projeto,
            quota_category=QuotaCategory.OPEN,
            submitted_at=ENVIO,
        )
        candidato.clean()
        candidato.homologate(at=ENVIO)
        candidato.save()
        return candidato

    enviado = convocacao.email_for(inscricao)
    enviado.mark_sent(ENVIO)
    enviado.save()

    falhado = convocacao.email_for(outra_inscricao("Beto", "11144477735", "b@e.com"))
    falhado.mark_failed("caixa cheia")
    falhado.save()

    pendente = convocacao.email_for(outra_inscricao("Caio", "12345678909", "c@e.com"))
    pendente.save()

    assert set(convocacao.emails.to_send()) == {falhado, pendente}
    assert list(convocacao.emails.sent()) == [enviado]
    assert list(convocacao.emails.failed()) == [falhado]
    assert list(convocacao.emails.pending()) == [pendente]
