# Plano — Concessão de Bolsas (seleção anual)

> Destino após aprovação: `scripts/helton/projects/plans/bolsas.md`
> (→ worktree `../simple_ppg_manager-bolsas`, branch `helton/bolsas`,
> projeto Compose `simple_ppg_manager-bolsas`). Origem:
> `specs/bolsas.md` (grill de 31/08/2026) — ao arquivar este plano, mover a
> spec para `specs/implemented/`.

## Contexto

Hoje a seleção de bolsas do PPGD roda em dois lugares e nenhum deles é este
sistema: o legado em `pos.direito.ufmg.br/acessorestrito` recebe a inscrição,
guarda os comprovantes e pontua item a item — **mas não classifica**. A ordem
final é montada à mão numa planilha pela Secretaria, que soma a bonificação
FUMP, separa os candidatos nas faixas de prioridade da CEPE 08/2023, aplica
uma regra de ordenação diferente em cada faixa, desempata em cinco níveis e
gera o PDF por nível. É trabalho manual sobre 44 candidatos (mestrado) + 33
(doutorado) por ano, num processo em que errar a ordem é errar quem recebe
bolsa.

O módulo existe para **eliminar a planilha**: o aluno se inscreve logado, lança
os itens do barema com comprovante, a Comissão avalia lançamento a lançamento,
e o sistema entrega a lista classificada e o PDF do resultado. A fronteira é
estreita e deliberada (Q1/Q2 da spec): **o KPG faz a seleção e para no
resultado final**. Convocação, lista de espera, declínio, reclassificação,
implementação junto à agência, relatórios trimestrais, cumulação e a revisão
anual do Art. 8º continuam em planilha, fora do sistema.

Nada disso existe no código: `Scholarship`, `Bareme`, `Committee` têm zero
ocorrências em `backend/`. O que existe e será reusado é o precedente inteiro
das disciplinas isoladas em `apps/academic` — máquina de estados com transição
manual, upload validado no model, permissão própria para download, ordenação
que não persiste.

## Decisões fechadas nesta sessão (não reabrir)

| # | Decisão | Consequência |
|---|---|---|
| B1 | App Django novo `backend/apps/scholarships/` | Nada de bolsas em `academic`; **nenhuma migration em app existente** |
| B2 | **O KPG gera o PDF** do resultado, por nível, com ReportLab | ADR novo; `reportlab` entra em `backend/pyproject.toml`; `apps/scholarships/pdf.py` |
| B3 | **Sem e-mail** — mantém o corte de SMTP das isoladas | Nenhuma story vira `human_gate`: nada escapa do canteiro |
| B4 | **Comissão de Bolsas modelada por edição**: model `CommitteeMember` | Registro histórico da composição anual; a **autorização continua vindo do Group** |
| B5 | **O sistema sorteia** o 5º critério de desempate, com semente gravada | `ScholarshipEdition.draw_seed` + `draw_order` por inscrição; reprodutível e auditado |
| B6 | **A Secretaria pode sobrescrever a faixa** de uma inscrição, com justificativa | Resolve 2.4-I e 2.4-II (sem pergunta no questionário) e todo caso omisso |
| B7 | Questionário **fixo em código**: 8 campos booleanos no model da inscrição | Pergunta não é dado cadastrável (Q12); mudar norma é mudar código |
| B8 | Comprovante é `FileField` **no próprio lançamento**, obrigatório | Um arquivo por lançamento (Q11); não repete o desenho um-por-tipo de `RequestDocument` |
| B9 | Nota da comissão e nota do candidato **convivem** no lançamento | Divergência exige `committee_note` — é a fundamentação que o recurso ataca (Q10) |
| B10 | Publicação **congela um snapshot** na própria inscrição | `published_band`, `published_score`, `published_position`; sem model de "resultado" |

### Assunções (marcar em docstring/seed; o humano confirma no merge)
- Desempate III/IV (subtotais de "Formação Acadêmica" e "Produção Bibliográfica")
  usa os subtotais **da comissão**, não os do candidato — é a nota que a
  comissão homologou que o edital publica (flag Q15, não respondida).
- O rótulo "Ordem de prioridade: N" é **derivado da posição na ordem canônica
  de 10 faixas** — com 2.4-II e 2.4-III publicadas, a residual é a **décima**.
