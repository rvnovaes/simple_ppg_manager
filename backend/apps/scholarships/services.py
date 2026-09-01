"""Operações do app scholarships que cruzam mais de um agregado.

ADR-002: service só existe quando a operação escreve em mais de um model
e precisa ser atômica. `clone_bareme` está aqui porque lê os itens de uma
edição e escreve na outra, com um `AuditLog` único — o CRUD do barema,
que toca um model só, continua chamando o manager direto do router.

Quem escreve aqui chama `clean()` antes de `save()` (ou confere o
invariante à mão, quando usa `bulk_create`): o Django não roda `clean()`
em `.save()`/`.create()`.
"""

import random
from datetime import datetime

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.core import audit
from apps.core.exceptions import DomainError

from .models import (
    BandResult,
    BaremeItem,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipLevel,
)

# Campos que o clone copia. `edition` é o destino; `id`, `created_at` e
# `updated_at` são do registro novo. Lista explícita, e não um
# `model_to_dict`: campo novo no `BaremeItem` deve exigir uma decisão
# consciente sobre se ele viaja no clone.
CAMPOS_CLONADOS = ("level", "section", "code", "text", "unit", "points_per_unit", "cap")


@transaction.atomic
def clone_bareme(
    *,
    source: ScholarshipEdition,
    target: ScholarshipEdition,
    request: HttpRequest | None = None,
) -> list[BaremeItem]:
    """Copia os itens do barema de uma edição para outra.

    Os dois níveis vêm juntos: o barema é por (edição, nível) e clonar
    meio edital não é caso de uso — quem quer só um nível apaga o outro
    depois, ainda em rascunho.

    Só com o **destino** em rascunho (`ensure_bareme_editable`, 409): a
    origem pode estar em qualquer estado, e no caso normal ela é a edição
    já publicada do ano anterior.

    A duplicata é conferida antes de escrever, e não item a item pelo
    `clean()`: `bulk_create` não roda `clean()`, e o ato é um só — ou o
    barema inteiro entra, ou nada entra e o 400 diz qual código colidiu.
    """
    if source.pk == target.pk:
        raise DomainError(
            "A edição de origem do barema precisa ser diferente da de destino.",
            code="same_edition",
        )
    target.ensure_bareme_editable()

    ja_existem = set(target.bareme_items.values_list("level", "code"))
    origem = list(source.bareme_items.all())
    for item in origem:
        if (item.level, item.code) in ja_existem:
            raise DomainError(
                f"O item {item.code} já existe no barema deste nível nesta "
                "edição: esvazie o barema do destino antes de clonar.",
                code="duplicate_bareme_item",
            )

    novos = BaremeItem.objects.bulk_create(
        [
            BaremeItem(
                edition=target,
                **{campo: getattr(item, campo) for campo in CAMPOS_CLONADOS},
            )
            for item in origem
        ]
    )
    # Um `AuditLog` só, com as contagens no payload: o ato é "clonei o
    # barema de 2026", não N criações soltas (mesmo desenho de
    # `close_isolated_cycle`, `apps/academic/services.py`).
    audit.record(
        "scholarships.bareme.clone",
        request=request,
        target=target,
        source_edition_id=source.pk,
        created=len(novos),
    )
    return novos


# ---------------------------------------------------------------------------
# Publicação do resultado
# ---------------------------------------------------------------------------
#
# Service, e não método do model, porque o ato escreve em dois agregados: a
# edição (situação, carimbo, semente) e TODA inscrição dela (o snapshot da
# decisão B10). Um `AuditLog` só, com as contagens no payload — o ato é
# "publiquei o preliminar de 2026", e não N eventos soltos (mesmo desenho de
# `close_isolated_cycle`, `apps/academic/services.py`).

