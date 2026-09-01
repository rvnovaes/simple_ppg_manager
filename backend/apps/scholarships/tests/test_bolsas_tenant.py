"""Nenhuma rota do módulo de bolsas alcança dado de outro programa.

Seção 7 do plano, e o motivo de o `seed_demo` semear **dois** programas:
vazamento de tenant não aparece em lint, não aparece em typecheck e, com
um único programa no banco, também não aparece em teste — a asserção
passa porque não há o que vazar.

Aqui o cenário é montado **inteiro nos dois programas** (edição, barema,
comissão, inscrição, comprovante, lançamento, observação e recurso) e um
usuário do programa A, com **todos os papéis da bolsa**, tenta alcançar
cada objeto do programa B por cada rota do módulo.

Duas coisas de propósito:

1. **A asserção é 404 estrito**, e não "não é 200". 403 ou 409 também
   seriam falha: os dois significam que a rota chegou ao objeto do outro
   programa e só então recusou por outro motivo — o escopo tem de entrar
   na *busca* (`for_program`), como em `_edicao_do_programa`.
2. **O usuário de A tem todos os papéis** (Discente, Secretaria, Comissão
   de Bolsas e Coordenação) justamente para que o 404 não possa ser
   confundido com o 403 de quem não tinha permissão nenhuma.

As duas edições estão em `appeals_under_review`, o estado em que quase
tudo do módulo é permitido: num estado restritivo, um vazamento poderia
se esconder atrás do 409 da guarda de fase.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.academic.models import Student, Teacher
from apps.programs.models import Program
from apps.scholarships.models import (
    AppealOutcome,
    ApplicationDocument,
    ApplicationDocumentKind,
    BaremeEntry,
    BaremeItem,
    CommitteeMember,
    ItemReview,
    PriorityBand,
    ScholarshipAppeal,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipEditionStatus,
    ScholarshipLevel,
)
from apps.scholarships.router import router

from .test_bolsas_api_edital import criar_docente
from .test_bolsas_api_inscricao import criar_discente
from .test_bolsas_api_lancamentos import criar_item

pytestmark = pytest.mark.django_db

BASE = "/api/v1/scholarships"

# Todos os papéis que participam do edital: o usuário do teste os acumula
# para que nenhuma resposta 404 possa ser explicada por falta de permissão.
PAPEIS_DA_BOLSA = ("Discente", "Secretaria", "Comissão de Bolsas", "Coordenação")


# --- cenário ---------------------------------------------------------------


@dataclass(frozen=True)
class Cenario:
    """Um edital de bolsas completo dentro de um programa."""

    program: Program
    edicao: ScholarshipEdition
    item: BaremeItem
    docente: Teacher
    membro: CommitteeMember
    aluno: Student
    inscricao: ScholarshipApplication
    documento: ApplicationDocument
    lancamento: BaremeEntry
    observacao: ItemReview
    recurso: ScholarshipAppeal


def arquivo(nome: str = "comprovante.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(nome, b"%PDF-1.4 prova", content_type="application/pdf")


def montar_cenario(program: Program, *, username: str, nome: str) -> Cenario:
    """O edital inteiro, escrito pelo ORM.

    Pelo ORM e não pela API de propósito: o cenário do programa B precisa
    existir mesmo para quem não tem sessão nele, e as guardas de fase e de
    posse não são o assunto deste arquivo.
    """
    edicao = ScholarshipEdition.objects.create(
        program=program,
        year=2026,
        title="Edital de Bolsas 2026",
        status=ScholarshipEditionStatus.APPEALS_UNDER_REVIEW,
    )
    item = criar_item(edicao)
    docente = criar_docente(
        program, f"Docente {nome}", f"docente-{username}@exemplo.br"
    )
    membro = CommitteeMember.objects.create(
        edition=edicao, teacher=docente, appointed_on=date(2026, 2, 1)
    )
    aluno = criar_discente(program=program, username=username, nome=nome)
    inscricao = ScholarshipApplication.for_student(edition=edicao, student=aluno)
    inscricao.save()
    documento = ApplicationDocument.objects.create(
        application=inscricao,
        kind=ApplicationDocumentKind.AFFIRMATIVE_ACTION,
        file=arquivo(f"autodeclaracao-{username}.pdf"),
    )
    lancamento = BaremeEntry.objects.create(
        application=inscricao,
        item=item,
        description="Estágio em docência 2026/1",
        quantity=Decimal("2"),
        candidate_score=item.raw_score(Decimal("2")),
        proof=arquivo(f"certificado-{username}.pdf"),
    )
    observacao = ItemReview.objects.create(
        application=inscricao, item=item, note="Comprovante ilegível."
    )
    recurso = ScholarshipAppeal.objects.create(
        application=inscricao, text="Peço a revisão da pontuação do item 1.8."
    )
    return Cenario(
        program=program,
        edicao=edicao,
        item=item,
        docente=docente,
        membro=membro,
        aluno=aluno,
        inscricao=inscricao,
        documento=documento,
        lancamento=lancamento,
        observacao=observacao,
        recurso=recurso,
    )


@pytest.fixture
def outro_programa(db) -> Program:
    return Program.objects.create(name="Pós em Economia", acronym="PPGE")


@pytest.fixture
def meu(program: Program) -> Cenario:
    return montar_cenario(program, username="ana", nome="Ana Ribeiro")


@pytest.fixture
def alheio(outro_programa: Program) -> Cenario:
    return montar_cenario(outro_programa, username="bruno", nome="Bruno Lima")


@pytest.fixture
def client_do_programa(client: Client, meu: Cenario) -> Client:
    """A sessão de quem tem vínculo ativo **só** no programa A.

    Os quatro papéis juntos são o pior caso para o escopo: se alguma rota
    dependesse da permissão para recortar o tenant, é aqui que o dado do
    outro programa apareceria.
    """
    user = meu.aluno.person.user
    assert user is not None
    for papel in PAPEIS_DA_BOLSA:
        user.groups.add(Group.objects.get(name=papel))
    client.force_login(user)
    return client


# --- as rotas, uma a uma ---------------------------------------------------
#
# Cada caso é uma chamada `(client, alheio, meu) -> response` que aponta
# para um objeto do programa B. A lista tem de acompanhar o `router.py`:
# rota nova do módulo entra aqui também.


def _json(client: Client, metodo: str, url: str, dados: Any) -> Any:
    return getattr(client, metodo)(url, data=dados, content_type="application/json")


CASOS: dict[str, Any] = {
    "GET /editions/{id}/": lambda c, b, a: c.get(f"{BASE}/editions/{b.edicao.pk}/"),
    "PATCH /editions/{id}/": lambda c, b, a: _json(
        c, "patch", f"{BASE}/editions/{b.edicao.pk}/", {"title": "Sequestrado"}
    ),
    "POST /editions/{id}/open-submissions": lambda c, b, a: c.post(
        f"{BASE}/editions/{b.edicao.pk}/open-submissions"
    ),
    "POST /editions/{id}/start-review": lambda c, b, a: c.post(
        f"{BASE}/editions/{b.edicao.pk}/start-review"
    ),
    "POST /editions/{id}/publish-preliminary": lambda c, b, a: c.post(
        f"{BASE}/editions/{b.edicao.pk}/publish-preliminary"
    ),
    "POST /editions/{id}/open-appeals": lambda c, b, a: c.post(
        f"{BASE}/editions/{b.edicao.pk}/open-appeals"
    ),
    "POST /editions/{id}/publish-final": lambda c, b, a: c.post(
        f"{BASE}/editions/{b.edicao.pk}/publish-final"
    ),
    "GET /editions/{id}/result": lambda c, b, a: c.get(
        f"{BASE}/editions/{b.edicao.pk}/result?level={ScholarshipLevel.MASTERS}"
    ),
    "GET /editions/{id}/result.pdf": lambda c, b, a: c.get(
        f"{BASE}/editions/{b.edicao.pk}/result.pdf?level={ScholarshipLevel.MASTERS}"
    ),
    "GET /editions/{id}/bareme/": lambda c, b, a: c.get(
        f"{BASE}/editions/{b.edicao.pk}/bareme/"
    ),
    "POST /editions/{id}/bareme/": lambda c, b, a: _json(
        c,
        "post",
        f"{BASE}/editions/{b.edicao.pk}/bareme/",
        {
            "level": ScholarshipLevel.MASTERS,
            "section": b.item.section,
            "code": "9.9",
            "text": "Linha intrusa",
            "unit": b.item.unit,
            "points_per_unit": "1.00",
            "cap": "2.00",
        },
    ),
    "PATCH /editions/{id}/bareme/{item}/": lambda c, b, a: _json(
        c,
        "patch",
        f"{BASE}/editions/{b.edicao.pk}/bareme/{b.item.pk}/",
        {"text": "Sequestrado"},
    ),
    "DELETE /editions/{id}/bareme/{item}/": lambda c, b, a: c.delete(
        f"{BASE}/editions/{b.edicao.pk}/bareme/{b.item.pk}/"
    ),
    "POST /editions/{id}/bareme/clone (destino alheio)": lambda c, b, a: _json(
        c,
        "post",
        f"{BASE}/editions/{b.edicao.pk}/bareme/clone",
        {"source_edition_id": a.edicao.pk},
    ),
    "POST /editions/{id}/bareme/clone (origem alheia)": lambda c, b, a: _json(
        c,
        "post",
        f"{BASE}/editions/{a.edicao.pk}/bareme/clone",
        {"source_edition_id": b.edicao.pk},
    ),
    "GET /editions/{id}/committee/": lambda c, b, a: c.get(
        f"{BASE}/editions/{b.edicao.pk}/committee/"
    ),
    "POST /editions/{id}/committee/": lambda c, b, a: _json(
        c,
        "post",
        f"{BASE}/editions/{b.edicao.pk}/committee/",
        {"teacher_id": b.docente.pk},
    ),
    "POST /editions/{id}/committee/ (docente alheio)": lambda c, b, a: _json(
        c,
        "post",
        f"{BASE}/editions/{a.edicao.pk}/committee/",
        {"teacher_id": b.docente.pk},
    ),
    "DELETE /editions/{id}/committee/{membro}/": lambda c, b, a: c.delete(
        f"{BASE}/editions/{b.edicao.pk}/committee/{b.membro.pk}/"
    ),
    "GET /editions/{id}/my-application": lambda c, b, a: c.get(
        f"{BASE}/editions/{b.edicao.pk}/my-application"
    ),
    "POST /applications/": lambda c, b, a: _json(
        c, "post", f"{BASE}/applications/", {"edition_id": b.edicao.pk}
    ),
    "PATCH /applications/{id}/": lambda c, b, a: _json(
        c,
        "patch",
        f"{BASE}/applications/{b.inscricao.pk}/",
        {"affirmative_action": True},
    ),
    "DELETE /applications/{id}/": lambda c, b, a: c.delete(
        f"{BASE}/applications/{b.inscricao.pk}/"
    ),
    "POST /applications/{id}/documents": lambda c, b, a: c.post(
        f"{BASE}/applications/{b.inscricao.pk}/documents",
        data={
            "kind": ApplicationDocumentKind.AFFIRMATIVE_ACTION,
            "file": arquivo("intruso.pdf"),
        },
    ),
    "GET /documents/{id}/download": lambda c, b, a: c.get(
        f"{BASE}/documents/{b.documento.pk}/download"
    ),
    "GET /applications/{id}/entries/": lambda c, b, a: c.get(
        f"{BASE}/applications/{b.inscricao.pk}/entries/"
    ),
    "POST /applications/{id}/entries/": lambda c, b, a: c.post(
        f"{BASE}/applications/{b.inscricao.pk}/entries/",
        data={
            "item_id": b.item.pk,
            "description": "Lançamento intruso",
            "quantity": "1",
            "proof": arquivo("intruso.pdf"),
        },
    ),
    "POST /applications/{id}/entries/ (item alheio)": lambda c, b, a: c.post(
        f"{BASE}/applications/{a.inscricao.pk}/entries/",
        data={
            "item_id": b.item.pk,
            "description": "Item de outro programa",
            "quantity": "1",
            "proof": arquivo("intruso.pdf"),
        },
    ),
    "PATCH /applications/{id}/entries/{entry}/": lambda c, b, a: _json(
        c,
        "patch",
        f"{BASE}/applications/{b.inscricao.pk}/entries/{b.lancamento.pk}/",
        {"description": "Sequestrado"},
    ),
    "PATCH /applications/{minha}/entries/{entry alheio}/": lambda c, b, a: _json(
        c,
        "patch",
        f"{BASE}/applications/{a.inscricao.pk}/entries/{b.lancamento.pk}/",
        {"description": "Sequestrado"},
    ),
    "POST /applications/{id}/entries/{entry}/proof": lambda c, b, a: c.post(
        f"{BASE}/applications/{b.inscricao.pk}/entries/{b.lancamento.pk}/proof",
        data={"proof": arquivo("intruso.pdf")},
    ),
    "DELETE /applications/{id}/entries/{entry}/": lambda c, b, a: c.delete(
        f"{BASE}/applications/{b.inscricao.pk}/entries/{b.lancamento.pk}/"
    ),
    "GET /entries/{id}/proof/download": lambda c, b, a: c.get(
        f"{BASE}/entries/{b.lancamento.pk}/proof/download"
    ),
    "GET /editions/{id}/applications/": lambda c, b, a: c.get(
        f"{BASE}/editions/{b.edicao.pk}/applications/?level={ScholarshipLevel.MASTERS}"
    ),
    "PATCH /entries/{id}/review": lambda c, b, a: _json(
        c,
        "patch",
        f"{BASE}/entries/{b.lancamento.pk}/review",
        {"committee_score": "1.00", "committee_note": "Intruso"},
    ),
    "GET /applications/{id}/item-reviews/": lambda c, b, a: c.get(
        f"{BASE}/applications/{b.inscricao.pk}/item-reviews/"
    ),
    "PUT /applications/{id}/item-review": lambda c, b, a: _json(
        c,
        "put",
        f"{BASE}/applications/{b.inscricao.pk}/item-review",
        {"item_id": b.item.pk, "note": "Intruso"},
    ),
    "PUT /applications/{minha}/item-review (item alheio)": lambda c, b, a: _json(
        c,
        "put",
        f"{BASE}/applications/{a.inscricao.pk}/item-review",
        {"item_id": b.item.pk, "note": "Item de outro programa"},
    ),
    "PATCH /applications/{id}/fump": lambda c, b, a: _json(
        c, "patch", f"{BASE}/applications/{b.inscricao.pk}/fump", {"fump_level": 2}
    ),
    "PATCH /applications/{id}/band": lambda c, b, a: _json(
        c,
        "patch",
        f"{BASE}/applications/{b.inscricao.pk}/band",
        {
            "band_override": PriorityBand.B24_I,
            "band_override_reason": "Intruso",
        },
    ),
    "POST /applications/{id}/appeal": lambda c, b, a: _json(
        c,
        "post",
        f"{BASE}/applications/{b.inscricao.pk}/appeal",
        {"text": "Recurso intruso"},
    ),
    "GET /applications/{id}/appeal": lambda c, b, a: c.get(
        f"{BASE}/applications/{b.inscricao.pk}/appeal"
    ),
    "PATCH /appeals/{id}/judge": lambda c, b, a: _json(
        c,
        "patch",
        f"{BASE}/appeals/{b.recurso.pk}/judge",
        {"outcome": AppealOutcome.GRANTED, "reasoning": "Intruso"},
    ),
}


# Um caso cruzado age sobre a inscrição do PRÓPRIO programa levando um id
# alheio no corpo, e para chegar até o id a rota precisa passar antes pela
# janela de inscrição. Sem abrir a janela, o 409 de `ensure_editable`
# esconderia o que este arquivo quer medir: o teste passaria sem nunca ter
# tocado o objeto do outro programa.
JANELA_ABERTA_NA_MINHA_EDICAO = ("POST /applications/{id}/entries/ (item alheio)",)


@pytest.mark.parametrize("nome", list(CASOS), ids=list(CASOS))
def test_rota_nao_alcanca_objeto_de_outro_programa(
    nome: str, client_do_programa: Client, alheio: Cenario, meu: Cenario
) -> None:
    """404 estrito: 403 ou 409 significariam que a rota chegou ao objeto."""
    if nome in JANELA_ABERTA_NA_MINHA_EDICAO:
        ScholarshipEdition.objects.filter(pk=meu.edicao.pk).update(
            status=ScholarshipEditionStatus.SUBMISSIONS_OPEN
        )
    resposta = CASOS[nome](client_do_programa, alheio, meu)
    assert resposta.status_code == 404, (
        f"{nome} devolveu {resposta.status_code} para dado de outro programa"
    )


def _forma(rota: str) -> str:
    """A rota sem o nome do parâmetro: as chaves dos casos dizem "{id}" e
    "{item}" onde o Django escreve "{int:edition_id}"."""
    return re.sub(r"\{[^}]+\}", "{}", rota)


def test_a_lista_de_casos_cobre_todas_as_rotas_com_id() -> None:
    """A cobertura é do arquivo inteiro, não do que alguém lembrou de escrever.

    Sem esta asserção, rota nova do módulo nasce fora do teste de tenant e
    ninguém percebe: o arquivo continua verde com uma rota a menos.
    """
    rotas_com_id = {
        f"{metodo} {caminho}"
        for caminho, path_view in router.path_operations.items()
        for operacao in path_view.operations
        for metodo in operacao.methods
        if "{" in caminho
    }
    cobertas = {nome.split(" (")[0] for nome in CASOS}
    faltando = {_forma(r) for r in rotas_com_id} - {_forma(c) for c in cobertas}
    assert not faltando, f"rotas com id fora do teste de tenant: {sorted(faltando)}"


# --- as listagens do próprio programa --------------------------------------
#
# O outro lado da mesma moeda: a lista de A nunca traz linha de B. É o caso
# que o 404 não pega, porque aqui a rota responde 200 — o vazamento estaria
# **dentro** do corpo.


def test_lista_de_edicoes_so_traz_as_do_programa(
    client_do_programa: Client, meu: Cenario, alheio: Cenario
) -> None:
    resposta = client_do_programa.get(f"{BASE}/editions/")
    assert resposta.status_code == 200
    ids = [linha["id"] for linha in resposta.json()["items"]]
    assert ids == [meu.edicao.pk]


def test_fila_de_analise_so_traz_inscricoes_do_programa(
    client_do_programa: Client, meu: Cenario, alheio: Cenario
) -> None:
    resposta = client_do_programa.get(
        f"{BASE}/editions/{meu.edicao.pk}/applications/"
        f"?level={ScholarshipLevel.MASTERS}"
    )
    assert resposta.status_code == 200
    ids = [linha["id"] for linha in resposta.json()["items"]]
    assert ids == [meu.inscricao.pk]


def test_barema_so_traz_itens_da_edicao_do_programa(
    client_do_programa: Client, meu: Cenario, alheio: Cenario
) -> None:
    resposta = client_do_programa.get(f"{BASE}/editions/{meu.edicao.pk}/bareme/")
    assert resposta.status_code == 200
    assert [linha["id"] for linha in resposta.json()] == [meu.item.pk]


def test_comissao_so_traz_membros_da_edicao_do_programa(
    client_do_programa: Client, meu: Cenario, alheio: Cenario
) -> None:
    resposta = client_do_programa.get(f"{BASE}/editions/{meu.edicao.pk}/committee/")
    assert resposta.status_code == 200
    assert [linha["id"] for linha in resposta.json()] == [meu.membro.pk]


def test_lancamentos_so_trazem_os_da_propria_inscricao(
    client_do_programa: Client, meu: Cenario, alheio: Cenario
) -> None:
    resposta = client_do_programa.get(
        f"{BASE}/applications/{meu.inscricao.pk}/entries/"
    )
    assert resposta.status_code == 200
    assert [linha["id"] for linha in resposta.json()] == [meu.lancamento.pk]


def test_observacoes_so_trazem_as_da_propria_inscricao(
    client_do_programa: Client, meu: Cenario, alheio: Cenario
) -> None:
    resposta = client_do_programa.get(
        f"{BASE}/applications/{meu.inscricao.pk}/item-reviews/"
    )
    assert resposta.status_code == 200
    assert [linha["id"] for linha in resposta.json()] == [meu.observacao.pk]


def test_resultado_so_traz_candidatos_do_programa(
    client_do_programa: Client, meu: Cenario, alheio: Cenario
) -> None:
    """As dez faixas do nível saem sempre; o que não pode sair é gente de B."""
    resposta = client_do_programa.get(
        f"{BASE}/editions/{meu.edicao.pk}/result?level={ScholarshipLevel.MASTERS}"
    )
    assert resposta.status_code == 200
    candidatos = [
        linha["application_id"] for faixa in resposta.json() for linha in faixa["rows"]
    ]
    assert candidatos == [meu.inscricao.pk]
