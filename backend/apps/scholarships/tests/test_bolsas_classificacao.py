"""A classificação: a nota final e a faixa de prioridade.

Primeira metade do algoritmo (Seção 2 do plano, itens 1 a 3): a nota que o
resultado publica — a da comissão mais o bônus da FUMP — e a faixa que o
questionário deriva. A ordenação dentro da faixa, o desempate e o sorteio
são a segunda metade e ficam para `classify()`.

Nível (a) da pirâmide (Seção 9): a tabela de derivação da faixa é objeto em
memória, sem banco, porque ela é uma decisão sobre nove booleanos e nada
mais. Só o que soma lançamento precisa de banco, e esses estão no fim,
marcados um a um com `django_db`.

Dois casos dão nome ao arquivo:

- **A ordem dos incisos do 2.4 é a regra, não a combinação.** Um candidato
  que responde "Sim" a mais de um inciso não fica em duas faixas nem na
  "mais grave": fica na **primeira aplicável** da ordem do edital. Uma
  cadeia de `if` na ordem errada dá lista errada e teste verde.
- **A nota final não é a nota da comissão.** O bônus da FUMP entra na nota
  (item 3.2), não no desempate — o nível 1 vale 15,00 pontos, e num barema
  em que um artigo qualificado vale 3,00 isso reordena a faixa inteira.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.academic.models import Student
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program, ResearchLine
from apps.scholarships.models import (
    BONUS_FUMP,
    INCISOS_DA_ATIVIDADE_REMUNERADA,
    ORDEM_DAS_FAIXAS,
    BaremeEntry,
    BaremeItem,
    BaremeSection,
    BaremeUnit,
    PriorityBand,
    ScholarshipApplication,
    ScholarshipEdition,
    ScholarshipLevel,
)


def _inscricao(**kwargs) -> ScholarshipApplication:
    """Inscrição em memória, sem tocar o banco.

    Edição e discente vão **sem pk** de propósito: com eles, o espelho da
    `UniqueConstraint` dentro de `clean()` consultaria o banco. Aqui não
    se chama `clean()`, mas a instância continua descartável — o que se
    testa é derivação, não persistência.
    """
    campos = {
        "program": Program(pk=1),
        "edition": ScholarshipEdition(program_id=1),
        "student": Student(program_id=1),
        "level": ScholarshipLevel.MASTERS,
    }
    return ScholarshipApplication(**{**campos, **kwargs})


def _com_atividade(**kwargs) -> ScholarshipApplication:
    """Inscrição do bloco 2.4: exerce atividade remunerada.

    Renda e carga horária vão junto porque `clean()` as exige nesse caso
    — não são lidas pela derivação da faixa, mas uma inscrição do 2.4 sem
    elas não existiria no banco, e o teste não deve fabricar um estado
    impossível.
    """
    return _inscricao(
        has_paid_activity=True,
        monthly_income=Decimal("2500.00"),
        weekly_hours=20,
        **kwargs,
    )


# ===========================================================================
# 1 e 2. A nota final: a da comissão mais o bônus da FUMP
# ===========================================================================
#
# Sem lançamento gravado a nota da comissão é 0,00 (a inscrição em memória
# não tem gerente reverso), e é exatamente por isso que estes casos isolam
# o bônus: aqui a nota final **é** o bônus. A soma dos dois aparece com
# banco, no fim do arquivo.


def test_sem_nivel_da_fump_nao_ha_bonus():
    """Zero é "sem nível", e não um nível que pontua pouco."""
    assert _inscricao(fump_level=0).final_score() == Decimal("0.00")


def test_nivel_um_da_fump_vale_quinze_pontos():
    assert _inscricao(fump_level=1).final_score() == Decimal("15.00")


def test_nivel_dois_da_fump_vale_nove_pontos():
    """Nível 2 vale MENOS que o 1: a escala da FUMP é de necessidade, e
    o nível 1 é o de maior vulnerabilidade."""
    assert _inscricao(fump_level=2).final_score() == Decimal("9.00")


def test_o_bonus_da_fump_e_o_do_edital():
    """Item 3.2: 15,00 e 9,00. O dict não tem a chave 0 de propósito."""
    assert {1: Decimal("15.00"), 2: Decimal("9.00")} == BONUS_FUMP
    assert 0 not in BONUS_FUMP


def test_a_nota_final_e_sempre_decimal():
    """CLAUDE.md Seção 8: nota é `Decimal`, nunca `float`."""
    assert isinstance(_inscricao(fump_level=1).final_score(), Decimal)


# ===========================================================================
# 3. A faixa — bloco 2.1: quem NÃO exerce atividade remunerada
# ===========================================================================


def test_acao_afirmativa_sem_atividade_remunerada_e_dois_um_um():
    assert _inscricao(affirmative_action=True).derived_band() == PriorityBand.B21_I


def test_vulnerabilidade_sem_atividade_remunerada_e_dois_um_um():
    """ "Ou", não "e": um dos dois basta para o 2.1-I."""
    assert (
        _inscricao(socioeconomic_vulnerability=True).derived_band()
        == PriorityBand.B21_I
    )


def test_os_dois_criterios_juntos_continuam_dois_um_um():
    inscricao = _inscricao(affirmative_action=True, socioeconomic_vulnerability=True)

    assert inscricao.derived_band() == PriorityBand.B21_I


def test_sem_atividade_e_sem_nenhum_dos_dois_criterios_e_dois_um_dois():
    """O bloco 2.1 não tem residual: quem não exerce atividade remunerada
    cai sempre num dos dois incisos."""
    assert _inscricao().derived_band() == PriorityBand.B21_II


def test_o_bloco_dois_um_ignora_os_incisos_da_atividade_remunerada():
    """Os booleanos do 2.4 marcados sem `has_paid_activity` não movem
    ninguém: a chave do questionário é uma só."""
    inscricao = _inscricao(
        substitute_teacher=True, public_service=True, private_service=True
    )

    assert inscricao.derived_band() == PriorityBand.B21_II


# ===========================================================================
# 3. A faixa — bloco 2.4: o PRIMEIRO inciso aplicável
# ===========================================================================


@pytest.mark.parametrize(
    ("campo", "faixa"),
    [
        ("substitute_teacher", PriorityBand.B24_III),
        ("basic_education_or_collective_health", PriorityBand.B24_IV),
        ("public_service", PriorityBand.B24_V),
        ("private_service", PriorityBand.B24_VI_VII_VIII),
        ("other_non_public_scholarship", PriorityBand.B24_IX),
    ],
)
def test_cada_inciso_isolado_da_a_sua_faixa(campo: str, faixa: str):
    assert _com_atividade(**{campo: True}).derived_band() == faixa


def test_atividade_remunerada_sem_inciso_nenhum_e_residual():
    """Disse que tem atividade remunerada e não marcou inciso: é
    exatamente para este candidato que a residual existe."""
    assert _com_atividade().derived_band() == PriorityBand.RESIDUAL


# --- a precedência: dois "Sim" e a faixa é a do primeiro da ordem ----------


def test_substituto_vence_todos_os_demais_incisos():
    inscricao = _com_atividade(
        substitute_teacher=True,
        basic_education_or_collective_health=True,
        public_service=True,
        private_service=True,
        other_non_public_scholarship=True,
    )

    assert inscricao.derived_band() == PriorityBand.B24_III


def test_educacao_basica_vence_o_servico_publico():
    inscricao = _com_atividade(
        basic_education_or_collective_health=True, public_service=True
    )

    assert inscricao.derived_band() == PriorityBand.B24_IV


def test_servico_publico_vence_o_servico_privado():
    """O caso comum do 2.4: quem tem cargo público e faz hora extra na
    iniciativa privada é 2.4-V, e a faixa 2.4-V ordena por MENOR
    rendimento — cair no 2.4-VI/VII/VIII o ordenaria por outra régua."""
    inscricao = _com_atividade(public_service=True, private_service=True)

    assert inscricao.derived_band() == PriorityBand.B24_V


def test_servico_privado_vence_a_outra_bolsa_nao_publica():
    inscricao = _com_atividade(private_service=True, other_non_public_scholarship=True)

    assert inscricao.derived_band() == PriorityBand.B24_VI_VII_VIII


def test_a_ordem_dos_incisos_e_a_do_edital():
    """A lista é dado nomeado justamente para ser lida no merge contra o
    item 2.4 — uma cadeia de `elif` na ordem errada passaria despercebida."""
    assert INCISOS_DA_ATIVIDADE_REMUNERADA == (
        ("substitute_teacher", PriorityBand.B24_III),
        ("basic_education_or_collective_health", PriorityBand.B24_IV),
        ("public_service", PriorityBand.B24_V),
        ("private_service", PriorityBand.B24_VI_VII_VIII),
        ("other_non_public_scholarship", PriorityBand.B24_IX),
    )


def test_o_bloco_dois_um_nao_afeta_o_dois_quatro():
    """Ação afirmativa e vulnerabilidade não puxam de volta ao 2.1 quem
    exerce atividade remunerada."""
    inscricao = _com_atividade(
        affirmative_action=True,
        socioeconomic_vulnerability=True,
        public_service=True,
    )

    assert inscricao.derived_band() == PriorityBand.B24_V


# ===========================================================================
# 3. A faixa — 2.4-I e 2.4-II só existem por sobrescrita (B6)
# ===========================================================================


@pytest.mark.parametrize("faixa", [PriorityBand.B24_I, PriorityBand.B24_II])
def test_as_duas_faixas_sem_pergunta_so_chegam_por_sobrescrita(faixa: str):
    inscricao = _inscricao(band_override=faixa, band_override_reason="Caso omisso.")

    assert inscricao.band() == faixa
    assert inscricao.derived_band() == PriorityBand.B21_II


def test_nenhuma_combinacao_do_questionario_deriva_as_duas_faixas():
    """Varre todo o questionário — 2⁶ combinações do 2.4 e as 4 do 2.1 —
    e confirma que 2.4-I e 2.4-II nunca aparecem. É a prova de que a
    válvula da secretaria é o único caminho até elas."""
    campos = [campo for campo, _ in INCISOS_DA_ATIVIDADE_REMUNERADA]
    derivadas = set()
    for combinacao in range(2 ** len(campos)):
        marcados = {
            campo: bool(combinacao & (1 << posicao))
            for posicao, campo in enumerate(campos)
        }
        derivadas.add(_com_atividade(**marcados).derived_band())
        derivadas.add(_inscricao(**marcados).derived_band())
    for afirmativa in (False, True):
        for vulneravel in (False, True):
            derivadas.add(
                _inscricao(
                    affirmative_action=afirmativa,
                    socioeconomic_vulnerability=vulneravel,
                ).derived_band()
            )

    assert PriorityBand.B24_I not in derivadas
    assert PriorityBand.B24_II not in derivadas
    assert derivadas <= set(ORDEM_DAS_FAIXAS)


# --- band(): a sobrescrita vence a derivação ------------------------------


def test_a_sobrescrita_vence_a_faixa_derivada():
    inscricao = _com_atividade(
        public_service=True,
        band_override=PriorityBand.B21_I,
        band_override_reason="Decisão do colegiado de 12/03, ata 04/2026.",
    )

    assert inscricao.derived_band() == PriorityBand.B24_V
    assert inscricao.band() == PriorityBand.B21_I


def test_sem_sobrescrita_band_e_a_derivada():
    assert _com_atividade(public_service=True).band() == PriorityBand.B24_V


def test_band_nunca_e_nula():
    """Toda inscrição tem faixa: ou a sobrescrita, ou a do questionário.
    Antes da derivação existir este método devolvia `None`, e um `None`
    aqui deixaria candidato fora de todas as dez listas."""
    assert _inscricao().band() in set(ORDEM_DAS_FAIXAS)


# ===========================================================================
# Com banco: a nota final sobre lançamentos de verdade
# ===========================================================================


@pytest.fixture
def edicao(program: Program) -> ScholarshipEdition:
    return ScholarshipEdition.objects.create(
        program=program, year=2026, title="Edital de Bolsas 2026"
    )


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


def _salvar_item(edicao: ScholarshipEdition, **kwargs) -> BaremeItem:
    campos = {
        "edition": edicao,
        "level": ScholarshipLevel.MASTERS,
        "section": BaremeSection.BIBLIOGRAPHIC,
        "code": "2.1",
        "text": "Artigo publicado em periódico qualificado",
        "unit": BaremeUnit.UNIT,
        "points_per_unit": Decimal("3.00"),
        "cap": Decimal("18.00"),
    }
    item = BaremeItem(**{**campos, **kwargs})
    item.clean()
    item.save()
    return item


def _lancamento(
    inscricao: ScholarshipApplication, item: BaremeItem, quantidade: str, **kwargs
) -> BaremeEntry:
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


@pytest.mark.django_db
def test_a_nota_final_soma_a_da_comissao_com_o_bonus(inscricao, edicao):
    item = _salvar_item(edicao)
    for _ in range(2):
        _lancamento(inscricao, item, "1", committee_score=Decimal("3.00"))
    inscricao.fump_level = 1

    assert inscricao.committee_score() == Decimal("6.00")
    assert inscricao.final_score() == Decimal("21.00")


@pytest.mark.django_db
def test_o_teto_do_item_e_aplicado_antes_do_bonus(inscricao, edicao):
    """O teto corta a SOMA dos lançamentos do item, e o bônus entra
    depois — cortar 18,00 + 9,00 pelo teto de 18,00 devolveria 18,00 e
    comeria o bônus inteiro."""
    item = _salvar_item(edicao, points_per_unit=Decimal("12.00"), cap=Decimal("18.00"))
    for _ in range(2):
        _lancamento(inscricao, item, "1", committee_score=Decimal("12.00"))
    inscricao.fump_level = 2

    assert inscricao.committee_score() == Decimal("18.00")
    assert inscricao.final_score() == Decimal("27.00")


@pytest.mark.django_db
def test_lancamento_nao_avaliado_conta_zero_na_nota_final(inscricao, edicao):
    """A nota final existe a qualquer momento: quem avisa que a lista
    ainda não está madura é `fully_reviewed()`, não um total que se
    recusa a existir."""
    item = _salvar_item(edicao)
    _lancamento(inscricao, item, "1", committee_score=Decimal("3.00"))
    _lancamento(inscricao, item, "1")
    inscricao.fump_level = 1

    assert inscricao.final_score() == Decimal("18.00")
    assert inscricao.fully_reviewed() is False


@pytest.mark.django_db
def test_sem_lancamento_nenhum_a_nota_final_e_so_o_bonus(inscricao):
    inscricao.fump_level = 1

    assert inscricao.committee_score() == Decimal("0.00")
    assert inscricao.final_score() == Decimal("15.00")


@pytest.mark.django_db
def test_o_subtotal_do_desempate_le_as_notas_da_comissao(inscricao, edicao):
    """ASSUNÇÃO A CONFIRMAR NO MERGE (item 3.3): os critérios III e IV
    comparam o que a comissão concedeu, não o que o candidato pediu."""
    item = _salvar_item(edicao, section=BaremeSection.BIBLIOGRAPHIC)
    _lancamento(
        inscricao,
        item,
        "4",
        committee_score=Decimal("3.00"),
        committee_note="Três dos quatro artigos são anteriores ao ingresso.",
    )

    assert inscricao.candidate_score() == Decimal("12.00")
    assert inscricao.subtotal(BaremeSection.BIBLIOGRAPHIC) == Decimal("3.00")
    assert inscricao.subtotal(BaremeSection.FORMATION) == Decimal("0.00")
