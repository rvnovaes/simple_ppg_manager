# PRD: Requerimento de Matrícula em Disciplina Isolada

> **Origem**: `docs/notes/2026-08-05-disciplinas-isoladas-grill.md` (27
> perguntas, com o protocolo oficial do PPGD transcrito) e **ADR-007**
> (`docs/adr/007-modalidade-e-situacao-do-aluno.md`), que preparou o
> modelo de dados para receber este fluxo.

## 1. Introduction/Overview

**Disciplina isolada** é uma disciplina da pós-graduação cursada por
alguém **sem vínculo com a UFMG** — o protocolo exige explicitamente *não
ser aluno de curso de Graduação ou de Pós-graduação da UFMG*. A pessoa
pode cursar **até duas** disciplinas isoladas num semestre, paga **uma
taxa** por isso, e **é excluída ao fim do semestre**. Se voltar em outro
semestre, recebe um número de matrícula novo.

Hoje o processo inteiro acontece fora do PPGD Manager: formulário web
externo para envio de documentos, formulário próprio que o docente manda
por e-mail à secretaria com a ordem de prioridade dos candidatos, listas
de deferimento publicadas no site, e comprovante de GRU enviado por um
link separado. Não há registro unificado de quem pediu o quê, quem
classificou, quem deferiu e por quê.

Esta PRD traz o fluxo inteiro para dentro do sistema: inscrição do
candidato com documentação, classificação pelo docente responsável,
deferimento pela secretaria dentro do limite de vagas, recurso,
comprovação do pagamento da GRU e efetivação da matrícula.

**Não é** um módulo de matrícula em disciplinas: a matrícula do aluno
regular continua inteiramente no sistema da UFMG (ver
`tasks/prd-matricula.md`).

### Dependências bloqueantes

Esta PRD **não pode ser executada isoladamente**. Ela depende de:

- **`tasks/prd-cadastros-basicos.md`** — `Student` (com `modality =
  ISOLATED`), `AcademicTerm`, `Teacher`, os grupos de domínio e o helper
  `current_program()`.
- **`tasks/prd-matricula.md` (US-001)** — o model `Discipline`, que é o
  catálogo referenciado pela oferta.

Ordem de execução: **cadastros básicos → acerto de matrícula →
isoladas**.

## 2. Goals

- Permitir que uma pessoa de fora da UFMG se inscreva em até duas
  disciplinas isoladas de um semestre, anexando a documentação exigida,
  sem e-mail e sem formulário externo.
- Permitir que o **docente responsável pela disciplina** ordene os
  candidatos por prioridade dentro do sistema, já que essa recomendação é
  o que decide o deferimento.
- Permitir que a secretaria defira, indefira ou cancele requerimentos
  vendo, na mesma tela, a classificação do docente e as vagas restantes.
- Registrar o ciclo completo — inscrição, classificação, deferimento,
  recurso, pagamento e efetivação — com auditoria de quem fez o quê.
- Fazer valer as janelas de data do edital, que são curtas e rígidas.

## 3. User Stories

### US-001: Model do ciclo de requerimento (o edital do semestre)
**Description:** Como secretaria, preciso cadastrar as datas do edital de
isoladas de cada semestre, para que o sistema faça valer as janelas em vez
de eu policiar prazo manualmente.

**Acceptance Criteria:**
- [ ] Model `IsolatedEnrollmentCycle` no app `academic`: `program` (FK
      para `programs.Program`, on_delete=PROTECT,
      related_name="isolated_cycles"), `term` (FK para
      `programs.AcademicTerm`, on_delete=PROTECT,
      related_name="isolated_cycles"), `submission_opens_at`
      (DateTimeField), `submission_closes_at` (DateTimeField),
      `result_published_on` (DateField), `appeal_opens_at`
      (DateTimeField), `appeal_closes_at` (DateTimeField),
      `final_result_on` (DateField), `payment_closes_at` (DateTimeField),
      `is_active` (BooleanField, default True).
- [ ] `UniqueConstraint` em (`program`, `term`) — um ciclo por semestre
      por programa.
- [ ] FK `program` direta e obrigatória, ainda que alcançável por
      navegação — ADR-007, decisão 5.
- [ ] Método `clean()` valida a ordem cronológica das datas
      (`submission_opens_at < submission_closes_at <= appeal_opens_at <
      appeal_closes_at <= payment_closes_at`); levanta `DomainError`
      (`code="invalid_cycle_dates"`).
- [ ] Método `submission_open(at)` devolve `True` se `at` está dentro da
      janela de inscrição; `appeal_open(at)` idem para recurso.
- [ ] Registrado no Django Admin do app `academic`.
- [ ] Migração criada e revisada (arquivo lido, não só gerado).
- [ ] Typecheck passes.
- [ ] Tests pass (em memória: `clean()` rejeita datas fora de ordem;
      `submission_open()` responde corretamente dentro e fora da janela).

