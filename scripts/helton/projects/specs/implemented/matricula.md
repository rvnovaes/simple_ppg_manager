# PRD: Acerto de Matrícula (ajuste de disciplinas)

> **Revisão de 2026-08-05.** Alinhada ao **ADR-007**
> (`docs/adr/007-modalidade-e-situacao-do-aluno.md`) e à revisão de
> `tasks/prd-cadastros-basicos.md`. Resumo das mudanças no Apêndice A.

## 1. Introduction/Overview

A matrícula em disciplinas do PPGD em si é feita e mantida no sistema
oficial da UFMG: o aluno escolhe as disciplinas por lá, e o orientador
aprova por lá. Isso está fora do escopo do PPGD Manager.

O que falta suportar é o que a secretaria chama de **acerto de
matrícula**: quando um aluno já matriculado precisa mudar disciplinas
(excluir uma, incluir outra) depois do prazo normal, esse ajuste passa
por um fluxo de aprovação interno antes de a secretaria replicar a
mudança manualmente no sistema da UFMG. Hoje esse fluxo não existe em
lugar nenhum — é resolvido informalmente. Esta feature cria o registro e
o fluxo de aprovação dentro do PPGD Manager, para dar rastreabilidade
(quem pediu o quê, quando, e se o orientador aprovou ou recusou).

Se não há necessidade de acerto, esse fluxo nunca é acionado — a
matrícula segue inteiramente no sistema da UFMG.

**Dependência bloqueante:** esta PRD só pode ser executada depois de
`tasks/prd-cadastros-basicos.md`, que entrega `Teacher`, `Student`,
`AcademicTerm`, os grupos Docente e Discente, contas com senha
utilizável e o helper `current_program()`. Todos são usados aqui.

## 2. Goals

- Permitir que o aluno registre, dentro do PPGD Manager, um pedido de
  ajuste de disciplinas (incluir e/ou excluir), sem precisar de e-mail ou
  papel.
- Permitir que o orientador aprove ou recuse esse pedido, com motivo
  quando recusa, direto no sistema.
- Dar à secretaria e à coordenação uma visão de leitura de todos os
  pedidos e seus status, filtrável por período letivo, para saberem o que
  ainda precisa ser replicado manualmente no sistema da UFMG.
- Manter o registro de disciplinas do programa (catálogo de referência)
  cadastrável pela secretaria **em tela do front**, como manda o ADR-006.

## 3. User Stories

### US-001: Model de disciplina (catálogo de referência)
**Description:** Como secretaria, preciso manter um catálogo de
disciplinas do programa, para que o aluno possa escolher entre elas ao
pedir um acerto.

**Acceptance Criteria:**
- [ ] Model `Discipline` no app `programs`: `program` (FK,
      on_delete=PROTECT, related_name="disciplines"), `code`
      (CharField), `name` (CharField), `is_active` (BooleanField,
      default True).
- [ ] `UniqueConstraint` em (`program`, `code`).
- [ ] Registrado no Django Admin do app `programs` — **apenas como
      quebra-vidro de sysadmin** (ADR-006). O caminho de uso da
      secretaria é a tela da US-008, não o Admin.
- [ ] Migração criada e revisada (arquivo lido, não só gerado).
- [ ] Typecheck/lint passam.

### US-002: Models da solicitação de acerto e seus itens
**Description:** Como desenvolvedor, preciso de um model que represente
uma solicitação de acerto com uma ou mais alterações de disciplina, para
que o restante do fluxo (criação, aprovação, recusa) tenha onde
persistir.

**Acceptance Criteria:**
- [ ] Model `EnrollmentAdjustmentRequest` no app `academic`: `program`
      (FK para `programs.Program`, on_delete=PROTECT,
      related_name="enrollment_adjustments"), `student` (FK para
      `Student`, on_delete=PROTECT, related_name="enrollment_adjustments"),
      `term` (FK para `programs.AcademicTerm`, on_delete=PROTECT,
      related_name="enrollment_adjustments"), `status` (TextChoices
      OPEN/APPROVED/REJECTED = "Aberta"/"Aprovada"/"Recusada", default
      OPEN), `justification` (TextField, blank=True), `decision_note`
      (TextField, blank=True), `decided_at` (DateTimeField, null=True,
      blank=True), `created_at` (auto_now_add).
