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
from apps.audit.models import AuditLog
from apps.core.exceptions import InvalidStateTransition
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
    ScholarshipEditionStatus,
    ScholarshipLevel,
)
from apps.scholarships.services import publish_final, publish_preliminary


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


# ===========================================================================
# `classify(level)`: a ordenação dentro da faixa, o desempate e o sorteio
# ===========================================================================
#
# Segunda metade do algoritmo (Seção 2 do plano, itens 4 a 7). Tudo daqui
# para baixo precisa de banco: a ordenação compara notas, e nota é soma de
# lançamento.
#
# O questionário que leva a cada faixa, escrito uma vez. 2.4-I e 2.4-II não
# estão aqui porque não têm pergunta — chegam por sobrescrita (B6), e é
# assim que o teste dos volumes de 2026 os produz.
QUESTIONARIO_DA_FAIXA: dict[str, dict] = {
    PriorityBand.B21_I: {"affirmative_action": True},
    PriorityBand.B21_II: {},
    PriorityBand.B24_III: {"has_paid_activity": True, "substitute_teacher": True},
    PriorityBand.B24_IV: {
        "has_paid_activity": True,
        "basic_education_or_collective_health": True,
    },
    PriorityBand.B24_V: {"has_paid_activity": True, "public_service": True},
    PriorityBand.B24_VI_VII_VIII: {
        "has_paid_activity": True,
        "private_service": True,
    },
    PriorityBand.B24_IX: {
        "has_paid_activity": True,
        "other_non_public_scholarship": True,
    },
    PriorityBand.RESIDUAL: {"has_paid_activity": True},
}


def _candidato(
    edicao: ScholarshipEdition,
    nome: str,
    faixa: str = PriorityBand.B21_II,
    *,
    nivel: str = Student.Level.MASTERS,
    **campos,
) -> ScholarshipApplication:
    """Um candidato inteiro (pessoa, discente e inscrição) numa faixa.

    A faixa vem do **questionário**, e não de um campo: é o caminho real,
    e um teste que gravasse `band_override` para montar o cenário nunca
    exercitaria a derivação. As duas faixas sem pergunta (2.4-I e 2.4-II)
    são a exceção e entram por `band_override` explícito no chamador.

    Renda e carga horária acompanham toda faixa do bloco 2.4 porque
    `clean()` as exige de quem declara atividade remunerada.
    """
    perguntas = dict(QUESTIONARIO_DA_FAIXA[faixa])
    if perguntas.get("has_paid_activity"):
        perguntas.setdefault("monthly_income", Decimal("2500.00"))
        perguntas.setdefault("weekly_hours", 20)
    pessoa = Person.objects.create(
        program=edicao.program,
        full_name=nome,
        primary_email=f"{nome.lower().replace(' ', '.')}@example.com",
    )
    # Aluno regular exige nível, projeto, ingresso e prazo
    # (`student_regular_requires_degree_fields`); a linha e o projeto são os
    # mesmos para todos os candidatos — o que se testa aqui é faixa e nota.
    linha, _ = ResearchLine.objects.get_or_create(
        program=edicao.program, name="Direito e Estado"
    )
    projeto, _ = CollectiveProject.objects.get_or_create(
        program=edicao.program, research_line=linha, name="Projeto coletivo"
    )
    aluno = Student.objects.create(
        program=edicao.program,
        person=pessoa,
        modality=Student.Modality.REGULAR,
        level=nivel,
        project=projeto,
        admission_date=date(2025, 3, 1),
        deadline=date(2027, 3, 1),
    )
    inscricao = ScholarshipApplication.for_student(
        edition=edicao, student=aluno, **{**perguntas, **campos}
    )
    inscricao.clean()
    inscricao.save()
    return inscricao


def _com_nota(
    inscricao: ScholarshipApplication,
    edicao: ScholarshipEdition,
    nota: str,
    *,
    section: str = BaremeSection.BIBLIOGRAPHIC,
    code: str = "2.1",
) -> None:
    """Dá ao candidato exatamente `nota` pontos numa seção do barema.

    O item vale 1,00 por unidade e a quantidade é a própria nota: assim a
    nota do candidato e a da comissão coincidem (e o `clean()` não cobra
    observação de divergência), e o teto não interfere.
    """
    item, _ = BaremeItem.objects.get_or_create(
        edition=edicao,
        level=inscricao.level,
        code=code,
        defaults={
            "section": section,
            "text": f"Item {code} do barema",
            "unit": BaremeUnit.UNIT,
            "points_per_unit": Decimal("1.00"),
            "cap": Decimal("9999.00"),
        },
    )
    _lancamento(inscricao, item, nota, committee_score=Decimal(nota))


