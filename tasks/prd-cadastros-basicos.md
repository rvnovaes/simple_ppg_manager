# PRD: Cadastros Básicos — Professores e Alunos

## 1. Introduction/Overview

O PPGD Manager já tem a fundação de identidade (`Person`, `Program`,
`User`), mas nenhum model representa os dois papéis centrais do domínio:
**professor (docente)** e **aluno (discente)**. Esta PRD cria o primeiro
módulo de negócio real do sistema: o app `academic`, com os cadastros
básicos de `Teacher` e `Student`, mais a estrutura de programa que os dois
referenciam — linhas de pesquisa e projetos coletivos.

Sem isso, nenhum outro módulo de negócio (incluindo o fluxo de acerto de
matrícula já especificado em `tasks/prd-matricula.md`) pode ser
implementado, porque todos dependem de `Teacher`/`Student` existirem.

## 2. Goals

- Cadastrar professores com a categoria CAPES (Permanente/Colaborador/
  Visitante), credenciamento, titulação e vínculo com linhas de pesquisa
  e projetos coletivos.
- Cadastrar alunos com nível (mestrado/doutorado), orientador, projeto
  coletivo, situação acadêmica e prazo regimental (com default calculado
  e prorrogação editável).
- Dar à Secretaria a capacidade de criar e editar professores e alunos
  pela tela do sistema (nunca pelo Django Admin — ADR-006), e à
  Coordenação a visão de leitura.
- Modelar linhas de pesquisa e os projetos coletivos vinculados a elas,
  já que professores e alunos se organizam em torno dessa estrutura.

## 3. User Stories

### US-001: Model de Linha de Pesquisa
**Description:** Como secretaria, preciso cadastrar as linhas de pesquisa
do programa, para que professores e projetos coletivos possam ser
vinculados a elas.

**Acceptance Criteria:**
- [ ] Model `ResearchLine` no app `programs`: `program` (FK, on_delete=
      PROTECT), `name` (CharField), `is_active` (BooleanField, default
      True).
- [ ] Registrado no Django Admin do app `programs`.
- [ ] Migração criada e revisada (arquivo lido, não só gerado).
- [ ] Typecheck passes.

### US-002: Model de Projeto Coletivo
**Description:** Como secretaria, preciso cadastrar os projetos
coletivos de cada linha de pesquisa, já que uma linha tem vários
projetos.

**Acceptance Criteria:**
- [ ] Model `CollectiveProject` no app `programs`: `research_line` (FK
      para `ResearchLine`, on_delete=PROTECT, related_name="projects"),
      `name` (CharField), `is_active` (BooleanField, default True).
- [ ] Registrado no Django Admin do app `programs` (com `research_line`
      visível em `list_display`).
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.

### US-003: App `academic` e model Teacher
**Description:** Como secretaria, preciso cadastrar um professor com
categoria CAPES, credenciamento, titulação e vínculo com linhas de
pesquisa e projetos, para manter o quadro docente do programa.

**Acceptance Criteria:**
- [ ] App `academic` criado seguindo a estrutura padrão do projeto
      (`models.py`, `admin.py`, `router.py`, `schemas.py`, `migrations/`,
      `tests/`), registrado em `INSTALLED_APPS`.
- [ ] Model `Teacher`: `person` (OneToOneField para `people.Person`,
      on_delete=PROTECT, related_name="teacher_profile"), `category`
      (TextChoices PERMANENT/COLLABORATOR/VISITING = "Permanente"/
      "Colaborador"/"Visitante"), `accredited_since` (DateField),
      `accredited_until` (DateField, null=True, blank=True),
      `academic_degree` (TextChoices DOCTORATE/POSTDOCTORATE/
      HABILITATION = "Doutor"/"Pós-doutor"/"Livre-docente"), `lattes_url`
      (URLField, blank=True), `home_institution` (CharField, blank=True),
      `research_lines` (ManyToManyField para `programs.ResearchLine`,
      related_name="teachers", blank=True), `projects`
      (ManyToManyField para `programs.CollectiveProject`,
      related_name="teachers", blank=True).
