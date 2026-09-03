"""O PDF da ata de exame (ADR-008: ReportLab, puro Python).

O documento é gerado **a partir do `content` congelado**, e não das notas
que estão hoje na tabela: é o `content` que o `content_hash` cobre e que
cada assinatura confere. Reler o `StageScore` aqui produziria um papel que
não corresponde ao que foi assinado — exatamente o erro que a ata
versionável existe para impedir.

Só há uma função pública, `render_record_pdf`, e ela devolve **bytes**:
quem grava o arquivo é o service (`sign_record`), que sabe o momento certo
e o `upload_to`. Nada aqui toca o banco além de ler as relações da ata.
"""

from datetime import datetime
from io import BytesIO
from typing import Any

from django.utils import formats, timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import ExaminationRecord, QuotaCategory, RecordSignature, SignatureMethod

# Helvetica é a fonte embutida do ReportLab: nenhum arquivo de fonte para
# instalar na imagem, e acentuação correta em Latin-1 estendida.
FONTE = "Helvetica"
FONTE_NEGRITO = "Helvetica-Bold"
FONTE_MONO = "Courier"

CINZA_DA_LINHA = colors.HexColor("#F2F2F2")
CINZA_DA_BORDA = colors.HexColor("#999999")

TITULO = ParagraphStyle(
    "titulo",
    fontName=FONTE_NEGRITO,
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    spaceAfter=2 * mm,
)
SUBTITULO = ParagraphStyle(
    "subtitulo",
    fontName=FONTE,
    fontSize=10,
    leading=13,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#555555"),
)
SECAO = ParagraphStyle(
    "secao",
    fontName=FONTE_NEGRITO,
    fontSize=11,
    leading=14,
    spaceBefore=6 * mm,
    spaceAfter=2 * mm,
)
CORPO = ParagraphStyle("corpo", fontName=FONTE, fontSize=9, leading=12)
NOTA_DE_RODAPE = ParagraphStyle(
    "rodape",
    fontName=FONTE,
    fontSize=8,
    leading=11,
    textColor=colors.HexColor("#555555"),
)
HASH = ParagraphStyle("hash", fontName=FONTE_MONO, fontSize=8, leading=11)

# Quantos hexadecimais do hash assinado entram no papel. O hash inteiro
# tem 64 e não cabe em coluna de tabela; 12 já distinguem as assinaturas
# entre si, e a conferência de verdade é `verify_hash()`, no sistema.
PREFIXO_DO_HASH = 12


def _texto(valor: Any) -> str:
    """Nunca deixa `None` virar a palavra "None" no papel."""
    return "—" if valor in (None, "") else str(valor)


def _instante(valor: datetime | None) -> str:
    if valor is None:
        return "—"
    return formats.date_format(timezone.localtime(valor), "DATETIME_FORMAT")


def _nome_do_professor(teacher: Any) -> str:
    """O nome da pessoa por trás do professor, sem explodir sem ela.

    `getattr(..., None)` cobre o `RelatedObjectDoesNotExist` (que herda de
    `AttributeError`) do professor montado em memória, sem `person`.
    """
    if teacher is None:
        return "—"
    person = getattr(teacher, "person", None)
    if person is None:
        return f"Professor(a) {teacher.pk}"
    return str(person.full_name)


def _alvo(record: ExaminationRecord) -> str:
    alvo = record.project or record.research_line
    return _texto(alvo)


def _assinaturas(record: ExaminationRecord) -> list[RecordSignature]:
    """As assinaturas da ata, ou nada quando ela ainda não foi salva.

    Consultar a relação reversa de instância sem `pk` é `ValueError` no
    Django; a ata em memória (rascunho de teste) simplesmente não tem
    assinatura para mostrar.
    """
    if record.pk is None:
        return []
    return list(record.signatures.select_related("signer__person"))


def _cabecalho(record: ExaminationRecord) -> Table:
    banca = record.board
    membros = ", ".join(
        f"{_nome_do_professor(t)} ({papel})"
        for t, papel in (
            (banca.president, "presidente"),
            (banca.member_1, "membro"),
            (banca.member_2, "membro"),
            (banca.alternate, "suplente"),
        )
    )
    linhas: list[tuple[str, str]] = [
        ("Edital", _texto(record.process)),
        ("Etapa", _texto(record.stage)),
        ("Nível", record.get_level_display()),
        ("Alvo", _alvo(record)),
        ("Banca", membros),
    ]
    if record.replaced_member_id is not None:
        linhas.append(("Titular impedido", _nome_do_professor(record.replaced_member)))
    linhas += [
        ("Versão", f"{record.version}"),
        ("Situação", record.get_status_display()),
        ("Congelada em", _instante(record.frozen_at)),
        ("Assinada em", _instante(record.signed_at)),
    ]
    tabela = Table(
        [[Paragraph(f"<b>{r}</b>", CORPO), Paragraph(v, CORPO)] for r, v in linhas],
        colWidths=[35 * mm, 130 * mm],
        hAlign="LEFT",
    )
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, CINZA_DA_BORDA),
            ]
        )
    )
    return tabela