- **Uma edição por ano cobre os dois níveis**; o barema é por (edição, nível) e
  as listas de mestrado e doutorado correm independentes.
- A transição de estado é **sempre para frente**: não há "voltar para
  rascunho" nem reabrir janela. Correção de rumo é quebra-vidro no Admin.
- O aluno pode **excluir a própria inscrição** enquanto a janela está aberta;
  depois disso, não.
- `quantity` é `DecimalField(6,2)` (o barema mede em semestres, meses e horas —
  "meia hora" não aparece nos dados, mas inteiro fecharia a porta sem ganho).

---

## 1. Modelo de dados — `backend/apps/scholarships/models.py`

Convenções válidas para todos os models (não repetir por model): FK `program`
direta com `PROTECT` (ADR-007), exceto filhos de agregado (`BaremeItem`,
`CommitteeMember`, `BaremeEntry`, `ApplicationDocument`, `ItemReview`,
`ScholarshipAppeal`), que chegam ao programa pelo pai — mesmo recorte e mesma
justificativa de `RequestDocument` (`apps/academic/models.py:1675`);
`created_at`/`updated_at`; QuerySet com `for_program()` como **primeiro** filtro
de toda busca; `clean()` levanta `DomainError(code=...)` cobrindo
`program_mismatch` e a duplicata de cada `UniqueConstraint`; transições **não
salvam** (quem persiste é o router/service, no mesmo `transaction.atomic()` do
`AuditLog`); `InvalidStateTransition` = 409.

**Todos os `TextChoices` no nível do módulo, com nome único** — precedente
`AdjustmentStatus`/`RequestDocumentKind` (`apps/academic/models.py:533` e
`:1658`): enum aninhado de nome repetido colide no gerador de OpenAPI e o
último registrado sobrescreve o outro, sem erro no backend.

### Enums e constantes de módulo

`ScholarshipEditionStatus` (`draft` · `submissions_open` · `under_review` ·
`preliminary_result` · `appeals_under_review` · `final_result`) ·
`ScholarshipLevel` (`masters`/`doctorate` — **mesmos valores de
`Student.Level`**) · `BaremeSection` (I..VI: `formation`, `bibliographic`,
`events`, `professional`, `boards`, `other_titles`) · `BaremeUnit` (`semester`,
`month`, `hour`, `unit`) · `PriorityBand` (10 valores, na ordem canônica) ·
`AppealOutcome` (`granted`, `partially_granted`, `denied`) ·
`ApplicationDocumentKind` (7 tipos, um por resposta "Sim" que exige
comprovante).

```python
ORDEM_DAS_FAIXAS = [B21_I, B21_II, B24_I, B24_II, B24_III, B24_IV,
                    B24_V, B24_VI_VII_VIII, B24_IX, RESIDUAL]
BONUS_FUMP = {1: Decimal("15.00"), 2: Decimal("9.00")}   # item 3.2 do edital
# Regra de ordenação por faixa — dado, para o cabeçalho do PDF e para o código:
ORDENACAO_DA_FAIXA = {
    B24_V:           ("income", "score"),
    B24_VI_VII_VIII: ("income", "hours", "score"),
    # todas as demais:  ("score",)
}
```

### Models

**`ScholarshipEdition`** — a edição anual do edital. `program`, `year`,
`title`, `status`, `notice_file` (`FileField`, blank), as datas do cronograma
como **informação** (`submission_starts_on`, `submission_ends_on`,
`preliminary_result_on`, `appeal_ends_on`, `final_result_on` — todas
`DateField(null=True)`; **nada abre ou fecha por relógio**, mesmo corte das
isoladas), `draw_seed` (`BigIntegerField`, null), `published_preliminary_at`,
`published_final_at`. Unique `(program, year)` → `duplicate_edition`.

Transições nomeadas, todas manuais e todas para frente:
`open_submissions()` (**congela o barema**) → `start_review()` →
`publish_preliminary()` → `open_appeals()` → `publish_final()`. Cada uma exige
o estado anterior e levanta `InvalidStateTransition`. Guardas de leitura:
`bareme_editable()`, `submission_open()`, `committee_can_review()` (verdadeiro
em `under_review` **e** em `appeals_under_review` — é o deferimento reabrindo o
lançamento), `appeal_open()`, `results_visible_to_student()` (a partir de
`preliminary_result`).

