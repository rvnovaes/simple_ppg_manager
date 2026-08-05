# PRD: Acerto de Matrícula (ajuste de disciplinas)

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

## 2. Goals

- Permitir que o aluno registre, dentro do PPGD Manager, um pedido de
  ajuste de disciplinas (incluir e/ou excluir), sem precisar de e-mail ou
  papel.
- Permitir que o orientador aprove ou recuse esse pedido, com motivo
  quando recusa, direto no sistema.
- Dar à secretaria e à coordenação uma visão de leitura de todos os
  pedidos e seus status, para saberem o que ainda precisa ser replicado
  manualmente no sistema da UFMG.
- Manter o registro de disciplinas do programa (catálogo de referência)
  cadastrável pela secretaria.

## 3. User Stories

### US-001: Cadastro de disciplina (catálogo de referência)
**Description:** Como secretaria, preciso manter um catálogo de
disciplinas do programa, para que o aluno possa escolher entre elas ao
pedir um acerto.

**Acceptance Criteria:**
- [ ] Model `Discipline` no app `programs`: `program` (FK), `code`,
      `name`, `is_active` (default `True`).
- [ ] Constraint de unicidade em (`program`, `code`).
- [ ] Migração criada e revisada.
- [ ] Visível e editável no Django Admin (é dado estrutural do programa,
      mas cadastrado pela secretaria — decidir se entra como tela Svelte
      simples ou fica temporariamente no Admin; ver Open Questions).
- [ ] Typecheck/lint passam.

### US-002: Model da solicitação de acerto e seus itens
**Description:** Como desenvolvedor, preciso de um model que represente
uma solicitação de acerto com uma ou mais alterações de disciplina, para
que o restante do fluxo (criação, aprovação, recusa) tenha onde
persistir.

**Acceptance Criteria:**
- [ ] Model `EnrollmentAdjustmentRequest` no app `academic`: `student`
      (FK), `status` (`OPEN`/`APPROVED`/`REJECTED`, default `OPEN`),
      `justification` (opcional), `decision_note` (opcional),
      `decided_at` (opcional), `created_at`.
- [ ] Model `EnrollmentAdjustmentItem`: `request` (FK, `related_name=
      "items"`), `discipline` (FK para `Discipline`), `action`
      (`ADD`/`DROP`).
- [ ] Constraint de unicidade em (`request`, `discipline`, `action`) —
      evita item duplicado no mesmo pedido.
- [ ] Método `approve(*, note="")`: só permitido a partir de `OPEN`;
      levanta `InvalidStateTransition` se já decidida.
- [ ] Método `reject(*, note)`: só permitido a partir de `OPEN`; levanta
      `InvalidStateTransition` se já decidida; levanta `DomainError`
      (`code="rejection_requires_note"`) se `note` vazio.
- [ ] Teste de invariante em memória (sem banco), no padrão de
      `Person.archive()`: aprovar uma solicitação já decidida levanta
      erro; recusar sem motivo levanta erro; aprovar/recusar uma
      solicitação `OPEN` muda o status corretamente.
- [ ] Migração criada e revisada.
- [ ] Typecheck/lint passam.

### US-003: Papéis Docente e Discente
**Description:** Como sistema, preciso que professores e alunos tenham
grupo próprio com as permissões corretas, para que a checagem de
permissão do fluxo de acerto funcione (hoje só existem os grupos
Secretaria e Coordenação).

**Acceptance Criteria:**
- [ ] Data migration cria grupos **Docente** e **Discente**, seguindo o
      padrão de `apps/programs/migrations/0002_programa_inicial_e_papeis.py`.
- [ ] Discente: `academic.add_enrollmentadjustmentrequest`,
      `academic.view_enrollmentadjustmentrequest`.
- [ ] Docente: `academic.view_enrollmentadjustmentrequest`,
      `academic.change_enrollmentadjustmentrequest`.
- [ ] Secretaria (grupo já existente) ganha
      `academic.view_enrollmentadjustmentrequest` e
      `programs.view_discipline`; e `programs.add_discipline` /
      `programs.change_discipline` para manter o catálogo.
- [ ] Coordenação (grupo já existente) ganha
      `academic.view_enrollmentadjustmentrequest`.
- [ ] Migração de dados revisada (lida e conferida, não só gerada).

### US-004: Endpoint — aluno cria solicitação
**Description:** Como aluno, quero abrir um pedido de acerto com uma ou
mais alterações de disciplina de uma vez, para não precisar abrir um
pedido separado por alteração.