def _nomes(faixas: list, faixa: str) -> list[str]:
    """Os nomes de uma faixa da saída, na ordem publicada."""
    (secao,) = [s for s in faixas if s.band == faixa]
    return [linha.name for linha in secao.rows]


def _secao(faixas: list, faixa: str):
    (secao,) = [s for s in faixas if s.band == faixa]
    return secao


# --- a forma da saída: dez faixas, sempre -----------------------------------


@pytest.mark.django_db
def test_a_saida_tem_as_dez_faixas_na_ordem_canonica_mesmo_vazias(edicao):
    """Q8: faixa sem candidato é publicada só com o cabeçalho — foi o caso
    de 2.4-IV e 2.4-IX nas duas listas de 2026."""
    _candidato(edicao, "Ana Souza", PriorityBand.B21_I)

    faixas = edicao.classify(ScholarshipLevel.MASTERS)

    assert [secao.band for secao in faixas] == ORDEM_DAS_FAIXAS
    assert len(faixas) == 10
    assert [len(secao.rows) for secao in faixas] == [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]


@pytest.mark.django_db
def test_a_edicao_sem_inscricao_publica_as_dez_faixas_vazias(edicao):
    faixas = edicao.classify(ScholarshipLevel.MASTERS)

    assert len(faixas) == 10
    assert all(secao.rows == [] for secao in faixas)


@pytest.mark.django_db
def test_o_cabecalho_publica_a_ordem_de_prioridade_e_a_regra(edicao):
    faixas = edicao.classify(ScholarshipLevel.MASTERS)

    assert _secao(faixas, PriorityBand.B21_I).priority_label == (
        "Ordem de prioridade: primeira"
    )
    assert _secao(faixas, PriorityBand.RESIDUAL).priority_label == (
        "Ordem de prioridade: décima"
    )
    assert _secao(faixas, PriorityBand.B21_I).ordering_rule == (
        "Nota do barema, em ordem decrescente."
    )
    assert (
        "menor carga horária"
        in _secao(faixas, PriorityBand.B24_VI_VII_VIII).ordering_rule
    )


@pytest.mark.django_db
def test_so_as_duas_faixas_do_rendimento_mostram_remuneracao(edicao):
    """A coluna "Remuneração" existe em 2.4-V e 2.4-VI/VII/VIII, e é
    exatamente onde a nota deixa de ordenar."""
    faixas = edicao.classify(ScholarshipLevel.MASTERS)

    com_remuneracao = {secao.band for secao in faixas if secao.shows_income}
    assert com_remuneracao == {
        PriorityBand.B24_V,
        PriorityBand.B24_VI_VII_VIII,
    }


@pytest.mark.django_db
def test_cada_nivel_corre_independente(edicao):
    """Mestrado e doutorado saem em documentos separados: uma chamada por
    nível, e a do mestrado não enxerga o doutorando."""
    _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    _candidato(edicao, "Bruno Dias", PriorityBand.B21_I, nivel=Student.Level.DOCTORATE)

    assert _nomes(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Ana Souza"
    ]
    assert _nomes(edicao.classify(ScholarshipLevel.DOCTORATE), PriorityBand.B21_I) == [
        "Bruno Dias"
    ]


@pytest.mark.django_db
def test_a_sobrescrita_da_secretaria_move_o_candidato_de_faixa(edicao):
    """2.4-I e 2.4-II só existem por aqui (B6) — e é assim que as listas
    de 2026 tinham gente na terceira faixa."""
    _candidato(
        edicao,
        "Ana Souza",
        PriorityBand.B21_II,
        band_override=PriorityBand.B24_I,
        band_override_reason="Caso omisso decidido pelo colegiado, ata 04/2026.",
    )

    faixas = edicao.classify(ScholarshipLevel.MASTERS)

    assert _nomes(faixas, PriorityBand.B24_I) == ["Ana Souza"]
    assert _nomes(faixas, PriorityBand.B21_II) == []


# --- 4. a ordenação dentro da faixa ----------------------------------------


@pytest.mark.django_db
def test_a_faixa_comum_ordena_pela_nota_decrescente(edicao):
    for nome, nota in [("Ana Souza", "10.00"), ("Bruno Dias", "30.00")]:
        _com_nota(_candidato(edicao, nome, PriorityBand.B21_I), edicao, nota)

    faixas = edicao.classify(ScholarshipLevel.MASTERS)

    assert _nomes(faixas, PriorityBand.B21_I) == ["Bruno Dias", "Ana Souza"]
    assert [linha.position for linha in _secao(faixas, PriorityBand.B21_I).rows] == [
        1,
        2,
    ]


