"""Operações do app scholarships que cruzam mais de um agregado.

ADR-002: service só existe quando a operação escreve em mais de um model
e precisa ser atômica. `clone_bareme` está aqui porque lê os itens de uma
edição e escreve na outra, com um `AuditLog` único — o CRUD do barema,
que toca um model só, continua chamando o manager direto do router.

Quem escreve aqui chama `clean()` antes de `save()` (ou confere o
invariante à mão, quando usa `bulk_create`): o Django não roda `clean()`
em `.save()`/`.create()`.
"""

from django.db import transaction
from django.http import HttpRequest

from apps.core import audit
from apps.core.exceptions import DomainError

from .models import BaremeItem, ScholarshipEdition

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