- [ ] Registrado no Django Admin do app `academic`.
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.

### US-004: Model Student
**Description:** Como secretaria, preciso cadastrar um aluno com nível,
projeto coletivo, orientador (opcional), situação e prazo regimental,
para acompanhar a vida acadêmica dele no programa.

**Acceptance Criteria:**
- [ ] Model `Student` no app `academic`: `person` (OneToOneField para
      `people.Person`, on_delete=PROTECT, related_name="student_profile"),
      `level` (TextChoices MASTERS/DOCTORATE = "Mestrado"/"Doutorado"),
      `project` (FK para `programs.CollectiveProject`, on_delete=PROTECT,
      related_name="students" — **obrigatória**, não nula), `advisor`
      (FK para `Teacher`, on_delete=PROTECT, related_name="advisees",
      null=True, blank=True — **opcional**), `registration_number`
      (CharField, max_length=30, null=True, blank=True, unique=True —
      número de matrícula global da UFMG, preenchido só depois que a
      universidade o gera), `status` (TextChoices REGULAR/LEAVE/
      ISOLATED/ELECTIVE/EXCLUDED = "Regular"/"Trancado"/"Isolada"/
      "Eletiva"/"Excluído", default REGULAR), `admission_date`
      (DateField), `deadline` (DateField — ver regra de cálculo abaixo),
      `defense_date` (DateField, null=True, blank=True).
- [ ] Regra de `deadline`: se não informado na criação, calcular
      automaticamente como `admission_date` + 24 meses (se `level ==
      MASTERS`) ou + 48 meses (se `level == DOCTORATE`); implementar como
      método no próprio model (ex.: `default_deadline()` chamado em
      `save()` quando `deadline` for `None`) — depois de criado, o campo
      é livremente editável (prorrogação = editar o valor).
- [ ] Sem regra de transição bloqueada em `status` (troca livre entre
      quaisquer valores) — não implementar método de validação de
      transição para este campo.
- [ ] Registrado no Django Admin do app `academic`.
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.
- [ ] Tests pass (teste em memória, sem banco: criar um `Student` sem
      `deadline` informado e verificar que o valor calculado bate com a
      regra de 24/48 meses por nível).

### US-005: Permissões — Secretaria e Coordenação nos novos models
**Description:** Como sistema, preciso que os grupos já existentes
(Secretaria, Coordenação) tenham as permissões corretas nos quatro novos
models, para que o padrão de autorização do projeto (`require_perm`)
funcione nas rotas que serão criadas.

**Acceptance Criteria:**
- [ ] Nova data migration (não editar a `0002_...` já aplicada) estende
      o grupo **Secretaria** com `add`/`change`/`view` em `ResearchLine`,
      `CollectiveProject`, `Teacher` e `Student`.
- [ ] Estende o grupo **Coordenação** com `view` em `ResearchLine`,
      `CollectiveProject`, `Teacher` e `Student`.
- [ ] Migração de dados revisada (arquivo lido, não só gerado).
- [ ] Typecheck passes.

### US-006: Endpoints — Linha de Pesquisa
**Description:** Como secretaria, quero cadastrar e editar linhas de
pesquisa pela API, para popular a estrutura que professores e projetos
vão referenciar.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `ResearchLineIn`/`ResearchLineOut` em
      `apps/programs/schemas.py` (nunca serializar o model direto).
- [ ] `GET /api/v1/programs/research-lines/` (paginado, `require_perm`
      com `programs.view_researchline`).
- [ ] `POST /api/v1/programs/research-lines/` (`require_perm` com
      `programs.add_researchline`).
- [ ] `PATCH /api/v1/programs/research-lines/{id}/` (`require_perm` com
      `programs.change_researchline`).