@pytest.mark.django_db
def test_a_nota_que_ordena_e_a_final_com_o_bonus_da_fump(edicao):
    """15,00 pontos de bônus reordenam a faixa inteira: quem tirou 20,00 e
    tem nível 1 passa na frente de quem tirou 30,00 sem nível."""
    _com_nota(
        _candidato(edicao, "Ana Souza", PriorityBand.B21_I, fump_level=1),
        edicao,
        "20.00",
    )
    _com_nota(_candidato(edicao, "Bruno Dias", PriorityBand.B21_I), edicao, "30.00")

    faixas = edicao.classify(ScholarshipLevel.MASTERS)

    assert _nomes(faixas, PriorityBand.B21_I) == ["Ana Souza", "Bruno Dias"]
    assert _secao(faixas, PriorityBand.B21_I).rows[0].score == Decimal("35.00")


@pytest.mark.django_db
def test_a_faixa_do_servico_publico_ordena_pelo_menor_rendimento(edicao):
    """2.4-V: menor rendimento primeiro, com a nota só desempatando."""
    _com_nota(
        _candidato(
            edicao,
            "Ana Souza",
            PriorityBand.B24_V,
            monthly_income=Decimal("4000.00"),
        ),
        edicao,
        "90.00",
    )
    _com_nota(
        _candidato(
            edicao,
            "Bruno Dias",
            PriorityBand.B24_V,
            monthly_income=Decimal("1500.00"),
        ),
        edicao,
        "10.00",
    )

    assert _nomes(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B24_V) == [
        "Bruno Dias",
        "Ana Souza",
    ]


@pytest.mark.django_db
def test_no_servico_publico_a_nota_desempata_o_mesmo_rendimento(edicao):
    for nome, nota in [("Ana Souza", "10.00"), ("Bruno Dias", "30.00")]:
        _com_nota(
            _candidato(
                edicao,
                nome,
                PriorityBand.B24_V,
                monthly_income=Decimal("2000.00"),
            ),
            edicao,
            nota,
        )

    assert _nomes(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B24_V) == [
        "Bruno Dias",
        "Ana Souza",
    ]


@pytest.mark.django_db
def test_na_faixa_vi_vii_viii_a_nota_nao_ordena(edicao):
    """O caso que os PDFs de 2026 provam: no mestrado, Amanda Pereira Reis
    (59,20) é **1ª** e Ana Rita Fontes Nascimento (73,29) é **5ª**, porque
    ali quem ordena é o rendimento — a nota é o terceiro critério."""
    dados = [
        ("Amanda Pereira Reis", "1200.00", 20, "59.20"),
        ("Beatriz Nunes Prado", "1800.00", 20, "62.00"),
        ("Carla Moreira Lopes", "2400.00", 20, "70.10"),
        ("Daniela Vieira Castro", "3000.00", 20, "71.00"),
        ("Ana Rita Fontes Nascimento", "3600.00", 20, "73.29"),
    ]
    for nome, renda, horas, nota in dados:
        _com_nota(
            _candidato(
                edicao,
                nome,
                PriorityBand.B24_VI_VII_VIII,
                monthly_income=Decimal(renda),
                weekly_hours=horas,
            ),
            edicao,
            nota,
        )

    secao = _secao(
        edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B24_VI_VII_VIII
    )

    assert secao.rows[0].name == "Amanda Pereira Reis"
    assert secao.rows[0].score == Decimal("59.20")
    assert secao.rows[4].name == "Ana Rita Fontes Nascimento"
    assert secao.rows[4].score == Decimal("73.29")


@pytest.mark.django_db
def test_na_faixa_vi_vii_viii_a_carga_horaria_vem_antes_da_nota(edicao):
    """Mesmo rendimento: quem trabalha menos horas passa na frente, ainda
    que tenha tirado menos."""
    _com_nota(
        _candidato(
            edicao,
            "Ana Souza",
            PriorityBand.B24_VI_VII_VIII,
            monthly_income=Decimal("2000.00"),
            weekly_hours=40,
        ),
        edicao,
        "90.00",
    )
    _com_nota(
        _candidato(
            edicao,
            "Bruno Dias",
            PriorityBand.B24_VI_VII_VIII,
            monthly_income=Decimal("2000.00"),
            weekly_hours=10,
        ),
        edicao,
        "10.00",
    )

    assert _nomes(
        edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B24_VI_VII_VIII
    ) == ["Bruno Dias", "Ana Souza"]