### US-002: Model da oferta de disciplina no ciclo
**Description:** Como secretaria, preciso registrar quais disciplinas são
oferecidas em cada ciclo, com quantas vagas e sob responsabilidade de qual
docente, porque é o docente quem classifica os candidatos e é a vaga que
limita o deferimento.

**Acceptance Criteria:**
- [ ] Model `DisciplineOffering` no app `academic`: `program` (FK,
      on_delete=PROTECT, related_name="offerings"), `cycle` (FK para
      `IsolatedEnrollmentCycle`, on_delete=PROTECT,
      related_name="offerings"), `discipline` (FK para
      `programs.Discipline`, on_delete=PROTECT,
      related_name="offerings"), `teacher` (FK para `academic.Teacher`,
      on_delete=PROTECT, related_name="offerings" — o docente responsável,
      **obrigatório**), `seats` (PositiveSmallIntegerField — número de
      vagas).
- [ ] `UniqueConstraint` em (`cycle`, `discipline`).
- [ ] Método `clean()` garante que `program`, `cycle.program`,
      `discipline.program` e `teacher.program` são o mesmo; levanta
      `DomainError` (`code="program_mismatch"`).
- [ ] Método `seats_taken()` conta os itens de requerimento **deferidos**
      naquela oferta; `seats_available()` devolve `seats - seats_taken()`.
- [ ] Registrado no Django Admin do app `academic` (com `cycle`,
      `discipline`, `teacher` e `seats` em `list_display`).
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.
- [ ] Tests pass (em memória: `clean()` rejeita docente de outro
      programa).

### US-003: Model do requerimento de isolada
**Description:** Como desenvolvedor, preciso do model que representa o
requerimento de uma pessoa num ciclo, com seus estados e o estado de
pagamento, para que o restante do fluxo tenha onde persistir.

**Acceptance Criteria:**
- [ ] Model `IsolatedEnrollmentRequest` no app `academic`: `program` (FK,
      on_delete=PROTECT, related_name="isolated_requests"), `cycle` (FK
      para `IsolatedEnrollmentCycle`, on_delete=PROTECT,
      related_name="requests"), `person` (FK para `people.Person`,
      on_delete=PROTECT, related_name="isolated_requests"), `status`
      (TextChoices), `payment_status` (TextChoices), `is_ufmg_staff`
      (BooleanField, default False — servidor da UFMG, base da isenção),
      `gru_url` (URLField, blank=True — link gerado pela UFMG, colado pela
      secretaria no deferimento), `decision_note` (TextField, blank=True),
      `decided_at` (DateTimeField, null=True, blank=True), `appeal_note`
      (TextField, blank=True), `appealed_at` (DateTimeField, null=True,
      blank=True), `submitted_at` (DateTimeField, null=True, blank=True),
      `created_at` (auto_now_add).
- [ ] `status`: `DRAFT` ("Rascunho") / `SUBMITTED` ("Inscrito") /
      `DEFERRED` ("Deferido") / `REJECTED` ("Indeferido") / `CANCELLED`
      ("Cancelado") / `ENROLLED` ("Matriculado").
- [ ] `payment_status`: `PENDING` ("Pendente") / `PAID` ("Pago") /
      `EXEMPT` ("Isento").
- [ ] `UniqueConstraint` em (`cycle`, `person`) — **um requerimento por
      pessoa por ciclo** (a inscrição carrega até duas disciplinas, não
      duas inscrições).
- [ ] FK `program` direta e obrigatória (ADR-007, decisão 5).
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.

### US-004: Transições de estado do requerimento
**Description:** Como desenvolvedor, preciso que as mudanças de estado do
requerimento sejam métodos do próprio model que recusam transição
inválida, no padrão de `Person.archive()`.

**Acceptance Criteria:**
- [ ] `submit(*, at)`: só a partir de `DRAFT`; exige que
      `cycle.submission_open(at)` seja verdadeiro, senão levanta
      `DomainError` (`code="submission_window_closed"`); exige pelo menos
      1 item e no máximo 2, senão `DomainError`
      (`code="invalid_item_count"`); exige a documentação obrigatória
      completa, senão `DomainError` (`code="missing_documents"`); carimba
      `submitted_at` e vai para `SUBMITTED`.
- [ ] `defer(*, note="")`: só a partir de `SUBMITTED`; vai para
      `DEFERRED`, carimba `decided_at`. Se `is_ufmg_staff` for `True`,
      define `payment_status = EXEMPT`; senão mantém `PENDING`.
- [ ] `reject(*, note)`: só a partir de `SUBMITTED`; `note` obrigatório
      (`DomainError`, `code="rejection_requires_note"`); vai para
      `REJECTED`, carimba `decided_at`.