- [ ] Router registrado na `NinjaAPI` raiz (`backend/api.py`).
- [ ] Typecheck passes.
- [ ] Tests pass.

### US-007: Endpoints — Projeto Coletivo
**Description:** Como secretaria, quero cadastrar e editar projetos
coletivos vinculados a uma linha de pesquisa pela API.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `CollectiveProjectIn`/`CollectiveProjectOut`
      em `apps/programs/schemas.py`.
- [ ] `GET /api/v1/programs/collective-projects/` (paginado, filtro
      opcional por `research_line_id`, `require_perm` com
      `programs.view_collectiveproject`).
- [ ] `POST /api/v1/programs/collective-projects/` (`require_perm` com
      `programs.add_collectiveproject`).
- [ ] `PATCH /api/v1/programs/collective-projects/{id}/` (`require_perm`
      com `programs.change_collectiveproject`).
- [ ] Typecheck passes.
- [ ] Tests pass.

### US-008: Endpoints — Professor
**Description:** Como secretaria, quero cadastrar e editar professores
pela API, incluindo seus vínculos de linha de pesquisa e projeto.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `TeacherIn`/`TeacherOut` em
      `apps/academic/schemas.py` (`TeacherOut` inclui `person` embutido —
      nome, e-mail — sem serializar `Person` direto).
- [ ] `GET /api/v1/academic/teachers/` (paginado, filtro opcional por
      `category`, `require_perm` com `academic.view_teacher`).
- [ ] `POST /api/v1/academic/teachers/` (cria `Person` + `Teacher` numa
      `transaction.atomic()` — operação multi-model, então usa
      `services.py` seguindo o padrão de
      `create_person_with_user` em `apps/people/services.py`;
      `require_perm` com `academic.add_teacher`; registra `AuditLog`
      `academic.teacher.create`).
- [ ] `PATCH /api/v1/academic/teachers/{id}/` (`require_perm` com
      `academic.change_teacher`; registra `AuditLog`
      `academic.teacher.update`).
- [ ] Router registrado na `NinjaAPI` raiz.
- [ ] Typecheck passes.
- [ ] Tests pass.

### US-009: Endpoints — Aluno
**Description:** Como secretaria, quero cadastrar e editar alunos pela
API, incluindo projeto obrigatório e orientador opcional.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `StudentIn`/`StudentOut` em
      `apps/academic/schemas.py` (`StudentOut` inclui `person` embutido,
      sem serializar `Person` direto).
- [ ] `GET /api/v1/academic/students/` (paginado, filtro opcional por
      `status`, `level`, `advisor_id`, `require_perm` com
      `academic.view_student`).
- [ ] `POST /api/v1/academic/students/` (cria `Person` + `Student` numa
      `transaction.atomic()` via `services.py`; `project` é obrigatório
      no payload; `advisor` é opcional; se `deadline` não vier no
      payload, aplica a regra de cálculo do model; `require_perm` com
      `academic.add_student`; registra `AuditLog` `academic.student.create`).
- [ ] `PATCH /api/v1/academic/students/{id}/` (`require_perm` com
      `academic.change_student`; registra `AuditLog`
      `academic.student.update`).
- [ ] Typecheck passes.
- [ ] Tests pass.

### US-010: Tela Svelte — Linhas de Pesquisa e Projetos Coletivos
**Description:** Como secretaria, quero uma tela para cadastrar e editar
linhas de pesquisa e seus projetos coletivos.

**Acceptance Criteria:**
- [ ] `make gen-api` rodado (backend de pé) antes de tipar a tela.
- [ ] Lista de linhas de pesquisa com seus projetos coletivos agrupados
      (linha 1 → N projetos, visualmente claro).
- [ ] Formulário de criar/editar linha e criar/editar projeto (com
      seletor de linha).