@pytest.mark.django_db
def test_na_faixa_vi_vii_viii_a_nota_desempata_renda_e_carga_iguais(edicao):
    for nome, nota in [("Ana Souza", "10.00"), ("Bruno Dias", "30.00")]:
        _com_nota(
            _candidato(
                edicao,
                nome,
                PriorityBand.B24_VI_VII_VIII,
                monthly_income=Decimal("2000.00"),
                weekly_hours=20,
            ),
            edicao,
            nota,
        )

    assert _nomes(
        edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B24_VI_VII_VIII
    ) == ["Bruno Dias", "Ana Souza"]


# --- 5. o desempate geral do item 3.3, um critério por vez ------------------


@pytest.mark.django_db
def test_desempate_i_menor_nivel_da_fump_com_o_zero_em_ultimo(edicao):
    """**A inversão**: o critério é "menor nível", mas 0 é "sem nível" —
    quem a FUMP não classificou — e por isso é o PIOR. A ordem é 1, 2, 0.

    As três notas finais são iguais de propósito (30,00 = 15,00 de barema
    + 15,00 do nível 1; 21,00 + 9,00 do nível 2; 30,00 sem bônus), senão o
    bônus resolveria antes e o critério I nunca seria exercitado.
    """
    _com_nota(
        _candidato(edicao, "Ana Souza", PriorityBand.B21_I, fump_level=1),
        edicao,
        "15.00",
    )
    _com_nota(
        _candidato(edicao, "Bruno Dias", PriorityBand.B21_I, fump_level=2),
        edicao,
        "21.00",
    )
    _com_nota(
        _candidato(edicao, "Carla Reis", PriorityBand.B21_I, fump_level=0),
        edicao,
        "30.00",
    )

    secao = _secao(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I)

    assert {linha.score for linha in secao.rows} == {Decimal("30.00")}
    assert [linha.name for linha in secao.rows] == [
        "Ana Souza",
        "Bruno Dias",
        "Carla Reis",
    ]
    assert all(linha.draw_order is None for linha in secao.rows)


@pytest.mark.django_db
def test_desempate_ii_o_cadastro_unico(edicao):
    _com_nota(
        _candidato(edicao, "Ana Souza", PriorityBand.B21_I, cadastro_unico=False),
        edicao,
        "30.00",
    )
    _com_nota(
        _candidato(edicao, "Bruno Dias", PriorityBand.B21_I, cadastro_unico=True),
        edicao,
        "30.00",
    )

    assert _nomes(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Bruno Dias",
        "Ana Souza",
    ]


@pytest.mark.django_db
def test_desempate_iii_maior_subtotal_em_formacao_academica(edicao):
    """Mesma nota total, composição diferente: quem pontuou em Formação
    Acadêmica passa na frente de quem pontuou o mesmo em Publicações."""
    ana = _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    _com_nota(ana, edicao, "20.00", section=BaremeSection.BIBLIOGRAPHIC, code="II.1")
    bruno = _candidato(edicao, "Bruno Dias", PriorityBand.B21_I)
    _com_nota(bruno, edicao, "20.00", section=BaremeSection.FORMATION, code="I.1")

    assert _nomes(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Bruno Dias",
        "Ana Souza",
    ]


@pytest.mark.django_db
def test_desempate_iv_maior_subtotal_em_producao_bibliografica(edicao):
    """Empatados até em Formação Acadêmica (10,00 cada): decide o subtotal
    de Publicações, e não a terceira seção."""
    for nome, secao_restante in [
        ("Ana Souza", BaremeSection.EVENTS),
        ("Bruno Dias", BaremeSection.BIBLIOGRAPHIC),
    ]:
        inscricao = _candidato(edicao, nome, PriorityBand.B21_I)
        _com_nota(
            inscricao, edicao, "10.00", section=BaremeSection.FORMATION, code="I.1"
        )
        codigo = "III.1" if secao_restante == BaremeSection.EVENTS else "II.1"
        _com_nota(inscricao, edicao, "10.00", section=secao_restante, code=codigo)

    assert _nomes(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Bruno Dias",
        "Ana Souza",
    ]


