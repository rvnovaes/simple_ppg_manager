"""Contrato HTTP do app selection.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md); nenhum
model é serializado direto. Preenchido pelas stories de API (F1 em diante).
"""

import datetime
from pathlib import Path

from django.utils import timezone
from ninja import Schema

from .models import SelectionKind, SelectionProcess, SelectionProcessStatus


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