`classify(level) -> list[BandResult]` é **método deste model** e é o coração do
módulo (detalhe na seção 2). Fica aqui e não num módulo `classification.py`
porque é regra de domínio da edição, não camada nova (ADR-002).

**`CommitteeMember`** — composição da comissão naquele ano. `edition`
(CASCADE), `teacher` (PROTECT), `appointed_on`, `ordinance` (portaria, blank).
Unique `(edition, teacher)`.

> **Docstring obrigatória, em caixa alta no arquivo**: este model é
> **registro histórico, não autorização**. Quem pode avaliar é quem está no
> Group "Comissão de Bolsas" — `require_perm`, como em todo o resto do projeto.
> Nenhuma rota consulta `CommitteeMember` para decidir acesso. Sem esse aviso o
> model vira um RBAC paralelo, que a Seção 2 do CLAUDE.md proíbe.

**`BaremeItem`** — `edition` (CASCADE), `level`, `section`, `code` ("1.3"),
`text`, `unit`, `points_per_unit` `Decimal(6,2)`, `cap` `Decimal(7,2)`.
Unique `(edition, level, code)` → `duplicate_bareme_item`.
`raw_score(quantity) -> Decimal` = `quantity * points_per_unit`.
`apply_cap(total) -> Decimal` = `min(total, cap)`.

> A separação das duas é o ponto sutil do barema: **o teto é do item, aplicado
> sobre a soma dos lançamentos**, não sobre cada lançamento. Confirmado nos
> dados (Q5 e a tela de análise do legado): dois lançamentos de 3,00 no item
> 1.8 somam 6,00 contra um limite de 18,00. Escrever o teto dentro de
> `raw_score` daria a mesma resposta nos casos fáceis e a errada exatamente no
> caso que importa.

**`ScholarshipApplication`** — a inscrição. `program`, `edition`, `student`
(PROTECT), `level` (copiado do `Student` no ato — congela), `submitted_at`.

*Questionário, fixo em código* (B7) — oito `BooleanField`:
`has_paid_activity` (a **chave**: joga do bloco 2.1 para o 2.4),
`affirmative_action`, `socioeconomic_vulnerability`, `substitute_teacher`,
`basic_education_or_collective_health`, `public_service`, `private_service`,
`other_non_public_scholarship`.

*Dados que a atividade remunerada carrega*: `monthly_income` `Decimal(10,2)`
null, `weekly_hours` `PositiveSmallIntegerField` null — **obrigatórios quando
`has_paid_activity`** (`clean()` → `income_required`), porque são eles que
ordenam as faixas 2.4-V e 2.4-VI/VII/VIII.

*Lançado pela Secretaria*: `fump_level` (`0`/`1`/`2`, default 0) — a FUMP manda
o resultado direto à Comissão, fora do sistema (Q9). Guardado também porque é o
**1º critério de desempate**.

*Sobrescrita de faixa* (B6): `band_override` (`PriorityBand`, null) +
`band_override_reason` (text, blank). `clean()` exige a justificativa quando há
override → `override_reason_required`.

*Snapshot da publicação* (B10): `published_band`, `published_score`
`Decimal(7,2)`, `published_position` (int), `draw_order` (int, null — a posição
sorteada), `published_at`. Todos null até a publicação.

Métodos derivados: `committee_score()` (soma por item, teto por item),
`candidate_score()` (idem, com as notas do candidato — é a coluna "Candidato"
do cabeçalho da tela de análise), `final_score()` = `committee_score()` +
`BONUS_FUMP`, `band()` (override, se houver; senão o derivado do
questionário), `subtotal(section)` (para o desempate III/IV),
`fully_reviewed()` (**derivado**: nenhum lançamento com `committee_score`
nulo — é o "Todos itens analisados" do legado, e não um botão), `pending_docs()`
(resposta "Sim" sem documento — o `Sim - Não enviado` do export).
`ensure_editable()` → só na janela aberta e só pelo próprio aluno.

Unique `(edition, student)` → `duplicate_application`.

