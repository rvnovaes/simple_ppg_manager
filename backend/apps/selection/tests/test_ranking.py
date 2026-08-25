"""Classificação — as funções puras, sem banco.

Nenhum teste aqui usa `django_db`: `rank_regular`/`rank_supplementary` não
tocam o ORM, e é exatamente essa separação que deixa a regra que decide
quem entra no programa ser exercida caso a caso, barato.
"""

from datetime import date
from decimal import Decimal

from apps.selection.models import QuotaCategory, RankingOutcome
from apps.selection.services import (
    RankingCandidate,
    rank_regular,
    rank_supplementary,
    sort_key,
)


def candidato(
    application_id: int,
    *,
    nota: str = "80.00",
    categoria: str = QuotaCategory.OPEN,
    desempates: tuple[str, ...] = (),
    nascimento: date | None = None,
) -> RankingCandidate:
    return RankingCandidate(
        application_id=application_id,
        quota_category=categoria,
        final_score=Decimal(nota),
        tiebreak_scores=tuple(Decimal(nota_de_etapa) for nota_de_etapa in desempates),
        birth_date=nascimento,
    )


def desfechos(resultados):
    return {r.application_id: r.outcome for r in resultados}


def posicoes(resultados):
    return {r.application_id: r.rank for r in resultados}


# ---------------------------------------------------------------------------
# sort_key
# ---------------------------------------------------------------------------


def test_ordem_por_nota_final_decrescente():
    ordenados = sorted(
        [candidato(1, nota="70.00"), candidato(2, nota="90.00")], key=sort_key
    )
    assert [c.application_id for c in ordenados] == [2, 1]


def test_desempate_pela_primeira_etapa():
    a = candidato(1, nota="80.00", desempates=("60.00", "99.00"))
    b = candidato(2, nota="80.00", desempates=("61.00", "10.00"))
    assert sorted([a, b], key=sort_key) == [b, a]


def test_desempate_pela_segunda_etapa_quando_a_primeira_empata():
    a = candidato(1, nota="80.00", desempates=("60.00", "70.00"))
    b = candidato(2, nota="80.00", desempates=("60.00", "71.00"))
    assert sorted([a, b], key=sort_key) == [b, a]


def test_desempate_por_idade_mais_velho_na_frente():
    novo = candidato(1, nascimento=date(1999, 5, 1))
    velho = candidato(2, nascimento=date(1980, 5, 1))
    assert sorted([novo, velho], key=sort_key) == [velho, novo]


def test_sem_data_de_nascimento_fica_atras_de_quem_tem():
    sem_data = candidato(1)
    com_data = candidato(2, nascimento=date(2005, 1, 1))
    assert sorted([sem_data, com_data], key=sort_key) == [com_data, sem_data]


def test_empate_total_ordena_por_application_id_e_marca_tie_unresolved():
    resultados = rank_regular(
        [
            candidato(7, nota="80.00", nascimento=date(1990, 1, 1)),
            candidato(3, nota="80.00", nascimento=date(1990, 1, 1)),
        ],
        open_seats=1,
        racial_seats=0,
    )
    assert posicoes(resultados) == {3: 1, 7: 2}
    assert all(r.tie_unresolved for r in resultados)
    assert desfechos(resultados) == {
        3: RankingOutcome.CLASSIFIED_OPEN,
        7: RankingOutcome.NOT_CLASSIFIED,
    }


def test_quem_nao_esta_empatado_nao_e_marcado():
    resultados = rank_regular(
        [
            candidato(1, nota="90.00"),
            candidato(2, nota="80.00"),
            candidato(3, nota="80.00"),
        ],
        open_seats=3,
        racial_seats=0,
    )
    marcados = {r.application_id: r.tie_unresolved for r in resultados}
    assert marcados == {1: False, 2: True, 3: True}


# ---------------------------------------------------------------------------
# rank_regular
# ---------------------------------------------------------------------------


def test_cotista_classificado_na_ampla_nao_consome_a_reserva():
    # O cotista 1 é o melhor de todos: entra pela ampla. A reserva continua
    # inteira para o próximo cotista da fila — é o ponto da política.
    resultados = rank_regular(
        [
            candidato(1, nota="95.00", categoria=QuotaCategory.RACIAL),
            candidato(2, nota="90.00"),
            candidato(3, nota="85.00", categoria=QuotaCategory.RACIAL),
            candidato(4, nota="84.00"),
        ],
        open_seats=2,
        racial_seats=1,
    )
    assert desfechos(resultados) == {
        1: RankingOutcome.CLASSIFIED_OPEN,
        2: RankingOutcome.CLASSIFIED_OPEN,
        3: RankingOutcome.CLASSIFIED_QUOTA,
        4: RankingOutcome.NOT_CLASSIFIED,
    }
    assert posicoes(resultados) == {1: 1, 2: 2, 3: 3, 4: 4}


def test_reserva_ociosa_reverte_para_a_ampla_sem_ultrapassar_o_total():
    # Duas reservas raciais, nenhum cotista: as duas viram ampla, e o total
    # classificado continua sendo 1 + 2 = 3 — não 5.
    resultados = rank_regular(
        [candidato(i, nota=f"9{9 - i}.00") for i in range(1, 6)],
        open_seats=1,
        racial_seats=2,
    )
    classificados = [
        r.application_id
        for r in resultados
        if r.outcome != RankingOutcome.NOT_CLASSIFIED
    ]
    assert classificados == [1, 2, 3]
    assert all(
        r.outcome == RankingOutcome.CLASSIFIED_OPEN
        for r in resultados
        if r.application_id in classificados
    )