- [ ] Coordenação vê a tela em modo somente leitura (ações de
      criar/editar ocultas se o usuário não tiver a permissão de
      `change`).
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-011: Tela Svelte — Cadastro de Professores
**Description:** Como secretaria, quero uma tela para cadastrar e editar
professores, incluindo categoria, credenciamento, titulação e vínculos
de linha/projeto.

**Acceptance Criteria:**
- [ ] Lista de professores com filtro por categoria (Permanente/
      Colaborador/Visitante).
- [ ] Formulário de criar/editar com todos os campos de `Teacher`
      (incluindo seleção múltipla de linhas de pesquisa e projetos).
- [ ] Coordenação vê a tela em modo somente leitura.
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-012: Tela Svelte — Cadastro de Alunos
**Description:** Como secretaria, quero uma tela para cadastrar e editar
alunos, incluindo nível, projeto, orientador, situação e prazo.

**Acceptance Criteria:**
- [ ] Lista de alunos com filtro por status e nível.
- [ ] Formulário de criar/editar com todos os campos de `Student`;
      `project` obrigatório (seletor); `advisor` opcional (seletor de
      professores); `deadline` pré-preenchido com o valor calculado mas
      editável.
- [ ] Coordenação vê a tela em modo somente leitura.
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

## 4. Functional Requirements

1. O sistema deve permitir cadastrar uma linha de pesquisa vinculada a um
   programa.
2. O sistema deve permitir cadastrar um projeto coletivo vinculado a
   exatamente uma linha de pesquisa.
3. O sistema deve permitir cadastrar um professor com categoria CAPES
   (Permanente/Colaborador/Visitante), data de credenciamento (e
   opcionalmente descredenciamento), titulação, e vínculo com múltiplas
   linhas de pesquisa e múltiplos projetos coletivos.
4. O sistema deve permitir cadastrar um aluno com nível (mestrado ou
   doutorado), vínculo obrigatório a um projeto coletivo, orientador
   opcional, situação acadêmica, data de ingresso e prazo regimental.
5. O sistema deve calcular automaticamente o prazo regimental do aluno
   (24 meses para mestrado, 48 para doutorado, a partir da data de
   ingresso) quando não informado na criação, permanecendo editável
   depois.
6. O sistema deve permitir trocar a situação do aluno livremente entre
   Regular, Trancado, Isolada, Eletiva e Excluído, sem validação de
   transição.
7. O sistema deve permitir que o número de matrícula do aluno
   (`registration_number`) fique em branco na criação e seja preenchido
   depois, quando a UFMG o gerar.
8. Apenas a Secretaria pode criar e editar professores, alunos, linhas de
   pesquisa e projetos coletivos; a Coordenação só pode visualizar.
9. Toda criação e edição de professor e aluno deve gerar um `AuditLog`.
10. Nenhuma dessas telas deve ser servida pelo Django Admin — são todas
    telas do front (ADR-006), exceto correção pontual feita por
    sysadmin em modo quebra-vidro.

## 5. Non-Goals (Out of Scope)

- CPF, data de nascimento e demais dados pessoais sensíveis (LGPD) —
  fora de escopo até um módulo concreto precisar deles.
- Dados de bolsa (agência, tipo, valor).
- Coorientador — só um orientador por aluno nesta versão.
- Histórico de mudança de categoria docente ao longo do tempo — só o
  estado atual (`category`, `accredited_since`, `accredited_until`).
- Workflow de "acerto de matrícula" (solicitação → aprovação do
  orientador) — especificado separadamente em `tasks/prd-matricula.md`,
  que **depende** desta PRD (precisa de `Teacher`/`Student` existirem
  primeiro).
- Processo seletivo (inscrição de candidato, documentos, aprovação,
  conversão em aluno) — módulo de negócio futuro, não especificado
  ainda. Nesta versão, o cadastro de `Student` é feito diretamente pela
  Secretaria via tela.
- Import de dados de sistema legado — não foi identificado nenhum
  sistema anterior com dados para migrar.
- Regras de transição bloqueada para `Student.status` — troca é livre
  por decisão explícita desta PRD.

