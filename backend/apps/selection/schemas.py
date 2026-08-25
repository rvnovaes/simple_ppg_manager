"""Contrato HTTP do app selection.

Schemas explícitos de entrada e saída (Seção 3 do CLAUDE.md); nenhum
model é serializado direto. Preenchido pelas stories de API (F1 em diante).
"""

import datetime
import decimal
from pathlib import Path
from typing import Any

from django.utils import timezone
from ninja import Schema

from apps.academic.models import Teacher

from .models import (
    Application,
    ApplicationDocument,
    ApplicationStatus,
    Board,
    Convocation,
    ConvocationEmail,
    EmailDeliveryStatus,
    ExaminationRecord,
    QuotaCategory,
    ReallocationKind,
    RecordSignature,
    RecordStatus,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionProcessStatus,
    SignatureMethod,
    Vacancy,
    VacancyReallocation,
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


# ---------------------------------------------------------------------------
# Inscrição pública (candidato sem login)
# ---------------------------------------------------------------------------


class PublicStageOut(Schema):
    """Etapa como o candidato a vê no edital aberto.

    Sem `id` de nada além da própria etapa e sem carimbo técnico: esta é a
    página que qualquer um na internet abre, e o que não serve para o
    candidato decidir se se inscreve não sai daqui.
    """

    name: str
    order: int
    session_at: datetime.datetime | None
    location: str


class PublicOptionOut(Schema):
    """Uma opção do formulário público — nível ou categoria de cota.

    Rótulo junto do valor porque a tela pública não tem a tabela de
    `TextChoices` do backend e não pode inventar tradução.
    """

    value: str
    label: str


class PublicTargetOut(Schema):
    """Alvo com vaga aberta: projeto coletivo (Regular) ou linha
    (Suplementar). Um dos dois ids é sempre nulo — é o XOR do model."""

    project_id: int | None
    research_line_id: int | None
    label: str


class PublicVacancyOut(Schema):
    """Combinação nível × alvo × cota que ainda tem vaga.

    A quantidade viaja porque o edital é público: quantas vagas há em cada
    linha da grade é informação do próprio documento, não dado interno.
    """

    level: SelectionLevel
    level_label: str
    project_id: int | None
    research_line_id: int | None
    target_label: str
    quota_category: QuotaCategory
    quota_category_label: str
    quantity: int

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


class PublicProcessOut(Schema):
    """Edital aberto, como a página pública o mostra.

    `program_acronym` viaja porque esta listagem NÃO é escopada por tenant
    (não há sessão de onde tirar o programa, e edital publicado é
    documento público): sem a sigla, dois editais de programas diferentes
    apareceriam como dois títulos indistinguíveis.

    `levels`, `targets` e `quota_categories` são derivados das vagas com
    `quantity > 0` — é o que o formulário oferece. Oferecer combinação sem
    vaga só levaria o candidato a preencher tudo para receber
    `no_vacancy_for_choice` no fim.
    """

    id: int
    kind: SelectionKind
    kind_label: str
    year: int
    title: str
    program_acronym: str
    submission_opens_at: datetime.datetime
    submission_closes_at: datetime.datetime
    notice_url: str
    stages: list[PublicStageOut]
    vacancies: list[PublicVacancyOut]
    levels: list[PublicOptionOut]
    targets: list[PublicTargetOut]
    quota_categories: list[PublicOptionOut]

    @staticmethod
    def resolve_kind_label(obj: SelectionProcess) -> str:
        return obj.get_kind_display()

    @staticmethod
    def resolve_program_acronym(obj: SelectionProcess) -> str:
        return obj.program.acronym

    @staticmethod
    def resolve_notice_url(obj: SelectionProcess) -> str:
        return obj.notice_file.url if obj.notice_file else ""

    @staticmethod
    def resolve_stages(obj: SelectionProcess) -> list[Any]:
        return list(obj.stages.all())

    @staticmethod
    def resolve_vacancies(obj: SelectionProcess) -> list[Any]:
        return _vagas_abertas(obj)

    @staticmethod
    def resolve_levels(obj: SelectionProcess) -> list[dict[str, str]]:
        return _opcoes(SelectionLevel, {v.level for v in _vagas_abertas(obj)})

    @staticmethod
    def resolve_quota_categories(obj: SelectionProcess) -> list[dict[str, str]]:
        return _opcoes(QuotaCategory, {v.quota_category for v in _vagas_abertas(obj)})

    @staticmethod
    def resolve_targets(obj: SelectionProcess) -> list[dict[str, Any]]:
        alvos: dict[tuple[int | None, int | None], dict[str, Any]] = {}
        for vaga in _vagas_abertas(obj):
            chave = (vaga.project_id, vaga.research_line_id)
            if chave not in alvos:
                alvo = vaga.project or vaga.research_line
                alvos[chave] = {
                    "project_id": vaga.project_id,
                    "research_line_id": vaga.research_line_id,
                    "label": str(alvo) if alvo is not None else "",
                }
        return list(alvos.values())


def _vagas_abertas(process: SelectionProcess) -> list[Vacancy]:
    """As vagas com quantidade > 0 deste edital, lidas uma vez só.

    Os quatro `resolve_` de `PublicProcessOut` derivam da mesma lista; sem
    o cache no objeto, cada um faria a própria consulta e a listagem
    pública viraria 4 × N queries.
    """
    cache = getattr(process, "_vagas_abertas", None)
    if cache is None:
        cache = [v for v in process.vacancies.all() if v.quantity > 0]
        process._vagas_abertas = cache  # type: ignore[attr-defined]
    return cache


def _opcoes(choices: Any, valores: set[str]) -> list[dict[str, str]]:
    """Value + label na ordem do `TextChoices`, filtrado pelo que existe."""
    return [
        {"value": str(opcao), "label": opcao.label}
        for opcao in choices
        if str(opcao) in valores
    ]


class ApplicationIn(Schema):
    """O formulário público de inscrição, sem os anexos.

    Vai por `Form(...)` porque a requisição é multipart: o candidato manda
    os dados e os cinco a sete documentos num POST só (não há sessão para
    guardar rascunho entre chamadas).

    Sem `program_id`: o tenant é o programa do edital, resolvido por
    `edital_com_inscricao_aberta`. Sem `status` nem `protocol` — os dois
    são do servidor.
    """

    process_id: int
    full_name: str
    email: str
    cpf: str
    birth_date: datetime.date
    phone_number: str = ""
    level: SelectionLevel
    project_id: int | None = None
    research_line_id: int | None = None
    quota_category: QuotaCategory


class ApplicationReceiptOut(Schema):
    """O comprovante que o candidato anota: protocolo e instante.

    Nada mais sai daqui. O que ele digitou já está na tela dele, e o que o
    sistema decidiu depois (homologação) se consulta pelo protocolo.
    """

    protocol: str
    submitted_at: datetime.datetime


class ApplicationStatusOut(Schema):
    """A consulta pública de protocolo.

    Sem nome, CPF, e-mail ou documento: quem tem o protocolo pode não ser o
    candidato (ele passa o número adiante), então a resposta diz só em que
    pé está a inscrição.
    """

    protocol: str
    status: ApplicationStatus
    status_label: str
    submitted_at: datetime.datetime
    process_title: str

    @staticmethod
    def resolve_status_label(obj: Application) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_process_title(obj: Application) -> str:
        return obj.process.title


# ---------------------------------------------------------------------------
# Inscrições (secretaria)
# ---------------------------------------------------------------------------


class ApplicationDocumentOut(Schema):
    """Um anexo da inscrição, sem o caminho do arquivo.

    Nem `file` nem `file.url` entram aqui, pelo mesmo motivo de
    `academic.RequestDocumentOut`: o MEDIA é servido pelo Nginx sem passar
    pelo Django, então publicar a URL entregaria o documento de identidade
    do candidato a quem descobrisse o endereço — e sem `AuditLog`. O único
    caminho para o conteúdo é a rota de download, que exige
    `download_applicationdocument` e registra a leitura.
    """

    id: int
    kind: str
    kind_label: str
    filename: str
    size: int
    uploaded_at: datetime.datetime

    @staticmethod
    def resolve_kind_label(obj: ApplicationDocument) -> str:
        return obj.get_kind_display()

    @staticmethod
    def resolve_filename(obj: ApplicationDocument) -> str:
        """Só o nome, sem o diretório: o caminho é detalhe do storage e
        expõe o id do edital e da inscrição sem necessidade."""
        return Path(obj.file.name or "").name

    @staticmethod
    def resolve_size(obj: ApplicationDocument) -> int:
        """Arquivo sumido do storage vale 0, e não erro 500: a lista
        precisa continuar mostrando que o anexo existe para a secretaria
        poder cobrar o reenvio."""
        try:
            return obj.file.size
        except (FileNotFoundError, ValueError):
            return 0


class ApplicationOut(Schema):
    """A inscrição como a lista da secretaria a vê.

    O CPF viaja inteiro: quem lê esta rota é a secretaria, que confere a
    inscrição contra o documento anexado, e a busca da tela é por nome,
    protocolo ou CPF. A rota pública de protocolo (`ApplicationStatusOut`)
    continua sem nada disso.
    """

    id: int
    program_id: int
    process_id: int
    process_title: str
    protocol: str
    full_name: str
    email: str
    cpf: str
    phone_number: str
    level: SelectionLevel
    level_label: str
    project_id: int | None
    research_line_id: int | None
    target_label: str
    quota_category: QuotaCategory
    quota_category_label: str
    status: ApplicationStatus
    status_label: str
    decision_note: str
    decided_at: datetime.datetime | None
    submitted_at: datetime.datetime

    @staticmethod
    def resolve_process_title(obj: Application) -> str:
        return obj.process.title

    @staticmethod
    def resolve_level_label(obj: Application) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_quota_category_label(obj: Application) -> str:
        return obj.get_quota_category_display()

    @staticmethod
    def resolve_status_label(obj: Application) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_target_label(obj: Application) -> str:
        alvo = obj.project or obj.research_line
        return str(alvo) if alvo is not None else ""


class ApplicationDetailOut(ApplicationOut):
    """O detalhe da inscrição: a lista mais os anexos.

    `missing_documents` sai resolvido porque quem homologa precisa saber,
    na mesma tela, se o candidato mandou tudo o que o edital e a cota dele
    exigem — a conta é do model (`required_document_kinds`), não da tela.
    """

    birth_date: datetime.date
    documents: list[ApplicationDocumentOut]
    missing_documents: list[str]

    @staticmethod
    def resolve_documents(obj: Application) -> Any:
        return obj.documents.all()

    @staticmethod
    def resolve_missing_documents(obj: Application) -> list[str]:
        return obj.missing_documents()


class ApplicationDecisionIn(Schema):
    """A justificativa da decisão da secretaria.

    Uma entrada para as duas rotas: na homologação a nota é opcional
    (registra a conferência, quando há algo a dizer) e no indeferimento é
    obrigatória — quem cobra é `Application.reject`, com
    `rejection_requires_note`, e não o schema: a regra é do domínio.
    """

    note: str = ""


# ---------------------------------------------------------------------------
# Notas da etapa (banca)
# ---------------------------------------------------------------------------


class BoardStageOut(Schema):
    """A etapa do edital, como a tela do docente a vê dentro da banca.

    Existe separada de `SelectionStageOut` porque o Docente **não** tem
    `view_selectionstage` (migration 0006): quem compõe banca lê a etapa
    pela própria banca, e não pela grade do edital. Sem `tiebreak_rank` e
    sem carimbos — para lançar nota basta saber qual sessão é, quando e
    onde.
    """

    id: int
    name: str
    order: int
    session_at: datetime.datetime | None
    location: str


class MyBoardOut(BoardOut):
    """Uma banca do docente da sessão, com as etapas do edital embutidas.

    As etapas viajam junto pelo motivo acima: a tela "minhas bancas"
    precisa oferecer a lista de sessões para lançar nota, e o docente não
    tem rota para buscá-las.
    """

    stages: list[BoardStageOut]

    @staticmethod
    def resolve_stages(obj: Board) -> Any:
        return obj.process.stages.all()


class StageScoreIn(Schema):
    """Uma linha do lote de notas: a inscrição e a nota — ou a ausência.

    `score` e `absent` são XOR, e quem cobra é `StageScore.clean()`
    (`absent_xor_score`), não o schema: é invariante do model, e vale
    também para quem escrever fora da rota.
    """

    application_id: int
    score: decimal.Decimal | None = None
    absent: bool = False


class StageScoreOut(Schema):
    """Uma linha da planilha da banca: o candidato vivo e a nota atual.

    A planilha nasce das **inscrições**, não das notas: enquanto a banca
    não lançou, a linha existe com `scored: false` e `score: null`. É o
    que faz a tela mostrar quem falta avaliar em vez de uma lista vazia.

    A nota da etapa chega pré-carregada em `nota_da_etapa` (um
    `Prefetch` com `to_attr` no router), então nenhuma linha desta lista
    consulta o banco por conta própria.
    """

    application_id: int
    protocol: str
    full_name: str
    level: SelectionLevel
    quota_category: QuotaCategory
    quota_category_label: str
    scored: bool
    score: decimal.Decimal | None
    absent: bool
    passed: bool
    entered_at: datetime.datetime | None
    entered_by: str

    @staticmethod
    def _nota(obj: Application) -> Any:
        notas = getattr(obj, "nota_da_etapa", [])
        return notas[0] if notas else None

    @staticmethod
    def resolve_application_id(obj: Application) -> int:
        return obj.pk

    @staticmethod
    def resolve_quota_category_label(obj: Application) -> str:
        return obj.get_quota_category_display()

    @staticmethod
    def resolve_scored(obj: Application) -> bool:
        return StageScoreOut._nota(obj) is not None

    @staticmethod
    def resolve_score(obj: Application) -> decimal.Decimal | None:
        nota = StageScoreOut._nota(obj)
        return None if nota is None else nota.score

    @staticmethod
    def resolve_absent(obj: Application) -> bool:
        nota = StageScoreOut._nota(obj)
        return False if nota is None else nota.absent

    @staticmethod
    def resolve_passed(obj: Application) -> bool:
        """Sem nota lançada, `false`: quem não foi avaliado não passou —
        e `scored` é o campo que distingue "não passou" de "ainda não
        tem nota"."""
        nota = StageScoreOut._nota(obj)
        return False if nota is None else nota.passed

    @staticmethod
    def resolve_entered_at(obj: Application) -> datetime.datetime | None:
        nota = StageScoreOut._nota(obj)
        return None if nota is None else nota.entered_at

    @staticmethod
    def resolve_entered_by(obj: Application) -> str:
        """O nome de quem lançou, para a banca saber com quem falar. Nota
        antiga sem autor (ou lançada por script) volta vazia."""
        nota = StageScoreOut._nota(obj)
        if nota is None or nota.entered_by is None:
            return ""
        return nota.entered_by.person.full_name


# ---------------------------------------------------------------------------
# Ata da etapa
# ---------------------------------------------------------------------------


class RecordRowOut(Schema):
    """Uma linha do `content` da ata — a nota como ela foi congelada.

    Não é lida do `StageScore`: vem do JSON gravado na ata, que é o que o
    `content_hash` cobre. Depois do congelamento a fonte da verdade da
    ata é ela mesma, e não a tabela de notas, que pode ter sido corrigida
    numa versão seguinte.

    `score` é **string** de propósito (`"85.50"`): é assim que está no
    JSON, porque `float` mudaria o hash entre gravações.
    """

    application_id: int
    protocol: str
    full_name: str
    quota_category: str
    score: str | None
    absent: bool
    passed: bool


class RecordSignatureOut(Schema):
    """Uma assinatura da ata, como as telas a mostram.

    O `token_hash` **não** sai daqui, e nem o token: o que a secretaria
    precisa saber é se o e-mail saiu (`token_sent_at`) e até quando o
    link vale. Do hash assinado viajam só os 12 primeiros dígitos — o
    suficiente para conferir a olho contra o rodapé do PDF, e nada além.
    """

    id: int
    signer_id: int
    signer_name: str
    signer_category: str
    signer_institution: str
    method: SignatureMethod
    method_label: str
    signed: bool
    signed_at: datetime.datetime | None
    signed_hash_prefix: str
    token_sent_at: datetime.datetime | None
    token_expires_at: datetime.datetime | None

    @staticmethod
    def resolve_signer_name(obj: RecordSignature) -> str:
        return obj.signer.person.full_name

    @staticmethod
    def resolve_signer_category(obj: RecordSignature) -> str:
        return obj.signer.get_category_display()

    @staticmethod
    def resolve_signer_institution(obj: RecordSignature) -> str:
        return obj.signer.home_institution

    @staticmethod
    def resolve_method_label(obj: RecordSignature) -> str:
        return obj.get_method_display()

    @staticmethod
    def resolve_signed(obj: RecordSignature) -> bool:
        return obj.is_signed

    @staticmethod
    def resolve_signed_hash_prefix(obj: RecordSignature) -> str:
        return obj.signed_hash[:12]


class RecordSummaryOut(Schema):
    """A ata sem o conteúdo: cabeçalho, situação e assinaturas.

    É o que a listagem da secretaria (`GET /records/`) devolve. O
    `content` fica de fora porque a lista traz **todas** as atas de um
    edital — etapa × nível × alvo, mais as versões antigas —, e cada
    conteúdo é a planilha inteira daquele alvo. Quem precisa das notas
    abre a ata (ou o PDF); quem acompanha o edital precisa de situação e
    de quem falta assinar.

    As assinaturas viajam dentro da ata, e não numa rota própria, pelo
    mesmo motivo das etapas em `MyBoardOut`: o Docente **não** tem
    `view_recordsignature` (migration 0006), e a tela dele precisa
    mostrar quem já assinou. Uma ata tem três assinaturas — não há o que
    paginar.

    `content_hash` sai inteiro porque é ele que o examinador confere
    antes de assinar (a rota de assinatura o recebe de volta).
    """

    id: int
    program_id: int
    process_id: int
    process_title: str
    stage_id: int
    stage_name: str
    board_id: int
    level: SelectionLevel
    level_label: str
    project_id: int | None
    research_line_id: int | None
    target_label: str
    replaced_member_id: int | None
    replaced_member_name: str
    version: int
    status: RecordStatus
    status_label: str
    content_hash: str
    hash_ok: bool
    has_pdf: bool
    frozen_at: datetime.datetime | None
    signed_at: datetime.datetime | None
    signatures: list[RecordSignatureOut]
    pending_signatures: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def resolve_process_title(obj: ExaminationRecord) -> str:
        return str(obj.process)

    @staticmethod
    def resolve_stage_name(obj: ExaminationRecord) -> str:
        return obj.stage.name

    @staticmethod
    def resolve_level_label(obj: ExaminationRecord) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_target_label(obj: ExaminationRecord) -> str:
        alvo = obj.project or obj.research_line
        return str(alvo) if alvo is not None else ""

    @staticmethod
    def resolve_replaced_member_name(obj: ExaminationRecord) -> str:
        impedido = obj.replaced_member
        return "" if impedido is None else impedido.person.full_name

    @staticmethod
    def resolve_status_label(obj: ExaminationRecord) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_hash_ok(obj: ExaminationRecord) -> bool:
        """Rascunho não tem hash e responde `false`: o campo só quer
        dizer algo depois do congelamento, onde `false` significa que o
        conteúdo gravado deixou de bater com o que foi assinado."""
        return obj.verify_hash()

    @staticmethod
    def resolve_has_pdf(obj: ExaminationRecord) -> bool:
        return bool(obj.pdf)

    @staticmethod
    def resolve_signatures(obj: ExaminationRecord) -> Any:
        return obj.signatures.all()

    @staticmethod
    def resolve_pending_signatures(obj: ExaminationRecord) -> int:
        return sum(1 for a in obj.signatures.all() if not a.is_signed)


class ExaminationRecordOut(RecordSummaryOut):
    """A ata de uma etapa, com o conteúdo congelado embutido.

    É o schema das rotas que tratam de **uma** ata — a da banca, a do
    examinador, a retificação. O `content` é a fotografia das notas no
    instante do congelamento, e é sobre ele que o `content_hash` (herdado
    do resumo) é calculado.
    """

    content: list[RecordRowOut]


class RecordFreezeIn(Schema):
    """Congelamento da ata, com o titular impedido quando houver.

    Só isso: o conteúdo da ata não vem do cliente em hipótese nenhuma —
    ele é lido das notas no servidor, no instante do congelamento.
    """

    replaced_member_id: int | None = None


class RecordSignIn(Schema):
    """Assinatura da ata pelo examinador logado.

    `content_hash` é o hash que a tela mostrou ao signatário. Vazio
    significa "assino o que está aí agora"; preenchido, o servidor confere
    e recusa com `record_changed` se a ata mudou desde a leitura — a
    assinatura vale sobre um texto, não sobre um identificador de ata.
    """

    content_hash: str = ""


# ---------------------------------------------------------------------------
# Assinatura por token (examinador externo, sem conta)
# ---------------------------------------------------------------------------


class PublicSignatureOut(Schema):
    """A ata como o examinador externo a vê antes de assinar.

    Cabeçalho, conteúdo e hash: é o mesmo documento que os examinadores
    logados conferem, com o que o link precisa dizer a quem chegou por
    e-mail (para quem é, e até quando vale).

    O que **não** sai daqui, e sai em `ExaminationRecordOut`: os ids de
    banca e programa, as outras assinaturas e o hash das demais. Quem tem
    o link é examinador de uma ata, não usuário do sistema — ele confere
    o texto que assina, e nada sobre o resto do processo.
    """

    signer_name: str
    signer_institution: str
    process_title: str
    stage_name: str
    level_label: str
    target_label: str
    version: int
    content: list[RecordRowOut]
    content_hash: str
    hash_ok: bool
    frozen_at: datetime.datetime | None
    token_expires_at: datetime.datetime | None
    pending_signatures: int

    @staticmethod
    def resolve_signer_name(obj: RecordSignature) -> str:
        return obj.signer.person.full_name

    @staticmethod
    def resolve_signer_institution(obj: RecordSignature) -> str:
        return obj.signer.home_institution

    @staticmethod
    def resolve_process_title(obj: RecordSignature) -> str:
        return str(obj.record.process)

    @staticmethod
    def resolve_stage_name(obj: RecordSignature) -> str:
        return obj.record.stage.name

    @staticmethod
    def resolve_level_label(obj: RecordSignature) -> str:
        return obj.record.get_level_display()

    @staticmethod
    def resolve_target_label(obj: RecordSignature) -> str:
        alvo = obj.record.project or obj.record.research_line
        return str(alvo) if alvo is not None else ""

    @staticmethod
    def resolve_version(obj: RecordSignature) -> int:
        return obj.record.version

    @staticmethod
    def resolve_content(obj: RecordSignature) -> Any:
        return obj.record.content

    @staticmethod
    def resolve_content_hash(obj: RecordSignature) -> str:
        return obj.record.content_hash

    @staticmethod
    def resolve_hash_ok(obj: RecordSignature) -> bool:
        return obj.record.verify_hash()

    @staticmethod
    def resolve_frozen_at(obj: RecordSignature) -> Any:
        return obj.record.frozen_at

    @staticmethod
    def resolve_pending_signatures(obj: RecordSignature) -> int:
        return obj.record.signatures.pending().count()


class PublicSignatureReceiptOut(Schema):
    """O comprovante da assinatura por token.

    O equivalente do `ApplicationReceiptOut` do candidato: quem assinou,
    quando, sobre qual hash e o que falta. Depois disto o link não abre
    mais (uso único), então a confirmação precisa vir na própria resposta
    — não há tela para onde voltar.
    """

    signer_name: str
    signed_at: datetime.datetime | None
    signed_hash: str
    record_status: RecordStatus
    record_status_label: str
    pending_signatures: int

    @staticmethod
    def resolve_signer_name(obj: RecordSignature) -> str:
        return obj.signer.person.full_name

    @staticmethod
    def resolve_record_status(obj: RecordSignature) -> str:
        return obj.record.status

    @staticmethod
    def resolve_record_status_label(obj: RecordSignature) -> str:
        return obj.record.get_status_display()

    @staticmethod
    def resolve_pending_signatures(obj: RecordSignature) -> int:
        return obj.record.signatures.pending().count()


# ---------------------------------------------------------------------------
# Convocação de etapa
# ---------------------------------------------------------------------------


class ConvocationEmailOut(Schema):
    """Um e-mail do lote, com o resultado da entrega.

    O corpo renderizado **não** viaja: são dezenas por lote, e a tela
    mostra situação, destinatário e o erro de quem falhou — que é o que
    a secretaria usa para decidir reenviar ou corrigir o endereço.
    """

    id: int
    application_id: int
    protocol: str
    full_name: str
    to_email: str
    status: EmailDeliveryStatus
    status_label: str
    attempts: int
    error: str
    sent_at: datetime.datetime | None

    @staticmethod
    def resolve_protocol(obj: ConvocationEmail) -> str:
        return obj.application.protocol

    @staticmethod
    def resolve_full_name(obj: ConvocationEmail) -> str:
        return obj.application.full_name

    @staticmethod
    def resolve_status_label(obj: ConvocationEmail) -> str:
        return obj.get_status_display()


class ConvocationOut(Schema):
    """Um lote de convocação, com a contagem por situação.

    É o resumo que a listagem devolve (mesma separação de
    `RecordSummaryOut`): a tela do edital mostra "10 enviados, 2
    falharam" por lote, e só quem abre o lote precisa da lista de
    destinatários.

    `subject` é a cópia guardada no disparo, não o template atual do
    edital — se alguém editou o edital depois, o que vale para o
    candidato é o que saiu.
    """

    id: int
    program_id: int
    process_id: int
    stage_id: int
    stage_name: str
    subject: str
    sent_by_name: str
    total: int
    sent: int
    failed: int
    pending: int
    created_at: datetime.datetime

    @staticmethod
    def resolve_stage_name(obj: Convocation) -> str:
        return obj.stage.name

    @staticmethod
    def resolve_sent_by_name(obj: Convocation) -> str:
        return "" if obj.sent_by is None else obj.sent_by.get_username()

    @staticmethod
    def resolve_total(obj: Convocation) -> int:
        return len(obj.emails.all())

    @staticmethod
    def resolve_sent(obj: Convocation) -> int:
        return sum(1 for e in obj.emails.all() if e.status == EmailDeliveryStatus.SENT)

    @staticmethod
    def resolve_failed(obj: Convocation) -> int:
        return sum(
            1 for e in obj.emails.all() if e.status == EmailDeliveryStatus.FAILED
        )

    @staticmethod
    def resolve_pending(obj: Convocation) -> int:
        return sum(
            1 for e in obj.emails.all() if e.status == EmailDeliveryStatus.PENDING
        )


class ConvocationDetailOut(ConvocationOut):
    """O lote com os destinatários — resposta do disparo e do reenvio,
    onde a secretaria precisa ver na hora quem ficou de fora."""

    emails: list[ConvocationEmailOut]

    @staticmethod
    def resolve_emails(obj: Convocation) -> Any:
        return obj.emails.all()


class ConvocableApplicationOut(Schema):
    """Um candidato que a etapa pode convocar, como a tela o mostra antes
    de disparar o lote.

    Quem decide o que é "convocável" é `Application.objects.convocable_for`
    — na etapa 1, quem está vivo; da 2 em diante, só as chaves cuja ata
    anterior está assinada. A tela nunca refaz essa conta: ela lê esta
    rota. `already_convoked` é o que o disparo vai pular (quem já recebeu
    e-mail nesta etapa, em lote nenhum), e existe para a secretaria saber
    de antemão quantos e-mails o botão manda.
    """

    id: int
    protocol: str
    full_name: str
    email: str
    level: SelectionLevel
    level_label: str
    target_label: str
    quota_category: QuotaCategory
    quota_category_label: str
    status: ApplicationStatus
    status_label: str
    already_convoked: bool

    @staticmethod
    def resolve_level_label(obj: Application) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_quota_category_label(obj: Application) -> str:
        return obj.get_quota_category_display()

    @staticmethod
    def resolve_status_label(obj: Application) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_target_label(obj: Application) -> str:
        alvo = obj.project or obj.research_line
        return str(alvo) if alvo is not None else ""


# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------


class RankingIn(Schema):
    """O recorte a classificar: um nível e um alvo.

    A classificação nunca é do edital inteiro — quem disputa entre si é
    quem concorre ao mesmo nível e ao mesmo alvo, porque é dele a grade de
    vagas. O alvo é XOR e amarrado ao tipo do edital (`ensure_target`).
    """

    level: SelectionLevel
    project_id: int | None = None
    research_line_id: int | None = None


class RankingSeatOut(Schema):
    """Uma linha da grade de vagas do alvo, como a tela do resultado a mostra."""

    quota_category: QuotaCategory
    quota_category_label: str
    quantity: int


class RankedApplicationOut(Schema):
    """Um candidato na lista de classificação.

    `tie_unresolved` não é campo do banco: é recalculado da nota e das
    notas de desempate a cada leitura, e marca quem o edital não conseguiu
    desempatar — a posição entre eles saiu do número da inscrição, que não
    é critério nenhum. Quem vê isto na tela precisa decidir fora do
    sistema.
    """

    id: int
    protocol: str
    full_name: str
    email: str
    level: SelectionLevel
    level_label: str
    target_label: str
    quota_category: QuotaCategory
    quota_category_label: str
    status: ApplicationStatus
    status_label: str
    final_score: decimal.Decimal | None
    final_rank: int | None
    final_outcome: str
    final_outcome_label: str
    ranked_at: datetime.datetime | None
    tie_unresolved: bool
    student_id: int | None

    @staticmethod
    def resolve_level_label(obj: Application) -> str:
        return obj.get_level_display()

    @staticmethod
    def resolve_quota_category_label(obj: Application) -> str:
        return obj.get_quota_category_display()

    @staticmethod
    def resolve_status_label(obj: Application) -> str:
        return obj.get_status_display()

    @staticmethod
    def resolve_final_outcome_label(obj: Application) -> str:
        return obj.get_final_outcome_display() if obj.final_outcome else ""

    @staticmethod
    def resolve_target_label(obj: Application) -> str:
        alvo = obj.project or obj.research_line
        return str(alvo) if alvo is not None else ""

    @staticmethod
    def resolve_tie_unresolved(obj: Application) -> bool:
        return bool(getattr(obj, "tie_unresolved", False))


class RankingOut(Schema):
    """A classificação de um (nível × alvo): vagas, lista e a trava.

    `locked` é o que desabilita o botão de recalcular na tela: com alguém
    já matriculado na chave, a lista virou matrícula e não se reescreve
    (`ranking_locked`). `computed_at` é o carimbo do último cálculo — nulo
    quando a chave ainda não foi classificada.
    """

    process_id: int
    level: SelectionLevel
    level_label: str
    project_id: int | None
    research_line_id: int | None
    target_label: str
    seats: list[RankingSeatOut]
    total_seats: int
    locked: bool
    computed_at: datetime.datetime | None
    applications: list[RankedApplicationOut]

    @staticmethod
    def resolve_process_id(obj: Any) -> int:
        return obj.process.pk

    @staticmethod
    def resolve_level_label(obj: Any) -> str:
        return dict(SelectionLevel.choices).get(obj.level, obj.level)

    @staticmethod
    def resolve_project_id(obj: Any) -> int | None:
        return None if obj.project is None else obj.project.pk

    @staticmethod
    def resolve_research_line_id(obj: Any) -> int | None:
        return None if obj.research_line is None else obj.research_line.pk

    @staticmethod
    def resolve_target_label(obj: Any) -> str:
        alvo = obj.project or obj.research_line
        return str(alvo) if alvo is not None else ""

    @staticmethod
    def resolve_seats(obj: Any) -> list[dict[str, Any]]:
        rotulos = dict(QuotaCategory.choices)
        return [
            {
                "quota_category": categoria,
                "quota_category_label": rotulos.get(categoria, categoria),
                "quantity": quantidade,
            }
            for categoria, quantidade in sorted(obj.seats.items())
        ]

    @staticmethod
    def resolve_total_seats(obj: Any) -> int:
        return sum(obj.seats.values())


# ---------------------------------------------------------------------------
# Realocação de vaga
# ---------------------------------------------------------------------------


class VacancyReallocationIn(Schema):
    """A decisão da comissão que move vaga de uma linha da grade para outra.

    Sem `program_id` e sem `process_id`: o programa é o da sessão e o
    edital vem da URL. `decided_by_note` é o número do ofício ou da ata —
    sem ele a realocação seria um número mudando no banco sem autoria.

    A espécie decide o que pode mudar: `level_transfer` é o mesmo alvo
    entre níveis diferentes, `notice_rectification` é o mesmo nível com
    alvo diferente. A categoria de cota é sempre preservada.
    """

    kind: ReallocationKind
    from_vacancy_id: int
    to_vacancy_id: int
    quantity: int
    reason: str
    decided_on: datetime.date
    decided_by_note: str


class VacancyReallocationOut(Schema):
    """A realocação como o histórico da tela de resultado a mostra.

    As duas vagas viajam inteiras (`VacancyOut`), com rótulo e nome do
    alvo já resolvidos: a linha do histórico precisa dizer "1 vaga de
    ampla, mestrado → doutorado" sem a tela cruzar ids.

    `quantity` da vaga é o saldo **de agora**, não o do dia da decisão:
    realocação não guarda foto da grade, e uma segunda realocação sobre a
    mesma linha muda o número que aparece aqui.
    """

    id: int
    program_id: int
    process_id: int
    kind: ReallocationKind
    kind_label: str
    from_vacancy: VacancyOut
    to_vacancy: VacancyOut
    quantity: int
    reason: str
    decided_on: datetime.date
    decided_by_note: str
    created_at: datetime.datetime

    @staticmethod
    def resolve_kind_label(obj: VacancyReallocation) -> str:
        return obj.get_kind_display()


# ---------------------------------------------------------------------------
# Conversão em aluno (secretaria)
# ---------------------------------------------------------------------------


class ApplicationEnrollIn(Schema):
    """O que a secretaria digita para transformar o classificado em aluno.

    `registration_number` vem de fora: quem emite matrícula é o sistema da
    UFMG. `project_id` é obrigatório mesmo no Regular, em que a inscrição
    já traz o projeto — o vínculo do aluno não herda por acidente um campo
    que a CheckConstraint do `Student` exige (armadilha 16 do plano), e no
    Suplementar a inscrição só tem linha de pesquisa.
    """

    registration_number: str
    admission_date: datetime.date
    project_id: int


class EnrollmentOut(Schema):
    """O vínculo recém-criado e a inscrição que virou ele.

    Os dois juntos porque a tela precisa dos dois: o aluno para o link de
    `/alunos` e a inscrição já em `enrolled` para trocar a linha da lista
    de classificação sem recarregar tudo.

    `deadline` sai preenchido sem ter entrado: o prazo regimental é
    calculado no `Student.save()` a partir do ingresso e do nível.
    """

    student_id: int
    person_id: int
    registration_number: str
    level: str
    project_id: int
    admission_date: datetime.date
    deadline: datetime.date | None
    application: ApplicationDetailOut

    @staticmethod
    def resolve_student_id(obj: dict[str, Any]) -> int:
        return int(obj["student"].pk)

    @staticmethod
    def resolve_person_id(obj: dict[str, Any]) -> int:
        return int(obj["student"].person_id)

    @staticmethod
    def resolve_registration_number(obj: dict[str, Any]) -> str:
        return str(obj["student"].registration_number or "")

    @staticmethod
    def resolve_level(obj: dict[str, Any]) -> str:
        return str(obj["student"].level or "")

    @staticmethod
    def resolve_project_id(obj: dict[str, Any]) -> int:
        return int(obj["student"].project_id)

    @staticmethod
    def resolve_admission_date(obj: dict[str, Any]) -> Any:
        return obj["student"].admission_date

    @staticmethod
    def resolve_deadline(obj: dict[str, Any]) -> Any:
        return obj["student"].deadline
