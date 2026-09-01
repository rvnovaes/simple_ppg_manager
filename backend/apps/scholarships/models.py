"""Models da concessão de bolsas do PPGD.

App próprio (plano `bolsas.md`): edição anual do edital, comissão, barema,
inscrição do discente, análise, classificação em faixas de prioridade,
recurso e publicação entram aqui, story a story, cada uma com a sua
migration.

Convenções válidas para todos os models deste app (não repetidas por
model):

- FK `program` direta com `PROTECT` (ADR-007), exceto filhos de agregado
  (`BaremeItem`, `CommitteeMember`, `BaremeEntry`, `ApplicationDocument`,
  `ItemReview`, `ScholarshipAppeal`), que chegam ao programa pelo pai —
  mesmo recorte de `RequestDocument` (`apps/academic/models.py`).
- `clean()` levanta `DomainError(code=...)` cobrindo `program_mismatch` e
  a duplicata de cada `UniqueConstraint` — `.save()` não roda `clean()`, e
  sem o espelho a violação vira `IntegrityError` → 500.
- QuerySet com `for_program()` como **primeiro** filtro de toda busca.
- Transições de estado **não salvam**: quem persiste é o router/service, no
  mesmo `transaction.atomic()` do `AuditLog`. `InvalidStateTransition` = 409.
- Todos os `TextChoices` no **nível do módulo**, com nome único: o gerador de
  OpenAPI batiza o schema pelo `__name__` da classe, e enums aninhados de
  nome repetido colidem — o último registrado sobrescreve o outro, sem erro
  no backend (precedente comentado em `apps/academic/models.py`).

Nada abre ou fecha por relógio: as datas do cronograma do edital são
informação, e toda mudança de estado é ato manual da secretaria — mesmo
corte das isoladas.
"""

from decimal import Decimal

from django.db import models

# ---------------------------------------------------------------------------
# Enums de módulo
# ---------------------------------------------------------------------------


class ScholarshipEditionStatus(models.TextChoices):
    """Estados da edição anual, sempre para frente (não há volta ao rascunho).

    Correção de rumo é quebra-vidro no Admin, não transição.
    """

    DRAFT = "draft", "Rascunho"
    SUBMISSIONS_OPEN = "submissions_open", "Inscrições abertas"
    UNDER_REVIEW = "under_review", "Em análise"
    PRELIMINARY_RESULT = "preliminary_result", "Resultado preliminar"
    APPEALS_UNDER_REVIEW = "appeals_under_review", "Recursos em análise"
    FINAL_RESULT = "final_result", "Resultado final"


class ScholarshipLevel(models.TextChoices):
    """Nível do vínculo a que a bolsa se refere.

    Mesmos valores de `Student.Level` (`apps/academic/models.py`) — a
    inscrição copia o nível do aluno no ato e o congela. Enum próprio (e não
    reuso do aninhado) porque enum de módulo é a regra deste app.
    """

    MASTERS = "masters", "Mestrado"
    DOCTORATE = "doctorate", "Doutorado"


class BaremeSection(models.TextChoices):
    """As seis seções (I..VI) do barema do edital."""

    FORMATION = "formation", "I - Formação Acadêmica"
    BIBLIOGRAPHIC = "bibliographic", "II - Produção Bibliográfica"
    EVENTS = "events", "III - Participação em Eventos"
    PROFESSIONAL = "professional", "IV - Atividade Profissional"
    BOARDS = "boards", "V - Participação em Bancas"
    OTHER_TITLES = "other_titles", "VI - Outros Títulos"


class BaremeUnit(models.TextChoices):
    """Unidade em que o item do barema mede a quantidade lançada."""

    SEMESTER = "semester", "Semestre"
    MONTH = "month", "Mês"
    HOUR = "hour", "Hora"
    UNIT = "unit", "Unidade"