- [ ] A FK `program` é direta e obrigatória, ainda que alcançável por
      `student.program` — ADR-007, decisão 5 (sem ela, `audit.record()`
      grava `AuditLog` com `program=None`).
- [ ] A FK `term` existe porque o acerto é sempre relativo a um semestre:
      é ele que dá sentido à tela "o que falta replicar **neste**
      período" (US-011). Entidade criada em
      `tasks/prd-cadastros-basicos.md` (US-003).
- [ ] Model `EnrollmentAdjustmentItem`: `request` (FK,
      related_name="items", on_delete=CASCADE), `discipline` (FK para
      `programs.Discipline`, on_delete=PROTECT), `action` (TextChoices
      ADD/DROP = "Incluir"/"Excluir").
- [ ] `UniqueConstraint` em (`request`, `discipline`, `action`) — evita
      item duplicado no mesmo pedido.
- [ ] Método `approve(*, note="")`: só permitido a partir de `OPEN`;
      levanta `InvalidStateTransition` se já decidida. Preenche
      `decided_at`.
- [ ] Método `reject(*, note)`: só permitido a partir de `OPEN`; levanta
      `InvalidStateTransition` se já decidida; levanta `DomainError`
      (`code="rejection_requires_note"`) se `note` vazio. Preenche
      `decided_at`.
- [ ] Método `clean()` garante `program == student.program == term.program`;
      levanta `DomainError` (`code="program_mismatch"`).
- [ ] Teste de invariante em memória (sem banco), no padrão de
      `Person.archive()`: aprovar uma solicitação já decidida levanta
      erro; recusar sem motivo levanta erro; aprovar/recusar uma
      solicitação `OPEN` muda o status e carimba `decided_at`.
- [ ] Migração criada e revisada.
- [ ] Typecheck/lint passam.

### US-003: Permissões do fluxo nos papéis existentes
**Description:** Como sistema, preciso que os grupos de domínio tenham as
permissões do fluxo de acerto, para que a checagem de permissão funcione.

**Acceptance Criteria:**
- [ ] Nova data migration, no padrão de
      `apps/programs/migrations/0002_programa_inicial_e_papeis.py`, que
      **estende** os grupos existentes. Os quatro grupos (Secretaria,
      Coordenação, Docente, Discente) **já foram criados** em
      `tasks/prd-cadastros-basicos.md` (US-006) — esta migração não cria
      nenhum grupo.
- [ ] Discente ganha `academic.add_enrollmentadjustmentrequest`,
      `academic.view_enrollmentadjustmentrequest` e
      `programs.view_discipline`.
- [ ] Docente ganha `academic.view_enrollmentadjustmentrequest`,
      `academic.change_enrollmentadjustmentrequest` e
      `programs.view_discipline`.
- [ ] Secretaria ganha `academic.view_enrollmentadjustmentrequest`,
      `programs.view_discipline`, `programs.add_discipline` e
      `programs.change_discipline`.
- [ ] Coordenação ganha `academic.view_enrollmentadjustmentrequest` e
      `programs.view_discipline`.
- [ ] Nenhum grupo recebe `delete` (mesma decisão da PRD de cadastros
      básicos: solicitação recusada é registro histórico, não se apaga).
- [ ] Migração de dados revisada (lida e conferida, não só gerada).
- [ ] Typecheck/lint passam.

### US-004: Endpoints — catálogo de disciplinas
**Description:** Como secretaria, quero cadastrar e editar disciplinas
pela API, para manter o catálogo que o aluno usa ao pedir um acerto.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `DisciplineIn`/`DisciplineOut` em
      `apps/programs/schemas.py` (nunca serializar o model direto).
