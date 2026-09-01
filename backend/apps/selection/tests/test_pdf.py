"""O PDF da ata: bytes válidos, com e sem assinatura.

Nível (a) da pirâmide — a ata é montada em memória, como em
`test_record.py`. O que se prova aqui é que `render_record_pdf` devolve um
PDF de verdade e que o conteúdo que o papel precisa carregar (protocolo,
nome, hash, assinatura) está lá dentro; conferir pixel é trabalho de olho
humano, não de teste.
"""

import base64
import re
import zlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.academic.models import Teacher
from apps.people.models import Person
from apps.programs.models import CollectiveProject, Program
from apps.selection.models import (
    Board,
    ExaminationRecord,
    RecordSignature,
    SelectionKind,
    SelectionLevel,
    SelectionProcess,
    SelectionStage,
    SignatureMethod,
)
from apps.selection.pdf import PREFIXO_DO_HASH, render_record_pdf

AGORA = datetime(2026, 3, 10, 14, 0, tzinfo=UTC)


def _professor(pk: int, nome: str, category: str = Teacher.Category.PERMANENT):
    professor = Teacher(pk=pk, program_id=1, category=category)
    # Pessoa não salva: só o `full_name` interessa ao papel.
    professor.person = Person(pk=pk, full_name=nome)
    return professor


def _banca() -> Board:
    edital = SelectionProcess(
        pk=1,
        program_id=1,
        kind=SelectionKind.REGULAR,
        year=2027,
        title="Edital 1/2027 — Seleção Regular",
    )
    return Board(
        pk=1,
        program_id=1,
        process=edital,
        level=SelectionLevel.MASTERS,
        project=CollectiveProject(pk=1, name="Direito e Tecnologia"),
        president=_professor(1, "Ana Matos"),
        member_1=_professor(2, "Bruno Lopes"),
        member_2=_professor(3, "Marta Queirós", Teacher.Category.EXTERNAL),
        alternate=_professor(4, "Carla Dias"),
    )


def _linha(nome: str, protocolo: str, score: str | None, absent: bool = False) -> dict:
    return {
        "application_id": 1,
        "protocol": protocolo,
        "full_name": nome,
        "quota_category": "racial",
        "score": score,
        "absent": absent,
        "passed": bool(score is not None and Decimal(score) >= 70),
    }


def _ata(**kwargs) -> ExaminationRecord:
    banca = _banca()
    campos = {
        "program": Program(pk=1),
        "process": banca.process,
        "stage": SelectionStage(
            pk=1, process=banca.process, order=2, name="Prova escrita"
        ),
        "level": banca.level,
        "project": banca.project,
        "board": banca,
    }
    return ExaminationRecord(**{**campos, **kwargs})


def _ata_congelada(**kwargs) -> ExaminationRecord:
    ata = _ata(**kwargs)
    ata.freeze(
        [
            _linha("Ana Ribeiro", "PS2027R-AAAA0001", "85.50"),
            _linha("Bruno Silva", "PS2027R-AAAA0002", "62.00"),
            _linha("Carla Nunes", "PS2027R-AAAA0003", None, absent=True),
        ],
        at=AGORA,
    )
    return ata


def _texto_do_pdf(pdf: bytes) -> str:
    """O texto que o papel carrega, para perguntar "este dado saiu?".

    O ReportLab comprime os fluxos de página (Flate) e ainda os passa
    por ASCII85, então ler os bytes crus não acha nada: cada `stream`
    precisa ser desfeito nessa ordem antes da busca. Latin-1 porque é
    assim que o operador de texto do PDF escreve com a Helvetica
    embutida.
    """
    partes = []
    for bruto in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        dados = bruto.strip()
        if dados.endswith(b"~>"):
            dados = base64.a85decode(dados, adobe=True)
        try:
            partes.append(zlib.decompress(dados))
        except zlib.error:
            partes.append(dados)
    return b"".join(partes).decode("latin-1")


# --- bytes válidos ---------------------------------------------------------


def test_ata_sem_assinatura_gera_pdf():
    pdf = render_record_pdf(_ata_congelada())

    assert pdf.startswith(b"%PDF")
    assert pdf.rstrip().endswith(b"%%EOF")


def test_ata_em_rascunho_e_sem_conteudo_ainda_gera_pdf():
    """A prévia do rascunho é o que a banca abre para ver quem falta."""
    pdf = render_record_pdf(_ata())

    assert pdf.startswith(b"%PDF")


def test_pdf_carrega_cabecalho_notas_e_hash():
    ata = _ata_congelada()

    texto = _texto_do_pdf(render_record_pdf(ata))

    assert "ATA DE EXAME" in texto
    assert "Prova escrita" in texto
    assert "Ana Ribeiro" in texto
    assert "PS2027R-AAAA0003" in texto
    assert "Ausente" in texto
    assert "Cota racial" in texto
    assert ata.content_hash in texto


def test_pdf_lista_a_banca_e_o_titular_impedido():
    banca = _banca()
    ata = _ata_congelada(board=banca, replaced_member=banca.member_2)

    texto = _texto_do_pdf(render_record_pdf(ata))

    assert "Ana Matos" in texto
    assert "Carla Dias" in texto
    assert "Titular impedido" in texto


@pytest.mark.django_db
def test_pdf_lista_as_assinaturas_com_prefixo_do_hash(
    edital_regular, banca_regular, inscricao
):
    """Com assinatura o papel precisa de banco: a relação reversa não
    existe em ata sem `pk`."""
    etapa = edital_regular.stages.first()
    ata = ExaminationRecord.objects.create(
        program=banca_regular.program,
        process=edital_regular,
        stage=etapa,
        level=banca_regular.level,
        project=banca_regular.project,
        research_line=banca_regular.research_line,
        board=banca_regular,
    )
    ata.freeze([_linha(inscricao.full_name, inscricao.protocol, "90.00")], at=AGORA)
    ata.save()
    assinatura = RecordSignature.objects.create(
        record=ata,
        signer=banca_regular.president,
        method=SignatureMethod.LOGIN,
        signed_at=timezone.now(),
        signed_hash=ata.content_hash,
    )
    RecordSignature.objects.create(
        record=ata,
        signer=banca_regular.member_1,
        method=SignatureMethod.LOGIN,
    )

    texto = _texto_do_pdf(render_record_pdf(ata))

    assert texto.count(str(SignatureMethod.LOGIN.label)) >= 2
    assert assinatura.signed_hash[:PREFIXO_DO_HASH] in texto
    # A pendente entra sem data e sem hash.
    assert "Nenhuma assinatura registrada." not in texto