**`BaremeEntry`** — o lançamento. `application` (CASCADE), `item` (PROTECT),
`description` (text), `quantity` `Decimal(6,2)`, `candidate_score`
`Decimal(7,2)` (gravado = `item.raw_score(quantity)`), `committee_score`
`Decimal(7,2)` **null = não avaliado**, `committee_note` (text, blank),
`reviewed_at`. `proof = FileField(upload_to=caminho_do_comprovante)` — **não
nulo, não blank**: sem comprovante o lançamento não existe (Q11), e a comissão
nunca recebe item vazio para zerar.

`clean()`: (a) `item.edition_id == application.edition_id` e
`item.level == application.level` → `bareme_item_mismatch`; (b) `quantity > 0`;
(c) **`committee_note` obrigatória quando `committee_score != candidate_score`**
→ `note_required`. Classe: `validate_upload(filename, size)` — cópia do
contrato de `RequestDocument.validate_upload` (`apps/academic/models.py:1723`),
mas **só PDF** e 10 MB (comprovante de barema é certificado, não foto).

`caminho_do_comprovante(instance, filename)` — função de módulo (a migração
precisa serializar a referência), particionando
`bolsas/edicao-{edition_id}/inscricao-{application_id}/{filename}`.

`Meta.permissions`: `("review_baremeentry", "Pode avaliar lançamento do barema")`
— avaliar não é `change`: o aluno tem `change` sobre a própria inscrição e não
pode encostar na nota da comissão.

**`ItemReview`** — a observação **por item do barema**, que o legado tem além da
observação por lançamento. `application` (CASCADE), `item` (PROTECT), `note`
(text). Unique `(application, item)`.

**`ApplicationDocument`** — o comprovante de cada resposta "Sim" do
questionário. `application` (CASCADE), `kind` (7 tipos), `file`. Unique
`(application, kind)` — reenviar substitui, não empilha. Espelha
`RequestDocument` inclusive na permissão própria
`("download_applicationdocument", ...)`: baixar é mais do que ver a inscrição.

**`ScholarshipAppeal`** — `application` (`OneToOneField`, CASCADE — um por
candidato por edição, Q14), `text` (do candidato), `submitted_at`, `outcome`
(null enquanto não julgado), `reasoning` (text, blank), `decided_at`.
**Sem documento novo** — o item 1.3 do edital veta postagem fora do prazo, ao
contrário do recurso das isoladas; a ausência de model de anexo aqui é
deliberada e vai comentada. `judge(outcome, reasoning)` exige
`appeals_under_review` e `reasoning` não vazia.

---

## 2. O algoritmo — `ScholarshipEdition.classify(level)`

É o núcleo do módulo e o item que mais pede olho humano no merge
(CLAUDE.md, "regra de classificação e contagem de vaga" → `review_required`).

1. **Nota da comissão** — para cada item do barema, soma os `committee_score`
   dos lançamentos daquele item e aplica `item.apply_cap()`; a nota é a soma
   dos itens já limitados. Lançamento não avaliado conta **zero** (e o
   `fully_reviewed()` da inscrição avisa que a lista ainda não está madura).
2. **Nota final** = nota da comissão + `BONUS_FUMP[fump_level]`. É esta que sai
   na coluna "Nota do Barema" do documento publicado (Q9).
3. **Faixa**: `band_override` quando existe; senão —
   `has_paid_activity == False` → `2.1-I` se (ação afirmativa **ou**
   vulnerabilidade), senão `2.1-II`; `has_paid_activity == True` → **primeiro
   inciso aplicável** na ordem `substitute_teacher` (2.4-III) →
   `basic_education_or_collective_health` (2.4-IV) → `public_service` (2.4-V) →
   `private_service` (2.4-VI/VII/VIII) → `other_non_public_scholarship` (2.4-IX);
   nenhum se aplicando → `residual`. **2.4-I e 2.4-II só por override** (B6).
4. **Ordenação dentro da faixa**, por `ORDENACAO_DA_FAIXA`: nota decrescente na
   maioria; `2.4-V` por **menor rendimento** com a nota desempatando;
   `2.4-VI/VII/VIII` por menor rendimento → **menor carga horária** → nota.
5. **Desempate geral** (item 3.3), só onde o critério da faixa não resolveu:
   I menor `fump_level` (0 = sem nível é o **pior**, não o melhor — cuidado com
   a inversão) → II CadÚnico → III maior subtotal em Formação Acadêmica → IV
   maior subtotal em Produção Bibliográfica → V **sorteio**.
