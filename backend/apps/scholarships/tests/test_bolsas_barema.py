"""O barema: a aritmética do item, o lançamento e as notas da inscrição.

Nível (a) da pirâmide (Seção 9): objeto em memória, sem banco. Os números
são os do edital citados no plano — teste que confere aritmética de
dinheiro/nota com valor inventado não confere nada.

O caso que dá nome ao arquivo aparece duas vezes, e é o mesmo: **o teto
é do item, aplicado sobre a soma dos lançamentos**. Primeiro no par
`raw_score`/`apply_cap`, e depois em `ScholarshipApplication.committee_score()`,
que é quem agrupa por item antes de cortar. Com um lançamento só, aplicar
o teto em `raw_score` daria a mesma resposta; é com dois que a diferença
aparece.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.academic.models import Student
from apps.core.exceptions import DomainError
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.scholarships.models import (
    TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA,
    BaremeEntry,
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    ItemReview,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipLevel,
)


def _item(**kwargs) -> BaremeItem:
    campos = {
        "edition": ScholarshipEdition(pk=1),
        "level": ScholarshipLevel.MASTERS,
        "section": BaremeSection.FORMATION,
        "code": "1.3",
        "text": "Item do barema",
        "unit": BaremeUnit.SEMESTER,
        "points_per_unit": Decimal("0.50"),
        "cap": Decimal("3.00"),
    }
    return BaremeItem(**{**campos, **kwargs})


# --- raw_score: pontuação de UM lançamento, sem teto ------------------------


def test_um_semestre_a_meio_ponto_vale_meio_ponto():
    item = _item(unit=BaremeUnit.SEMESTER, points_per_unit=Decimal("0.50"))

    assert item.raw_score(Decimal("1")) == Decimal("0.50")


def test_doze_meses_a_zero_virgula_vinte_e_cinco_batem_exatamente_no_teto():
    """3,00 contra limite de 3,00: o teto não corta o que apenas alcança."""
    item = _item(
        unit=BaremeUnit.MONTH, points_per_unit=Decimal("0.25"), cap=Decimal("3.00")
    )

    bruto = item.raw_score(Decimal("12"))

    assert bruto == Decimal("3.00")
    assert item.apply_cap(bruto) == Decimal("3.00")


def test_tres_horas_a_um_centesimo_valem_tres_centesimos():
    item = _item(unit=BaremeUnit.HOUR, points_per_unit=Decimal("0.01"))

    assert item.raw_score(Decimal("3")) == Decimal("0.03")


def test_raw_score_nao_corta_pelo_teto():
    """`raw_score` ignora o `cap` de propósito: quem corta é `apply_cap`."""
    item = _item(points_per_unit=Decimal("0.50"), cap=Decimal("3.00"))

    assert item.raw_score(Decimal("20")) == Decimal("10.00")


def test_quantidade_fracionaria_pontua_proporcional():
    item = _item(unit=BaremeUnit.SEMESTER, points_per_unit=Decimal("0.50"))

    assert item.raw_score(Decimal("2.50")) == Decimal("1.250")


# --- apply_cap: o teto é do ITEM, sobre a SOMA dos lançamentos -------------


def test_teto_do_item_corta_a_soma_dos_lancamentos_e_nao_cada_um():
    """Dois lançamentos de 3,00 no item 1.8 somam 6,00 contra o limite de
    18,00: nenhum é cortado sozinho, e a soma passa inteira. É este caso
    que separa `raw_score` de `apply_cap`."""
    item = _item(code="1.8", points_per_unit=Decimal("3.00"), cap=Decimal("18.00"))

    lancamentos = [item.raw_score(Decimal("1")), item.raw_score(Decimal("1"))]

    assert lancamentos == [Decimal("3.00"), Decimal("3.00")]
    assert item.apply_cap(sum(lancamentos, Decimal("0.00"))) == Decimal("6.00")


def test_soma_acima_do_teto_e_cortada_no_teto():
    item = _item(code="1.8", points_per_unit=Decimal("3.00"), cap=Decimal("18.00"))

    total = sum((item.raw_score(Decimal("1")) for _ in range(10)), Decimal("0.00"))

    assert total == Decimal("30.00")
    assert item.apply_cap(total) == Decimal("18.00")


def test_apply_cap_nao_altera_soma_abaixo_do_teto():
    item = _item(cap=Decimal("3.00"))

    assert item.apply_cap(Decimal("0.50")) == Decimal("0.50")


# --- dinheiro/nota nunca é float -------------------------------------------


def test_pontuacao_e_sempre_decimal():
    """CLAUDE.md Seção 8: nota é `Decimal`, nunca `float` — 0,1 + 0,2 em
    binário não é 0,3, e o barema soma centésimos."""
    item = _item()

    assert isinstance(item.raw_score(Decimal("3")), Decimal)
    assert isinstance(item.apply_cap(Decimal("3.00")), Decimal)


# --- clean sem banco --------------------------------------------------------


def test_clean_sem_edicao_nao_consulta_o_banco():
    _item(edition=None, code="").clean()


# --- com banco --------------------------------------------------------------


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program, year=2026, title="Edital de Bolsas 2026"
    )


def _salvar_item(edicao: ScholarshipEdition, **kwargs) -> BaremeItem:
    item = _item(edition=edicao, **kwargs)
    item.clean()
    item.save()
    return item


@pytest.mark.django_db
def test_clean_rejeita_codigo_repetido_no_mesmo_nivel_da_edicao(edicao):
    """A duplicata vira `duplicate_bareme_item` (400), não `IntegrityError`."""
    _salvar_item(edicao, code="1.3")

    with pytest.raises(DomainError) as exc:
        _item(edition=edicao, code="1.3").clean()

    assert exc.value.code == "duplicate_bareme_item"
    assert exc.value.status_code == 400


@pytest.mark.django_db
def test_mesmo_codigo_no_outro_nivel_e_item_independente(edicao):
    """O barema é por (edição, nível): o 1.3 do mestrado e o do doutorado
    são itens diferentes, e podem valer pontos diferentes."""
    _salvar_item(edicao, code="1.3", level=ScholarshipLevel.MASTERS)

    doutorado = _salvar_item(
        edicao,
        code="1.3",
        level=ScholarshipLevel.DOCTORATE,
        points_per_unit=Decimal("1.00"),
    )

    assert BaremeItem.objects.for_edition(edicao).count() == 2
    assert doutorado.raw_score(Decimal("1")) == Decimal("1.00")


@pytest.mark.django_db
def test_clean_aceita_o_proprio_item_na_edicao(edicao):
    item = _salvar_item(edicao, code="1.3")

    item.text = "Descrição retificada"
    item.clean()


@pytest.mark.django_db
def test_for_program_chega_ao_programa_pela_edicao(edicao, program):
    _salvar_item(edicao, code="1.3")

    assert BaremeItem.objects.for_program(program).count() == 1


@pytest.mark.django_db
def test_for_level_separa_os_dois_baremas(edicao):
    _salvar_item(edicao, code="1.3", level=ScholarshipLevel.MASTERS)
    _salvar_item(edicao, code="1.3", level=ScholarshipLevel.DOCTORATE)

    itens = BaremeItem.objects.for_edition(edicao).for_level(ScholarshipLevel.MASTERS)

    assert [i.level for i in itens] == [ScholarshipLevel.MASTERS]


# ===========================================================================
# BaremeEntry — o lançamento, e as duas notas que convivem nele
# ===========================================================================
#
# Tudo aqui precisa de banco: as regras do lançamento comparam `item` com
# `application`, e as duas comparações só existem quando as FKs estão
# gravadas. O caso que dá nome a esta metade é o do teto: **o `cap` é do
# item e corta a SOMA dos lançamentos**, e é `committee_score()` da
# inscrição que o aplica.


@pytest.fixture
def discente(program: Program) -> Student:
    linha = ResearchLine.objects.create(program=program, name="Direito e Estado")
    projeto = CollectiveProject.objects.create(
        program=program, research_line=linha, name="Projeto coletivo"
    )
    pessoa = Person.objects.create(
        program=program, full_name="Maria Lima", primary_email="maria@example.com"
    )
    return Student.objects.create(
        program=program,
        person=pessoa,
        modality=Student.Modality.REGULAR,
        level=Student.Level.MASTERS,
        project=projeto,
        admission_date=date(2025, 3, 1),
    )


@pytest.fixture
def inscricao(edicao, discente) -> ScholarshipApplication:
    aplicacao = ScholarshipApplication.for_student(edition=edicao, student=discente)
    aplicacao.save()
    return aplicacao


def _lancamento(
    inscricao: ScholarshipApplication, item: BaremeItem, quantidade: str, **kwargs
) -> BaremeEntry:
    """Lançamento gravado, com `candidate_score` calculado como manda o
    plano: `item.raw_score(quantity)`, sem teto."""
    quantity = Decimal(quantidade)
    campos = {
        "application": inscricao,
        "item": item,
        "description": "Lançamento do candidato",
        "quantity": quantity,
        "candidate_score": item.raw_score(quantity),
        "proof": SimpleUploadedFile(f"comprovante-{item.code}.pdf", b"%PDF-1.4"),
    }
    lancamento = BaremeEntry(**{**campos, **kwargs})
    lancamento.clean()
    lancamento.save()
    return lancamento


# --- clean: o item precisa ser desta edição e deste nível ------------------


@pytest.mark.django_db
def test_clean_recusa_item_de_outra_edicao(inscricao, program):
    """Pontuar pela tabela de outro edital é o erro que a checagem impede."""
    outra = ScholarshipEdition.objects.create(
        program=program, year=2025, title="Edital de Bolsas 2025"
    )
    item = _salvar_item(outra, code="1.3")

    with pytest.raises(DomainError) as exc:
        BaremeEntry(
            application=inscricao,
            item=item,
            description="x",
            quantity=Decimal("1"),
            candidate_score=Decimal("0.50"),
        ).clean()

    assert exc.value.code == "bareme_item_mismatch"
    assert exc.value.status_code == 400


@pytest.mark.django_db
def test_clean_recusa_item_do_outro_nivel_da_mesma_edicao(inscricao, edicao):
    """O "1.3" do doutorado é outro item, com outros pontos — e a inscrição
    é de mestrado."""
    item = _salvar_item(edicao, code="1.3", level=ScholarshipLevel.DOCTORATE)

    with pytest.raises(DomainError) as exc:
        BaremeEntry(
            application=inscricao,
            item=item,
            description="x",
            quantity=Decimal("1"),
            candidate_score=Decimal("0.50"),
        ).clean()

    assert exc.value.code == "bareme_item_mismatch"


@pytest.mark.django_db
def test_clean_aceita_item_da_mesma_edicao_e_nivel(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3")

    assert _lancamento(inscricao, item, "2").candidate_score == Decimal("1.00")


# --- clean: quantidade e observação ----------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("quantidade", ["0", "-1.50"], ids=["zero", "negativa"])
def test_clean_recusa_quantidade_nao_positiva(inscricao, edicao, quantidade):
    item = _salvar_item(edicao, code="1.3")

    with pytest.raises(DomainError) as exc:
        BaremeEntry(
            application=inscricao,
            item=item,
            description="x",
            quantity=Decimal(quantidade),
            candidate_score=Decimal("0.00"),
        ).clean()

    assert exc.value.code == "invalid_quantity"


@pytest.mark.django_db
def test_clean_exige_observacao_quando_a_comissao_diverge(inscricao, edicao):
    """Decisão B9: a divergência é o que o recurso ataca, e recorrer contra
    um número sem motivo escrito não é recorrer."""
    item = _salvar_item(edicao, code="1.3")
    lancamento = _lancamento(inscricao, item, "2")

    lancamento.committee_score = Decimal("0.00")

    with pytest.raises(DomainError) as exc:
        lancamento.clean()

    assert exc.value.code == "note_required"


@pytest.mark.django_db
def test_divergencia_com_observacao_passa(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3")
    lancamento = _lancamento(inscricao, item, "2")

    lancamento.committee_score = Decimal("0.50")
    lancamento.committee_note = "O certificado cobre um semestre, não dois."
    lancamento.clean()


@pytest.mark.django_db
def test_confirmar_a_nota_do_candidato_nao_exige_observacao(inscricao, edicao):
    """Concordar é o caso comum: cobrar justificativa dele encheria a
    análise de texto vazio e faria a observação perder o sentido."""
    item = _salvar_item(edicao, code="1.3")
    lancamento = _lancamento(inscricao, item, "2")

    lancamento.committee_score = lancamento.candidate_score
    lancamento.clean()


@pytest.mark.django_db
def test_lancamento_nao_avaliado_nao_exige_observacao(inscricao, edicao):
    """Nulo é "ainda não olhei", e não uma divergência."""
    item = _salvar_item(edicao, code="1.3")

    lancamento = _lancamento(inscricao, item, "2")

    assert lancamento.committee_score is None


# --- validate_upload: comprovante do barema é só PDF -----------------------


@pytest.mark.parametrize("filename", ["certificado.pdf", "CERTIFICADO.PDF"])
def test_comprovante_do_barema_aceita_pdf(filename):
    BaremeEntry.validate_upload(filename=filename, size=1024)


@pytest.mark.parametrize(
    "filename",
    ["", "certificado", "foto.jpg", "foto.png", "certificado.pdf.exe"],
    ids=["vazio", "sem_extensao", "jpg", "png", "dupla"],
)
def test_comprovante_do_barema_recusa_o_que_nao_e_pdf(filename):
    """Mais estrito que o do questionário de propósito: aqui o anexo é
    certificado, não foto de celular."""
    with pytest.raises(DomainError) as exc:
        BaremeEntry.validate_upload(filename=filename, size=1024)

    assert exc.value.code == "invalid_document"


def test_comprovante_do_barema_aceita_exatamente_o_limite():
    BaremeEntry.validate_upload(
        filename="certificado.pdf", size=TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA
    )


def test_comprovante_do_barema_recusa_acima_do_limite():
    with pytest.raises(DomainError) as exc:
        BaremeEntry.validate_upload(
            filename="certificado.pdf",
            size=TAMANHO_MAXIMO_DO_COMPROVANTE_DO_BAREMA + 1,
        )

    assert exc.value.code == "invalid_document"


@pytest.mark.django_db
def test_comprovante_e_gravado_particionado_por_edicao_e_inscricao(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3")

    lancamento = _lancamento(inscricao, item, "1")

    assert lancamento.proof.name.startswith(
        f"bolsas/edicao-{edicao.pk}/inscricao-{inscricao.pk}/"
    )


# --- as notas da inscrição: o teto é do ITEM, sobre a SOMA -----------------


@pytest.mark.django_db
def test_committee_score_soma_dois_lancamentos_abaixo_do_teto(inscricao, edicao):
    """Dois lançamentos de 3,00 no item de limite 18,00 somam 6,00: nenhum
    é cortado sozinho e a soma passa inteira."""
    item = _salvar_item(
        edicao, code="1.8", points_per_unit=Decimal("3.00"), cap=Decimal("18.00")
    )
    for _ in range(2):
        _lancamento(inscricao, item, "1", committee_score=Decimal("3.00"))

    assert inscricao.committee_score() == Decimal("6.00")


@pytest.mark.django_db
def test_committee_score_corta_no_teto_do_item(inscricao, edicao):
    """Dois de 12,00 contra o limite de 18,00 somam 24,00 e saem 18,00 —
    é aqui que aplicar o teto por lançamento daria a resposta errada
    (12,00 + 12,00 continuariam 24,00, ou virariam 36,00)."""
    item = _salvar_item(
        edicao, code="1.8", points_per_unit=Decimal("12.00"), cap=Decimal("18.00")
    )
    for _ in range(2):
        _lancamento(inscricao, item, "1", committee_score=Decimal("12.00"))

    assert inscricao.committee_score() == Decimal("18.00")


@pytest.mark.django_db
def test_o_teto_e_por_item_e_nao_da_inscricao(inscricao, edicao):
    """Dois itens diferentes, cada um no seu limite: os tetos não se
    somam num teto geral, e as notas dos itens sim."""
    primeiro = _salvar_item(
        edicao, code="1.8", points_per_unit=Decimal("12.00"), cap=Decimal("18.00")
    )
    segundo = _salvar_item(
        edicao, code="2.1", points_per_unit=Decimal("10.00"), cap=Decimal("5.00")
    )
    for _ in range(2):
        _lancamento(inscricao, primeiro, "1", committee_score=Decimal("12.00"))
    _lancamento(inscricao, segundo, "1", committee_score=Decimal("10.00"))

    assert inscricao.committee_score() == Decimal("23.00")


@pytest.mark.django_db
def test_lancamento_nao_avaliado_conta_zero_na_nota_da_comissao(inscricao, edicao):
    """Nulo não interrompe o cálculo: a lista pode ser somada a qualquer
    momento, e quem avisa que ela não está madura é `fully_reviewed()`."""
    item = _salvar_item(
        edicao, code="1.8", points_per_unit=Decimal("3.00"), cap=Decimal("18.00")
    )
    _lancamento(inscricao, item, "1", committee_score=Decimal("3.00"))
    _lancamento(inscricao, item, "1")

    assert inscricao.committee_score() == Decimal("3.00")
    assert inscricao.fully_reviewed() is False


@pytest.mark.django_db
def test_candidate_score_le_o_que_o_candidato_pediu(inscricao, edicao):
    """A coluna "Candidato" da tela de análise, com o mesmo teto por item —
    o candidato pediu 24,00 e o item só comporta 18,00."""
    item = _salvar_item(
        edicao, code="1.8", points_per_unit=Decimal("12.00"), cap=Decimal("18.00")
    )
    for _ in range(2):
        _lancamento(
            inscricao,
            item,
            "1",
            committee_score=Decimal("0.00"),
            committee_note="Sem comprovação.",
        )

    assert inscricao.candidate_score() == Decimal("18.00")
    assert inscricao.committee_score() == Decimal("0.00")


@pytest.mark.django_db
def test_inscricao_sem_lancamento_tem_nota_zero_e_esta_analisada(inscricao):
    """Vacuamente analisada: não há o que avaliar."""
    assert inscricao.committee_score() == Decimal("0.00")
    assert inscricao.candidate_score() == Decimal("0.00")
    assert inscricao.fully_reviewed() is True


@pytest.mark.django_db
def test_fully_reviewed_vira_verdadeiro_quando_o_ultimo_e_pontuado(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3")
    pendente = _lancamento(inscricao, item, "2")

    assert inscricao.fully_reviewed() is False

    pendente.committee_score = pendente.candidate_score
    pendente.save()

    assert inscricao.fully_reviewed() is True


@pytest.mark.django_db
def test_subtotal_separa_as_secoes_do_barema(inscricao, edicao):
    """Os critérios III e IV do desempate (item 3.3) leem subtotal de
    seção, não a nota inteira."""
    formacao = _salvar_item(
        edicao,
        code="1.3",
        section=BaremeSection.FORMATION,
        points_per_unit=Decimal("2.00"),
        cap=Decimal("10.00"),
    )
    producao = _salvar_item(
        edicao,
        code="2.1",
        section=BaremeSection.BIBLIOGRAPHIC,
        points_per_unit=Decimal("5.00"),
        cap=Decimal("10.00"),
    )
    _lancamento(inscricao, formacao, "1", committee_score=Decimal("2.00"))
    _lancamento(inscricao, producao, "1", committee_score=Decimal("5.00"))

    assert inscricao.subtotal(BaremeSection.FORMATION) == Decimal("2.00")
    assert inscricao.subtotal(BaremeSection.BIBLIOGRAPHIC) == Decimal("5.00")
    assert inscricao.committee_score() == Decimal("7.00")


@pytest.mark.django_db
def test_for_program_e_o_primeiro_filtro_da_busca_de_lancamentos(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3")
    lancamento = _lancamento(inscricao, item, "1")

    assert list(BaremeEntry.objects.for_program(inscricao.program)) == [lancamento]
    assert list(BaremeEntry.objects.pending_review()) == [lancamento]


@pytest.mark.django_db
def test_apagar_a_inscricao_leva_os_lancamentos_junto(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3")
    _lancamento(inscricao, item, "1")

    inscricao.delete()

    assert not BaremeEntry.objects.exists()


@pytest.mark.django_db
def test_a_permissao_de_avaliar_existe_e_e_separada_de_change():
    """Avaliar não é `change`: o candidato altera o próprio lançamento e
    não pode encostar na nota da comissão."""
    codenames = set(
        Permission.objects.filter(
            content_type__app_label="scholarships",
            content_type__model="baremeentry",
        ).values_list("codename", flat=True)
    )

    assert "review_baremeentry" in codenames
    assert "change_baremeentry" in codenames


# ===========================================================================
# ItemReview — a observação por item do barema
# ===========================================================================


@pytest.mark.django_db
def test_uma_observacao_por_item_da_inscricao(inscricao, edicao):
    """A duplicata vira `duplicate_item_review` (400), não `IntegrityError`."""
    item = _salvar_item(edicao, code="1.3")
    ItemReview.objects.create(application=inscricao, item=item, note="Reclassificado.")

    with pytest.raises(DomainError) as exc:
        ItemReview(application=inscricao, item=item, note="Outra").clean()

    assert exc.value.code == "duplicate_item_review"


@pytest.mark.django_db
def test_observacao_por_item_e_independente_da_do_lancamento(inscricao, edicao):
    """São duas observações diferentes: a do lançamento explica uma linha,
    esta comenta o item inteiro."""
    item = _salvar_item(edicao, code="1.3")
    lancamento = _lancamento(
        inscricao,
        item,
        "2",
        committee_score=Decimal("0.50"),
        committee_note="O certificado cobre um semestre.",
    )
    observacao = ItemReview.objects.create(
        application=inscricao, item=item, note="Produção reclassificada em bloco."
    )

    assert lancamento.committee_note != observacao.note
    assert inscricao.item_reviews.count() == 1


@pytest.mark.django_db
def test_observacao_recusa_item_de_outro_nivel(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3", level=ScholarshipLevel.DOCTORATE)

    with pytest.raises(DomainError) as exc:
        ItemReview(application=inscricao, item=item, note="x").clean()

    assert exc.value.code == "bareme_item_mismatch"


@pytest.mark.django_db
def test_for_program_e_o_primeiro_filtro_da_busca_de_observacoes(inscricao, edicao):
    item = _salvar_item(edicao, code="1.3")
    observacao = ItemReview.objects.create(
        application=inscricao, item=item, note="Observação"
    )

    assert list(ItemReview.objects.for_program(inscricao.program)) == [observacao]