def test_reserva_parcialmente_ociosa_volta_so_o_que_sobrou():
    resultados = rank_regular(
        [
            candidato(1, nota="90.00"),
            candidato(2, nota="88.00"),
            candidato(3, nota="70.00", categoria=QuotaCategory.RACIAL),
            candidato(4, nota="60.00"),
        ],
        open_seats=1,
        racial_seats=2,
    )
    assert desfechos(resultados) == {
        1: RankingOutcome.CLASSIFIED_OPEN,
        2: RankingOutcome.CLASSIFIED_OPEN,
        3: RankingOutcome.CLASSIFIED_QUOTA,
        4: RankingOutcome.NOT_CLASSIFIED,
    }


def test_open_seats_zero_classifica_so_pela_reserva():
    resultados = rank_regular(
        [
            candidato(1, nota="99.00"),
            candidato(2, nota="80.00", categoria=QuotaCategory.RACIAL),
        ],
        open_seats=0,
        racial_seats=1,
    )
    assert desfechos(resultados) == {
        1: RankingOutcome.NOT_CLASSIFIED,
        2: RankingOutcome.CLASSIFIED_QUOTA,
    }
    assert posicoes(resultados) == {1: 1, 2: 2}


def test_sem_vaga_nenhuma_ninguem_classifica():
    resultados = rank_regular([candidato(1)], open_seats=0, racial_seats=0)
    assert desfechos(resultados) == {1: RankingOutcome.NOT_CLASSIFIED}


def test_sem_candidato_devolve_lista_vazia():
    assert rank_regular([], open_seats=3, racial_seats=1) == []


def test_mais_vaga_que_candidato_classifica_todo_mundo():
    resultados = rank_regular(
        [candidato(1), candidato(2, nota="70.00")], open_seats=5, racial_seats=2
    )
    assert set(desfechos(resultados).values()) == {RankingOutcome.CLASSIFIED_OPEN}


def test_vaga_negativa_e_erro_do_chamador():
    try:
        rank_regular([], open_seats=-1, racial_seats=0)
    except ValueError as erro:
        assert "open_seats" in str(erro)
    else:
        raise AssertionError("esperava ValueError")


def test_categoria_fora_do_regular_e_erro_do_chamador():
    try:
        rank_regular(
            [candidato(1, categoria=QuotaCategory.TRANS)],
            open_seats=1,
            racial_seats=0,
        )
    except ValueError as erro:
        assert "trans" in str(erro)
    else:
        raise AssertionError("esperava ValueError")


# ---------------------------------------------------------------------------
# rank_supplementary
# ---------------------------------------------------------------------------


def test_suplementar_classifica_por_categoria_sem_ordem_geral():
    # O quilombola 3 tem nota menor que o indígena 2 e mesmo assim classifica:
    # cada ação afirmativa disputa só com os seus.
    resultados = rank_supplementary(
        [
            candidato(1, nota="90.00", categoria=QuotaCategory.INDIGENOUS),
            candidato(2, nota="85.00", categoria=QuotaCategory.INDIGENOUS),
            candidato(3, nota="60.00", categoria=QuotaCategory.QUILOMBOLA),
        ],
        seats_by_category={
            QuotaCategory.INDIGENOUS: 1,
            QuotaCategory.QUILOMBOLA: 1,
            QuotaCategory.TRANS: 1,
        },
    )
    assert desfechos(resultados) == {
        1: RankingOutcome.CLASSIFIED_QUOTA,
        2: RankingOutcome.NOT_CLASSIFIED,
        3: RankingOutcome.CLASSIFIED_QUOTA,
    }
    # `rank` é a posição dentro da categoria, não numa fila geral.
    assert posicoes(resultados) == {1: 1, 2: 2, 3: 1}


def test_suplementar_categoria_sem_candidato_nao_gera_resultado():
    resultados = rank_supplementary(
        [candidato(1, categoria=QuotaCategory.DISABILITY)],
        seats_by_category={
            QuotaCategory.DISABILITY: 1,
            QuotaCategory.QUILOMBOLA: 3,
        },
    )
    assert [r.application_id for r in resultados] == [1]


def test_suplementar_categoria_sem_vaga_nao_classifica():
    resultados = rank_supplementary(
        [candidato(1, categoria=QuotaCategory.TRANS)],
        seats_by_category={QuotaCategory.DISABILITY: 2},
    )
    assert desfechos(resultados) == {1: RankingOutcome.NOT_CLASSIFIED}


def test_suplementar_desempata_dentro_da_categoria():
    resultados = rank_supplementary(
        [
            candidato(
                1,
                categoria=QuotaCategory.TRANS,
                desempates=("50.00",),
                nascimento=date(2000, 1, 1),
            ),
            candidato(
                2,
                categoria=QuotaCategory.TRANS,
                desempates=("70.00",),
                nascimento=date(2000, 1, 1),
            ),
        ],
        seats_by_category={QuotaCategory.TRANS: 1},
    )
    assert desfechos(resultados) == {
        2: RankingOutcome.CLASSIFIED_QUOTA,
        1: RankingOutcome.NOT_CLASSIFIED,
    }
    assert not any(r.tie_unresolved for r in resultados)


def test_suplementar_recusa_ampla_concorrencia():
    try:
        rank_supplementary(
            [candidato(1, categoria=QuotaCategory.OPEN)],
            seats_by_category={QuotaCategory.TRANS: 1},
        )
    except ValueError as erro:
        assert "ampla concorrência" in str(erro)
    else:
        raise AssertionError("esperava ValueError")