@pytest.mark.django_db
def test_desempate_v_o_sorteio_ordena_quem_sobrou(edicao):
    """Idênticos em tudo o que o edital sabe comparar: só o sorteio
    resolve, e é ele que grava `draw_order`."""
    for nome in ["Ana Souza", "Bruno Dias", "Carla Reis"]:
        _com_nota(_candidato(edicao, nome, PriorityBand.B21_I), edicao, "30.00")

    secao = _secao(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I)

    assert sorted(linha.draw_order for linha in secao.rows) == [1, 2, 3]
    assert [linha.draw_order for linha in secao.rows] == [1, 2, 3]
    assert sorted(linha.name for linha in secao.rows) == [
        "Ana Souza",
        "Bruno Dias",
        "Carla Reis",
    ]


@pytest.mark.django_db
def test_quem_nao_empatou_nao_recebe_ordem_de_sorteio(edicao):
    """`draw_order` nula é "não precisou de sorteio" — e é o caso normal."""
    for nome, nota in [("Ana Souza", "10.00"), ("Bruno Dias", "30.00")]:
        _com_nota(_candidato(edicao, nome, PriorityBand.B21_I), edicao, nota)

    secao = _secao(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I)

    assert [linha.draw_order for linha in secao.rows] == [None, None]


# --- 6. o sorteio é reprodutível -------------------------------------------


@pytest.mark.django_db
def test_a_mesma_semente_da_a_mesma_lista(edicao):
    """Republicar tem de dar a mesma lista: a semente é gerada uma vez, na
    primeira publicação, e nunca regerada."""
    for nome in ["Ana Souza", "Bruno Dias", "Carla Reis", "Diego Alves"]:
        _com_nota(_candidato(edicao, nome, PriorityBand.B21_I), edicao, "30.00")
    edicao.draw_seed = 20260317
    edicao.save(update_fields=["draw_seed"])

    primeira = _secao(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I)
    segunda = _secao(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I)

    assert [(linha.name, linha.draw_order) for linha in primeira.rows] == [
        (linha.name, linha.draw_order) for linha in segunda.rows
    ]


@pytest.mark.django_db
def test_sementes_diferentes_dao_listas_diferentes(edicao):
    """Sem isto o teste acima passaria com um sorteio que não sorteia."""
    for nome in "ABCDEFGH":
        _com_nota(
            _candidato(edicao, f"Candidato {nome}", PriorityBand.B21_I),
            edicao,
            "30.00",
        )

    ordens = set()
    for semente in [1, 2, 3, 4]:
        edicao.draw_seed = semente
        ordens.add(
            tuple(
                linha.name
                for linha in _secao(
                    edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I
                ).rows
            )
        )

    assert len(ordens) > 1


# --- 7. os volumes de 2026 --------------------------------------------------

# As oito faixas publicadas em 2026 e quantos candidatos cada uma tinha
# (fonte: os dois PDFs de resultado, registrados na spec). 2.4-II e 2.4-III
# não apareciam nos documentos daquele ano — a decisão Q8 manda publicá-las
# mesmo assim, vazias, e é por isso que elas entram aqui com zero.
VOLUMES_DE_2026: dict[str, dict[str, int]] = {
    ScholarshipLevel.MASTERS: {
        PriorityBand.B21_I: 6,
        PriorityBand.B21_II: 18,
        PriorityBand.B24_I: 4,
        PriorityBand.B24_II: 0,
        PriorityBand.B24_III: 0,
        PriorityBand.B24_IV: 0,
        PriorityBand.B24_V: 2,
        PriorityBand.B24_VI_VII_VIII: 6,
        PriorityBand.B24_IX: 0,
        PriorityBand.RESIDUAL: 8,
    },
    ScholarshipLevel.DOCTORATE: {
        PriorityBand.B21_I: 5,
        PriorityBand.B21_II: 17,
        PriorityBand.B24_I: 2,
        PriorityBand.B24_II: 0,
        PriorityBand.B24_III: 0,
        PriorityBand.B24_IV: 0,
        PriorityBand.B24_V: 4,
        PriorityBand.B24_VI_VII_VIII: 3,
        PriorityBand.B24_IX: 0,
        PriorityBand.RESIDUAL: 2,
    },
}

NIVEL_DO_DISCENTE: dict[str, str] = {
    ScholarshipLevel.MASTERS: Student.Level.MASTERS,
    ScholarshipLevel.DOCTORATE: Student.Level.DOCTORATE,
}


