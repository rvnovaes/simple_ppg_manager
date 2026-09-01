# Plano — Processo Seletivo (mestrado e doutorado)

> Destino após aprovação: `scripts/helton/projects/plans/processo-seletivo.md`
> (→ worktree `../simple_ppg_manager-processo-seletivo`, branch
> `helton/processo-seletivo`). Origem: `specs/processo-seletivo.md` (grill de
> 20/08/2026) + `specs/bancas-projeto-coletivo.md` (12/08/2026), **absorvida
> aqui** — ao arquivar este plano, mover as duas specs para `specs/implemented/`.

## Contexto

Hoje o processo seletivo do PPGD acontece fora do sistema: edital no WordPress,
inscrição por formulário externo, bancas produzem um PDF assinado por etapa e
**a secretaria transcreve as notas à mão**. O módulo existe para **inverter o
fluxo**: a banca lança notas no sistema, o sistema gera a ata, os membros
assinam eletronicamente, a ata assinada fecha a etapa e promove quem passou;
no fim a secretaria converte o aprovado em `Student` sem recadastro.

Nada disso existe no código (`Board`, `SelectionProcess`, `Application`: zero
ocorrências). A spec de bancas nunca virou plano; entra aqui com a chave
trocada (FK para o edital em vez de `selection_year` inteiro).

## Decisões fechadas nesta sessão (não reabrir)

| # | Decisão | Consequência |
|---|---|---|
| P1 | **Um plano só**, app Django novo `backend/apps/selection/` | Nada de processo seletivo em `academic`; `Board` nasce em `selection` |
| P2 | `Board` → FK `process` (edital), não ano inteiro | Spec de bancas absorvida; F8 (banca do Suplementar) coberta |
| P3 | **Membro externo existe**: `Teacher.Category.EXTERNAL`, assina por **link com token** por e-mail | Segunda superfície pública; migration em `academic` (AlterField de choices) |
| P4 | **Suplementar chaveia por linha de pesquisa; Regular por projeto coletivo** | Vaga, banca, inscrição e ata carregam `project`/`research_line` nuláveis com XOR |
| P5 | PDF da ata com **ReportLab** (ADR-008) | Puro Python, sem libs de sistema; layout em `apps/selection/pdf.py` |
| P6 | E-mail via `django.core.mail`, sem fila/agendador (ADR-009) | Dois e-mails: convocação de etapa (lote, template do edital) e link de assinatura do externo (unitário) |
| P7 | Candidato **sem login**; inscrição = **um POST multipart** público com todos os anexos; devolve protocolo | `Application` guarda dados próprios; `Person`+`Student` só na conversão |
| P8 | Nota `DecimalField(5,2)`, corte `70.00`, final = última etapa | Desempate por `SelectionStage.tiebreak_rank` + `birth_date` |
| P9 | Recursos → fase 2; ata **versionável desde já** (`version`, `supersedes`) | `rectify_record` nasce como service, sem rota/tela |

### Assunções (marcar em docstring/seed; o humano confirma no merge)
- Desempate do **Suplementar**: memorial → prova oral → mais velho (espelho do Regular).
- Realocação de vaga **preserva a categoria de cota** (`from.quota_category == to.quota_category`).
- **Aprovado nos dois editais**: o sistema não força escolha; a secretaria converte um e a outra inscrição fica `approved` sem `student`.
- Protocolo: `PS{year}{R|S}-{8 hex maiúsculos}` (não sequencial).
- Ofício de 5 nomes ao DRCA e documentos de divulgação: **fora do sistema**.
- Sorteio do ponto da prova oral: presencial, fora do sistema.

---

## 1. Modelo de dados — `backend/apps/selection/models.py`

Convenções para todos os models (não repetir por model): FK `program` direta
com `PROTECT` (ADR-007) exceto filhos de agregado (`SelectionStage`,
`ApplicationDocument`, `ConvocationEmail`, `RecordSignature`) que chegam ao
programa pelo pai; `created_at`/`updated_at`; QuerySet com `for_program()`;
`clean()` levanta `DomainError(code=...)` cobrindo `program_mismatch` e a
duplicata de cada `UniqueConstraint` (padrão de `AcademicTerm.clean()`);
transições **não salvam**; `InvalidStateTransition` = 409. **Todos os
`TextChoices` no nível do módulo com nome único** (precedente:
`AdjustmentStatus` em `apps/academic/models.py:533`) — enum aninhado colide no
OpenAPI.

### Enums de módulo
`SelectionKind` (regular/supplementary) · `SelectionProcessStatus`
(draft/published/closed) · `SelectionLevel` (masters/doctorate — mesmos valores
de `Student.Level`) · `QuotaCategory` (open/racial/disability/quilombola/trans/
indigenous) · `ApplicationStatus` (submitted/homologated/rejected/eliminated/
approved/enrolled) · `RankingOutcome` (classified_open/classified_quota/
not_classified) · `ApplicationDocumentKind` (identity/diploma/lattes/
expanded_abstract/memorial/payment_receipt/quota_proof) · `RecordStatus`
(draft/awaiting_signatures/signed/superseded) · `SignatureMethod` (login/token)
· `ReallocationKind` (level_transfer/notice_rectification) ·
`EmailDeliveryStatus` (pending/sent/failed).

Constantes: `CATEGORIAS_POR_TIPO = {REGULAR: {OPEN, RACIAL}, SUPPLEMENTARY:
{DISABILITY, QUILOMBOLA, TRANS, INDIGENOUS}}`, `NOTA_DE_CORTE = Decimal("70.00")`,
`NOTA_MAXIMA = Decimal("100.00")`.