class PriorityBand(models.TextChoices):
    """As dez faixas de prioridade, nomeadas pelo inciso do edital.

    `B24_I` e `B24_II` só existem por sobrescrita da secretaria: não há
    pergunta no questionário que as derive. A residual é a décima e recebe
    quem não se encaixa em nenhum inciso.
    """

    B21_I = "b21_i", "2.1-I"
    B21_II = "b21_ii", "2.1-II"
    B24_I = "b24_i", "2.4-I"
    B24_II = "b24_ii", "2.4-II"
    B24_III = "b24_iii", "2.4-III"
    B24_IV = "b24_iv", "2.4-IV"
    B24_V = "b24_v", "2.4-V"
    B24_VI_VII_VIII = "b24_vi_vii_viii", "2.4-VI/VII/VIII"
    B24_IX = "b24_ix", "2.4-IX"
    RESIDUAL = "residual", "Residual"


class AppealOutcome(models.TextChoices):
    """Resultado do julgamento do recurso."""

    GRANTED = "granted", "Deferido"
    PARTIALLY_GRANTED = "partially_granted", "Parcialmente deferido"
    DENIED = "denied", "Indeferido"


class ApplicationDocumentKind(models.TextChoices):
    """Um tipo por resposta "Sim" do questionário que exige comprovante.

    São sete: `has_paid_activity` é a chave que joga o candidato do bloco
    2.1 para o 2.4 e não pede documento próprio — quem comprova são os
    incisos abaixo dela.
    """

    AFFIRMATIVE_ACTION = "affirmative_action", "Ação afirmativa"
    SOCIOECONOMIC_VULNERABILITY = (
        "socioeconomic_vulnerability",
        "Vulnerabilidade socioeconômica",
    )
    SUBSTITUTE_TEACHER = "substitute_teacher", "Professor substituto"
    BASIC_EDUCATION_OR_COLLECTIVE_HEALTH = (
        "basic_education_or_collective_health",
        "Educação básica ou saúde coletiva",
    )
    PUBLIC_SERVICE = "public_service", "Serviço público"
    PRIVATE_SERVICE = "private_service", "Serviço privado"
    OTHER_NON_PUBLIC_SCHOLARSHIP = (
        "other_non_public_scholarship",
        "Outra bolsa não pública",
    )


# ---------------------------------------------------------------------------
# Constantes de módulo
# ---------------------------------------------------------------------------

# Ordem canônica em que as faixas são publicadas. O rótulo "Ordem de
# prioridade: N" é **derivado da posição nesta lista** — não é campo. A
# residual é sempre a última.
ORDEM_DAS_FAIXAS: list[str] = [
    PriorityBand.B21_I,
    PriorityBand.B21_II,
    PriorityBand.B24_I,
    PriorityBand.B24_II,
    PriorityBand.B24_III,
    PriorityBand.B24_IV,
    PriorityBand.B24_V,
    PriorityBand.B24_VI_VII_VIII,
    PriorityBand.B24_IX,
    PriorityBand.RESIDUAL,
]

# Bônus somado à nota da comissão conforme o nível da FUMP (item 3.2 do
# edital). Nível 0 é "sem nível" e não pontua — por isso fica fora do dict,
# que é consultado com `.get(fump_level, Decimal("0.00"))`.
BONUS_FUMP: dict[int, Decimal] = {1: Decimal("15.00"), 2: Decimal("9.00")}

# Regra de ordenação dentro de cada faixa. Faixa ausente ordena só por
# nota (decrescente); as duas listadas ordenam antes pela remuneração —
# menor rendimento primeiro — e a 2.4-VI/VII/VIII ainda pela menor carga
# horária. É dado, não código: o cabeçalho do PDF publica esta mesma regra.
ORDENACAO_DA_FAIXA: dict[str, tuple[str, ...]] = {
    PriorityBand.B24_V: ("income", "score"),
    PriorityBand.B24_VI_VII_VIII: ("income", "hours", "score"),
}