def _semear_volumes_de_2026(edicao: ScholarshipEdition) -> None:
    """As 44 inscrições do mestrado e as 33 do doutorado de 2026.

    A faixa 2.4-I sai por sobrescrita (é a única com gente em 2026 sem
    pergunta que a derive) e todas as outras, pelo questionário.
    """
    for nivel, volumes in VOLUMES_DE_2026.items():
        for faixa, quantidade in volumes.items():
            for indice in range(quantidade):
                nome = f"{nivel[:3]} {faixa} {indice:02d}"
                if faixa in (PriorityBand.B24_I, PriorityBand.B24_II):
                    _candidato(
                        edicao,
                        nome,
                        PriorityBand.B21_II,
                        nivel=NIVEL_DO_DISCENTE[nivel],
                        band_override=faixa,
                        band_override_reason="Caso omisso, ata 04/2026.",
                    )
                    continue
                extras: dict = {}
                if faixa in (PriorityBand.B24_V, PriorityBand.B24_VI_VII_VIII):
                    extras["monthly_income"] = Decimal(1000 + indice * 100)
                    extras["weekly_hours"] = 10 + indice
                _candidato(
                    edicao, nome, faixa, nivel=NIVEL_DO_DISCENTE[nivel], **extras
                )


@pytest.mark.django_db
def test_os_volumes_de_2026_saem_faixa_a_faixa(edicao):
    """Mestrado 6+18+4+0+2+6+0+8 = 44; doutorado 5+17+2+0+4+3+0+2 = 33.

    É o teste de calibração do módulo: reproduz os dois documentos
    publicados em 2026 a partir do questionário, e não de um campo de
    faixa gravado à mão.
    """
    _semear_volumes_de_2026(edicao)

    for nivel, volumes in VOLUMES_DE_2026.items():
        faixas = edicao.classify(nivel)
        assert {secao.band: len(secao.rows) for secao in faixas} == volumes

    assert sum(VOLUMES_DE_2026[ScholarshipLevel.MASTERS].values()) == 44
    assert sum(VOLUMES_DE_2026[ScholarshipLevel.DOCTORATE].values()) == 33


@pytest.mark.django_db
def test_a_classificacao_numera_de_um_ate_o_fim_de_cada_faixa(edicao):
    """A "Classificação" da coluna publicada é a posição **dentro da
    faixa**, e recomeça em cada seção."""
    _semear_volumes_de_2026(edicao)

    for secao in edicao.classify(ScholarshipLevel.MASTERS):
        assert [linha.position for linha in secao.rows] == list(
            range(1, len(secao.rows) + 1)
        )


@pytest.mark.django_db
def test_classify_nao_grava_nada(edicao):
    """`draw_order` sai na linha, não no banco: quem persiste o snapshot é
    o service da publicação."""
    inscricoes = [
        _candidato(edicao, nome, PriorityBand.B21_I)
        for nome in ["Ana Souza", "Bruno Dias"]
    ]

    edicao.classify(ScholarshipLevel.MASTERS)

    for inscricao in inscricoes:
        inscricao.refresh_from_db()
        assert inscricao.draw_order is None
        assert inscricao.published_band is None
        assert inscricao.published_position is None


# ===========================================================================
# A publicação: o snapshot, a semente e o `AuditLog` único
# ===========================================================================
#
# Terceira parte (Seção 3 do plano). O service escreve em dois agregados —
# a edição e toda inscrição dela —, e o que estes casos guardam é o que
# separa "publicar" de "classificar": a lista publicada **para de mudar**.
#
# Nível (b) por natureza (é persistência), mas sem HTTP: a borda das duas
# rotas e a leitura do resultado estão em `test_bolsas_api_resultado.py`.


@pytest.fixture
def edicao_em_analise(program: Program) -> ScholarshipEdition:
    """Uma edição no estado de onde se publica o preliminar."""
    return ScholarshipEdition.objects.create(
        program=program,
        year=2027,
        title="Edital de Bolsas 2027",
        status=ScholarshipEditionStatus.UNDER_REVIEW,
    )


@pytest.mark.django_db
def test_publicar_o_preliminar_grava_o_snapshot_em_toda_inscricao(edicao_em_analise):
    """B10: depois de publicado, é o snapshot que a tela e o PDF leem."""
    edicao = edicao_em_analise
    ana = _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    _com_nota(ana, edicao, "10")
    bruno = _candidato(edicao, "Bruno Dias", PriorityBand.B21_I)
    _com_nota(bruno, edicao, "4")

    publish_preliminary(edition=edicao)

    ana.refresh_from_db()
    bruno.refresh_from_db()
    assert ana.published_band == PriorityBand.B21_I
    assert ana.published_score == Decimal("10.00")
    assert ana.published_position == 1
    assert bruno.published_position == 2
    assert ana.published_at is not None
    assert ana.published_at == bruno.published_at == edicao.published_preliminary_at