- [ ] `GET /api/v1/programs/disciplines/` (paginado, escopado por
      `current_program(request)`, filtro opcional por `is_active` e busca
      por `code`/`name`; `require_perm` com `programs.view_discipline`).
- [ ] `POST /api/v1/programs/disciplines/` (`require_perm` com
      `programs.add_discipline`; `program` vem de
      `current_program(request)`, não do payload; registra `AuditLog`
      `programs.discipline.create`).
- [ ] `PATCH /api/v1/programs/disciplines/{id}/` (`require_perm` com
      `programs.change_discipline`; registra `AuditLog`
      `programs.discipline.update`).
- [ ] Typecheck/lint passam.
- [ ] Tests pass.

### US-005: Endpoint — aluno cria solicitação
**Description:** Como aluno, quero abrir um pedido de acerto com uma ou
mais alterações de disciplina de uma vez, para não precisar abrir um
pedido separado por alteração.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `EnrollmentAdjustmentItemIn`/`Out` e
      `EnrollmentAdjustmentRequestIn`/`Out` em
      `apps/academic/schemas.py`.
- [ ] `POST /api/v1/academic/enrollment-requests/` recebe `term_id`,
      `justification` (opcional) e uma lista não vazia de itens
      (`discipline_id`, `action`).
- [ ] `require_perm(request, "academic.add_enrollmentadjustmentrequest")`
      na primeira linha.
- [ ] Checagem explícita adicional: o `Student` do payload é o mesmo
      vinculado ao `Person`/`User` autenticado — aluno só cria
      solicitação para si mesmo, nunca para outro aluno (levanta
      `NotAllowed` caso contrário).
- [ ] **Bloqueio de solicitação sem quem decida**: se o `Student` não tem
      `advisor`, levanta `DomainError` (`code="advisor_required"`, 409)
      com mensagem clara. Sem isso a solicitação nasce presa, porque só o
      orientador pode decidi-la (US-006).
- [ ] **Restrição de modalidade**: só `Student` com `modality = REGULAR`
      pode abrir acerto — isolada e eletiva não têm matrícula de grau a
      ajustar nem orientador. Levanta `DomainError`
      (`code="regular_students_only"`, 409). A regra decorre do ADR-007.
- [ ] Cria a solicitação e os itens numa `transaction.atomic()`; registra
      `AuditLog` (`academic.enrollment_adjustment.create`).
- [ ] Resposta via schema explícito, nunca serializando o model direto.
- [ ] Typecheck/lint passam.
- [ ] Tests pass (inclusive os dois bloqueios acima e a tentativa de
      criar em nome de outro aluno).