- [ ] `cancel(*, note)`: a partir de `SUBMITTED` ou `DEFERRED`; vai para
      `CANCELLED` — é o que **devolve a vaga** quando a pessoa deferida
      não paga. Não existe expiração automática.
- [ ] `appeal(*, note, at)`: só a partir de `REJECTED`; exige
      `cycle.appeal_open(at)`, senão `DomainError`
      (`code="appeal_window_closed"`); `note` obrigatório; carimba
      `appealed_at`. **Não muda o status** — o requerimento continua
      `REJECTED` até a secretaria rejulgar.
- [ ] `enroll()`: só a partir de `DEFERRED` **e** com `payment_status` em
      (`PAID`, `EXEMPT`), senão `DomainError`
      (`code="payment_required"`); vai para `ENROLLED`.
- [ ] Toda transição inválida levanta `InvalidStateTransition` (409), no
      padrão de `Person.archive()`.
- [ ] Typecheck passes.
- [ ] Tests pass — testes de invariante **em memória, sem banco**:
      submeter fora da janela; submeter com 0 ou 3 itens; deferir um
      requerimento já decidido; recusar sem motivo; recorrer de um
      requerimento deferido; efetivar sem pagamento; efetivar isento
      (deve passar).

### US-005: Model dos itens do requerimento
**Description:** Como candidato, quero pedir uma ou duas disciplinas num
único requerimento, com a mesma documentação e uma única taxa.

**Acceptance Criteria:**
- [ ] Model `IsolatedEnrollmentItem` no app `academic`: `request` (FK,
      on_delete=CASCADE, related_name="items"), `offering` (FK para
      `DisciplineOffering`, on_delete=PROTECT, related_name="items"),
      `rank` (PositiveSmallIntegerField, null=True, blank=True — a
      posição atribuída pelo docente; nulo até ele classificar).
- [ ] `UniqueConstraint` em (`request`, `offering`).
- [ ] `UniqueConstraint` em (`offering`, `rank`) com
      `condition=Q(rank__isnull=False)` — duas pessoas não ocupam a mesma
      posição na mesma oferta.
- [ ] Método `clean()` garante `request.cycle == offering.cycle`; levanta
      `DomainError` (`code="cycle_mismatch"`).
- [ ] O limite de **no máximo 2 itens por requerimento** é validado em
      `IsolatedEnrollmentRequest.submit()` (US-004), não por constraint de
      banco — depende de contagem de linhas relacionadas.
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.
- [ ] Tests pass (com banco: item duplicado na mesma oferta é rejeitado;
      dois itens com o mesmo `rank` na mesma oferta são rejeitados).

### US-006: Model dos documentos anexados
**Description:** Como candidato, preciso anexar a documentação exigida
pelo edital, e como secretaria preciso conferi-la antes de deferir.

**Acceptance Criteria:**
- [ ] Model `RequestDocument` no app `academic`: `request` (FK,
      on_delete=CASCADE, related_name="documents"), `kind`
      (TextChoices), `file` (FileField, `upload_to` particionado por
      ciclo e requerimento), `uploaded_at` (auto_now_add).
