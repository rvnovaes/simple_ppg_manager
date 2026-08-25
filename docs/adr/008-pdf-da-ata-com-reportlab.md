# ADR-008: gerar o PDF da ata com ReportLab

- **Data**: 2026-08-25
- **Status**: aceito

## Contexto

A ata de exame do processo seletivo precisa virar **papel**: é o documento que
os três examinadores assinam, que a secretaria arquiva e que sustenta o
resultado se alguém contestar. O sistema já guarda o conteúdo da ata em JSON
(`ExaminationRecord.content`) e o hash que cada assinatura confere
(`content_hash`); falta renderizar isso num arquivo estável, com o hash impresso,
para que o PDF baixado hoje e o baixado no ano que vem sejam o mesmo documento.

As alternativas de mercado se dividem em duas famílias:

1. **HTML → PDF** (WeasyPrint, wkhtmltopdf, Playwright). Bonito de escrever, mas
   todas trazem dependência de sistema: WeasyPrint precisa de Pango, Cairo e
   GDK-PixBuf; wkhtmltopdf é um binário Qt sem manutenção; Playwright quer um
   Chromium inteiro dentro da imagem. Isso muda o `Dockerfile`, muda o que a
   infra instala no servidor de produção e cria uma classe de falha nova — o PDF
   que quebra porque a imagem base trocou de versão de biblioteca C.
2. **Composição direta em Python** (ReportLab, fpdf2). Nenhuma dependência de
   sistema; o layout é código.

O time é forte em infraestrutura e a régua do `CLAUDE.md` é **menos peças
móveis**. Uma ata com cabeçalho, uma tabela e um rodapé não precisa de motor de
CSS.

## Decisão

Usamos **ReportLab** (`platypus`: `SimpleDocTemplate` + `Table`), fonte Helvetica
— a embutida no próprio PDF, sem arquivo de fonte para instalar. O layout mora
em `backend/apps/selection/pdf.py`, com uma função pública só:

```python
render_record_pdf(record: ExaminationRecord) -> bytes
```

Ela devolve bytes e **não escreve no banco nem no disco**: quem grava o arquivo
no `FileField` é o service (`sign_record`), que sabe o momento certo.

Duas regras de conteúdo, que são o motivo de o módulo existir:

- **O PDF nasce do `content` congelado**, nunca de uma releitura do `StageScore`.
  É o `content` que o `content_hash` cobre; reler a tabela de notas produziria um
  papel diferente do que foi assinado.
- **O `content_hash` é impresso no rodapé**, junto com a versão da ata e, por
  assinatura, nome, método, instante e os 12 primeiros hexadecimais do
  `signed_hash`. O papel carrega a prova de que todos assinaram o mesmo texto.

Descartado o **fpdf2** (API de baixo nível: tabela com quebra de página seria
código nosso) e o **LaTeX** (toolchain de centenas de MB para três seções).

## Consequências

- **Fica mais fácil**: o PDF é testável sem navegador nem binário externo — o
  teste monta a ata em memória e confere os bytes (`%PDF`) e o texto dos fluxos.
  A imagem do backend não ganha nenhum pacote de sistema.
- **Fica mais difícil**: layout é código imperativo, não CSS. Mudança visual
  (coluna nova, cabeçalho institucional com logotipo) é edição em `pdf.py`, e o
  ajuste fino de largura de coluna é tentativa e erro — a coluna estreita demais
  **quebra a linha em silêncio**, sem erro nenhum.
- **`uv add reportlab` muda o lock e exige rebuild da imagem**
  (`docker compose up -d --build backend`): o venv está em `/opt/venv` na
  imagem, não no volume. Sem o rebuild, o container antigo continua sem a
  biblioteca e o erro é um `ModuleNotFoundError` no meio da assinatura.
- **O ReportLab não tem stubs de tipo**, então entra em
  `[[tool.mypy.overrides]] ignore_missing_imports` no `pyproject.toml`. Isso vale
  só para a biblioteca de terceiros; nenhuma verificação do código do projeto é
  afrouxada.
- Ele traz **Pillow** como dependência (roda com wheel, sem compilar).
- **Reabre o assunto**: exigência de assinatura digital ICP-Brasil no arquivo
  (PAdES), ou layout que dependa de HTML/CSS de verdade. Aí se discute
  biblioteca de assinatura ou motor de renderização — com a exigência escrita,
  não por antecipação.