### US-006: Endpoint — orientador aprova ou recusa
**Description:** Como orientador, quero aprovar ou recusar (com motivo)
um pedido de acerto de um dos meus orientandos, para que a secretaria
saiba se deve replicar a mudança no sistema da UFMG.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/enrollment-requests/{id}/approve` e
      `POST /api/v1/academic/enrollment-requests/{id}/reject` (recebe
      `note` obrigatório no reject).
- [ ] `require_perm(request, "academic.change_enrollmentadjustmentrequest")`
      na primeira linha de ambas.
- [ ] Checagem explícita adicional: o usuário autenticado é exatamente o
      `Teacher` que é `advisor` do `student` daquela solicitação — levanta
      `NotAllowed` se for outro docente, mesmo que tenha a permissão de
      grupo.
- [ ] Transição inválida (solicitação já decidida) retorna 409 via
      `InvalidStateTransition`, sem try/except no router (regra mora no
      model).
- [ ] `transaction.atomic()` com `save(update_fields=[...])` +
      `AuditLog` (`academic.enrollment_adjustment.approve` / `.reject`).
- [ ] Typecheck/lint passam.
- [ ] Tests pass.

### US-007: Endpoint — listagem escopada por papel
**Description:** Como usuário do sistema (aluno, orientador, secretaria
ou coordenação), quero ver as solicitações relevantes pra mim, sem
precisar de telas separadas por papel no backend.

**Acceptance Criteria:**
- [ ] `GET /api/v1/academic/enrollment-requests/` escopa primeiro por
      `current_program(request)` e depois filtra pelo papel de quem
      pergunta: aluno vê só as suas; orientador vê as dos seus orientandos
      (`student__advisor__person__user=request.user`);
      secretaria/coordenação veem todas as do programa.
- [ ] O escopo de programa vem de `current_program(request)`
      (`apps/core/tenancy.py`, entregue em
      `tasks/prd-cadastros-basicos.md` US-008) — não de `program_id` no
      query string.
- [ ] Filtros opcionais por `status` e `term_id`.
- [ ] `require_perm(request, "academic.view_enrollmentadjustmentrequest")`
      na primeira linha.
- [ ] Paginado, seguindo o padrão de `list_people`
      (`apps/people/router.py`).
- [ ] Typecheck/lint passam.
- [ ] Tests pass (um teste por papel, verificando que cada um vê
      exatamente o conjunto esperado).

### US-008: Tela Svelte — catálogo de disciplinas
**Description:** Como secretaria, quero uma tela para cadastrar e editar
as disciplinas do programa, sem depender do Django Admin.

**Acceptance Criteria:**
- [ ] `make gen-api` rodado (backend de pé) antes de tipar a tela.
- [ ] Lista de disciplinas com busca por código/nome e filtro de ativas.
- [ ] Formulário de criar/editar (`code`, `name`, `is_active`).
- [ ] Coordenação, Docente e Discente veem a tela em modo somente leitura
      (ou não veem o item de menu, se não tiverem `view_discipline`).
- [ ] Toda chamada via `lib/api/client.ts` tipado (`fetch` cru proibido).
- [ ] Typecheck (svelte-check) passa.
- [ ] Verify in browser using dev-browser skill.

### US-009: Tela Svelte — aluno abre solicitação
**Description:** Como aluno, quero uma tela para escolher disciplinas do
catálogo, marcar incluir/excluir, justificar e acompanhar o status dos
meus pedidos.

**Acceptance Criteria:**
- [ ] Formulário com seletor de período letivo e lista de disciplinas do
      catálogo, com opção incluir/excluir por disciplina.
- [ ] Campo de justificativa opcional.
- [ ] Lista das solicitações do próprio aluno com status (Aberta/
      Aprovada/Recusada) e, quando recusada, o motivo visível.
- [ ] Se o aluno não tem orientador, a tela explica isso e desabilita o
      envio, em vez de deixar o backend recusar com 409
      (`advisor_required`) depois de o formulário todo ser preenchido.
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passa.
- [ ] Verify in browser using dev-browser skill.

### US-010: Tela Svelte — orientador aprova ou recusa
**Description:** Como orientador, quero uma tela listando os pedidos
pendentes dos meus orientandos, com ação de aprovar ou recusar.

**Acceptance Criteria:**
- [ ] Lista de solicitações pendentes (status `OPEN`) dos orientandos do
      orientador logado, visível logo na entrada da área dele (não
      enterrada em submenu) — é ação recorrente e sensível a prazo.
- [ ] Ação de aprovar (nota opcional) e recusar (nota obrigatória, com
      validação no front antes de enviar).
- [ ] Após a decisão, a lista atualiza sem exigir refresh manual.
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passa.
- [ ] Verify in browser using dev-browser skill: golden path (aluno cria
      → orientador aprova) e caminho de recusa (orientador recusa com
      motivo → aluno vê o motivo).

### US-011: Tela Svelte — leitura para secretaria e coordenação
**Description:** Como secretaria/coordenação, quero uma tela somente
leitura com todas as solicitações do programa, para saber o que ainda
precisa ser replicado manualmente no sistema da UFMG.

**Acceptance Criteria:**
- [ ] Lista todas as solicitações do programa com aluno, orientador,
      período, itens, status e data de decisão.
- [ ] Filtro por status (Aberta/Aprovada/Recusada) e por período letivo.
- [ ] Tela é somente leitura (sem ação de aprovar/recusar/editar).
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passa.
- [ ] Verify in browser using dev-browser skill.

## 4. Functional Requirements

1. O sistema deve permitir a um aluno autenticado criar uma solicitação
   de acerto, referente a um período letivo, contendo uma ou mais
   alterações de disciplina (inclusão e/ou exclusão) em um único pedido.
2. O sistema deve impedir que um aluno crie uma solicitação em nome de
   outro aluno.
3. O sistema deve impedir que um aluno sem orientador definido crie uma
   solicitação, com erro explícito, para não gerar pedido que ninguém
   pode decidir.
4. O sistema deve restringir o fluxo de acerto a alunos de modalidade
   Regular.
5. O sistema deve permitir que o orientador do aluno aprove a
   solicitação, opcionalmente com uma nota.
6. O sistema deve permitir que o orientador do aluno recuse a
   solicitação, exigindo uma nota com o motivo.
7. O sistema deve impedir que qualquer docente que não seja o orientador
   daquele aluno específico aprove ou recuse a solicitação, mesmo tendo
   a permissão de grupo Docente.
8. O sistema deve impedir decidir (aprovar/recusar) uma solicitação que
   já foi decidida anteriormente (transição inválida, HTTP 409).
9. O sistema deve manter um catálogo de disciplinas por programa, com
   código único por programa, mantido pela secretaria em tela do front.
10. O sistema deve listar as solicitações escopadas pelo programa
    corrente e pelo papel de quem pergunta: aluno vê as suas, orientador
    vê as de seus orientandos, secretaria/coordenação veem todas as do
    programa.
11. Toda criação, aprovação e recusa de solicitação deve gerar um
    `AuditLog` com a chave de programa preenchida.
12. O sistema NÃO deve tentar replicar a alteração no sistema da UFMG —
    essa etapa continua manual, fora do PPGD Manager.

## 5. Non-Goals (Out of Scope)

- Não há rastreio, dentro do sistema, de que a secretaria já replicou a
  mudança aprovada no sistema da UFMG — aprovação do orientador encerra
  o ciclo no PPGD Manager; a replicação é controle manual externo.
- Sem coorientador no fluxo de aprovação (só o orientador único de
  `Student.advisor` decide).
- Sem notificação por e-mail — o orientador vê pendências na lista
  in-app. O projeto não tem `EMAIL_BACKEND` configurado, e adicionar SMTP
  é decisão adiada com a infra.
- Sem sincronização automática do catálogo `Discipline` com a UFMG — é
  cadastro manual da secretaria.
- Sem reabertura de solicitação recusada — o aluno abre uma nova
  solicitação; a recusada permanece como registro histórico.
- Sem edição nem cancelamento de uma solicitação já criada pelo aluno —
  para mudar os itens, abre outra.
- Sem acerto para alunos de modalidade Isolada ou Eletiva — a matrícula
  em isolada nasce de um fluxo próprio (fora desta PRD e da de cadastros
  básicos) e não tem orientador que decida.
- Sem registro de quais disciplinas o aluno efetivamente cursa — o
  catálogo é referência para o pedido, não um histórico escolar. O
  histórico vive na UFMG.
- Sem processo seletivo / conversão de candidato em aluno.

## 6. Design Considerations

- Reaproveitar o padrão visual e de formulário já usado nas telas Svelte
  existentes (Tailwind v4, runas do Svelte 5).
- A lista de solicitações pendentes do orientador deve ficar visível logo
  na entrada da área dele.
- O vocabulário das telas usa "Aberta/Aprovada/Recusada" para o aluno e
  o orientador. (A secretaria usa "deferir/indeferir" no contexto de
  inscrição em disciplina isolada, que é outro fluxo, de outra PRD — não
  misturar os dois vocabulários.)

## 7. Technical Considerations

- `Discipline` entra em `apps/programs` (estrutura do programa, como
  `Program` e `AcademicTerm`); o restante entra em `apps/academic`
  (junto de `Teacher`/`Student`).
- **Pré-requisitos entregues por `tasks/prd-cadastros-basicos.md`**, e
  usados aqui sem serem recriados: `Teacher`, `Student`, `AcademicTerm`,
  os grupos Docente e Discente, contas com senha utilizável (US-007) e
  `current_program()` (US-008).
- `EnrollmentAdjustmentRequest` carrega FK `program` direta, como todo
  model de negócio do projeto (ADR-007, decisão 5), para que
  `apps.core.audit.record()` não grave `AuditLog` com `program=None`.
- `DomainError` e subclasses (`apps/core/exceptions.py`): reaproveitar
  `InvalidStateTransition` para decisão duplicada; `rejection_requires_note`,
  `advisor_required` e `regular_students_only` podem ser `DomainError`
  com `code=` explícito, sem subclasse nova.
- `require_perm` (`apps/core/permissions.py`) cobre só a permissão de
  grupo; a posse (aluno é dono / docente é o orientador daquele aluno) é
  checagem adicional explícita no router, no mesmo espírito da Seção 5 do
  CLAUDE.md.
- `AuditLog` via `apps.core.audit.record(event, request=, target=)` —
  nunca instanciar `AuditLog` direto.
- Regra de transição de estado vive em método do próprio model
  (`approve()`/`reject()`), no padrão de `Person.archive()` — não em
  service, porque a operação toca só um model.
- `services.py` do app `academic` é usado na **criação** (solicitação +
  itens + auditoria numa transação), não na decisão.

## 8. Success Metrics

- Um pedido de acerto sai do "resolvido informalmente por e-mail/papel"
  e passa a ter registro rastreável no sistema, com autor, decisão e
  motivo.
- Secretaria consegue, numa única tela, filtrar por período e ver todas
  as solicitações aprovadas que ainda precisam ser replicadas na UFMG.
- Zero solicitação decidida duas vezes (garantido pelo invariante do
  model, não por convenção de uso).
- Zero solicitação criada sem orientador que possa decidi-la.

## 9. Open Questions

- **Quem mantém o catálogo `Discipline` atualizado e com que
  frequência** — a secretaria digita manualmente toda mudança de oferta
  da UFMG? Se o volume for alto, importação por planilha vira candidata a
  PRD própria.
- **Prazo do acerto.** O acerto acontece dentro de uma janela do
  calendário? Se sim, `AcademicTerm` precisaria de datas de início e fim
  do período de acerto, e a criação seria bloqueada fora dela. Não
  levantado com o usuário; hoje não há restrição de data.
- **`term` obrigatório na solicitação** foi introduzido nesta revisão
  (não estava na versão anterior). Se na prática a secretaria não pensa o
  acerto por semestre, é remover a FK antes de rodar — barato agora,
  caro depois.

## Apêndice A — O que mudou nesta revisão

Mudanças em relação à versão de 2026-08-05 (commit `a4852cc`):

| # | Mudança | Origem |
|---|---|---|
| 1 | `Discipline` ganha tela Svelte (US-004 + US-008); Admin passa a ser só quebra-vidro | violava o ADR-006 |
| 2 | US-003 apenas **estende** grupos; Docente/Discente passam a nascer na PRD de cadastros básicos | dependência circular entre as duas PRDs |
| 3 | FK `program` direta em `EnrollmentAdjustmentRequest` | corrige `AuditLog` com `program=None` |
| 4 | FK `term` em `EnrollmentAdjustmentRequest` | `AcademicTerm` passou a existir (ADR-007); dá sentido à tela da secretaria |
| 5 | Aluno sem orientador é bloqueado na criação (`advisor_required`) | era pergunta aberta que gerava solicitação presa |
| 6 | Só aluno `modality=REGULAR` abre acerto | decorre do ADR-007 |
| 7 | Listagem escopada por `current_program()` | "todas as do programa" não tinha implementação possível |
| 8 | Telas Svelte viram três US separadas + a do catálogo | alinha a numeração do PRD com a do `prd.matricula.json` |
| 9 | Numeração de US refeita (7 → 11) | inserção da US-004 e separação das telas |
