# ADR-010: o PDF do resultado do edital de bolsas

- **Data**: 2026-09-01
- **Status**: aceito

## Contexto

O resultado do edital de bolsas é publicado como **papel**: é o documento que a
secretaria afixa, que o candidato imprime para interpor recurso e que sustenta a
distribuição das cotas se alguém contestar. O sistema já tem a lista pronta —
`ScholarshipEdition.result(level)` devolve as dez faixas de prioridade, na ordem
canônica, com o cabeçalho de cada uma e as linhas na posição final (f16 e f18).
Falta renderizar isso num arquivo.

A escolha da biblioteca **já foi feita** no [ADR-008](008-pdf-da-ata-com-reportlab.md)
para a ata de exame: ReportLab, `platypus`, Helvetica embutida, nenhuma dependência
de sistema. Nada no resultado de bolsas reabre aquela comparação — é o mesmo
tipo de documento (cabeçalho, tabelas, rodapé) e o mesmo time operando a mesma
imagem. Este ADR existe para registrar as decisões **próprias deste documento**,
não para reescrever a decisão de motor.

## Decisão

O layout mora em `backend/apps/scholarships/pdf.py`, espelhando o desenho de
`apps/selection/pdf.py`, com uma função pública:

```python
montar_resultado(edition: ScholarshipEdition, level: str, kind: str) -> bytes
```

Ela devolve bytes e **não escreve no banco nem no disco**; a rota
(`GET /api/v1/scholarships/editions/{id}/result.pdf?level=`) só a embrulha num
`FileResponse`. Quatro decisões de conteúdo:

- **Um documento por nível.** Mestrado e doutorado correm independentes e saem
  em papéis separados, como já saem no JSON. Não existe documento dos dois
  juntos.
- **O PDF lê `result(level)`, nunca `classify()`.** Publicado o preliminar, é o
  **snapshot** que vai ao papel. Se este módulo recalculasse, o PDF baixado
  durante a fase de recursos discordaria da tela ao lado a cada deferimento —
  que é exatamente o que os campos `published_*` da inscrição existem para
  impedir.
- **As dez seções saem sempre, inclusive as vazias** (decisão Q8). Faixa sem
  candidato é publicada só com o cabeçalho: uma faixa que sumisse viraria uma
  ordem de prioridade a menos na lista, e mudaria o sentido do documento.
- **A coluna varia por faixa.** "Remuneração" só aparece onde o rendimento
  ordenou a faixa (2.4-V e 2.4-VI/VII/VIII), pela mesma chave `shows_income`
  que `classify()` usou. Nas outras oito o rendimento não entrou na conta, e
  imprimi-lo sugeriria que entrou. Pelo mesmo motivo o cabeçalho de cada seção
  publica a **regra de ordenação escrita**, que vem da mesma constante
  (`REGRA_DE_ORDENACAO_DA_FAIXA`) que ordenou — texto e algoritmo saem do mesmo
  lugar para não divergirem.

A visibilidade é a **mesma** do JSON, numa função só
(`_garantir_resultado_visivel`, em `router.py`): quem trabalha o edital vê a
prévia; o candidato só a partir do preliminar publicado (403
`result_not_published`). Duas cópias da regra divergiriam, e a que vazasse seria
justamente a imprimível.

## Consequências

- **Fica mais fácil**: nenhuma dependência nova. O `reportlab` já está no
  `pyproject.toml` desde o ADR-008, com o `ignore_missing_imports` do mypy —
  esta story **não** toca o `pyproject.toml` nem exige rebuild da imagem.
- **Fica mais difícil**: layout é código imperativo. Coluna estreita demais
  quebra a linha **em silêncio**; a largura das duas composições
  (`COLUNAS_SEM_REMUNERACAO`/`COLUNAS_COM_REMUNERACAO`) tem de somar os 170 mm
  úteis do A4.
- **O papel não é fonte**: ele é renderização de `result(level)`, como o PDF da
  ata é renderização do `content` congelado. Corrigir resultado é refazer
  lançamento e republicar, nunca editar o documento.
- **Reabre o assunto**: brasão/identidade visual da instituição no cabeçalho, ou
  assinatura digital do documento publicado. Aí se discute — com a exigência
  escrita, e sem trocar de motor por causa dela.
