"""O PDF do resultado do edital de bolsas (ADR-010, que herda o ADR-008).

Um documento **por nível**: mestrado e doutorado correm independentes e
saem em papéis separados, como as dez seções da ordem canônica saem
sempre — inclusive as vazias (decisão Q8). Faixa sem candidato que sumisse
do papel viraria uma prioridade a menos na lista publicada.

O conteúdo vem de `ScholarshipEdition.result(level)`, o mesmo objeto que a
tela lê: publicado o preliminar é o snapshot, antes dele é a prévia. É por
isso que este módulo não classifica nada — se ele recalculasse, o PDF
baixado durante a fase de recursos discordaria da tela ao lado.

Só há uma função pública, `montar_resultado`, e ela devolve **bytes**:
nada aqui escreve no banco nem no disco. A rota (`.../result.pdf`) só
embrulha o retorno num `FileResponse`.
"""

from decimal import Decimal
from io import BytesIO
from typing import Any

from django.utils import formats, timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import BandResult, ScholarshipEdition, ScholarshipLevel

# Helvetica é a fonte embutida do ReportLab: nenhum arquivo de fonte para
# instalar na imagem, e acentuação correta em Latin-1 estendida.
FONTE = "Helvetica"
FONTE_NEGRITO = "Helvetica-Bold"

CINZA_DA_LINHA = colors.HexColor("#F2F2F2")
CINZA_DA_BORDA = colors.HexColor("#999999")

# Os dois tipos de documento. Não é campo de model: sai do carimbo de
# publicação da edição (`tipo_do_resultado`), e é o que muda o título do
# papel — a lista em si é a mesma leitura.
RESULTADO_PRELIMINAR = "preliminary"
RESULTADO_FINAL = "final"

TITULO_DO_DOCUMENTO: dict[str, str] = {
    RESULTADO_PRELIMINAR: "RESULTADO PRELIMINAR",
    RESULTADO_FINAL: "RESULTADO FINAL",
}

# O nome do arquivo baixado, montado com o id da edição e o nível para
# que dois documentos da mesma edição não se sobreponham na pasta de
# quem baixou os dois.
PREFIXO_DO_ARQUIVO: dict[str, str] = {
    RESULTADO_PRELIMINAR: "resultado-preliminar",
    RESULTADO_FINAL: "resultado-final",
}

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
    spaceAfter=1 * mm,
)
CORPO = ParagraphStyle("corpo", fontName=FONTE, fontSize=9, leading=12)
NOTA_DE_RODAPE = ParagraphStyle(
    "rodape",
    fontName=FONTE,
    fontSize=8,
    leading=11,
    textColor=colors.HexColor("#555555"),
)

# Larguras em milímetros, nas duas composições de coluna. A soma tem de
# caber nos 170 mm úteis do A4 com as margens abaixo: coluna estreita
# demais quebra a linha **em silêncio**, sem erro nenhum.
COLUNAS_SEM_REMUNERACAO = [20 * mm, 120 * mm, 30 * mm]
COLUNAS_COM_REMUNERACAO = [20 * mm, 90 * mm, 30 * mm, 30 * mm]


def tipo_do_resultado(edition: ScholarshipEdition) -> str:
    """Qual dos dois documentos esta edição publica hoje.

    O carimbo do final manda: uma vez publicado, é ele que o papel
    anuncia. Antes de qualquer publicação o documento é a prévia da
    secretaria, e sai rotulado como preliminar — é o que ela está
    conferindo antes de congelar.
    """
    if edition.published_final_at is not None:
        return RESULTADO_FINAL
    return RESULTADO_PRELIMINAR


def nome_do_arquivo(edition: ScholarshipEdition, level: str, kind: str) -> str:
    return (
        f"{PREFIXO_DO_ARQUIVO.get(kind, PREFIXO_DO_ARQUIVO[RESULTADO_PRELIMINAR])}"
        f"-{edition.year}-{level}-edicao-{edition.pk}.pdf"
    )


def _texto(valor: Any) -> str:
    """Nunca deixa `None` virar a palavra "None" no papel."""
    return "—" if valor in (None, "") else str(valor)


def _dinheiro(valor: "Decimal | None") -> str:
    """Rendimento com separador de milhar — `force_grouping` é obrigatório.

    `USE_THOUSAND_SEPARATOR` é falso por padrão no Django, e sem o
    argumento o papel publicaria "3200,00": legível, mas não é assim que
    valor em real se escreve num documento oficial.
    """
    if valor is None:
        return "—"
    formatado = formats.number_format(
        valor, decimal_pos=2, use_l10n=True, force_grouping=True
    )
    return f"R$ {formatado}"


def _nota(valor: "Decimal | None") -> str:
    if valor is None:
        return "—"
    return str(formats.number_format(valor, decimal_pos=2, use_l10n=True))


def _data(valor: Any) -> str:
    if valor is None:
        return "—"
    return str(formats.date_format(timezone.localtime(valor), "DATETIME_FORMAT"))


def _nivel(level: str) -> str:
    try:
        return str(ScholarshipLevel(level).label)
    except ValueError:
        return _texto(level)


