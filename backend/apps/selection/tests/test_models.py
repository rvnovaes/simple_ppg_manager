"""Invariantes do edital e das etapas.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco e sem mock.
Os pks são atribuídos à mão só para as FKs terem id — nada é salvo. Os
testes que precisam da UniqueConstraint de verdade ficam no fim, marcados
com `django_db`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.selection.models import (
    CATEGORIAS_POR_TIPO,
    QuotaCategory,
    SelectionKind,
    SelectionProcess,
    SelectionProcessStatus,
    SelectionStage,
    xor_de_alvo,
)

ABERTURA = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
ENCERRAMENTO = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
AGORA = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def _edital(kind: str = SelectionKind.REGULAR, **kwargs) -> SelectionProcess:
    campos = {
        "program": Program(pk=1, acronym="PPGD"),
        "kind": kind,
        "year": 2027,
        "title": "Edital 2027",
        "submission_opens_at": ABERTURA,
        "submission_closes_at": ENCERRAMENTO,
    }
    return SelectionProcess(**{**campos, **kwargs})


# --- janela e clean ---------------------------------------------------------


def test_clean_aceita_janela_em_ordem():
    _edital(program=None).clean()


@pytest.mark.parametrize("encerramento", [ABERTURA, datetime(2025, 12, 1, tzinfo=UTC)])
def test_clean_rejeita_janela_que_fecha_antes_ou_no_instante_de_abrir(encerramento):
    with pytest.raises(DomainError) as exc:
        _edital(program=None, submission_closes_at=encerramento).clean()

    assert exc.value.code == "invalid_submission_window"
    assert exc.value.status_code == 400


def test_submission_open_inclui_abertura_e_exclui_fechamento():
    edital = _edital(status=SelectionProcessStatus.PUBLISHED)

    assert edital.submission_open(ABERTURA)
    assert edital.submission_open(AGORA)
    assert not edital.submission_open(ENCERRAMENTO)


def test_submission_open_e_falso_em_rascunho_mesmo_dentro_da_janela():
    assert not _edital().submission_open(AGORA)


# --- publish / close / ensure_editable --------------------------------------


def test_publish_carimba_status_e_instante_sem_salvar():
    edital = _edital()

    edital.publish(at=AGORA)

    assert edital.status == SelectionProcessStatus.PUBLISHED
    assert edital.published_at == AGORA
    assert edital.pk is None


@pytest.mark.parametrize(
    "status", [SelectionProcessStatus.PUBLISHED, SelectionProcessStatus.CLOSED]
)
def test_publish_fora_do_rascunho_e_409(status):
    with pytest.raises(InvalidStateTransition) as exc:
        _edital(status=status).publish(at=AGORA)

    assert exc.value.code == "process_not_draft"
    assert exc.value.status_code == 409


def test_close_encerra_edital_publicado():
    edital = _edital(status=SelectionProcessStatus.PUBLISHED)

    edital.close(at=AGORA)

    assert edital.status == SelectionProcessStatus.CLOSED
    assert edital.closed_at == AGORA


@pytest.mark.parametrize(
    "status", [SelectionProcessStatus.DRAFT, SelectionProcessStatus.CLOSED]
)
def test_close_fora_de_publicado_e_409(status):
    with pytest.raises(InvalidStateTransition) as exc:
        _edital(status=status).close(at=AGORA)

    assert exc.value.code == "process_not_published"


def test_ensure_editable_so_passa_em_rascunho():
    _edital().ensure_editable()

    with pytest.raises(InvalidStateTransition) as exc:
        _edital(status=SelectionProcessStatus.PUBLISHED).ensure_editable()

    assert exc.value.code == "process_not_editable"


# --- cota por tipo ----------------------------------------------------------


def test_categorias_por_tipo_cobrem_todas_as_cotas_sem_sobreposicao():
    regular = CATEGORIAS_POR_TIPO[SelectionKind.REGULAR]
    suplementar = CATEGORIAS_POR_TIPO[SelectionKind.SUPPLEMENTARY]

    assert regular & suplementar == set()
    assert regular | suplementar == set(QuotaCategory.values)


@pytest.mark.parametrize("categoria", [QuotaCategory.OPEN, QuotaCategory.RACIAL])
def test_regular_aceita_ampla_e_racial(categoria):
    _edital(SelectionKind.REGULAR).ensure_quota_category(categoria)


@pytest.mark.parametrize(
    "categoria",
    [
        QuotaCategory.DISABILITY,
        QuotaCategory.QUILOMBOLA,
        QuotaCategory.TRANS,
        QuotaCategory.INDIGENOUS,
    ],
)
def test_regular_recusa_cotas_do_suplementar(categoria):
    with pytest.raises(DomainError) as exc:
        _edital(SelectionKind.REGULAR).ensure_quota_category(categoria)

    assert exc.value.code == "quota_category_not_allowed"


@pytest.mark.parametrize(
    "categoria",
    [
        QuotaCategory.DISABILITY,
        QuotaCategory.QUILOMBOLA,
        QuotaCategory.TRANS,
        QuotaCategory.INDIGENOUS,
    ],
)
def test_suplementar_aceita_acoes_afirmativas(categoria):
    _edital(SelectionKind.SUPPLEMENTARY).ensure_quota_category(categoria)


@pytest.mark.parametrize("categoria", [QuotaCategory.OPEN, QuotaCategory.RACIAL])
def test_suplementar_recusa_ampla_e_racial(categoria):
    with pytest.raises(DomainError) as exc:
        _edital(SelectionKind.SUPPLEMENTARY).ensure_quota_category(categoria)

    assert exc.value.code == "quota_category_not_allowed"


# --- alvo por tipo ----------------------------------------------------------

PROJETO = CollectiveProject(pk=1, name="Projeto A")
LINHA = ResearchLine(pk=1, name="Linha A")


def test_regular_exige_projeto_sem_linha():
    _edital(SelectionKind.REGULAR).ensure_target(PROJETO, None)


@pytest.mark.parametrize(
    ("projeto", "linha"), [(None, LINHA), (None, None), (PROJETO, LINHA)]
)
def test_regular_recusa_alvo_que_nao_e_so_projeto(projeto, linha):
    with pytest.raises(DomainError) as exc:
        _edital(SelectionKind.REGULAR).ensure_target(projeto, linha)

    assert exc.value.code == "target_mismatch"


def test_suplementar_exige_linha_sem_projeto():
    _edital(SelectionKind.SUPPLEMENTARY).ensure_target(None, LINHA)


@pytest.mark.parametrize(
    ("projeto", "linha"), [(PROJETO, None), (None, None), (PROJETO, LINHA)]
)
def test_suplementar_recusa_alvo_que_nao_e_so_linha(projeto, linha):
    with pytest.raises(DomainError) as exc:
        _edital(SelectionKind.SUPPLEMENTARY).ensure_target(projeto, linha)

    assert exc.value.code == "target_mismatch"


def test_xor_de_alvo_nomeia_a_constraint_pelo_model():
    constraint = xor_de_alvo("vacancy")

    assert constraint.name == "vacancy_exactly_one_target"


# --- convocação -------------------------------------------------------------


@dataclass
class _Inscricao:
    """Stub: `Application` só chega em f0-application-document; o método
    é duck typing e precisa só destes dois atributos."""

    full_name: str
    protocol: str


def test_render_convocation_preenche_placeholders():
    edital = _edital(
        title="Edital Regular 2027",
        convocation_subject="Convocação — {etapa}",
        convocation_body=(
            "{nome} ({protocolo}): {etapa} em {data_hora}, {local}. {edital}"
        ),
    )
    etapa = SelectionStage(
        process=edital,
        name="Prova oral",
        order=2,
        session_at=datetime(2026, 3, 10, 14, 30, tzinfo=UTC),
        location="Sala 101",
    )

    assunto, corpo = edital.render_convocation(
        _Inscricao(full_name="Ana Lima", protocol="PS2027R-ABCDEF01"), etapa
    )

    assert assunto == "Convocação — Prova oral"
    assert corpo == (
        "Ana Lima (PS2027R-ABCDEF01): Prova oral em 10/03/2026 11:30, Sala 101. "
        "Edital Regular 2027"
    )


def test_render_convocation_deixa_placeholder_desconhecido_literal():
    edital = _edital(
        convocation_subject="{etapa}", convocation_body="Olá {nome}, sala {sala}."
    )
    etapa = SelectionStage(process=edital, name="Entrevista", order=3)

    _, corpo = edital.render_convocation(_Inscricao("Ana", "PS2027R-1"), etapa)

    assert corpo == "Olá Ana, sala {sala}."


def test_render_convocation_sem_sessao_marcada_deixa_data_vazia():
    edital = _edital(convocation_body="[{data_hora}]")
    etapa = SelectionStage(process=edital, name="Entrevista", order=3)

    _, corpo = edital.render_convocation(_Inscricao("Ana", "PS2027R-1"), etapa)

    assert corpo == "[]"


# --- etapa ------------------------------------------------------------------


def test_stage_clean_rejeita_ordem_zero():
    with pytest.raises(DomainError) as exc:
        SelectionStage(name="Entrevista", order=0).clean()

    assert exc.value.code == "invalid_stage_order"


# --- com banco: espelhos das UniqueConstraints -------------------------------


@pytest.mark.django_db
def test_clean_rejeita_segundo_edital_do_mesmo_tipo_no_ano(edital_regular):
    with pytest.raises(DomainError) as exc:
        _edital(program=edital_regular.program).clean()

    assert exc.value.code == "duplicate_process"


@pytest.mark.django_db
def test_mesmo_ano_em_tipos_diferentes_e_permitido(edital_regular):
    _edital(SelectionKind.SUPPLEMENTARY, program=edital_regular.program).clean()


@pytest.mark.django_db
def test_open_for_submission_filtra_por_janela_e_status(
    edital_regular, edital_suplementar
):
    edital_suplementar.status = SelectionProcessStatus.DRAFT
    edital_suplementar.save()

    abertos = SelectionProcess.objects.open_for_submission(
        datetime(2026, 6, 1, tzinfo=UTC)
    )

    assert list(abertos) == [edital_regular]
    assert not SelectionProcess.objects.open_for_submission(
        datetime(2027, 6, 1, tzinfo=UTC)
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("nome", "ordem", "desempate"),
    [("Outra", 1, None), ("Prova oral", 9, None), ("Outra", 9, 2)],
    ids=["ordem", "nome", "desempate"],
)
def test_stage_clean_rejeita_duplicata_no_edital(
    edital_regular, nome, ordem, desempate
):
    with pytest.raises(DomainError) as exc:
        SelectionStage(
            process=edital_regular, name=nome, order=ordem, tiebreak_rank=desempate
        ).clean()

    assert exc.value.code == "duplicate_stage"


@pytest.mark.django_db
def test_stage_sem_desempate_nao_colide_com_outra_sem_desempate(edital_regular):
    SelectionStage(process=edital_regular, name="Extra", order=9).clean()


@pytest.mark.django_db
def test_stage_is_first_is_last_e_previous(edital_regular):
    primeira, segunda, ultima = edital_regular.stages.order_by("order")

    assert primeira.is_first and not primeira.is_last
    assert primeira.previous() is None
    assert segunda.previous() == primeira
    assert ultima.is_last and not ultima.is_first
    assert ultima.program_id == edital_regular.program_id
