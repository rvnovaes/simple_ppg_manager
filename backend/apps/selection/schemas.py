"""Contrato HTTP do app selection.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md); nenhum
model é serializado direto. Preenchido pelas stories de API (F1 em diante).
"""

import datetime
from pathlib import Path

from django.utils import timezone
from ninja import Schema

from apps.academic.models import Teacher

from .models import (
    Board,
    QuotaCategory,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionProcessStatus,
    Vacancy,
)


class SelectionProcessIn(Schema):
    """Abertura do edital, digitada pela secretaria.

    Sem `program_id`: o programa é o da requisição (`current_program`),
    nunca o que o chamador escolher. Sem `status` também — o edital nasce
    em rascunho e muda de estado só por `publish`/`close`, que cobram o
    que a publicação exige e carimbam a data.

    O template de convocação é opcional aqui porque ele costuma ser
    escrito depois da grade de vagas; quem cobra é `publish_process`.
    """

    kind: SelectionKind
    year: int
    title: str
    submission_opens_at: datetime.datetime
    submission_closes_at: datetime.datetime
    convocation_subject: str = ""
    convocation_body: str = ""


class SelectionProcessPatch(Schema):
    """Correção do edital em rascunho: só os campos presentes são aplicados.

    Depois de publicado nada disto muda (`ensure_editable`): o candidato já
    se inscreveu contra este conteúdo, e vaga se corrige por
    `VacancyReallocation`, com ofício da comissão.
    """

    kind: SelectionKind | None = None
    year: int | None = None
    title: str | None = None
    submission_opens_at: datetime.datetime | None = None
    submission_closes_at: datetime.datetime | None = None
    convocation_subject: str | None = None
    convocation_body: str | None = None


class SelectionProcessOut(Schema):
    """O edital como a tela da secretaria o vê.

    `submission_open` vem resolvido do servidor: comparar a janela no
    navegador deixaria "as inscrições estão abertas" dependendo do relógio
    de quem acessa.

    `stage_count` e `vacancy_count` viajam porque a tela precisa dizer o
    que falta para publicar sem fazer uma chamada por edital — as rotas de
    listagem e de detalhe anotam os dois; o fallback conta na hora, para o
    objeto recém-escrito que volta do POST/PATCH.
    """

    id: int
    program_id: int
    kind: SelectionKind
    kind_label: str
    year: int
    title: str
    status: SelectionProcessStatus
    status_label: str
    submission_opens_at: datetime.datetime
    submission_closes_at: datetime.datetime
    submission_open: bool
    # O PDF do edital é público por natureza (é o documento que convoca os
    # candidatos), então aqui a URL do MEDIA basta — ao contrário do anexo
    # de inscrição, que só sai pelo endpoint de download auditado.
    notice_filename: str
    notice_url: str
    convocation_subject: str
    convocation_body: str
    published_at: datetime.datetime | None
    closed_at: datetime.datetime | None
    stage_count: int
    vacancy_count: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_kind_label(obj: SelectionProcess) -> str:
        return obj.get_kind_display()

    @staticmethod
    def resolve_status_label(obj: SelectionProcess) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_submission_open(obj: SelectionProcess) -> bool:
        return obj.submission_open(timezone.now())

    @staticmethod
    def resolve_notice_filename(obj: SelectionProcess) -> str:
        """Só o nome do arquivo: o diretório é detalhe do storage."""
        return Path(obj.notice_file.name or "").name

    @staticmethod
    def resolve_notice_url(obj: SelectionProcess) -> str:
        return obj.notice_file.url if obj.notice_file else ""

    @staticmethod
    def resolve_stage_count(obj: SelectionProcess) -> int:
        anotado = getattr(obj, "stage_count", None)
        return obj.stages.count() if anotado is None else anotado

    @staticmethod
    def resolve_vacancy_count(obj: SelectionProcess) -> int:
        anotado = getattr(obj, "vacancy_count", None)
        return obj.vacancies.count() if anotado is None else anotado


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------


class SelectionStageIn(Schema):
    """Etapa nova do edital, digitada pela secretaria.

    Sem `process_id`: o edital é o da URL, escopado por programa. Sem
    `program_id` pela mesma razão de sempre — quem escolhe o tenant é a
    sessão.

    `tiebreak_rank` nulo significa "esta etapa não entra no desempate"; é
    o caso da última etapa dos dois tipos de edital.
    """

    name: str
    order: int
    session_at: datetime.datetime | None = None
    location: str = ""
    tiebreak_rank: int | None = None


class SelectionStagePatch(Schema):
    """Correção da etapa em rascunho: só os campos presentes são aplicados.

    `session_at` e `tiebreak_rank` aceitam `null` explícito (desmarcar a
    sessão, tirar a etapa do desempate), então aqui o corte é por
    `exclude_unset` e não por `exclude_none`.
    """

    name: str | None = None
    order: int | None = None
    session_at: datetime.datetime | None = None
    location: str | None = None
    tiebreak_rank: int | None = None


