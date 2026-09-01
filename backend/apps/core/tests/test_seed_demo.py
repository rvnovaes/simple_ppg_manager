"""A carga de demonstração roda duas vezes, nos dois programas, sem erro.

Não é teste de regra de negócio — as regras têm os testes dos seus apps.
O que se cobra aqui é o que o `seed_demo` promete e o que quebra em
silêncio quando alguém mexe num model: que a carga **completa** (é uma
transação só; qualquer `clean()` novo derruba tudo), que ela é idempotente
e que o segundo tenant não pisa no primeiro.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.programs.models import Program
from apps.selection.models import (
    Application,
    ApplicationStatus,
    Board,
    Convocation,
    ExaminationRecord,
    RecordStatus,
    SelectionProcess,
)

SEGUNDO_PROGRAMA = (
    "--acronym",
    "PPGA",
    "--name",
    "Pós-Graduação em Administração",
    "--email-domain",
    "ppga.test",
)


@pytest.fixture
def raiz_temporaria(settings, tmp_path):
    """Manda o `CONTAS-DEMO.txt` para um diretório descartável.

    O caminho sai de `BASE_DIR.parent` (a raiz do repositório); sem esta
    troca, rodar a suíte reescreveria o arquivo de quem está com o
    canteiro de pé.
    """
    backend = tmp_path / "backend"
    backend.mkdir()
    settings.BASE_DIR = backend
    return tmp_path


def carregar(*args: str) -> None:
    call_command("seed_demo", "--force", *args, stdout=StringIO())


@pytest.mark.django_db
def test_carga_completa_e_idempotente_nos_dois_programas(raiz_temporaria):
    carregar()
    carregar(*SEGUNDO_PROGRAMA)
    # A segunda passada é o que prova a idempotência: `get_or_create` em
    # tudo, e as operações que não têm chave natural (convocação, ata,
    # matrícula) atrás de uma guarda de existência.
    carregar()
    carregar(*SEGUNDO_PROGRAMA)

    assert Program.objects.count() == 2
    for programa in Program.objects.all():
        editais = SelectionProcess.objects.filter(program=programa)
        assert editais.count() == 2, programa.acronym
        assert all(edital.is_published for edital in editais)
        assert all(edital.stages.count() == 3 for edital in editais)
        assert Board.objects.filter(program=programa).count() == 4

        inscricoes = Application.objects.filter(program=programa)
        assert set(inscricoes.values_list("status", flat=True)) == set(
            ApplicationStatus.values
        )

        ata = ExaminationRecord.objects.filter(
            program=programa, status=RecordStatus.SIGNED
        ).first()
        assert ata is not None
        assert ata.pdf, "a última assinatura grava o PDF da ata"
        assert ata.verify_hash()
        assert not ata.signatures.pending().exists()

        lote = Convocation.objects.filter(program=programa).first()
        assert lote is not None
        assert lote.emails.exists()


@pytest.mark.django_db
def test_ata_assinada_elimina_quem_ficou_abaixo_do_corte(raiz_temporaria):
    """O `eliminated` da carga vem da ata, e não de um status semeado."""
    carregar()

    eliminada = Application.objects.get(status=ApplicationStatus.ELIMINATED)
    assert eliminada.eliminated_at_stage is not None
    assert eliminada.eliminated_at_stage.order == 1
    assert eliminada.scores.get(stage=eliminada.eliminated_at_stage).passed is False


@pytest.mark.django_db
def test_contas_demo_guarda_um_bloco_por_programa(raiz_temporaria):
    carregar()
    carregar(*SEGUNDO_PROGRAMA)

    arquivo = raiz_temporaria / "CONTAS-DEMO.txt"
    conteudo = arquivo.read_text(encoding="utf-8")
    assert conteudo.count("## PPGD ") == 1
    assert conteudo.count("## PPGA ") == 1
    # O segundo tenant não pode apagar o bloco do primeiro, e cada bloco
    # traz as contas com o domínio do seu programa.
    assert "comissao@ppgd.test" in conteudo
    assert "comissao@ppga.test" in conteudo

    carregar()
    assert arquivo.read_text(encoding="utf-8").count("## PPGA ") == 1