**Acceptance Criteria:**
- [ ] `POST /api/v1/academic/enrollment-requests/` recebe `justification`
      (opcional) e uma lista de itens (`discipline_id`, `action`).
- [ ] `require_perm(request, "academic.add_enrollmentadjustmentrequest")`
      na primeira linha.
- [ ] Checagem explícita adicional: o `Student` do payload é o mesmo
      vinculado ao `Person`/`User` autenticado — aluno só cria solicitação
      para si mesmo, nunca para outro aluno (levanta `NotAllowed` caso
      contrário).
- [ ] Cria a solicitação e os itens numa `transaction.atomic()`; registra
      `AuditLog` (`academic.enrollment_adjustment.create`).
- [ ] Resposta via schema explícito (`EnrollmentAdjustmentRequestOut`),
      nunca serializando o model direto.
- [ ] Typecheck/lint passam.

### US-005: Endpoint — orientador aprova ou recusa
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
      `AuditLog` (`academic.enrollment_adjustment.approve` /
      `.reject`).
- [ ] Typecheck/lint passam.

### US-006: Endpoint — listagem escopada por papel
**Description:** Como usuário do sistema (aluno, orientador, secretaria
ou coordenação), quero ver as solicitações relevantes pra mim, sem
precisar de telas separadas por papel no backend.

**Acceptance Criteria:**
- [ ] `GET /api/v1/academic/enrollment-requests/` filtra o queryset pelo
      papel de quem pergunta: aluno vê só as suas; orientador vê as dos
      seus orientandos (`student__advisor__person__user=request.user`);
      secretaria/coordenação veem todas as do programa.
- [ ] Paginado, seguindo o padrão de `list_people`
      (`apps/people/router.py:24-31`).
- [ ] Typecheck/lint passam.

### US-007: Telas Svelte (aluno, orientador, secretaria/coordenação)
**Description:** Como usuário do sistema, quero acessar esse fluxo pela
tela, não por chamada de API manual.

**Acceptance Criteria:**
- [ ] Tela do aluno: formulário para escolher disciplinas do catálogo,
      marcar incluir/excluir, justificativa opcional, listar suas
      solicitações e status.
- [ ] Tela do orientador: lista de solicitações pendentes dos seus
      orientandos, com ação de aprovar/recusar (motivo obrigatório na
      recusa).
- [ ] Tela de leitura para secretaria/coordenação: todas as solicitações
      do programa com status, filtrável.
- [ ] Toda chamada via `lib/api/client.ts` tipado (`fetch` cru proibido).
- [ ] `schema.d.ts` regenerado (`make gen-api`) antes de tipar as telas.
- [ ] Typecheck (svelte-check) passa.
- [ ] Verificado no navegador usando a skill dev-browser: golden path
      (aluno cria → orientador aprova) e o caminho de recusa (orientador
      recusa com motivo → aluno vê o motivo).

## 4. Functional Requirements

1. O sistema deve permitir a um aluno autenticado criar uma solicitação
   de acerto contendo uma ou mais alterações de disciplina (inclusão
   e/ou exclusão) em um único pedido.
2. O sistema deve impedir que um aluno crie uma solicitação em nome de
   outro aluno.
3. O sistema deve permitir que o orientador do aluno aprove a
   solicitação, opcionalmente com uma nota.
4. O sistema deve permitir que o orientador do aluno recuse a
   solicitação, exigindo uma nota com o motivo.
5. O sistema deve impedir que qualquer docente que não seja o orientador
   daquele aluno específico aprove ou recuse a solicitação, mesmo tendo
   a permissão de grupo Docente.
6. O sistema deve impedir decidir (aprovar/recusar) uma solicitação que
   já foi decidida anteriormente (transição inválida, HTTP 409).
7. O sistema deve manter um catálogo de disciplinas por programa
   (`Discipline`), com código único por programa, mantido pela
   secretaria.
8. O sistema deve listar as solicitações de forma escopada por papel:
   aluno vê as suas, orientador vê as de seus orientandos,
   secretaria/coordenação veem todas as do programa.
9. Toda criação, aprovação e recusa de solicitação deve gerar um
   `AuditLog` (quem, quando, o quê, alvo).
10. O sistema NÃO deve tentar replicar a alteração no sistema da UFMG —
    essa etapa continua manual, fora do PPGD Manager.

## 5. Non-Goals (Out of Scope)

