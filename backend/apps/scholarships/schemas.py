"""Contrato HTTP do app scholarships.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md); nenhum model
é serializado direto. Preenchido pelas stories de API.
"""

import datetime
from pathlib import Path

from ninja import Schema

from .models import (
    CommitteeMember,
    ScholarshipEdition,
    ScholarshipEditionStatus,
)

# ---------------------------------------------------------------------------
# Edição do edital de bolsas
# ---------------------------------------------------------------------------


class ScholarshipEditionIn(Schema):
    """Abertura da edição do ano, digitada pela secretaria.

    Sem `program_id`: o programa é o da requisição (`current_program`),
    nunca o que o chamador escolher. Sem `status` também — a edição nasce
    em rascunho e só anda pelas cinco rotas de transição.

    As datas do cronograma são opcionais e todas nulas por padrão: elas são
    **informação publicada**, não gatilho (nada abre ou fecha por relógio),
    e no momento em que a secretaria abre a edição o calendário ainda está
    sendo fechado.
    """

    year: int
    title: str
    submission_starts_on: datetime.date | None = None
    submission_ends_on: datetime.date | None = None
    preliminary_result_on: datetime.date | None = None
    appeal_ends_on: datetime.date | None = None
    final_result_on: datetime.date | None = None


class ScholarshipEditionPatch(Schema):
    """Retificação da edição: só os campos presentes são aplicados.

    Vale em qualquer estado, de propósito. O que a edição publica de
    cronograma é texto informativo, e retificar data divulgada é o caso
    normal do edital — quem trava o que muda nota já dada é
    `bareme_editable()`, no barema, não aqui. O `year` continua defendido
    pelo `clean()` (`duplicate_edition`).
    """

    year: int | None = None
    title: str | None = None
    submission_starts_on: datetime.date | None = None
    submission_ends_on: datetime.date | None = None
    preliminary_result_on: datetime.date | None = None
    appeal_ends_on: datetime.date | None = None
    final_result_on: datetime.date | None = None


class ScholarshipEditionOut(Schema):
    """A edição como a tela da secretaria a vê.

    As cinco guardas de leitura do model viajam resolvidas: é o servidor
    que decide se o barema ainda é editável ou se o resultado já aparece
    para o discente, e a tela só desenha o que elas dizem. Repetir a
    máquina de estados no front seria a segunda porta que o CLAUDE.md
    proíbe.
    """

    id: int
    program_id: int
    year: int
    title: str
    status: ScholarshipEditionStatus
    status_label: str
    submission_starts_on: datetime.date | None
    submission_ends_on: datetime.date | None
    preliminary_result_on: datetime.date | None
    appeal_ends_on: datetime.date | None
    final_result_on: datetime.date | None
    # O PDF do edital é público por natureza (é o documento que convoca os
    # candidatos), então aqui a URL do MEDIA basta — ao contrário do anexo
    # da inscrição, que só sai pelo endpoint de download auditado.
    notice_filename: str
    notice_url: str
    bareme_editable: bool
    submission_open: bool
    committee_can_review: bool
    appeal_open: bool
    results_visible_to_student: bool
    published_preliminary_at: datetime.datetime | None
    published_final_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_status_label(obj: ScholarshipEdition) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_notice_filename(obj: ScholarshipEdition) -> str:
        """Só o nome do arquivo: o diretório é detalhe do storage."""
        return Path(obj.notice_file.name or "").name

    @staticmethod
    def resolve_notice_url(obj: ScholarshipEdition) -> str:
        return obj.notice_file.url if obj.notice_file else ""

    @staticmethod
    def resolve_bareme_editable(obj: ScholarshipEdition) -> bool:
        return obj.bareme_editable()

    @staticmethod
    def resolve_submission_open(obj: ScholarshipEdition) -> bool:
        return obj.submission_open()

    @staticmethod
    def resolve_committee_can_review(obj: ScholarshipEdition) -> bool:
        return obj.committee_can_review()

    @staticmethod
    def resolve_appeal_open(obj: ScholarshipEdition) -> bool:
        return obj.appeal_open()

    @staticmethod
    def resolve_results_visible_to_student(obj: ScholarshipEdition) -> bool:
        return obj.results_visible_to_student()


# ---------------------------------------------------------------------------
# Comissão de Bolsas
# ---------------------------------------------------------------------------


class CommitteeMemberIn(Schema):
    """Designação de um professor na comissão daquele ano.

    Sem `edition_id`: a edição vem da URL, já escopada no programa da
    sessão. `teacher_id` é conferido contra o programa na rota, e o
    `clean()` do model guarda o mesmo invariante para quem escrever fora
    dela.
    """

    teacher_id: int
    appointed_on: datetime.date | None = None
    ordinance: str = ""


class CommitteeMemberOut(Schema):
    """Um membro da comissão, com o nome já resolvido.

    A tela lista a composição do ano e não deve cruzar id de professor com
    nome. Nada aqui é autorização: quem avalia é quem está no Group
    "Comissão de Bolsas" (docstring de `CommitteeMember`).
    """

    id: int
    edition_id: int
    teacher_id: int
    teacher_name: str
    appointed_on: datetime.date | None
    ordinance: str
    created_at: datetime.datetime

    @staticmethod
    def resolve_teacher_name(obj: CommitteeMember) -> str:
        return obj.teacher.person.full_name
