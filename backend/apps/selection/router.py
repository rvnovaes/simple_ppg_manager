"""Borda HTTP do app selection, montada em /api/v1/selection/.

Padrão de toda rota: require_perm na primeira linha, current_program logo
depois, chamada ao model/service, schema de saída explícito. Zero regra de
negócio aqui. Ainda sem rotas: elas chegam com as stories de API.
"""

from ninja import Router

router = Router(tags=["selection"])