def _cabecalho(edition: ScholarshipEdition, level: str, kind: str) -> Table:
    publicado_em = (
        edition.published_final_at
        if kind == RESULTADO_FINAL
        else edition.published_preliminary_at
    )
    linhas: list[tuple[str, str]] = [
        ("Programa", _texto(getattr(edition.program, "name", None))),
        ("Edital", _texto(edition.title)),
        ("Ano", _texto(edition.year)),
        ("Nível", _nivel(level)),
        ("Situação da edição", str(edition.get_status_display())),
        ("Publicado em", _data(publicado_em)),
    ]
    tabela = Table(
        [[Paragraph(f"<b>{r}</b>", CORPO), Paragraph(v, CORPO)] for r, v in linhas],
        colWidths=[40 * mm, 130 * mm],
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


def _tabela_da_faixa(faixa: BandResult) -> Table:
    """A tabela de uma seção, com a coluna "Remuneração" só onde ela ordena.

    `shows_income` é a mesma chave que `classify()` usou para ordenar a
    faixa (2.4-V e 2.4-VI/VII/VIII): o papel publica a coluna que decidiu
    a ordem, e não uma coluna a mais em toda seção — nas outras oito o
    rendimento não entrou na conta e imprimi-lo sugeriria que entrou.
    """
    cabecalho = ["Ordem", "Candidato(a)", "Nota"]
    if faixa.shows_income:
        cabecalho.append("Remuneração")
    corpo = []
    for linha in faixa.rows:
        celulas = [
            Paragraph(str(linha.position), CORPO),
            Paragraph(_texto(linha.name), CORPO),
            Paragraph(_nota(linha.score), CORPO),
        ]
        if faixa.shows_income:
            celulas.append(Paragraph(_dinheiro(linha.income), CORPO))
        corpo.append(celulas)
    vazia = not corpo
    if vazia:
        corpo = [
            [Paragraph("Nenhum candidato nesta faixa.", CORPO)]
            + [Paragraph("", CORPO)] * (len(cabecalho) - 1)
        ]
    larguras = (
        COLUNAS_COM_REMUNERACAO if faixa.shows_income else COLUNAS_SEM_REMUNERACAO
    )
    tabela = Table(
        [[Paragraph(f"<b>{c}</b>", CORPO) for c in cabecalho], *corpo],
        colWidths=larguras,
        hAlign="LEFT",
        repeatRows=1,
    )
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.25, CINZA_DA_BORDA),
        ("BACKGROUND", (0, 0), (-1, 0), CINZA_DA_LINHA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    if not vazia:
        estilo.append(("ALIGN", (2, 1), (-1, -1), "RIGHT"))
    tabela.setStyle(TableStyle(estilo))
    return tabela


def _secao(faixa: BandResult) -> list[Any]:
    """O cabeçalho da seção mais a tabela — nesta ordem, sempre.

    Título, "Ordem de prioridade: N" e a **regra de ordenação escrita**
    vêm prontos do `BandResult`, que os leu da mesma constante que
    ordenou a faixa. Texto e algoritmo saem do mesmo lugar justamente
    para não divergirem.
    """
    elementos: list[Any] = [
        Paragraph(f"{faixa.priority_label} — {faixa.title}", SECAO),
        Paragraph(f"Critério de ordenação: {faixa.ordering_rule}", NOTA_DE_RODAPE),
        Spacer(1, 2 * mm),
        _tabela_da_faixa(faixa),
    ]
    if any(linha.draw_order is not None for linha in faixa.rows):
        elementos.append(Spacer(1, 1 * mm))
        elementos.append(
            Paragraph(
                "Nesta faixa houve empate resolvido por sorteio, na forma do "
                "item 3.3 do edital.",
                NOTA_DE_RODAPE,
            )
        )
    return elementos


def montar_resultado(
    edition: ScholarshipEdition, level: str, kind: str = RESULTADO_PRELIMINAR
) -> bytes:
    """O PDF do resultado de um nível desta edição, como bytes.

    Função pura: lê `edition.result(level)` — o snapshot publicado, ou a
    prévia antes dele — e devolve o documento. Não grava arquivo, não
    escreve `AuditLog` e não decide quem pode ver: isso é da rota.

    As dez faixas saem na ordem canônica, cada uma com o seu cabeçalho,
    **mesmo sem candidato**.
    """
    buffer = BytesIO()
    titulo = TITULO_DO_DOCUMENTO.get(kind, "RESULTADO")
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{titulo} — {edition.title} — {_nivel(level)}",
        author="PPGM",
    )
    elementos: list[Any] = [
        Paragraph(titulo, TITULO),
        Paragraph(f"{_texto(edition.title)} — {_nivel(level)}", SUBTITULO),
        Spacer(1, 6 * mm),
        _cabecalho(edition, level, kind),
    ]
    for faixa in edition.result(level):
        elementos.extend(_secao(faixa))
    elementos.append(Spacer(1, 8 * mm))
    elementos.append(
        Paragraph(
            "Lista de prioridade organizada nas faixas do edital, na ordem "
            "canônica: a primeira seção é a de maior prioridade. Faixa sem "
            "candidato é publicada apenas com o cabeçalho.",
            NOTA_DE_RODAPE,
        )
    )
    documento.build(elementos)
    return buffer.getvalue()