class SelectionStageOut(Schema):
    """A etapa como a tela do edital a vê.

    `program_id` viaja porque a etapa é filha de agregado e a tela não tem
    o edital carregado em toda listagem; a propriedade do model resolve.
    """

    id: int
    process_id: int
    program_id: int
    name: str
    order: int
    session_at: datetime.datetime | None
    location: str
    tiebreak_rank: int | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ---------------------------------------------------------------------------
# Vagas
# ---------------------------------------------------------------------------


class VacancyIn(Schema):
    """Linha da grade de vagas: nível × alvo × categoria de cota.

    O alvo é XOR e amarrado ao tipo do edital (`ensure_target`): Regular
    pede `project_id`, Suplementar pede `research_line_id`. Mandar os dois
    (ou nenhum) volta `target_mismatch`, não um 500 da CheckConstraint.
    """

    level: SelectionLevel
    project_id: int | None = None
    research_line_id: int | None = None
    quota_category: QuotaCategory
    quantity: int


class VacancyPatch(Schema):
    """Correção da vaga em rascunho.

    O caso comum é `quantity`; os demais campos existem porque em rascunho
    a grade inteira ainda é rascunho. Depois de publicado nada disto muda —
    a correção vira `VacancyReallocation`, com ofício da comissão.
    """

    level: SelectionLevel | None = None
    project_id: int | None = None
    research_line_id: int | None = None
    quota_category: QuotaCategory | None = None
    quantity: int | None = None


class VacancyOut(Schema):
    """A vaga como a grade da secretaria a vê.

    Os rótulos e o nome do alvo viajam resolvidos: a tela lista dezenas de
    linhas e não deve ter que cruzar id de projeto com nome de projeto.
    """

    id: int
    program_id: int
    process_id: int
    level: SelectionLevel
    level_label: str
    project_id: int | None
    research_line_id: int | None
    target_label: str
    quota_category: QuotaCategory
    quota_category_label: str
    quantity: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_level_label(obj: Vacancy) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_quota_category_label(obj: Vacancy) -> str:
        return obj.get_quota_category_display()

    @staticmethod
    def resolve_target_label(obj: Vacancy) -> str:
        alvo = obj.project or obj.research_line
        return str(alvo) if alvo is not None else ""


# ---------------------------------------------------------------------------
# Bancas
# ---------------------------------------------------------------------------


class BoardMemberOut(Schema):
    """Um examinador, como a tela da banca o mostra.

    Nome, categoria e instituição viajam resolvidos porque a tela lista os
    quatro papéis de cada banca e precisa distinguir o docente do programa
    do externo — e, no externo, de onde ele vem (`home_institution` é
    obrigatória nessa categoria).
    """

    id: int
    full_name: str
    category: str
    category_label: str
    home_institution: str

    @staticmethod
    def resolve_full_name(obj: Teacher) -> str:
        return obj.person.full_name

    @staticmethod
    def resolve_category_label(obj: Teacher) -> str:
        return obj.get_category_display()


class BoardIn(Schema):
    """Banca nova: nível × alvo do edital e os quatro examinadores.

    Sem `program_id` (é o da sessão). `process_id` vem no corpo porque a
    rota é `boards/` e não pende do edital — a tela de bancas lista as
    bancas de vários editais.

    O alvo é XOR e amarrado ao tipo do edital, como na vaga: Regular pede
    `project_id`, Suplementar pede `research_line_id`.
    """

    process_id: int
    level: SelectionLevel
    project_id: int | None = None
    research_line_id: int | None = None
    president_id: int
    member_1_id: int
    member_2_id: int
    alternate_id: int


class BoardPatch(Schema):
    """Correção da banca — enquanto nenhuma ata dela saiu do rascunho.

    `process_id` não está aqui: mudar a banca de edital seria criar outra
    banca. O alvo e os quatro papéis mudam porque impedimento e
    substituição de examinador acontecem antes da primeira sessão.
    """

    level: SelectionLevel | None = None
    project_id: int | None = None
    research_line_id: int | None = None
    president_id: int | None = None
    member_1_id: int | None = None
    member_2_id: int | None = None
    alternate_id: int | None = None


class BoardOut(Schema):
    """A banca como a tela da secretaria a vê.

    Os quatro examinadores vêm expandidos (nome, categoria, instituição) —
    a tela não deve cruzar id de professor com nome. `in_use` diz se a
    banca ainda é editável: a listagem anota a contagem de atas fora do
    rascunho; o fallback consulta na hora, para o objeto recém-escrito que
    volta do POST/PATCH.
    """

    id: int
    program_id: int
    process_id: int
    process_title: str
    level: SelectionLevel
    level_label: str
    project_id: int | None
    research_line_id: int | None
    target_label: str
    president: BoardMemberOut
    member_1: BoardMemberOut
    member_2: BoardMemberOut
    alternate: BoardMemberOut
    in_use: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_process_title(obj: Board) -> str:
        return str(obj.process)

    @staticmethod
    def resolve_level_label(obj: Board) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_target_label(obj: Board) -> str:
        alvo = obj.project or obj.research_line
        return str(alvo) if alvo is not None else ""

    @staticmethod
    def resolve_in_use(obj: Board) -> bool:
        anotado = getattr(obj, "atas_fora_do_rascunho", None)
        return obj.in_use() if anotado is None else bool(anotado)