@pytest.mark.django_db
def test_a_publicacao_alcanca_os_dois_niveis(edicao_em_analise):
    """Uma publicação, duas listas: mestrado e doutorado saem juntos, e
    quem escolhe o nível é o documento, não o ato."""
    edicao = edicao_em_analise
    mestranda = _candidato(edicao, "Ana Souza", nivel=Student.Level.MASTERS)
    doutorando = _candidato(edicao, "Bruno Dias", nivel=Student.Level.DOCTORATE)

    publish_preliminary(edition=edicao)

    mestranda.refresh_from_db()
    doutorando.refresh_from_db()
    assert mestranda.published_position == 1
    assert doutorando.published_position == 1


@pytest.mark.django_db
def test_a_semente_nasce_na_publicacao_e_nunca_e_regerada(edicao_em_analise):
    """Republicar tem de dar a mesma lista: a semente do preliminar é a
    do final, e o sorteio não se refaz porque alguém recorreu."""
    edicao = edicao_em_analise
    assert edicao.draw_seed is None

    publish_preliminary(edition=edicao)
    semente = edicao.draw_seed
    edicao.open_appeals()
    edicao.save(update_fields=["status", "updated_at"])
    publish_final(edition=edicao)

    assert semente is not None
    assert edicao.draw_seed == semente
    edicao.refresh_from_db()
    assert edicao.draw_seed == semente


@pytest.mark.django_db
def test_republicar_mantem_a_mesma_ordem_de_sorteio(edicao_em_analise):
    """Três empatadas em tudo: a ordem entre elas é a do sorteio, e ela
    não pode mudar entre o preliminar e o final."""
    edicao = edicao_em_analise
    empatadas = [
        _candidato(edicao, nome, PriorityBand.B21_I)
        for nome in ["Ana Souza", "Bruno Dias", "Carla Melo"]
    ]
    for inscricao in empatadas:
        _com_nota(inscricao, edicao, "5")

    publish_preliminary(edition=edicao)
    preliminar = {
        inscricao.pk: (inscricao.published_position, inscricao.draw_order)
        for inscricao in ScholarshipApplication.objects.filter(edition=edicao)
    }
    edicao.open_appeals()
    edicao.save(update_fields=["status", "updated_at"])
    publish_final(edition=edicao)

    final = {
        inscricao.pk: (inscricao.published_position, inscricao.draw_order)
        for inscricao in ScholarshipApplication.objects.filter(edition=edicao)
    }
    assert final == preliminar
    assert sorted(ordem for _, ordem in final.values()) == [1, 2, 3]


@pytest.mark.django_db
def test_o_snapshot_nao_grava_sorteio_em_quem_nao_empatou(edicao_em_analise):
    edicao = edicao_em_analise
    ana = _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    _com_nota(ana, edicao, "10")

    publish_preliminary(edition=edicao)

    ana.refresh_from_db()
    assert ana.draw_order is None


@pytest.mark.django_db
def test_ha_um_auditlog_por_publicacao_com_as_contagens(edicao_em_analise):
    """O ato é "publiquei o preliminar de 2027", e não N eventos soltos —
    mesmo desenho de `close_isolated_cycle`."""
    edicao = edicao_em_analise
    _candidato(edicao, "Ana Souza", nivel=Student.Level.MASTERS)
    _candidato(edicao, "Bruno Dias", nivel=Student.Level.MASTERS)
    _candidato(edicao, "Carla Melo", nivel=Student.Level.DOCTORATE)

    publish_preliminary(edition=edicao)

    registro = AuditLog.objects.get(event="scholarships.edition.publish_preliminary")
    assert registro.program_id == edicao.program_id
    assert registro.target_id == str(edicao.pk)
    assert registro.payload["published"] == 3
    assert registro.payload["by_level"] == {"masters": 2, "doctorate": 1}
    assert registro.payload["draw_seed"] == edicao.draw_seed
    assert registro.payload["status"] == ScholarshipEditionStatus.PRELIMINARY_RESULT


@pytest.mark.django_db
def test_publicar_fora_do_estado_recusa_e_nao_escreve_nada(edicao):
    """A transição recusa antes de gerar semente ou classificar: a edição
    em rascunho sai da chamada exatamente como entrou."""
    ana = _candidato(edicao, "Ana Souza")

    with pytest.raises(InvalidStateTransition) as erro:
        publish_preliminary(edition=edicao)

    assert erro.value.code == "edition_not_under_review"
    edicao.refresh_from_db()
    ana.refresh_from_db()
    assert edicao.draw_seed is None
    assert ana.published_at is None
    assert not AuditLog.objects.filter(
        event="scholarships.edition.publish_preliminary"
    ).exists()