## 6. Design Considerations

- Seguir o padrão visual e de formulário já usado nas telas Svelte
  existentes (Tailwind v4, runas do Svelte 5).
- Na tela de professor e de aluno, os campos que só se aplicam de forma
  condicional (ex.: `home_institution` mais relevante para Colaborador/
  Visitante) continuam visíveis para todas as categorias — não esconder
  campo por regra de UI que não existe como regra de negócio no backend.

## 7. Technical Considerations

- Novo app `academic`, criado com a estrutura padrão do projeto (ver
  `apps/people/` como referência de app completo: `models.py`,
  `admin.py`, `router.py`, `schemas.py`, `services.py`, `migrations/`,
  `tests/`).
- `ResearchLine`/`CollectiveProject` entram no app `programs` (estrutura
  do programa, junto de `Program`), não em `academic` — `academic`
  depende de `programs`, nunca o contrário.
- `Teacher`/`Student` em relação 1:1 (`OneToOneField`) com `Person`, não
  substituindo os campos que já existem lá (`full_name`, `primary_email`,
  `phone_number`, `status` genérico de `Person` continuam sendo a fonte
  desses dados).
- Criação de `Teacher`/`Student` atravessa dois models (`Person` + o
  perfil) numa única operação atômica — usar `services.py`, no mesmo
  padrão de `create_person_with_user` (`apps/people/services.py`), com
  `@transaction.atomic` e `audit.record(...)` dentro da mesma transação.
  Edição (`PATCH`), por tocar só o model do perfil, fica direto no
  router, sem service, seguindo `archive_person`
  (`apps/people/router.py:48-57`).
- `AuditLog` sempre via `apps.core.audit.record(event, request=,
  target=)` — nunca instanciar `AuditLog` direto.
- Regra de cálculo do `deadline` mora em método do próprio model
  `Student` (ADR-002) — não em service nem em validação de schema.
- Grupos "Secretaria" e "Coordenação" já existem
  (`apps/programs/migrations/0002_programa_inicial_e_papeis.py`); esta
  PRD só estende as permissões deles numa migração nova, sem tocar na
  já aplicada.

## 8. Success Metrics

- Secretaria consegue cadastrar um professor e um aluno completos (todos
  os campos desta PRD) sem precisar do Django Admin.
- Coordenação consegue ver a lista de professores e alunos do programa
  sem conseguir editar nada.
- Todo aluno criado sem `deadline` explícito recebe o prazo calculado
  corretamente pela regra de 24/48 meses.
- `tasks/prd-matricula.md` deixa de ter a dependência bloqueante em
  `apps.academic.models.Student`/`Teacher` — passa a poder ser executado
  depois desta PRD.

## 9. Open Questions

- A lista exata de `academic_degree` (Doutor/Pós-doutor/Livre-docente,
  proposta nesta PRD) não foi confirmada literalmente pelo usuário —
  vale revisar antes de rodar, é troca barata de `TextChoices` se
  estiver errada.
- O significado exato de "Isolada" e "Eletiva" como situação de aluno
  não foi detalhado (termos específicos da UFMG) — armazenado como valor
  sem regra de negócio atrelada; se algum dia precisar de comportamento
  diferente por status, revisitar.
- Quando a US-005 estender as permissões de Secretaria/Coordenação, uma
  pergunta em aberto do PRD original: a Secretaria também deveria poder
  **excluir** (delete) `ResearchLine`/`CollectiveProject`/`Teacher`/
  `Student`, ou só criar/editar/ver (sem delete), como foi
  explicitamente combinado? Esta PRD assume **sem delete** — só add/
  change/view — por não ter sido mencionado.
- A pergunta de fechamento do grill-me ("falta mais alguma coisa?") não
  chegou a ser respondida antes da sessão mudar de assunto — pode haver
  campo ou regra que ainda não foi capturado; revisitar com o usuário se
  algo faltar na prática.