6. **Sorteio** (B5): `random.Random(f"{edition.pk}:{draw_seed}")` embaralha os
   ainda empatados e grava `draw_order`. A semente é gerada uma vez, na
   primeira publicação, e **nunca regerada** — republicar tem de dar a mesma
   lista. Vai no `AuditLog` da publicação.
7. Saída: as **10 faixas na ordem canônica, todas presentes mesmo vazias**
   (Q8), cada uma com título, o rótulo "Ordem de prioridade: N" derivado da
   posição, a regra de ordenação escrita, e as linhas com Nome, Nota,
   Classificação — mais **Remuneração** em 2.4-V e 2.4-VI/VII/VIII.
   Uma chamada por nível: mestrado e doutorado correm independentes.

> **CadÚnico** aparece no critério II do desempate mas não tem campo no
> questionário da spec. Entra como `cadastro_unico` (`BooleanField`) na
> inscrição, junto do bloco de vulnerabilidade — sem ele o critério II é letra
> morta. Marcar como assunção a confirmar no merge.

Testes obrigatórios (`test_bolsas_classificacao.py`): reproduzir os volumes de
2026 registrados na spec (mestrado 6+18+4+0+2+6+0+8 = 44; doutorado
5+17+2+0+4+3+0+2 = 33) e o caso que prova a regra da faixa VI/VII/VIII — nota
59,20 em 1º e 73,29 em 5º, porque ali a nota **não** ordena.

---

## 3. Publicação e PDF

`services.py` (só o que cruza mais de um model, ADR-002):

- `publish_preliminary(edition, request)` — gera `draw_seed` se ainda não
  houver, roda `classify()` nos dois níveis, grava o snapshot em cada
  inscrição, transiciona a edição e escreve **um** `AuditLog` com as contagens
  no payload (mesmo desenho de `close_isolated_cycle`,
  `apps/academic/services.py:379`: o ato é "publiquei o preliminar", não N
  eventos soltos).
- `publish_final(edition, request)` — idem, a partir de
  `appeals_under_review`.
- `clone_bareme(origem, destino, request)` — copia os `BaremeItem` de uma
  edição para outra (só com o destino em `draft`) + `AuditLog`.

`apps/scholarships/pdf.py` (B2) — ReportLab, um documento por nível, as 10
seções na ordem canônica, colunas variando por faixa. Função pura
`montar_resultado(edition, level, kind) -> bytes`; a rota só devolve o
`FileResponse`. **ADR novo** em `docs/adr/`, com o mesmo conteúdo do ADR de PDF
que o plano do processo seletivo propõe (ReportLab por ser puro Python, sem
dependência de sistema) — se aquele plano entrar antes, este vira uma
referência de meia página em vez de decisão nova. Numeração a acertar no
merge: a base está em 007.

`reportlab` entra em `backend/pyproject.toml` (`dependencies`).

---

## 4. Borda — `router.py`, `schemas.py`, registro em `api.py`

Prefixo `/api/v1/scholarships/`. Registro em `backend/api.py` (uma linha de
import + um `add_router`) e em `INSTALLED_APPS`
(`backend/config/settings/base.py`, depois de `apps.academic`, de que depende
por `Student` e `Teacher`).

Toda rota abre com `require_perm(...)` e, logo depois, `current_program(request)`
— sem exceção, e **nenhuma rota pública** neste módulo (o aluno já está logado).