- [ ] `kind`: `IDENTITY` ("Identidade e CPF") / `DIPLOMA` ("Diploma de
      graduação ou certidão de conclusão") / `LATTES` ("Currículo Lattes
      em PDF") / `ADDRESS` ("Comprovante de endereço") / `PAYSLIP`
      ("Contracheque de servidor da UFMG") / `SUPERVISOR_AUTH`
      ("Autorização da chefia") / `PAYMENT_RECEIPT` ("Comprovante de
      pagamento da GRU").
- [ ] `UniqueConstraint` em (`request`, `kind`) — um documento por tipo.
- [ ] Método/propriedade `IsolatedEnrollmentRequest.missing_documents()`
      devolve os tipos obrigatórios ainda ausentes: `IDENTITY`, `DIPLOMA`,
      `LATTES` e `ADDRESS` sempre; mais `PAYSLIP` e `SUPERVISOR_AUTH`
      quando `is_ufmg_staff` é `True`. `PAYMENT_RECEIPT` **não** conta
      para a submissão — ele só existe depois do deferimento.
- [ ] Os arquivos ficam armazenados **indefinidamente** (decisão
      explícita do usuário no levantamento) e são visíveis **apenas pela
      Secretaria** — a permissão de download é separada da de ver o
      requerimento.
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.
- [ ] Tests pass (em memória: `missing_documents()` inclui contracheque e
      autorização da chefia só quando `is_ufmg_staff` é `True`).

### US-007: Papel Candidato e permissões do fluxo
**Description:** Como sistema, preciso de um papel para quem ainda não é
aluno, com permissão apenas sobre o próprio requerimento.

**Acceptance Criteria:**
- [ ] Data migration no padrão de
      `apps/programs/migrations/0002_programa_inicial_e_papeis.py` cria o
      grupo **Candidato**, com
      `academic.add_isolatedenrollmentrequest`,
      `academic.view_isolatedenrollmentrequest`,
      `academic.change_isolatedenrollmentrequest` e
      `academic.view_disciplineoffering`.
- [ ] O grupo Candidato **não** recebe `is_staff` nem `is_superuser`, e
      nenhuma permissão sobre `Student`, `Teacher` ou outros dados de
      negócio (CLAUDE.md, Seção 5).
- [ ] **Secretaria** ganha `view`/`change` em
      `IsolatedEnrollmentRequest`, `add`/`change`/`view` em
      `IsolatedEnrollmentCycle` e `DisciplineOffering`, e a permissão
      customizada `academic.download_requestdocument`.
- [ ] **Docente** ganha `view_isolatedenrollmentrequest` e a permissão
      customizada `academic.rank_disciplineoffering` — **sem**
      `download_requestdocument`.
- [ ] **Coordenação** ganha apenas `view` em requerimento, ciclo e oferta.
      Sem `download_requestdocument`.
- [ ] As duas permissões customizadas (`download_requestdocument`,
      `rank_disciplineoffering`) são declaradas em `Meta.permissions` dos
      respectivos models.
- [ ] Migração de dados revisada (lida e conferida, não só gerada).
- [ ] Typecheck passes.

### US-008: Endpoint de auto-registro do candidato
**Description:** Como pessoa de fora da UFMG, preciso criar uma conta para
me inscrever e depois voltar para acompanhar o resultado e enviar o
comprovante de pagamento.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/isolated/signup` — **o único endpoint
      público de escrita do projeto**. Marcado no código com `# público`
      e uma justificativa em comentário, conforme a Seção 5 do CLAUDE.md,
      que exige isso de toda rota sem `require_perm`.
- [ ] Recebe nome completo, e-mail, telefone e senha. Cria `User`
      (username = e-mail), `Person` (vinculada ao `User` e ao programa) e
      coloca o usuário no grupo **Candidato**, tudo numa
      `transaction.atomic()` via `services.py`.
- [ ] Se já existe `Person` com aquele e-mail no programa, **não** cria
      outra nem vaza a informação de que o e-mail existe: responde o mesmo
      corpo de sucesso e não altera nada. (A `UniqueConstraint (program,
      primary_email)` continua sendo a garantia no banco.)
- [ ] Aplica limite de tentativas por IP (rate limit simples em cache),
      porque é rota pública sem sessão.
- [ ] **Sem confirmação de e-mail** — o projeto não tem SMTP e não vai
      ganhar um nesta PRD; quem faz o papel de porteiro é o deferimento
      manual da secretaria.
- [ ] Registra `AuditLog` `academic.isolated.signup`.
- [ ] Typecheck passes.
- [ ] Tests pass (criar conta nova; repetir o mesmo e-mail não duplica
      `Person` nem devolve erro distinguível; rate limit dispara).

### US-009: Endpoints — candidato monta e envia o requerimento
**Description:** Como candidato, quero escolher até duas disciplinas
ofertadas no semestre e enviar meu requerimento dentro do prazo.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `IsolatedRequestIn`/`IsolatedRequestOut` e
      `IsolatedItemIn`/`IsolatedItemOut` em `apps/academic/schemas.py`
      (nunca serializar model direto).
- [ ] `GET /api/v1/academic/isolated/offerings/` lista as ofertas do ciclo
      aberto, com `seats` e `seats_available()`; `require_perm` com
      `academic.view_disciplineoffering`.
- [ ] `POST /api/v1/academic/isolated/requests/` cria o requerimento em
      `DRAFT` com seus itens; `require_perm` com
      `academic.add_isolatedenrollmentrequest`; checagem explícita
      adicional de que a `Person` do payload é a do usuário autenticado.
- [ ] `PATCH /api/v1/academic/isolated/requests/{id}/` altera itens e
      `is_ufmg_staff` **apenas enquanto** `status = DRAFT`.
- [ ] `POST /api/v1/academic/isolated/requests/{id}/submit` chama
      `submit()` (US-004); os erros de janela, contagem de itens e
      documentação faltante voltam como 4xx do handler central, **sem
      try/except no router**.
- [ ] `GET /api/v1/academic/isolated/requests/` devolve **apenas os
      requerimentos do próprio candidato** quando quem pergunta é do grupo
      Candidato.
- [ ] Toda escrita registra `AuditLog` (`academic.isolated.create`,
      `.update`, `.submit`).
- [ ] Typecheck passes.
- [ ] Tests pass (candidato não vê nem edita requerimento de outro;
      submissão fora da janela é recusada; edição depois de submetido é
      recusada).

### US-010: Endpoints — upload e download de documentos
**Description:** Como candidato, quero anexar meus documentos; como
secretaria, quero baixá-los para conferir.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/isolated/requests/{id}/documents`
      (multipart) cria/substitui o documento de um `kind`; só o dono do
      requerimento, e só enquanto `DRAFT` — exceto `PAYMENT_RECEIPT`, que
      é aceito quando `status = DEFERRED` (ver US-013).
- [ ] Valida extensão (PDF e imagens) e tamanho máximo por arquivo;
      recusa com `DomainError` (`code="invalid_document"`).
- [ ] `GET /api/v1/academic/isolated/documents/{id}/download` exige
      `require_perm(request, "academic.download_requestdocument")` —
      **só a Secretaria**. Docente e Coordenação recebem 403 mesmo
      conseguindo ver o requerimento.
- [ ] O candidato pode baixar **os próprios** documentos (checagem
      explícita de posse, em vez da permissão de Secretaria).
- [ ] `GET .../requests/{id}/documents` lista os documentos anexados sem
      expor URL direta do arquivo.
- [ ] Registra `AuditLog` no upload (`academic.isolated.document_upload`)
      e **também no download** (`academic.isolated.document_download`) —
      é acesso a documento de identidade, o rastro importa.
- [ ] Typecheck passes.
- [ ] Tests pass (docente recebe 403 no download; candidato baixa o
      próprio; upload com extensão inválida é recusado).

### US-011: Endpoints — docente classifica os candidatos
**Description:** Como docente responsável pela disciplina, quero ordenar
os candidatos por prioridade, porque é essa ordem que decide quem é
matriculado dentro do limite de vagas.

**Acceptance Criteria:**
- [ ] `GET /api/v1/academic/isolated/offerings/{id}/candidates` lista os
      itens `SUBMITTED` daquela oferta com nome do candidato e `rank`
      atual; `require_perm` com `academic.rank_disciplineoffering` **e**
      checagem explícita de que o usuário é o `teacher` daquela oferta —
      outro docente recebe 403.
- [ ] `POST /api/v1/academic/isolated/offerings/{id}/rank` recebe a lista
      ordenada de ids de item e grava `rank` sequencial (1, 2, 3…) numa
      `transaction.atomic()`.
- [ ] Recusa a operação se algum item enviado não pertencer àquela oferta
      (`DomainError`, `code="item_not_in_offering"`).
- [ ] `GET /api/v1/academic/isolated/offerings/?mine=true` devolve as
      ofertas do docente autenticado, com um marcador de **quais ainda
      não têm classificação** — é a informação que ele precisa ver
      primeiro.
- [ ] Registra `AuditLog` `academic.isolated.rank`.
- [ ] Typecheck passes.
- [ ] Tests pass (docente de outra oferta recebe 403; classificação grava
      ranks sequenciais; item de outra oferta é recusado).

### US-012: Endpoints — secretaria defere, indefere e cancela
**Description:** Como secretaria, quero deferir os requerimentos seguindo
a classificação do docente e o limite de vagas, e cancelar quem não pagar
para devolver a vaga.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/isolated/requests/{id}/defer` chama
      `defer()`; `require_perm` com
      `academic.change_isolatedenrollmentrequest`. Aceita `gru_url` no
      payload e o grava.
- [ ] **Recusa deferir** quando algum item do requerimento está numa
      oferta **sem vaga disponível** (`DomainError`,
      `code="no_seats_available"`), ou quando a oferta **ainda não foi
      classificada** pelo docente (`DomainError`,
      `code="offering_not_ranked"`) — sem a lista do docente, ninguém é
      matriculado.
- [ ] `POST .../requests/{id}/reject` chama `reject()` com `note`
      obrigatório.
- [ ] `POST .../requests/{id}/cancel` chama `cancel()` — devolve a vaga.
- [ ] `GET /api/v1/academic/isolated/requests/?cycle=&status=` lista
      todos os requerimentos do programa para Secretaria e Coordenação,
      escopado por `current_program(request)`.
- [ ] Cada operação numa `transaction.atomic()` com
      `save(update_fields=[...])` e `AuditLog`
      (`academic.isolated.defer` / `.reject` / `.cancel`).
- [ ] Typecheck passes.
- [ ] Tests pass (deferir sem vaga é recusado; deferir oferta não
      classificada é recusado; cancelar libera a vaga e o próximo passa a
      caber; servidor da UFMG deferido nasce `EXEMPT`).

### US-013: Endpoints — recurso e comprovante da GRU
**Description:** Como candidato indeferido, quero interpor recurso
anexando o documento que faltou; como candidato deferido, quero enviar o
comprovante de pagamento.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/isolated/requests/{id}/appeal` chama
      `appeal()` (US-004): exige janela de recurso aberta e `note`; aceita
      upload de documento faltante junto. Só o dono do requerimento.
- [ ] A secretaria rejulga pelo mesmo `defer`/`reject` da US-012 — o
      recurso **não é entidade nova**, é reabertura da decisão. O recurso
      **não derruba a classificação do docente** e **não dispensa a GRU**.
- [ ] `POST .../requests/{id}/payment-receipt` (multipart) aceita o
      `PAYMENT_RECEIPT` quando `status = DEFERRED` e
      `payment_status = PENDING`; recusa fora da janela
      (`payment_closes_at`) com `DomainError`
      (`code="payment_window_closed"`); define `payment_status = PAID`.
- [ ] Requerimento com `payment_status = EXEMPT` recusa envio de
      comprovante (`DomainError`, `code="payment_not_required"`).
- [ ] Registra `AuditLog` (`academic.isolated.appeal`,
      `.payment_receipt`).
- [ ] Typecheck passes.
- [ ] Tests pass (recurso fora da janela é recusado; comprovante em
      requerimento isento é recusado; comprovante fora do prazo é
      recusado).

### US-014: Endpoint — efetivar a matrícula
**Description:** Como secretaria, depois de lançar a matrícula no sistema
da UFMG e receber o número, quero registrá-lo aqui e transformar o
requerimento num vínculo de aluno.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/isolated/requests/{id}/enroll` recebe
      `registration_number`; `require_perm` com
      `academic.change_isolatedenrollmentrequest`.
- [ ] Numa `transaction.atomic()` via `services.py`: chama `enroll()` no
      requerimento e **cria um `Student`** com `modality = ISOLATED`,
      `status = ACTIVE`, `person` do requerimento, `term` do ciclo e o
      `registration_number` informado — sem `level`, `project`,
      `advisor`, `admission_date` nem `deadline`, como exige a
      `CheckConstraint` do ADR-007.
- [ ] Chama `full_clean()` antes de salvar o `Student` (o Django não roda
      `clean()` em `.create()`).
- [ ] Recusa se `payment_status` for `PENDING` (`DomainError`,
      `code="payment_required"`).
- [ ] Coloca o usuário do candidato no grupo **Discente** e o remove do
      grupo **Candidato**.
- [ ] Registra `AuditLog` `academic.isolated.enroll`.
- [ ] Typecheck passes.
- [ ] Tests pass (efetivar sem pagamento é recusado; efetivar isento
      funciona; o `Student` criado passa nas constraints do ADR-007; a
      mesma `Person` pode ter dois `Student` de ciclos diferentes).

### US-015: Endpoint — encerrar o período
**Description:** Como secretaria, quero encerrar o semestre e marcar como
excluídos, de uma vez, todos os alunos de isolada daquele período.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/isolated/cycles/{id}/close` marca
      `status = EXCLUDED` em todos os `Student` com
      `modality = ISOLATED` e `term` daquele ciclo que ainda estão
      `ACTIVE`, e define `is_active = False` no ciclo.
- [ ] Operação em lote numa `transaction.atomic()` em `services.py`, com
      **um único** `AuditLog` `academic.isolated.close_cycle` contendo a
      contagem de alunos afetados no `payload` — não N eventos soltos.
- [ ] `require_perm` com `academic.change_isolatedenrollmentcycle`.
- [ ] Não há expiração automática: nada roda sozinho, é sempre esta ação
      explícita da secretaria.
- [ ] Typecheck passes.
- [ ] Tests pass (encerrar marca só os `ISOLATED` `ACTIVE` daquele termo,
      e não toca em aluno regular nem em quem já estava excluído).

### US-016: Tela Svelte — cadastro e inscrição do candidato
**Description:** Como pessoa de fora da UFMG, quero criar minha conta,
escolher até duas disciplinas e anexar meus documentos.

**Acceptance Criteria:**
- [ ] `make gen-api` rodado (backend de pé) antes de tipar as telas.
- [ ] Tela pública de criação de conta, fora da área autenticada.
- [ ] Formulário de requerimento: lista as ofertas do ciclo aberto com
      vagas, permite escolher **no máximo duas** (a UI impede a terceira),
      e marcar "sou servidor da UFMG".
- [ ] Área de upload com a lista de documentos exigidos e indicação clara
      do que ainda falta; marcar "servidor da UFMG" acrescenta
      contracheque e autorização da chefia à lista.
- [ ] Botão de enviar fica desabilitado enquanto faltar documento ou a
      janela estiver fechada, com a razão visível — nada de botão que
      falha sem explicação.
- [ ] Toda chamada via `lib/api/client.ts` tipado (`fetch` cru proibido).
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-017: Tela Svelte — acompanhamento do candidato
**Description:** Como candidato, quero voltar ao sistema para ver se fui
deferido, pagar a GRU e enviar o comprovante.

**Acceptance Criteria:**
- [ ] Mostra o estado atual do requerimento com o vocabulário do edital
      ("Inscrito", "Deferido", "Indeferido", "Matriculado").
- [ ] Quando deferido e não isento: exibe o **link da GRU** gravado pela
      secretaria e o campo de envio do comprovante, com o prazo visível.
- [ ] Quando isento: diz que não há taxa a pagar, e não oferece envio de
      comprovante.
- [ ] Quando indeferido e dentro da janela: oferece interpor recurso com
      texto e anexo.
- [ ] Fora das janelas, os controles somem com a razão explicada.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-018: Tela Svelte — classificação pelo docente
**Description:** Como docente, quero ver quem pediu minha disciplina e
ordenar por prioridade.

**Acceptance Criteria:**
- [ ] Lista as ofertas do docente logado, destacando as que **ainda não
      foram classificadas**.
- [ ] Tela de classificação com a lista de candidatos reordenável, e o
      número de vagas visível para ele saber onde cai o corte.
- [ ] Não expõe nenhum link de download de documento (o docente não tem
      essa permissão — US-010).
- [ ] Ao salvar, a ordem é persistida e a tela confirma.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-019: Tela Svelte — análise e deferimento pela secretaria
**Description:** Como secretaria, quero analisar os requerimentos com a
documentação, a classificação do docente e as vagas na mesma tela.

**Acceptance Criteria:**
- [ ] Lista os requerimentos do ciclo, filtrável por status, com a posição
      atribuída pelo docente e as vagas restantes de cada oferta.
- [ ] **Aviso em destaque para ofertas sem classificação** enquanto o
      ciclo está aberto — sem a lista do docente ninguém é matriculado, e
      o custo do silêncio é a disciplina ficar vazia.
- [ ] Permite abrir cada documento anexado (só este papel tem a
      permissão).
- [ ] Ações de deferir (com campo para colar o link da GRU), indeferir
      (motivo obrigatório) e cancelar.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-020: Tela Svelte — ciclo, ofertas e encerramento
**Description:** Como secretaria, quero cadastrar o edital do semestre com
suas datas e ofertas, e encerrar o período quando ele acabar.

**Acceptance Criteria:**
- [ ] Formulário do ciclo com todas as datas do edital, validando a ordem
      cronológica antes de enviar.
- [ ] Cadastro de ofertas do ciclo: disciplina, docente responsável e
      número de vagas.
- [ ] Ação de encerrar o período, com confirmação que informa **quantos
      alunos serão marcados como excluídos** antes de executar.
- [ ] Coordenação vê tudo em modo somente leitura.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

## 4. Functional Requirements

1. O sistema deve permitir que uma pessoa sem vínculo com a UFMG crie uma
   conta e se inscreva em disciplinas isoladas.
2. O sistema deve aceitar **no máximo duas** disciplinas por requerimento
   e **um requerimento por pessoa por ciclo**.
3. O sistema deve exigir identidade/CPF, diploma de graduação, currículo
   Lattes e comprovante de endereço; e, para servidor da UFMG,
   adicionalmente contracheque e autorização da chefia.
4. O sistema deve recusar submissão fora da janela de inscrição do ciclo.
5. O sistema deve permitir ao docente responsável ordenar os candidatos
   da sua oferta por prioridade.
6. O sistema **não deve permitir deferimento em oferta ainda não
   classificada** pelo docente.
7. O sistema não deve permitir deferimento além do número de vagas da
   oferta.
8. O sistema deve permitir à secretaria cancelar um requerimento
   deferido, devolvendo a vaga; nada expira automaticamente.
9. O sistema deve permitir recurso de requerimento indeferido dentro da
   janela, com anexo de documento faltante — sem derrubar a classificação
   do docente e sem dispensar o pagamento.
10. O sistema deve isentar da taxa quem é servidor da UFMG e apresentou
    contracheque, e exigir comprovante de pagamento dos demais antes de
    efetivar a matrícula.
11. O sistema deve registrar o link da GRU gerado pela UFMG para que o
    candidato o veja ao entrar.
12. O sistema deve criar um `Student` com `modality = ISOLATED` ao
    efetivar a matrícula, com o número de matrícula fornecido pela UFMG.
13. O sistema deve permitir encerrar o período, marcando como excluídos
    todos os alunos de isolada daquele semestre de uma vez.
14. Apenas a Secretaria pode baixar os documentos anexados.
15. Toda transição do requerimento deve gerar `AuditLog`, inclusive o
    download de documento.

## 5. Non-Goals (Out of Scope)

- **Disciplina eletiva** — o levantamento foi adiado explicitamente pelo
  usuário. A modalidade existe no enum do ADR-007, mas nenhum fluxo dela
  é especificado aqui.
- **Geração da GRU e conciliação financeira** — a guia é gerada pela
  UFMG; o sistema guarda o link, o estado e o comprovante. Sem valor, sem
  `DecimalField`, sem baixa bancária.
- **Notificação por e-mail** — o projeto não tem SMTP. O candidato
  descobre o resultado voltando ao sistema.
- **Expiração automática de prazo** — nada roda sozinho; não entra
  agendador de tarefas no projeto.
- **Nota, frequência e aprovação** — desempenho acadêmico fica na UFMG.
- **Lançamento da matrícula na UFMG** — continua sendo trabalho manual da
  secretaria no sistema da universidade.
- **Contato entre candidato e docente** — o edital diz que cabe à pessoa
  procurar o professor; o sistema registra a classificação, não
  intermedeia o contato.
- **Descarte de documentos** — ficam armazenados indefinidamente, por
  decisão explícita.

## 6. Design Considerations

- Usar o vocabulário do edital nas telas: **deferir/indeferir**, não
  "aprovar/recusar"; **requerimento**, não "pedido". É o termo que a
  secretaria e os candidatos reconhecem.
- A tela do candidato é a única acessível a quem não é do programa —
  deve funcionar sem nenhum conhecimento prévio do sistema, e deixar
  explícito o que falta para concluir.
- As janelas do edital são curtas (a de inscrição dura **um dia**). Prazo
  e tempo restante precisam estar visíveis, não escondidos.

## 7. Technical Considerations

- Tudo no app `academic`, exceto o que já existe em `programs`
  (`Discipline`, `AcademicTerm`).
- `DisciplineOffering` reintroduz a relação **disciplina ↔ docente
  responsável**, que as PRDs anteriores conseguiram evitar. Ela entra
  aqui porque o fluxo depende dela em dois pontos: a classificação
  (US-011) e o portão do deferimento (US-012).
- Regras de transição vivem em métodos do model (ADR-002), como
  `Person.archive()`. Router não faz `try/except` de negócio — o handler
  central de `DomainError` já converte para 4xx.
- `services.py` para as operações multi-model: auto-registro (US-008),
  efetivação (US-014) e encerramento do ciclo (US-015).
- FK `program` direta em todos os models novos (ADR-007, decisão 5),
  senão `audit.record()` grava `program=None`.
- Uploads vão para `MEDIA_ROOT`, que já existe em `base.py`. **Isso é
  assunto novo para a infra**: backup e restauração de arquivos passam a
  fazer parte do plano, e não só o `pg_dump`.
- O endpoint de auto-registro é o primeiro público de escrita. Vale
  revisar com atenção: rate limit, e nenhuma resposta que permita
  descobrir se um e-mail já está cadastrado.

## 8. Success Metrics

- Um requerimento de isolada deixa de existir em formulário externo,
  e-mail de docente e planilha de vagas, e passa a ter registro único e
  auditável.
- A secretaria consegue ver, numa tela, quais ofertas ainda não foram
  classificadas — antes de o prazo acabar e a disciplina ficar vazia.
- Nenhum deferimento acima do número de vagas, garantido pelo sistema e
  não por conferência manual.
- Nenhuma matrícula efetivada sem pagamento ou isenção comprovada.

## 9. Open Questions

- **Conta própria × número de protocolo.** Esta PRD adota **conta com
  login**, que foi a resposta direta do usuário no levantamento. O
  protocolo oficial descreve o processo atual como acesso *"pelo
  protocolo recebido no ato da inscrição"*. O conflito foi levantado mas
  não foi fechado explicitamente — vale confirmar antes de rodar, porque
  muda a US-008 e a US-017.
- **Divergência de datas no próprio edital.** O texto corrido diz que a
  lista de aprovados sai até 12/08; a agenda diz deferidos em 11/08 e
  resultado final em 13/08. Confirmar com a secretaria qual vale.
- **Ciclo por programa ou institucional.** Esta PRD adota **por
  programa** (cada PPG publica seu edital), diferente de `AcademicTerm`,
  que é institucional. Se na prática houver um edital único da
  universidade, muda a US-001.
- **O que acontece se o docente classificar só parte dos candidatos.**
  A US-012 exige que a oferta esteja classificada, mas não define se
  classificação parcial conta. Recomendação: exigir que todos os itens
  `SUBMITTED` daquela oferta tenham `rank`.
- **Reaproveitamento de crédito.** O motivo de cursar isolada costuma ser
  aproveitar o crédito depois, ao entrar como aluno regular. O sistema
  registra que a pessoa cursou, mas não a aprovação (fica na UFMG). Se o
  processo seletivo precisar dessa informação, é levantamento próprio.