# --- `result()`: o snapshot depois de publicado, a prévia antes ------------


@pytest.mark.django_db
def test_antes_de_publicar_o_resultado_e_a_previa(edicao):
    """A secretaria confere a lista antes de congelá-la."""
    _candidato(edicao, "Ana Souza", PriorityBand.B21_I)

    resultado = edicao.result(ScholarshipLevel.MASTERS)

    assert [secao.band for secao in resultado] == ORDEM_DAS_FAIXAS
    assert _nomes(resultado, PriorityBand.B21_I) == ["Ana Souza"]


@pytest.mark.django_db
def test_o_resultado_publicado_nao_muda_quando_a_comissao_refaz_lancamento(
    edicao_em_analise,
):
    """É para isto que o snapshot existe: durante a fase de recursos a
    comissão corrige nota, e o preliminar publicado continua o que foi
    lido."""
    edicao = edicao_em_analise
    ana = _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    _com_nota(ana, edicao, "4")
    bruno = _candidato(edicao, "Bruno Dias", PriorityBand.B21_I)
    _com_nota(bruno, edicao, "10")
    publish_preliminary(edition=edicao)
    assert _nomes(edicao.result(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Bruno Dias",
        "Ana Souza",
    ]

    # O recurso da Ana é deferido: a comissão refaz o lançamento dela.
    lancamento = ana.bareme_entries.get()
    lancamento.committee_score = Decimal("30.00")
    lancamento.save(update_fields=["committee_score", "updated_at"])

    publicado = edicao.result(ScholarshipLevel.MASTERS)
    assert _nomes(publicado, PriorityBand.B21_I) == ["Bruno Dias", "Ana Souza"]
    assert _secao(publicado, PriorityBand.B21_I).rows[1].score == Decimal("4.00")
    # A prévia, essa sim, já mostra a nota nova.
    assert _nomes(edicao.classify(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Ana Souza",
        "Bruno Dias",
    ]


@pytest.mark.django_db
def test_a_publicacao_final_incorpora_o_que_o_recurso_mudou(edicao_em_analise):
    """O final é a lista recalculada: publicar de novo é o que faz o
    deferimento chegar ao documento."""
    edicao = edicao_em_analise
    ana = _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    _com_nota(ana, edicao, "4")
    bruno = _candidato(edicao, "Bruno Dias", PriorityBand.B21_I)
    _com_nota(bruno, edicao, "10")
    publish_preliminary(edition=edicao)
    lancamento = ana.bareme_entries.get()
    lancamento.committee_score = Decimal("30.00")
    lancamento.save(update_fields=["committee_score", "updated_at"])

    edicao.open_appeals()
    edicao.save(update_fields=["status", "updated_at"])
    publish_final(edition=edicao)

    assert _nomes(edicao.result(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Ana Souza",
        "Bruno Dias",
    ]
    ana.refresh_from_db()
    assert ana.published_position == 1
    assert ana.published_score == Decimal("30.00")
    assert ana.published_at == edicao.published_final_at


@pytest.mark.django_db
def test_o_resultado_publicado_tem_as_dez_faixas_e_os_cabecalhos(edicao_em_analise):
    """Q8 vale igual no snapshot: faixa vazia é publicada com cabeçalho."""
    edicao = edicao_em_analise
    _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    publish_preliminary(edition=edicao)

    resultado = edicao.result(ScholarshipLevel.MASTERS)

    assert [secao.band for secao in resultado] == ORDEM_DAS_FAIXAS
    assert [len(secao.rows) for secao in resultado] == [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert _secao(resultado, PriorityBand.B21_I).priority_label == (
        "Ordem de prioridade: primeira"
    )
    assert _secao(resultado, PriorityBand.B24_V).shows_income is True


@pytest.mark.django_db
def test_inscricao_criada_depois_da_publicacao_fica_fora_da_lista(edicao_em_analise):
    """Sem `published_at` não se está na lista publicada — e é assim que
    uma inscrição gravada pelo Admin depois do resultado não entra nele
    sem que alguém publique de novo."""
    edicao = edicao_em_analise
    _candidato(edicao, "Ana Souza", PriorityBand.B21_I)
    publish_preliminary(edition=edicao)

    _candidato(edicao, "Bruno Dias", PriorityBand.B21_I)

    assert _nomes(edicao.result(ScholarshipLevel.MASTERS), PriorityBand.B21_I) == [
        "Ana Souza"
    ]