| Rota | Quem | Nota |
|---|---|---|
| `GET/POST/PATCH /editions/` , `POST /editions/{id}/{transicao}` | Secretaria | 5 transições nomeadas, uma rota cada |
| `GET/POST/PATCH/DELETE /editions/{id}/bareme/` , `POST /editions/{id}/bareme/clone` | Secretaria | escrita só com a edição em `draft` |
| `GET/POST/DELETE /editions/{id}/committee/` | Secretaria | composição do ano |
| `GET /editions/{id}/my-application` , `POST /applications/` , `PATCH`, `DELETE` | Discente | um por aluno por edição |
| `POST /applications/{id}/documents` , `GET /documents/{id}/download` | Discente / Comissão+Secretaria | download é permissão própria |
| `GET/POST/PATCH/DELETE /applications/{id}/entries/` | Discente | `POST` é multipart: o comprovante vem junto |
| `GET /editions/{id}/applications/` | Comissão, Secretaria, Coordenação | **a fila de trabalho**: filtros por nível (obrigatório), linha, orientador, ano de entrada, cada uma das 8 respostas, estado do recurso, e `pending_review=true` (o "somente candidatos com itens a analisar" do legado) |
| `PATCH /entries/{id}/review` | Comissão | **só `committee_score` e `committee_note`** — o schema de entrada não tem os outros campos, e é assim que "a comissão não mexe no que o aluno digitou" (Q10) vira código, não combinado |
| `PUT /applications/{id}/item-review` | Comissão | observação por item |
| `PATCH /applications/{id}/fump` , `PATCH /applications/{id}/band` | Secretaria | nível FUMP; override de faixa com justificativa |
| `POST /applications/{id}/appeal` , `PATCH /appeals/{id}/judge` | Discente / Comissão | sem anexo |
| `GET /editions/{id}/result?level=` | todos com `view` | JSON das 10 faixas — só a partir de `preliminary_result` para o Discente |
| `GET /editions/{id}/result.pdf?level=` | idem | ReportLab |

Schemas de saída explícitos, sempre (nunca serializar model direto). O
`BandOut` carrega `band`, `title`, `priority_label`, `ordering_rule` e as
linhas — o mesmo objeto alimenta a tela e o PDF.

---

## 5. Papéis — data migration `000X_papeis_da_bolsa.py`

Espelho de `apps/academic/migrations/0011_papeis_da_isolada.py`, inclusive na
docstring que explica quem faz o quê e por quê. Grupo novo: **"Comissão de
Bolsas"**. Nenhum grupo recebe `delete_*`, `is_staff` ou `is_superuser`.

- **Discente** — `add`/`view`/`change` da inscrição e do lançamento,
  `view` de edição e de item do barema, `add`/`view` do recurso.
- **Comissão de Bolsas** — `view` de inscrição, lançamento, edição e barema;
  `review_baremeentry`; `download_applicationdocument`;
  `change_scholarshipappeal` (o julgamento).
- **Secretaria** — `add`/`change`/`view` de edição, barema e `CommitteeMember`;
  `view` de inscrição e lançamento; `download_applicationdocument`;
  `publish_scholarshipedition` (permissão própria: publicar é o ato que congela
  o ano); `set_fump_level` e `override_band` como permissões próprias no
  `ScholarshipApplication` (a Secretaria mexe em dado da inscrição alheia sem
  ter `change` sobre ela).
- **Coordenação** — só `view`.

`seed_demo` (`apps/core/management/commands/seed_demo.py`) ganha uma edição de
bolsas **nos dois programas** que ele já semeia — é a única forma de o
vazamento de tenant aparecer em teste.

---

## 6. Frontend — `frontend/src/routes/(app)/bolsas/`

`svelte 5` com runas, toda chamada via `lib/api/client.ts`, `fetch` cru
proibido. Upload usa o `bodySerializer` multipart que já existe em
`client.ts:49`.

- `bolsas/edital/+page.svelte` — Secretaria: edição, cronograma, barema
  (com clonar da edição anterior), comissão, as 5 transições, publicar.
- `bolsas/inscricao/+page.svelte` — Discente: questionário (8 perguntas, com os
  campos de rendimento/CH aparecendo ao marcar atividade remunerada),
  documentos, e a lista de lançamentos agrupada por seção do barema.
- `bolsas/analise/+page.svelte` — Comissão: a fila com todos os filtros do
  legado + o toggle "somente com itens a analisar"; a tela de um candidato
  reproduz o legado — cabeçalho "Candidato: X — Comissão: Y", corpo agrupado
  por seção e por item (com o texto normativo do item como cabeçalho:
  `1.3 - ... - 0,50 pts/semestre - Limite: 3,00`), "Nota total" por item com o
  teto aplicado, e a observação da comissão em destaque sob o lançamento.
- `bolsas/resultado/+page.svelte` — as 10 faixas por nível + botão do PDF.
- `bolsas/recurso/+page.svelte` — Discente interpõe; o julgamento entra pela
  tela de análise.

Menu em `(app)/+layout.svelte`, por permissão e não por papel — mesmo critério
já comentado ali (`:121`). `make gen-api` regenera `openapi.json` e
`schema.d.ts` (gerados; PR que os edita à mão é recusado).