def _situacao_da_linha(row: dict[str, Any]) -> str:
    if row.get("absent"):
        return "Ausente"
    return "Aprovado(a)" if row.get("passed") else "Reprovado(a)"


def _cota(valor: Any) -> str:
    try:
        return str(QuotaCategory(valor).label)
    except ValueError:
        return _texto(valor)


def _tabela_de_notas(record: ExaminationRecord) -> Table:
    cabecalho = ["Protocolo", "Candidato(a)", "Cota", "Nota", "Situação"]
    corpo = [
        [
            Paragraph(_texto(row.get("protocol")), CORPO),
            Paragraph(_texto(row.get("full_name")), CORPO),
            Paragraph(_cota(row.get("quota_category")), CORPO),
            Paragraph(_texto(row.get("score")), CORPO),
            Paragraph(_situacao_da_linha(row), CORPO),
        ]
        for row in record.content
    ]
    if not corpo:
        corpo = [[Paragraph("Nenhum candidato nesta ata.", CORPO), "", "", "", ""]]
    tabela = Table(
        [[Paragraph(f"<b>{c}</b>", CORPO) for c in cabecalho], *corpo],
        colWidths=[38 * mm, 59 * mm, 26 * mm, 17 * mm, 25 * mm],
        hAlign="LEFT",
        repeatRows=1,
    )
    tabela.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, CINZA_DA_BORDA),
                ("BACKGROUND", (0, 0), (-1, 0), CINZA_DA_LINHA),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tabela


def _tabela_de_assinaturas(assinaturas: list[RecordSignature]) -> Table:
    cabecalho = ["Signatário(a)", "Método", "Assinada em", "Hash assinado"]
    corpo = []
    for assinatura in assinaturas:
        metodo = SignatureMethod(assinatura.method).label
        prefixo = (assinatura.signed_hash or "")[:PREFIXO_DO_HASH]
        corpo.append(
            [
                Paragraph(_nome_do_professor(assinatura.signer), CORPO),
                Paragraph(str(metodo), CORPO),
                Paragraph(_instante(assinatura.signed_at), CORPO),
                Paragraph(_texto(prefixo), HASH),
            ]
        )
    if not corpo:
        corpo = [[Paragraph("Nenhuma assinatura registrada.", CORPO), "", "", ""]]
    tabela = Table(
        [[Paragraph(f"<b>{c}</b>", CORPO) for c in cabecalho], *corpo],
        colWidths=[58 * mm, 30 * mm, 45 * mm, 32 * mm],
        hAlign="LEFT",
        repeatRows=1,
    )
    tabela.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, CINZA_DA_BORDA),
                ("BACKGROUND", (0, 0), (-1, 0), CINZA_DA_LINHA),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tabela


def render_record_pdf(record: ExaminationRecord) -> bytes:
    """O PDF desta ata, como bytes.

    Cabeçalho (edital, etapa, nível, alvo, banca), a tabela do `content` e
    o rodapé com a versão, o `content_hash` e uma linha por assinatura.
    """
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Ata — {record.stage} — {record.get_level_display()}",
        author="PPGM",
    )
    assinaturas = _assinaturas(record)
    elementos: list[Any] = [
        Paragraph("ATA DE EXAME", TITULO),
        Paragraph(_texto(record.process), SUBTITULO),
        Spacer(1, 6 * mm),
        _cabecalho(record),
        Paragraph("Resultado da etapa", SECAO),
        _tabela_de_notas(record),
        Paragraph("Assinaturas", SECAO),
        _tabela_de_assinaturas(assinaturas),
        Spacer(1, 6 * mm),
        KeepTogether(
            [
                Paragraph(
                    f"Versão {record.version} da ata. "
                    "A autenticidade deste documento é conferida pelo hash "
                    "do conteúdo, que é o que cada signatário assinou:",
                    NOTA_DE_RODAPE,
                ),
                Paragraph(_texto(record.content_hash), HASH),
            ]
        ),
    ]
    documento.build(elementos)
    return buffer.getvalue()