### Alvo (projeto × linha) — padrão repetido em Vacancy, Board, Application, ExaminationRecord
```python
project = FK("programs.CollectiveProject", PROTECT, null=True, related_name="selection_<x>")
research_line = FK("programs.ResearchLine", PROTECT, null=True, related_name="selection_<x>")
# constraints:
CheckConstraint(condition=Q(project__isnull=False, research_line__isnull=True)
                        | Q(project__isnull=True, research_line__isnull=False),
                name="<model>_exactly_one_target")
UniqueConstraint(fields=[..., "project", "research_line", ...], nulls_distinct=False, name=...)
```
Helper de módulo `xor_de_alvo(nome) -> CheckConstraint` (sem mixin/abstract).
A amarração ao tipo do edital não cabe em CheckConstraint (está em outra
tabela): é `SelectionProcess.ensure_target(project, research_line)` →
`target_mismatch`, chamada no `clean()` dos quatro.

### Models

**`SelectionProcess`** (edital): `program`, `kind`, `year` ("ano do processo
seletivo" — PS2027 = 2027), `title`, `status`, `submission_opens_at`,
`submission_closes_at`, `notice_file` (`FileField(upload_to=caminho_do_edital,
blank=True)`), `convocation_subject`, `convocation_body` (placeholders `{nome}
{protocolo} {etapa} {data_hora} {local} {edital}`), `published_at`, `closed_at`.
Unique `(program, kind, year)` → `duplicate_process`. QuerySet: `published()`,
`open_for_submission(at)`. Métodos: `clean()` (`invalid_submission_window`),
`allowed_quota_categories()`, `ensure_quota_category(cat)` →
`quota_category_not_allowed`, `ensure_target(...)`, `submission_open(at)`,
`ensure_editable()` → `process_not_editable` (vaga/etapa/janela só em `draft`),
`publish()` (`process_not_draft`), `close()` (`process_not_published`),
`render_convocation(application, stage) -> (subject, body)` via `format_map`
com mapping tolerante (placeholder desconhecido fica literal).

**`SelectionStage`**: `process` (CASCADE, `stages`), `name`, `order`,
`session_at`, `location`, `tiebreak_rank` (null = não entra no desempate).
Unique `(process, order)`, `(process, name)`, `(process, tiebreak_rank)`
condicional. Métodos: `is_first`, `is_last`, `previous()`, `clean()` →
`invalid_stage_order`, `duplicate_stage`. Dado, não código: Regular = resumo
expandido (tb 1) → prova oral (tb 2) → entrevista; Suplementar = memorial (tb 1)
→ prova oral (tb 2) → análise do projeto e memorial.

**`Vacancy`**: `program`, `process` (PROTECT, `vacancies`), `level`, alvo XOR,
`quota_category`, `quantity` (0 permitido — linha zerada por realocação é
histórico). Unique `(process, level, project, research_line, quota_category)`
`nulls_distinct=False` → `duplicate_vacancy`. `target_key() -> (level,
project_id, research_line_id)`.

**`Board`**: `program`, `process` (PROTECT, `boards`), `level`, alvo XOR,
`president`, `member_1`, `member_2`, `alternate` (FK `academic.Teacher`,
PROTECT, `related_name="selection_boards_as_<papel>"`). Unique `(process,
level, project, research_line)` `nulls_distinct=False` → `duplicate_board`.
QuerySet: `for_process`, `with_teacher(teacher)` (o `Q()` de 4 ramos, uma vez).
Métodos: `clean()` → `duplicate_board_member`, `teacher_from_other_program`,
`teacher_not_accredited`; `titular_members()`, `is_member(teacher)`,
`expected_signers(replaced_member=None)` (3 titulares, ou titulares − impedido
+ suplente; `not_a_titular_member`).

**`Application`**: `program`, `process` (PROTECT, `applications`), `protocol`
(unique), `full_name`, `email`, `cpf` (11 dígitos), `birth_date`,
`phone_number`, `level`, alvo XOR, `quota_category`, `status`, `decision_note`,
`decided_at`, `eliminated_at_stage` (FK `SelectionStage`, null),
`final_score` (Decimal null), `final_rank`, `final_outcome`, `ranked_at`,
`student` (`OneToOneField("academic.Student", PROTECT, null=True,
related_name="selection_application")`), `submitted_at`. Unique `(process,
cpf)` → `duplicate_application` (mesma pessoa nos dois editais é permitida).
Checks: `final_score` 0–100 ou null; `eliminated ⇒ eliminated_at_stage`;
`enrolled ⇒ student`. QuerySet: `for_process`, `alive()` (= homologated),
`for_target(level, project, research_line)`, `approved()`,
`convocable_for(stage)`. Métodos: `clean()` (`invalid_cpf` mod-11,
`invalid_birth_date`), `required_document_kinds()` (identity, diploma, lattes,
payment_receipt + expanded_abstract|memorial por kind + quota_proof se cota),
`missing_documents()`, `homologate(note="")`, `reject(note)` →
`rejection_requires_note`, `eliminate(stage)`, `approve(score)`, `reinstate()`
(fase 2, só via retificação), `enroll(student)` → `not_classified`,
`_exigir_status()`.

**`ApplicationDocument`**: `application` (CASCADE, `documents`), `kind`, `file`
(`upload_to` → `selecao/edital-{process_id}/inscricao-{application_id}/{filename}`),
`uploaded_at`. Unique `(application, kind)`. `validate_upload(filename, size)`
importando `EXTENSOES_DE_DOCUMENTO` e `TAMANHO_MAXIMO_DO_DOCUMENTO` de
`apps.academic.models` (uma fonte). Permissão custom `download_applicationdocument`.

**`StageScore`** (nota — rascunho até a ata assinar): `program`, `application`
(PROTECT, `scores`), `stage` (PROTECT, `scores`), `score` (Decimal null),
`absent` (bool), `entered_by` (FK Teacher null), `entered_at`. Unique
`(application, stage)`; Check `absent XOR score`; Check range 0–100.
Semântica: linha com score = avaliado; `absent=True` = faltou (elimina); **sem
linha** = não avaliado porque eliminado antes/etapa não chegou. `passed`
property. `clean()` → `stage_mismatch`.

**`ExaminationRecord`** (ata, versionável): `program`, `process`, `stage`,
`level`, alvo XOR, `board` (PROTECT, `records`), `replaced_member` (FK Teacher
null — titular impedido), `version` (default 1), `supersedes`
(`OneToOneField("self", PROTECT, null)`), `rectification_reason`, `status`,
`content` (JSON: lista de `{application_id, protocol, full_name,
quota_category, score: "85.50"|null, absent, passed}` ordenada por nome),
`content_hash` (sha256 do `json.dumps(sort_keys, separators=(",",":"),
ensure_ascii=False)` + cabeçalho com ids/version), `pdf` (`FileField` →
`selecao/edital-{process_id}/atas/ata-{id}-v{version}.pdf`), `frozen_at`,
`signed_at`. Unique `(process, stage, level, project, research_line, version)`
`nulls_distinct=False`; Check `version=1 ⇔ supersedes IS NULL`. Invariante "uma
ata corrente (não superseded) por chave" no `clean()` → `record_already_exists`.
Métodos: `freeze(content, at)` (`record_not_draft`, `no_candidates`),
`reopen()`, `mark_signed(at)`, `supersede()`, `is_current`,
`expected_signers()`, `compute_hash()`, `verify_hash()`.

**`RecordSignature`**: `record` (PROTECT, `signatures`), `signer` (FK Teacher),
`method` (token se `signer.category == EXTERNAL`), `signed_at` (null =
pendente), `signed_hash`, `signed_by_user` (SET_NULL), `ip_address`,
`token_hash`, `token_expires_at`, `token_sent_at`, `token_used_at`. Unique
`(record, signer)`; Check `method="token" OR token_hash=""`. Métodos:
`sign(at, content_hash, user=None, ip=None)` → `already_signed`,
`record_changed`; `issue_token(at, ttl=7d) -> str` (`secrets.token_urlsafe(32)`,
grava só o sha256, devolve o texto uma vez; `token_not_applicable`);
`consume_token(at)` → `token_expired`, `token_already_used`;
`ensure_can_sign_by_login(user)` → `NotAllowed`. QuerySet: `pending()`,
`by_token(raw)`.

**`VacancyReallocation`** (decisão da comissão / retificação): `program`,
`process`, `kind`, `from_vacancy`, `to_vacancy` (PROTECT,
`reallocations_out/_in`), `quantity`, `reason`, `decided_on` (DateField),
`decided_by_note` (nº do ofício/ata da comissão). Imutável. `clean()` →
`process_mismatch`, `same_target_required` (level_transfer: mesmo alvo, níveis
diferentes), `same_level_required` (rectification), `insufficient_vacancies`,
`process_still_draft`, categoria preservada.

**`Convocation`**: `program`, `process`, `stage`, `subject`, `body_template`
(cópias no instante do envio), `sent_by`, `created_at`.
**`ConvocationEmail`**: `convocation` (CASCADE, `emails`), `application`,
`to_email`, `rendered_subject`, `rendered_body`, `status`, `error`, `attempts`,
`sent_at`. Unique `(convocation, application)`. `mark_sent`, `mark_failed`.

### Alteração fora do app
`apps/academic/models.py`: `Teacher.Category.EXTERNAL = "external", "Externo
(banca)"` + ramo em `Teacher.clean()` exigindo `home_institution`
(`home_institution_required`). Docstring do enum avisa que a categoria não é
CAPES. Migration `academic/migrations/0012_categoria_externa.py`.

### Papéis (data migration `selection/migrations/000N_papeis_da_selecao.py`, no molde de `academic/0011`)
- **Comissão de Seleção** (grupo novo): `add/view_vacancyreallocation`, `view_*` do app.
- **Secretaria**: `add/change/view` de process, stage, vacancy, board;
  `change/view_application`; `download_applicationdocument`; `add/view_convocation`;
  `view_*`. Também `academic.add_teacher` já tem (cadastra o externo).
- **Docente**: `view_selectionprocess/board/application/examinationrecord`,
  `add/change/view_stagescore`, `add/change/view_examinationrecord`, custom
  `sign_examinationrecord`. O recorte real é `Board.is_member(teacher)`
  checado na rota (`NotAllowed`), nunca a permissão sozinha.
- **Coordenação**: `view_*`. Ninguém recebe `delete_*`.

---

## 2. Máquinas de estado

### `Application`
| De → Para | Quem | Guarda |
|---|---|---|
| ∅ → submitted | público (`submit_application`) | edital published ∧ janela (`submission_window_closed`); alvo/cota compatíveis; existe `Vacancy` com `quantity>0` (`no_vacancy_for_choice`); CPF inédito no edital; todos os documentos exigidos no mesmo POST (`missing_documents`); `validate_upload` em cada; rate limit |
| submitted → homologated / rejected | Secretaria (router, model só) | `reject` exige nota |
| homologated → eliminated | sistema, em `_close_stage` | `StageScore` com `absent` ou `< 70`; `eliminated_at_stage` |
| homologated → homologated (promovido) | sistema | `≥ 70` em etapa não-final: status não muda; promoção deriva da ata assinada |
| homologated → approved | sistema | última etapa ∧ `≥ 70`; `final_score` carimbado |
| approved (+ rank) | `compute_ranking` | idempotente até existir `enrolled` no (nível × alvo) (`ranking_locked`) |
| approved → enrolled | Secretaria (`convert_to_student`) | `final_outcome ∈ classified_*`; `registration_number` obrigatório |
| eliminated → homologated | fase 2 (`reinstate`, só por ata `version>1`) | método existe, sem rota |

**Nota é rascunho** enquanto a ata corrente da (etapa × nível × alvo) não
existe ou está `draft`; em `awaiting_signatures`/`signed` a nota é só leitura
(`record_frozen`, 409).

### `ExaminationRecord`
| De → Para | Quem | Guarda |
|---|---|---|
| ∅ → draft | presidente/titular (`generate_record`) | edital published; Board existe; sem ata corrente na chave (`record_already_exists`); etapa `k>1` exige ata de `k-1` signed (`previous_stage_open`); `content` vem das notas vivas; `refresh_record` regera enquanto draft |
| draft → awaiting_signatures | **presidente** (`freeze_record(replaced_member)`) | toda inscrição viva do alvo tem `StageScore` (`scores_incomplete`, payload lista protocolos); hash; cria 3 `RecordSignature` por `expected_signers`; token + e-mail para externo via `transaction.on_commit` |
| awaiting → draft | presidente (`reopen_record`) | zero assinaturas (`record_has_signatures`); apaga pendentes — único `delete` do app |
| awaiting → signed | sistema, na 3ª assinatura (`sign_record` / `sign_record_with_token`) | cada assinatura confere `content_hash`; `select_for_update` na ata antes de contar; ao completar: `mark_signed`, aplica desfechos, gera PDF — tudo num `atomic` (`selection.stage.close`) |
| signed → superseded | sistema, quando versão `n+1` fica signed | re-sincroniza desfechos só de quem mudou `passed` |

---

## 3. Classificação — funções puras em `services.py`
Dataclasses congeladas `RankingCandidate(application_id, quota_category,
final_score, tiebreak_scores: tuple, birth_date)` e `RankingResult(application_id,
rank, outcome, tie_unresolved)`. Funções sem ORM, testadas em
`tests/test_ranking.py` **sem `django_db`**:

- `sort_key(c)` = `(-final_score, -tb1, -tb2, ..., birth_date)`; empate total →
  ordem por `application_id` e `tie_unresolved=True`.
- `rank_regular(candidates, *, open_seats, racial_seats)`: (1) ordena todos, os
  `open_seats` primeiros → `classified_open` (qualquer categoria); (2) dos
  restantes, `racial` em ordem até `racial_seats` → `classified_quota`; (3)
  reserva ociosa → próximos da ordem geral viram `classified_open`; (4) resto
  `not_classified`. `rank` = posição na ordem geral.
- `rank_supplementary(candidates, *, seats_by_category)`: por categoria, ordena
  só os dela; `seats` primeiros → `classified_quota`; sobra fica vazia; `open`
  na entrada é `ValueError` (bug do chamador).
- Entrada: só `approved`; vagas = `Vacancy.quantity` já líquido de realocações.
- Testes mínimos: cotista classificado na ampla não consome reserva; reserva
  ociosa reverte sem ultrapassar o total; desempate por etapa 1, 2, idade;
  empate total; categoria sem candidato; `open_seats=0`.

---

## 4. Services — `apps/selection/services.py`
Todas `@transaction.atomic`, `request=None`, `clean()` antes de `save()`,
`audit.record(...)` (`apps/core/audit.py`).

| Função | Evento |
|---|---|
| `publish_process(*, process, request)` — exige ≥1 etapa, ≥1 vaga, template (`process_incomplete`) | `selection.process.publish` |
| `submit_application(*, process, dados, files: dict[kind, UploadedFile], request)` **público** — protocolo com retry em `IntegrityError` (5×); payload de auditoria **sem CPF** | `selection.application.submit` |
| `generate_record(...)`, `refresh_record(...)` | `selection.record.generate/refresh` |
| `freeze_record(*, record, replaced_member, request)` — token + e-mail no `on_commit`; falha de envio → `token_sent_at=None` + `selection.record.token_email_failed` | `selection.record.freeze`, `selection.record.token_issued` |
| `reopen_record(...)` | `selection.record.reopen` |
| `sign_record(*, record, user, ip, request)` / `sign_record_with_token(*, token, ip, request)` **público** → chama `_close_stage` na 3ª | `selection.record.sign` |
| `resend_signature_token(*, signature, request)` — invalida o anterior | `selection.record.token_reissued` |
| `_close_stage(record)` — signed + pdf + `eliminate/approve/reinstate` + `supersede` | `selection.stage.close` (promoted/eliminated/approved/version) |
| `rectify_record(*, record, reason, request)` — nova versão draft; libera edição das notas da chave | `selection.record.rectify` |
| `compute_ranking(*, process, level, project, research_line, request)` — exige ata da última etapa signed | `selection.ranking.compute` |
| `reallocate_vacancy(*, from_vacancy, to_vacancy, quantity, kind, reason, decided_on, note, request)` — `select_for_update` nas duas vagas; zera rank dos `approved` afetados | `selection.vacancy.reallocate` |
| `send_convocations(*, process, stage, request)` — bloco atômico cria lote `pending`; **fora** da transação envia um a um com `try/except (OSError, smtplib.SMTPException)` → `mark_sent/mark_failed`; nunca 500 | `selection.convocation.send` |
| `resend_convocation_emails(*, convocation, request)` | `selection.convocation.resend` |
| `convert_to_student(*, application, registration_number, admission_date, project, request)` — `Person` find-or-create por `(program, primary_email)`; `Student(modality=REGULAR, level, project, term?)` com `full_clean()` → `DomainError(invalid_student)` (como `enroll_isolated_request`); **`project` obrigatório** (no Suplementar a inscrição só tem linha — a secretaria escolhe o projeto dentro dela, `project_required`) | `selection.application.enroll` |

`apps/selection/pdf.py`: `render_record_pdf(record) -> bytes` (ReportLab
`SimpleDocTemplate` + `Table`; Helvetica; rodapé com `content_hash`, versão e
por assinatura nome/método/`signed_at`/12 hex do `signed_hash`).
`apps/selection/emails.py`: `enviar_convocacao(email: ConvocationEmail)`,
`enviar_token_de_assinatura(signature, token)` — montam `EmailMessage` com
`SITE_URL` do settings (nunca `build_absolute_uri`, que atrás do Nginx dá `backend:8000`).

---

## 5. API — `apps/selection/router.py` + `schemas.py`, prefixo `/api/v1/selection/`
Registrar em `backend/api.py` (`api.add_router("/selection/", router)`).
Padrão de toda rota autenticada: `require_perm` → `current_program` → model/
service → schema de saída explícito → `audit.record` no mesmo `atomic`
(operações de um model só ficam no router; multi-model vai ao service).

**Secretaria** — `processes/` (GET paginado, POST, GET id, PATCH, POST
`publish`, POST `close`, POST `notice-file` multipart); `processes/{id}/stages/`
(GET, POST, PATCH, DELETE só em draft); `processes/{id}/vacancies/` (GET,
POST, PATCH só em draft); `boards/` (GET com filtros `process_id`, `level`,
`project_id`, `research_line_id`, `teacher_id`; POST; GET id; PATCH com
`ensure_editable` → `board_in_use` se há ata não-draft); `applications/` (GET
paginado com filtros `process_id`, `status`, `level`, `quota_category`, alvo,
busca por nome/protocolo/CPF; GET id com documentos expandidos; POST
`homologate`, `reject`); `documents/{id}/download` (`download_applicationdocument`,
audita leitura, `FileResponse`); `processes/{id}/stages/{sid}/convocations`
(POST envia lote; GET lista lotes com contagem por status); `convocations/{id}/resend`
(POST); `records/` (GET listagem por processo, com status/assinaturas);
`records/{id}/pdf` (download); `records/{id}/signatures/{sid}/resend-token`
(POST); `processes/{id}/ranking` (POST calcula para um (nível × alvo); GET
resultado); `reallocations/` (GET, POST — permissão da Comissão);
`applications/{id}/enroll` (POST → `convert_to_student`).

**Banca (Docente)** — `boards/mine` (GET: bancas do `Teacher` da sessão via
`with_teacher`); `boards/{id}/stages/{sid}/scores` (GET candidatos vivos do
alvo com nota atual; PUT lote `[{application_id, score|absent}]`, 409
`record_frozen`); `boards/{id}/stages/{sid}/record` (GET ata corrente; POST
gera; POST `refresh`; POST `freeze` com `replaced_member_id` opcional — só
presidente; POST `reopen`; POST `sign` — login). Helper
`teacher_da_sessao(request, program)` → `NotAllowed("not_a_board_member")`.

**Público** (`auth=None`, comentário `# público` com justificativa, padrão de
`academic/router.py:1462`):
| Rota | Proteção |
|---|---|
| `GET public/processes` — editais abertos agora, com etapas, níveis, alvos, categorias com vaga>0, sigla do programa | `enforce_rate_limit("selection-public-read", 60, 60)`; sem dado pessoal |
| `POST public/applications` — multipart: campos `Form(...)` + `identity/diploma/lattes/payment_receipt: UploadedFile = File(...)`, `expanded_abstract/memorial/quota_proof: UploadedFile \| None = File(None)`; devolve `{protocol, submitted_at}` | `@decorate_view(csrf_protect)`; rate limit `selection-apply` 5/h; tenant = `process_id` validado por `open_for_submission(now)`; `validate_upload` antes de qualquer escrita |
| `GET public/applications/{protocol}` — `{status, submitted_at, process_title}` | rate limit 20/min; 404 genérico |
| `GET public/signatures/{token}` — cabeçalho + `content` + hash para conferência | lookup por sha256; pendente e não expirado; 404 genérico |
| `POST public/signatures/{token}/sign` | `csrf_protect`; rate limit 10/h; `consume_token` + `sign` na mesma transação |

Schemas: `Decimal` com `Field(max_digits=5, decimal_places=2, ge=0, le=100)`;
vira `string` no `schema.d.ts` (aceito). Após cada mudança de contrato: `make
gen-api` (backend de pé) — `openapi.json` e `schema.d.ts` são versionados.

---

## 6. Telas Svelte — `frontend/src/routes/`
Padrão: `professores/+page.svelte` (CRUD inline com runas, `api` de
`lib/api/client.ts`, `mensagemDeErro`, classes de `app.css`); upload com
`comoFormData`; menu em `(app)/+layout.svelte` com `{#if sessao.pode(...)}` e
ícones novos no mapa `FORMAS` de `lib/Icone.svelte` (`selecao`, `banca`, `ata`).
`/inscricao` já é da isolada — as rotas novas vivem sob `/selecao/`.

**Públicas** (fora de `(app)`, novo grupo `(publico)/selecao/...`, como
`(auth)/cadastro`): `inscricao/+page.svelte` (escolhe edital aberto → nível →
alvo → categoria; dados pessoais; um `<input type=file>` por documento exigido
conforme kind/cota; `garantirCsrf()` antes do POST; mostra protocolo e manda
guardar); `protocolo/+page.svelte` (consulta situação por protocolo);
`assinatura/[token]/+page.svelte` (mostra a ata, hash e botão "Assinar"; estados
assinado/expirado/inválido).

**Secretaria** `(app)/selecao/`: `editais/+page.svelte` (lista + form do
edital; sub-blocos de etapas e vagas — vagas em grade nível × alvo × categoria
para preencher rápido; upload do PDF; publicar/encerrar; template da
convocação); `bancas/+page.svelte` (listagem agrupada linha → projeto →
presidente/titular 1/titular 2/suplente, filtro por edital e nível; form numa
linha só com 4 `<select>` de docentes credenciados — inclui externos com
instituição; validação de UX de membro repetido); `inscricoes/+page.svelte`
(lista filtrável, detalhe com documentos para download, homologar/indeferir com
nota); `convocacoes/+page.svelte` (por edital × etapa: quem é convocável,
botão enviar lote, status por destinatário, reenviar falhas); `atas/+page.svelte`
(todas as atas do edital, status, assinaturas pendentes, reenviar token,
baixar PDF); `resultado/+page.svelte` (por nível × alvo: calcular classificação,
tabela com rank/nota/desfecho/empate, realocação de vaga — form da Comissão —,
botão "converter em aluno" com nº de matrícula, data de admissão e projeto).
Secretaria também cadastra o externo em `professores/` (já existe: acrescentar
`external` às `CATEGORIAS` e tornar instituição obrigatória na UX).

**Banca** `(app)/selecao/minhas-bancas/+page.svelte` (bancas do docente) e
`minhas-bancas/[id]/+page.svelte` (por etapa: grade de notas com campo decimal
e checkbox "ausente", salvar lote; gerar/atualizar ata; presidente congela
(escolhendo impedido/suplente) e reabre; cada membro assina; status das
assinaturas; após assinada, link do PDF e resumo promovidos/eliminados).

`sessao.rotaInicial` não muda. Item de menu "Processo seletivo" (submenu:
Editais, Bancas, Inscrições, Convocações, Atas, Resultado) para
`selection.view_selectionprocess`; "Minhas bancas" para
`selection.add_stagescore`.

---

## 7. Infra, settings e ADRs
- `backend/pyproject.toml`: `uv add reportlab` (lock muda). **Rebuild da imagem**
  (`docker compose up -d --build backend`) — o venv está em `/opt/venv` na
  imagem, não no volume.
- `config/settings/base.py`: `INSTALLED_APPS += "apps.selection"` (depois de
  `academic`); `EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")`,
  `EMAIL_HOST/PORT/USE_TLS/HOST_USER/HOST_PASSWORD` via env,
  `DEFAULT_FROM_EMAIL`, `SITE_URL = os.getenv("SITE_URL", "http://localhost:8080")`.
  `.env.example` ganha as chaves documentadas (**gate**: `.env*`).
- `docker-compose.yml`: serviço `mailpit` (`axllent/mailpit`, sem porta
  publicada) e `EMAIL_BACKEND=smtp`, `EMAIL_HOST=mailpit`, `EMAIL_PORT=1025` no
  `backend`. Verificação do loop: `docker compose exec backend curl
  http://mailpit:8025/api/v1/messages`. Publicar a UI do Mailpit no host
  (`MAILPIT_UI_PORT` em `.env.worktree` + `obra.conf`) é story **gate** à parte,
  sem dependentes.
- `nginx/nginx.conf`: `client_max_body_size 80m` só em `location
  /api/v1/selection/public/` (default 25m no resto).
- `docs/adr/008-pdf-da-ata-com-reportlab.md` e `docs/adr/009-email-de-convocacao-sem-fila.md`
  (registra que o corte de SMTP das isoladas não vale aqui; sem Celery; falha
  visível e reenviável; SPF/DKIM/relay com a infra).
- `CLAUDE.md` raiz: ADR-008/009 na lista; armadilhas novas na seção "Além dos
  gates" (rebuild após `uv add`; e-mail em canteiro vai ao Mailpit; `SITE_URL`).
- `seed_demo` (`apps/core/management/commands/seed_demo.py`): dois editais
  (Regular e Suplementar) publicados e abertos por programa, etapas, vagas,
  ~4 bancas (uma com externo), inscrições em todos os status, notas, uma ata
  assinada com PDF, uma convocação enviada. Atualizar `CONTAS-DEMO.txt`.
- `manual_dev.md` (raiz): seção do fluxo de seleção e do Mailpit.

---

## 8. Fases (ordem do cronograma) — cada bullet é uma story candidata
Effort `high` deve ser quebrado pelo `/cronograma`; abaixo já está fatiado.

**F0 — Fundação** (`review_required`: migrations, permissões)
1. App `selection` (apps.py, `INSTALLED_APPS`, router vazio em `api.py`, `admin.py`, `tests/conftest.py` com `MEDIA_ROOT=tmp_path` e fixtures `edital_regular`, `edital_suplementar`, `docente`, `externo`).
2. `Teacher.Category.EXTERNAL` + `clean()` + migration `academic/0012` + teste.
3. Enums, helpers (`xor_de_alvo`, caminhos de upload) e `SelectionProcess` + `SelectionStage` + migration + testes em memória.
4. `Vacancy` + `Board` + migration + testes (XOR, unicidade com nulos, membros distintos, credenciamento, alvo × kind).
5. `Application` + `ApplicationDocument` + migration + testes (CPF, documentos exigidos por kind/cota, transições).
6. `StageScore` + `ExaminationRecord` + `RecordSignature` + migration + testes (absent XOR score, hash canônico, versão/supersedes, token issue/consume).
7. `VacancyReallocation` + `Convocation` + `ConvocationEmail` + migration + testes.
8. Data migration de papéis (Comissão de Seleção + permissões) + `admin.py` completo.

**F1 — Edital, vagas e bancas (secretaria)**
9. Schemas + rotas de `processes` (CRUD, publish/close, `notice-file`) + `publish_process` + testes de API (inclui vazamento entre os dois programas).
10. Rotas de `stages` e `vacancies` (só em draft) + testes.
11. Rotas de `boards` (com `with_teacher`, `board_in_use`) + testes.
12. Settings de e-mail + `SITE_URL` + `mailpit` no compose + ADR-009. (`.env.example` → story gate separada.)
13. `make gen-api`; tela `selecao/editais`; item de menu; ícones.
14. Tela `selecao/bancas` + `external` na tela de professores.

**F2 — Inscrição pública e homologação**
15. `submit_application` + `POST/GET public/*` (processes, applications, protocolo) + rate limits + `nginx.conf` + testes (janela, cota × kind, sem vaga, CPF duplicado, documentos faltando, upload inválido, tenant).
16. Rotas de `applications` (lista, detalhe, homologate/reject, download) + testes.
17. Telas públicas `(publico)/selecao/inscricao` e `protocolo`.
18. Tela `selecao/inscricoes`.

**F3 — Notas, ata, assinatura e PDF**
19. Helper `teacher_da_sessao`; rotas `boards/mine` e `scores` (GET/PUT lote, `record_frozen`) + testes.
20. `generate_record`/`refresh_record`/`freeze_record`/`reopen_record` + rotas + testes (`scores_incomplete`, `previous_stage_open`, hash, `expected_signers` com impedimento, token e-mail com `django_capture_on_commit_callbacks`).
21. ADR-008 + `uv add reportlab` + `pdf.py` + teste que gera bytes válidos (`%PDF`).
22. `sign_record` + `_close_stage` (promove/elimina/approve, PDF, `select_for_update`) + rota + testes de fechamento por etapa (1ª, intermediária, última; ausente; corte exato 70.00).
23. `sign_record_with_token` + `resend_signature_token` + rotas públicas de assinatura + testes (expirado, reuso, reemissão, `record_changed`).
24. `rectify_record` (service + teste; sem rota/tela — fase 2).
25. Tela `minhas-bancas` (lista) e `minhas-bancas/[id]` (notas, ata, assinaturas).
26. Tela pública `(publico)/selecao/assinatura/[token]`.
27. Tela `selecao/atas` (secretaria) + rota `records/` + `records/{id}/pdf` + reenviar token.

**F4 — Convocação**
28. `send_convocations`/`resend_convocation_emails` + `emails.py` + `convocable_for` + rotas + testes (`mail.outbox`, falha simulada com `mock` no `send` não derruba o lote, reexecução pega só novos).
29. Tela `selecao/convocacoes`.

**F5 — Classificação, realocação e conversão**
30. Funções puras de ranking + `tests/test_ranking.py` (sem banco).
31. `compute_ranking` + rotas + testes (`ranking_locked`, exige ata final signed).
32. `reallocate_vacancy` + rotas (Comissão) + testes (mesmo alvo/níveis, retificação, saldo, invalida rank).
33. `convert_to_student` + rota `enroll` + testes (Person find-or-create, `project_required` no Suplementar, `full_clean` → `invalid_student`, grupo Discente se há user).
34. Tela `selecao/resultado` (ranking, realocação, converter em aluno).

**F6 — Fechamento**
35. `seed_demo` do módulo + `CONTAS-DEMO.txt`.
36. `manual_dev.md` + `CLAUDE.md` (ADRs 008/009, armadilhas) + mover specs para `implemented/` fica para o `arquivar-plano.sh`.
37. **Gate**: `.env.example` com chaves de e-mail/`SITE_URL`.
38. **Gate**: `MAILPIT_UI_PORT` em `.env.worktree` + `obra.conf` (porta da UI do Mailpit por canteiro). Sem dependentes.

---

## 9. Human gates e review_required (régua do `CLAUDE.md`: "o efeito escapa do canteiro?")
- **`human_gate: true`** (só estes): stories 37 e 38 (`.env*`, `obra.conf` —
  segredos e esteira). Nenhuma outra story depende delas → nada fica
  `blocked_by_gate`. Em canteiro o e-mail vai ao Mailpit/console: não sai da
  máquina; o SMTP real é configuração de `.env` de produção, fora deste plano.
- **`review_required: true`**: toda migration (F0), papéis/permissões (8),
  tenant nas rotas públicas (15, 23), contrato de API (todas as stories com
  router/schemas + `gen-api`), classificação e contagem de vaga (30–32),
  fechamento de etapa e desfechos (22), conversão em aluno (33 — a spec chamava
  de gate; pela régua revista de 22/08 é canteiro, logo revisão no merge),
  `docker-compose.yml`/`nginx.conf` (12, 15), ADRs (12, 21).

## 10. Arquivos reivindicados (claims para o `/compatibilizar`)
`backend/apps/selection/**` (novo) · `backend/apps/academic/models.py` (só
`Teacher.Category`/`clean`) · `backend/apps/academic/migrations/0012_*` ·
`backend/api.py` · `backend/config/settings/base.py`, `dev.py` ·
`backend/pyproject.toml`, `uv.lock` · `backend/apps/core/management/commands/seed_demo.py`
· `docker-compose.yml` · `nginx/nginx.conf` · `docs/adr/008-*.md`, `009-*.md` ·
`CLAUDE.md`, `manual_dev.md`, `CONTAS-DEMO.txt` · `frontend/src/routes/(publico)/selecao/**`
(novo) · `frontend/src/routes/(app)/selecao/**` (novo) ·
`frontend/src/routes/(app)/+layout.svelte` · `frontend/src/routes/(app)/professores/+page.svelte`
· `frontend/src/lib/Icone.svelte` · `frontend/src/lib/selecao.ts` (rótulos) ·
`frontend/src/lib/api/openapi.json`, `schema.d.ts` (gerados) · gates: `.env.example`,
`.env.worktree`, `scripts/helton/obra/obra.conf`. **`creates_migration: true`**
em `academic` e `selection`.

## 11. Verificação
- `make ready` (ruff + mypy + svelte-check + pytest) é o piso de toda story.
- Backend: `cd backend && uv run pytest apps/selection -q`; ranking sem banco:
  `uv run pytest apps/selection/tests/test_ranking.py`.
- Contrato: `make gen-api` e diff limpo de `openapi.json`/`schema.d.ts` após
  regenerar (se sujo, a story esqueceu de regenerar).
- Rebuild após `uv add`: `docker compose up -d --build backend`; front:
  `docker compose up -d --build frontend` antes de olhar tela.
- E-mail no canteiro: `docker compose exec backend curl -s http://mailpit:8025/api/v1/messages | head`.
- Fluxo ponta a ponta no browser (porta `NGINX_PORT` do `.env` da worktree,
  contas de `CONTAS-DEMO.txt`): secretaria cria edital → publica → inscrição
  pública (anônimo) recebe protocolo → homologa → docente lança notas → presidente
  congela → 2 assinam logados + externo assina por link (colher o link no Mailpit)
  → ata `signed`, PDF baixa, eliminados/promovidos corretos → convocação em lote
  aparece no Mailpit → última etapa → ranking → conversão em aluno aparece em
  `/alunos`.
- Tenant: todo teste de listagem/pública cria dado nos **dois** programas do
  `seed_demo` e afirma que o outro não aparece.

## 12. Armadilhas (o loop tropeça aqui)
1. `uv add reportlab` sem rebuild → `ModuleNotFoundError` só em runtime no container.
2. Sem `EMAIL_BACKEND` o Django tenta SMTP em `localhost:25`; em `pytest-django` é `locmem` → assert em `django.core.mail.outbox`; `on_commit` só roda com `django_capture_on_commit_callbacks(execute=True)`.
3. Envio de e-mail **fora** do `transaction.atomic` (ou em `on_commit`): exceção de SMTP dentro do bloco reverteria a ata assinada.
4. `FileField` em teste grava em disco: `MEDIA_ROOT = tmp_path` autouse no conftest de `selection`.
5. `.save()` não roda `clean()`; toda `UniqueConstraint` tem espelho no `clean()` com `code` estável, senão `IntegrityError` → 500. `Student` na conversão usa `full_clean()` traduzido.
6. Enum aninhado colide no OpenAPI → todos `TextChoices` de módulo com nome único.
7. `Decimal` → `string` no `schema.d.ts`; no `content` JSON da ata gravar `str(score)`.
8. `nulls_distinct=False` aparece na migration gerada — ler; sem ele duas vagas com `research_line=NULL` passariam.
9. Hash canônico: `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`; `verify_hash()` no teste de assinatura.
10. Migrations em dois apps: `selection/0001` depende de `academic/0012` e `programs/0006`.
11. POST público com 7 anexos × 10 MB > `client_max_body_size 25m` → subir só no `location` público.
12. Rota pública não usa `current_program`; tenant = `SelectionProcess` aberto; `audit.record(program=process.program)` explícito.
13. `Teacher` da sessão pode não existir (secretaria) → `NotAllowed`, não 404.
14. Duas assinaturas simultâneas → `select_for_update()` na ata antes de contar.
15. `reopen_record` é o único `delete` do app (assinaturas pendentes).
16. `Student.project` obrigatório no regular (CheckConstraint) → conversão do Suplementar exige `project` no payload.
17. `/inscricao` já é da isolada — rotas novas sob `/selecao/`; página pública fora de `(app)`.
18. `SITE_URL` para links em e-mail; nunca `request.build_absolute_uri`.

## 13. Fora desta rodada
Recursos (inscrição e etapa) e a rota/tela de retificação de ata; documentos de
divulgação (homologação/resultados) e página pública de resultado; geração de
GRU e conciliação; ofício ao DRCA; declaração de impedimento/suspeição (F7 da
spec de bancas); `code` em `CollectiveProject` (F5); exportação da relação
nominal das bancas (F6); escolha do orientador; sorteio do ponto da prova oral.