# Os cinco campos do snapshot, mais o carimbo técnico: `bulk_update` não
# dispara `auto_now`, então `updated_at` entra na lista com o valor da
# publicação em vez de ficar mentindo a data da última alteração.
CAMPOS_DO_SNAPSHOT = (
    "published_band",
    "published_score",
    "published_position",
    "draw_order",
    "published_at",
    "updated_at",
)


def publish_preliminary(
    *, edition: ScholarshipEdition, request: HttpRequest | None = None
) -> ScholarshipEdition:
    """Publica o resultado preliminar da edição (409 fora de `under_review`).

    É aqui que a semente do sorteio nasce, e só aqui.
    """
    return _publicar(
        edition=edition,
        request=request,
        transicao="publish_preliminary",
        evento="scholarships.edition.publish_preliminary",
        campos=["status", "published_preliminary_at"],
    )


def publish_final(
    *, edition: ScholarshipEdition, request: HttpRequest | None = None
) -> ScholarshipEdition:
    """Publica o resultado final, a partir de `appeals_under_review`.

    Mesmo caminho do preliminar, e de propósito: o final é a mesma lista
    recalculada depois dos recursos julgados, com a **mesma** semente — o
    sorteio de desempate não se refaz porque alguém recorreu.
    """
    return _publicar(
        edition=edition,
        request=request,
        transicao="publish_final",
        evento="scholarships.edition.publish_final",
        campos=["status", "published_final_at"],
    )


@transaction.atomic
def _publicar(
    *,
    edition: ScholarshipEdition,
    request: HttpRequest | None,
    transicao: str,
    evento: str,
    campos: list[str],
) -> ScholarshipEdition:
    """O corpo comum das duas publicações.

    A ordem importa:

    1. A transição primeiro — ela é quem recusa (409) o estado errado, e
       recusar antes de gerar semente ou classificar é o que deixa o
       método barato de chamar por engano.
    2. A semente **só se ainda não houver**. Republicar (o final depois do
       preliminar) tem de dar a mesma ordem de sorteio; regerá-la aqui
       embaralharia de novo quem empatou, e o candidato veria a lista
       trocar sem que nada tivesse sido julgado.
    3. Um `at` só para tudo: o carimbo da edição e o `published_at` de
       toda inscrição são o mesmo instante, que é o que permite ler "o que
       foi publicado naquela hora" depois.
    """
    at = timezone.now()
    getattr(edition, transicao)(at=at)
    a_salvar = list(campos)
    if edition.draw_seed is None:
        edition.draw_seed = random.randrange(1, 2**63)
        a_salvar.append("draw_seed")

    contagem = {
        nivel.value: _gravar_snapshot(edition.classify(nivel), at)
        for nivel in ScholarshipLevel
    }
    edition.save(update_fields=[*a_salvar, "updated_at"])
    audit.record(
        evento,
        request=request,
        target=edition,
        status=edition.status,
        draw_seed=edition.draw_seed,
        published=sum(contagem.values()),
        by_level=contagem,
    )
    return edition


def _gravar_snapshot(faixas: list[BandResult], at: datetime) -> int:
    """Congela faixa, nota, posição e sorteio em cada inscrição da lista.

    `bulk_update` porque o ato é um só e as linhas já estão carregadas
    (`classify()` as trouxe com os lançamentos): salvar uma a uma seria
    uma consulta por candidato dentro da transação. Não há `clean()` a
    rodar aqui — nenhum destes campos participa de invariante; quem os
    escreve é o algoritmo, não um formulário.
    """
    inscricoes = []
    for faixa in faixas:
        for linha in faixa.rows:
            inscricao = linha.application
            inscricao.published_band = faixa.band
            inscricao.published_score = linha.score
            inscricao.published_position = linha.position
            inscricao.draw_order = linha.draw_order
            inscricao.published_at = at
            inscricao.updated_at = at
            inscricoes.append(inscricao)
    ScholarshipApplication.objects.bulk_update(inscricoes, CAMPOS_DO_SNAPSHOT)
    return len(inscricoes)
