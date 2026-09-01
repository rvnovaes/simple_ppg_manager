"""A retificação da ata assinada — versão `n+1`, pelo service.

Story de fase 2 sem rota e sem tela: `rectify_record` existe para o
`_close_stage` da versão nova ter quem o alimente, e é chamado direto
aqui. O resto do ciclo (congelar, assinar) vai pela API, como nos demais
testes do app — o que se está afirmando é o comportamento de ponta a
ponta, não o da função isolada.

O que este arquivo guarda, e nenhum outro guarda:

- **retificar preserva a versão anterior.** A v1 fica no banco como
  `superseded`, com o PDF que os examinadores assinaram; nada é apagado.
- **a v1 é substituída no ato de criar a v2, não quando a v2 é
  assinada.** O `clean()` da ata não admite duas correntes na mesma
  chave — é por isso que a ordem em `rectify_record` é essa.
- **a nota volta a ser editável sozinha.** `record_frozen` olha a ata
  corrente, e corrente passa a ser a v2 em rascunho.
- **retificar de trás para frente.** Etapa cuja seguinte já congelou não
  se retifica (`next_stage_closed`): reintegrar aqui deixaria viva uma
  pessoa que a etapa seguinte nunca avaliou.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError, InvalidStateTransition
from apps.programs.models import CollectiveProject, Program
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    ExaminationRecord,
    RecordStatus,
    SelectionProcess,
    StageScore,
)
from apps.selection.services import rectify_record

from .test_fechamento_de_etapa import (
    assinar_todos as assinar_todos_,
)
from .test_fechamento_de_etapa import (
    ata_congelada,
    congelar,
    criar_inscricao,
    dar_conta,
    pontuar,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def clients_da_banca(professores, banca_regular: Board) -> list[Client]:
    """Um `Client` próprio por titular: três `force_login` no mesmo client
    fariam o último vencer e as três assinaturas sairiam do mesmo
    professor."""
    clients = []
    for indice, papel in enumerate(("presidente", "membro1", "membro2")):
        sessao = Client()
        sessao.force_login(dar_conta(professores[indice], papel))
        clients.append(sessao)
    return clients


def notas_da_etapa(client: Client, banca: Board, etapa) -> int:
    """Status de um PUT de notas — é o que devolve `record_frozen`."""
    resposta = client.put(
        f"/api/v1/selection/boards/{banca.pk}/stages/{etapa.pk}/scores",
        data=[],
        content_type="application/json",
    )
    return resposta.status_code


def etapa_assinada_com_reprovada(
    clients: list[Client],
    program: Program,
    edital: SelectionProcess,
    banca: Board,
    inscricao: Application,
    projeto: CollectiveProject,
) -> tuple[ExaminationRecord, Application, StageScore]:
    """Primeira etapa fechada com a `inscricao` eliminada (40) e uma
    segunda candidata aprovada (80)."""
    etapa = edital.stages.get(order=1)
    outra = criar_inscricao(program, edital, "Caio Prado", "10001371711", projeto)
    reprovada = pontuar(program, inscricao, etapa, "40")
    pontuar(program, outra, etapa, "80")
    v1 = ata_congelada(clients[0], banca, etapa)
    assinar_todos_(clients, banca, etapa)
    inscricao.refresh_from_db()
    assert inscricao.status == ApplicationStatus.ELIMINATED
    v1.refresh_from_db()
    return v1, outra, reprovada


# --- o caminho inteiro ------------------------------------------------------


def test_retificacao_corrige_a_nota_e_reintegra_o_eliminado(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    projeto: CollectiveProject,
):
    """Ponta a ponta: retificar, corrigir a nota, congelar, assinar — a v1
    fica `superseded` e quem ela eliminou volta a `homologated`."""
    etapa = edital_regular.stages.get(order=1)
    v1, outra, reprovada = etapa_assinada_com_reprovada(
        clients_da_banca, program, edital_regular, banca_regular, inscricao, projeto
    )

    v2 = rectify_record(record=v1, reason="Erro de digitação na nota da Ana.")

    assert v2.version == 2
    assert v2.supersedes_id == v1.pk
    assert v2.status == RecordStatus.DRAFT
    assert v2.rectification_reason == "Erro de digitação na nota da Ana."
    assert v2.board_id == v1.board_id
    # A v1 é substituída no ato: o `clean()` não admite duas correntes.
    v1.refresh_from_db()
    assert v1.status == RecordStatus.SUPERSEDED
    assert v1.pdf  # o papel que os três assinaram continua lá
    # As linhas da v2 são as mesmas pessoas da v1, inclusive a eliminada.
    assert sorted(linha["application_id"] for linha in v2.content) == sorted(
        [inscricao.pk, outra.pk]
    )

    reprovada.refresh_from_db()
    reprovada.score = Decimal("88.00")
    reprovada.save(update_fields=["score"])
    congelar(clients_da_banca[0], banca_regular, etapa)
    assinar_todos_(clients_da_banca, banca_regular, etapa)

    v2.refresh_from_db()
    inscricao.refresh_from_db()
    outra.refresh_from_db()
    assert v2.status == RecordStatus.SIGNED
    assert inscricao.status == ApplicationStatus.HOMOLOGATED
    assert inscricao.eliminated_at_stage is None
    assert outra.status == ApplicationStatus.HOMOLOGATED
    assert [
        linha["score"]
        for linha in v2.content
        if linha["application_id"] == inscricao.pk
    ] == ["88.00"]


def test_retificacao_libera_a_nota_para_edicao(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    projeto: CollectiveProject,
):
    """Com a v1 assinada a nota é só leitura; com a v2 em rascunho ela
    volta a ser editável, sem nenhuma liberação explícita."""
    etapa = edital_regular.stages.get(order=1)
    v1, _outra, _reprovada = etapa_assinada_com_reprovada(
        clients_da_banca, program, edital_regular, banca_regular, inscricao, projeto
    )
    assert notas_da_etapa(clients_da_banca[0], banca_regular, etapa) == 409

    rectify_record(record=v1, reason="Nota trocada entre candidatos.")

    assert notas_da_etapa(clients_da_banca[0], banca_regular, etapa) == 200


def test_retificacao_audita_o_motivo(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    projeto: CollectiveProject,
):
    v1, _outra, _reprovada = etapa_assinada_com_reprovada(
        clients_da_banca, program, edital_regular, banca_regular, inscricao, projeto
    )

    v2 = rectify_record(record=v1, reason="  Erro na soma dos itens.  ")

    evento = AuditLog.objects.filter(event="selection.record.rectify").get()
    assert evento.program_id == program.pk
    assert evento.target_id == str(v2.pk)
    assert evento.payload["version"] == 2
    assert evento.payload["supersedes_id"] == v1.pk
    assert evento.payload["reason"] == "Erro na soma dos itens."
    assert evento.payload["rows"] == 2
    assert v2.rectification_reason == "Erro na soma dos itens."


# --- recusas ----------------------------------------------------------------


def test_ata_nao_assinada_nao_se_retifica(
    clients_da_banca: list[Client],
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    """Congelada e sem assinatura o caminho é reabrir, não versionar."""
    etapa = edital_regular.stages.get(order=1)
    ata = ata_congelada(clients_da_banca[0], banca_regular, etapa)

    with pytest.raises(InvalidStateTransition) as erro:
        rectify_record(record=ata, reason="Qualquer motivo.")

    assert erro.value.code == "record_not_signed"
    ata.refresh_from_db()
    assert ata.status == RecordStatus.AWAITING_SIGNATURES
    assert not ExaminationRecord.objects.filter(version=2).exists()


def test_retificacao_exige_motivo(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    projeto: CollectiveProject,
):
    """O motivo vai no PDF da versão nova: sem ele a v2 não explica por
    que existe."""
    v1, _outra, _reprovada = etapa_assinada_com_reprovada(
        clients_da_banca, program, edital_regular, banca_regular, inscricao, projeto
    )

    with pytest.raises(DomainError) as erro:
        rectify_record(record=v1, reason="   ")

    assert erro.value.code == "rectification_reason_required"
    v1.refresh_from_db()
    assert v1.status == RecordStatus.SIGNED


def test_nao_retifica_etapa_cuja_seguinte_ja_congelou(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    """A etapa 2 foi decidida sobre quem a 1 promoveu: retificar a 1 aqui
    deixaria viva gente que a 2 nunca avaliou."""
    primeira = edital_regular.stages.get(order=1)
    segunda = edital_regular.stages.get(order=2)
    v1 = ata_congelada(clients_da_banca[0], banca_regular, primeira)
    assinar_todos_(clients_da_banca, banca_regular, primeira)
    pontuar(program, inscricao, segunda, "90")
    ata_congelada(clients_da_banca[0], banca_regular, segunda)
    v1.refresh_from_db()

    with pytest.raises(InvalidStateTransition) as erro:
        rectify_record(record=v1, reason="Nota errada na primeira etapa.")

    assert erro.value.code == "next_stage_closed"
    v1.refresh_from_db()
    assert v1.status == RecordStatus.SIGNED


def test_retifica_com_a_seguinte_apenas_em_rascunho(
    clients_da_banca: list[Client],
    program: Program,
    banca_regular: Board,
    edital_regular: SelectionProcess,
    inscricao: Application,
    nota: StageScore,
):
    """Rascunho da etapa seguinte não decide nada — não barra."""
    primeira = edital_regular.stages.get(order=1)
    segunda = edital_regular.stages.get(order=2)
    v1 = ata_congelada(clients_da_banca[0], banca_regular, primeira)
    assinar_todos_(clients_da_banca, banca_regular, primeira)
    criada = clients_da_banca[0].post(
        f"/api/v1/selection/boards/{banca_regular.pk}/stages/{segunda.pk}/record"
    )
    assert criada.status_code == 201, criada.content
    v1.refresh_from_db()

    v2 = rectify_record(record=v1, reason="Nota errada na primeira etapa.")

    assert v2.version == 2