- Não há rastreio, dentro do sistema, de que a secretaria já replicou a
  mudança aprovada no sistema da UFMG — aprovação do orientador encerra
  o ciclo no PPGD Manager; a replicação é controle manual externo.
- Sem coorientador no fluxo de aprovação (só o orientador único de
  `Student.advisor` decide).
- Sem notificação por e-mail — o orientador vê pendências na lista
  in-app.
- Sem sincronização automática do catálogo `Discipline` com a UFMG — é
  cadastro manual da secretaria.
- Sem reabertura de solicitação recusada — o aluno abre uma nova
  solicitação; a recusada permanece como registro histórico.
- Sem processo seletivo / conversão de candidato em aluno (módulo
  separado, fora desta PRD).
- Sem edição de uma solicitação já criada pelo aluno (para mudar os
  itens, cancela — se necessário — e abre outra; não há fluxo de edição
  nesta primeira versão).

## 6. Design Considerations

- Reaproveitar o padrão visual e de formulário já usado nas telas
  Svelte existentes (Tailwind v4, runas do Svelte 5).
- Lista de solicitações pendentes do orientador deve ficar visível logo
  na entrada da área dele (não enterrada em submenu), já que é uma ação
  recorrente e sensível a prazo.

## 7. Technical Considerations

- Seguir o padrão de app do projeto: `Discipline` entra em
  `apps/programs` (estrutura do programa, como `Program`); o restante
  entra em `apps/academic` (junto com `Teacher`/`Student`, que devem
  existir antes desta feature — ver PRD/cadastro básico de
  professores e alunos).
- `DomainError` e subclasses (`apps/core/exceptions.py`): reaproveitar
  `InvalidStateTransition` para decisão duplicada; criar exceção nova só
  se `rejection_requires_note` precisar de um `code` estável próprio
  (pode ser `DomainError` genérico com `code=` explícito, sem precisar de
  subclasse nova).
- `require_perm` (`apps/core/permissions.py`) cobre só a permissão de
  grupo; a posse (aluno é dono / docente é o orientador daquele aluno) é
  checagem adicional explícita no router, no mesmo espírito da Seção 5 do
  CLAUDE.md.
- `AuditLog` via `apps.core.audit.record(event, request=, target=)` —
  nunca instanciar `AuditLog` direto.
- Regra de transição de estado vive em método do próprio model
  (`approve()`/`reject()`), no padrão de `Person.archive()`
  (`apps/people/models.py`) — não em service, porque a operação toca só
  um model (mais os itens relacionados, que são criados junto na mesma
  transação de criação, não em cada aprovação/recusa).
- `services.py` só é necessário se aprovar/recusar precisar,
  futuramente, mexer em outro model (ex.: gerar automaticamente um
  registro de disciplina cursada) — não é o caso nesta primeira versão.
- Grupos "Docente" e "Discente" seguem o padrão de data migration de
  `apps/programs/migrations/0002_programa_inicial_e_papeis.py`.

## 8. Success Metrics

- Um pedido de acerto sai do "resolvido informalmente por e-mail/papel"
  e passa a ter registro rastreável no sistema, com autor, decisão e
  motivo.
- Secretaria consegue, olhando uma única tela, ver todas as solicitações
  aprovadas que ainda precisam ser replicadas manualmente na UFMG (via
  filtro de status).
- Zero solicitação decidida duas vezes (garantido pelo invariante do
  model, não por convenção de uso).

## 9. Open Questions

- Quem mantém o catálogo `Discipline` atualizado e com que frequência —
  a secretaria digita manualmente toda mudança de oferta de disciplinas
  da UFMG?
- O que acontece se o aluno não tiver orientador definido
  (`Student.advisor` nulo) e tentar abrir uma solicitação — bloqueia a
  criação com uma mensagem clara, ou permite criar e a solicitação fica
  sem ninguém que possa decidir? (Recomendação: bloquear na criação com
  `DomainError` explícito, para não gerar solicitação "presa".)
- O cadastro de `Discipline` deve ter tela Svelte própria (US-001 hoje
  aponta pro Admin como opção temporária), ou já nasce como tela de
  secretaria, seguindo a regra geral do CLAUDE.md de que todo cadastro
  usado por usuário de negócio vai para o front? (Recomendação: como é
  usuário de negócio — secretaria — mantendo a regra da Seção 2 do
  CLAUDE.md, deveria ser tela Svelte, não Admin; ajustar US-001 quando
  isso for confirmado.)