---

## 7. Testes — `backend/apps/scholarships/tests/`

Pirâmide da Seção 9: invariante no model sem banco; fluxo pela API real.

`test_bolsas_edital.py` (transições e o congelamento do barema) ·
`test_bolsas_barema.py` (aritmética: 1 sem × 0,50 = 0,50; 12 meses × 0,25 =
3,00 batendo exatamente no teto; 3 h × 0,01 = 0,03; e o teto por item sobre a
soma) · `test_bolsas_inscricao.py` · `test_bolsas_documentos.py` (obrigatório
para salvar, substituição, download só com permissão) · `test_bolsas_analise.py`
(comissão não altera quantidade; observação obrigatória na divergência) ·
**`test_bolsas_classificacao.py`** (faixas, ordenação por faixa, os 5
desempates, sorteio reprodutível, os volumes de 2026) · `test_bolsas_recurso.py`
(deferimento reabre lançamento e a nota é recalculada) · `test_bolsas_papeis.py`
· `test_bolsas_tenant.py` (a lista de um programa nunca traz inscrição do
outro) · `test_bolsas_pdf.py` (as 10 seções saem mesmo vazias).

Verificação de ponta a ponta: `make ready` verde (lint + typecheck + test), e
`make up` + `make seed` para abrir http://localhost:8080 e percorrer inscrição →
análise → publicação → PDF com o usuário semeado de cada papel.

---

## 8. Ordem de execução (o cronograma sai daqui)

1. App + settings + `api.py` + enums e constantes (fatia vazia que compila).
2. `ScholarshipEdition` + `CommitteeMember` + **a migration** — cedo de
   propósito, para que o resto seja construído sobre o schema definitivo.
3. `BaremeItem` + clonagem + congelamento.
4. `ScholarshipApplication` + questionário + documentos.
5. `BaremeEntry` + comprovante + as duas notas.
6. Análise da comissão (`review`, `ItemReview`, a fila com filtros).
7. FUMP + override de faixa.
8. **`classify()`** — a fatia que mais pede revisão.
9. Recurso e o recálculo.
10. Publicação (snapshot + sorteio) e o PDF + ADR.
11. Telas Svelte, na mesma ordem.

## 9. Gates — o que o `prd.json` marca

**`human_gate: true`: nenhuma story.** Sem e-mail (B3), sem integração e sem
serviço externo, nada aqui escapa do canteiro: PDF é gerado e baixado, anexo
vai para `backend/media/`, tudo o mais é o banco do próprio Compose. Um
`desmontar-canteiro.sh --volumes` e um `git revert` desfazem o módulo inteiro.

**`review_required: true`**: a migration (passo 2); todo o passo 8 (faixa,
ordenação, os 5 desempates, sorteio); o passo 7 (override de faixa é decisão
sobre a vida acadêmica); a data migration de papéis e qualquer coisa que toque
`require_perm`/`current_program`; o contrato de API (`router.py`, `schemas.py`,
`openapi.json`, `schema.d.ts`); o ADR do PDF; e a entrada de `reportlab` no
`pyproject.toml`.

## 10. Antes de montar o canteiro — o choque com `processo-seletivo`

`plans/processo-seletivo.md` está pendente e com branch viva
(`origin/helton/processo-seletivo`), e **não existe
`plans/manifest.json`**. Os dois planos disputam:

| Arquivo | Choque |
|---|---|
| `backend/api.py` , `config/settings/base.py` | uma linha cada; conflito trivial de merge |
| `backend/pyproject.toml` | **ambos adicionam `reportlab`** |
| `docs/adr/` | ambos numeram a partir de 008 |
| `frontend/.../openapi.json` , `schema.d.ts` | gerados; regerar depois do merge resolve |
| `(app)/+layout.svelte` | um item de menu cada |

**Migrations não colidem**: bolsas nasce inteiro em `apps/scholarships/` e
**não cria migration em app existente** (B1) — é o motivo de o
"Conflicting migrations detected" não se aplicar aqui.

Ainda assim, a regra do CLAUDE.md é explícita: sem manifesto, não se montam
dois canteiros que mexam em schema. O caminho é `/compatibilizar` antes de
`montar-canteiro.sh bolsas`.
