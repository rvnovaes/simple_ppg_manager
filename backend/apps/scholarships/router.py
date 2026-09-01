"""Borda HTTP do app scholarships, montada em /api/v1/scholarships/.

Padrão de toda rota: `require_perm` na primeira linha, `current_program`
logo depois, chamada ao model/service, schema de saída explícito. Zero
regra de negócio aqui. As rotas entram nas stories de API.
"""

from ninja import Router

router = Router(tags=["scholarships"])
