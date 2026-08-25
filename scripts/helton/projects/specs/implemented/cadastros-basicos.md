# PRD: Cadastros Básicos — Professores e Alunos

> **Revisão de 2026-08-05.** Esta versão incorpora o **ADR-007**
> (`docs/adr/007-modalidade-e-situacao-do-aluno.md`), que substitui a
> modelagem de `Student` da versão anterior. Resumo das mudanças no
> Apêndice A.

## 1. Introduction/Overview

O PPGD Manager já tem a fundação de identidade (`Person`, `Program`,
`User`), mas nenhum model representa os dois papéis centrais do domínio:
**professor (docente)** e **aluno (discente)**. Esta PRD cria o primeiro
módulo de negócio real do sistema: o app `academic`, com os cadastros
básicos de `Teacher` e `Student`, mais a estrutura de programa que os dois
referenciam — linhas de pesquisa, projetos coletivos e períodos letivos.

Ela também fecha duas lacunas de fundação que nenhum módulo consegue
contornar sozinho: **quem cadastra um professor ou aluno precisa deixá-lo
apto a entrar no sistema** (senha e grupo), e **toda rota precisa saber a
que programa a requisição pertence**. Sem as duas, o fluxo de
`tasks/prd-matricula.md` fica escrito mas inexequível.

## 2. Goals

- Cadastrar professores com a categoria CAPES (Permanente/Colaborador/
  Visitante), credenciamento, titulação e vínculo com linhas de pesquisa
  e projetos coletivos.
- Cadastrar alunos nas três modalidades de vínculo (Regular, Isolada,
  Eletiva), com os campos de grau exigidos apenas de quem é regular,
  conforme o ADR-007.
- Modelar a estrutura do programa que professores e alunos referenciam:
  linhas de pesquisa, projetos coletivos e períodos letivos.
- Dar à Secretaria a capacidade de criar e editar tudo isso pela tela do
  sistema (nunca pelo Django Admin — ADR-006), e à Coordenação a visão de
  leitura.
- Deixar professor e aluno **aptos a usar o sistema** assim que
  cadastrados: no grupo correto e com senha definível pela Secretaria.
- Estabelecer o **programa corrente da requisição** como conceito único e
  reutilizável, em vez de cada rota inventar o seu.

## 3. User Stories

### US-001: Model de Linha de Pesquisa
**Description:** Como secretaria, preciso cadastrar as linhas de pesquisa
do programa, para que professores e projetos coletivos possam ser
vinculados a elas.

**Acceptance Criteria:**
- [ ] Model `ResearchLine` no app `programs`: `program` (FK,
      on_delete=PROTECT, related_name="research_lines"), `name`
      (CharField), `is_active` (BooleanField, default True).
- [ ] `UniqueConstraint` em (`program`, `name`).
- [ ] Registrado no Django Admin do app `programs`.
- [ ] Migração criada e revisada (arquivo lido, não só gerado).
- [ ] Typecheck passes.

### US-002: Model de Projeto Coletivo
**Description:** Como secretaria, preciso cadastrar os projetos
coletivos de cada linha de pesquisa, já que uma linha tem vários
projetos.

**Acceptance Criteria:**
- [ ] Model `CollectiveProject` no app `programs`: `program` (FK,
      on_delete=PROTECT, related_name="collective_projects"),
      `research_line` (FK para `ResearchLine`, on_delete=PROTECT,
      related_name="projects"), `name` (CharField), `is_active`
      (BooleanField, default True).
- [ ] A FK `program` é **direta e obrigatória**, mesmo sendo alcançável
      por `research_line.program` — ver ADR-007, decisão 5 (regra de
      tenant da Seção 1 do CLAUDE.md + `audit.record()` infere o programa
      de `target.program`).
- [ ] Método `clean()` garante `program == research_line.program`;
      levanta `DomainError` (`code="program_mismatch"`) se divergir.
- [ ] Registrado no Django Admin do app `programs` (com `research_line`
      visível em `list_display`).
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.
- [ ] Tests pass (teste em memória: `clean()` levanta erro quando o
      programa do projeto diverge do programa da linha).

### US-003: Model de Período Letivo
**Description:** Como secretaria, preciso cadastrar os períodos letivos
(semestres) do programa, para que os vínculos de aluno de isolada e
eletiva possam ser recortados por semestre.

**Acceptance Criteria:**
- [ ] Model `AcademicTerm` no app `programs`, **institucional — sem FK
      `program`** (ADR-007, decisão 4): `year` (PositiveSmallInteger),
      `half` (PositiveSmallInteger, choices `1`/`2`), `starts_on`
      (DateField), `ends_on` (DateField), `is_active` (BooleanField,
      default True).
      O calendário 2026/1 é o mesmo da UFMG inteira; um cadastro por
      programa produziria "PPGD 2026/1" e "PPGA 2026/1" divergentes.
      É a **única exceção** à regra de FK `program` direta desta PRD, e
      é deliberada.
- [ ] `UniqueConstraint` em (`year`, `half`).
- [ ] `__str__` devolve o rótulo canônico `"2026/1"` — é a única forma de
      escrever um semestre no sistema (ADR-007, decisão 4).
- [ ] Método `clean()` garante `ends_on > starts_on`; levanta
      `DomainError` (`code="invalid_term_range"`).
- [ ] Como o model não tem FK `program`, o `AuditLog` das escritas de
      `AcademicTerm` grava `program=None` — e isso está **correto**, não
      é o defeito que a decisão 5 do ADR-007 evita: a entidade é
      institucional, não pertence a programa nenhum.
- [ ] Registrado no Django Admin do app `programs`.
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.
- [ ] Tests pass (teste em memória: `__str__` formata "2026/1";
      `clean()` rejeita fim anterior ao início).

### US-004: App `academic` e model Teacher
**Description:** Como secretaria, preciso cadastrar um professor com
categoria CAPES, credenciamento, titulação e vínculo com linhas de
pesquisa e projetos, para manter o quadro docente do programa.

**Acceptance Criteria:**
- [ ] App `academic` criado seguindo a estrutura padrão do projeto
      (`models.py`, `admin.py`, `router.py`, `schemas.py`, `services.py`,
      `migrations/`, `tests/`), registrado em `INSTALLED_APPS` depois de
      `apps.programs` e `apps.people`.
- [ ] Model `Teacher`: `program` (FK para `programs.Program`,
      on_delete=PROTECT, related_name="teachers"), `person`
      (**OneToOneField** para `people.Person`, on_delete=PROTECT,
      related_name="teacher_profile"), `category` (TextChoices
      PERMANENT/COLLABORATOR/VISITING = "Permanente"/"Colaborador"/
      "Visitante"), `accredited_since` (DateField), `accredited_until`
      (DateField, null=True, blank=True), `academic_degree` (TextChoices
      DOCTORATE/POSTDOCTORATE/HABILITATION = "Doutor"/"Pós-doutor"/
      "Livre-docente"), `lattes_url` (URLField, blank=True),
      `home_institution` (CharField, blank=True), `research_lines`
      (ManyToManyField para `programs.ResearchLine`,
      related_name="teachers", blank=True), `projects` (ManyToManyField
      para `programs.CollectiveProject`, related_name="teachers",
      blank=True).
- [ ] `person` continua `OneToOneField` (ao contrário de `Student`) —
      ADR-007, decisão 2.
- [ ] Método `clean()` garante `program == person.program`; levanta
      `DomainError` (`code="program_mismatch"`).
- [ ] Registrado no Django Admin do app `academic`.
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.

### US-005: Model Student
**Description:** Como secretaria, preciso cadastrar um aluno indicando a
modalidade do vínculo (regular, isolada ou eletiva) e a situação atual,
com os campos de grau exigidos só de quem é regular, para acompanhar a
vida acadêmica dele no programa.

**Acceptance Criteria:**
- [ ] Model `Student` no app `academic` com os campos de identificação:
      `program` (FK para `programs.Program`, on_delete=PROTECT,
      related_name="students"), `person` (**ForeignKey** para
      `people.Person`, on_delete=PROTECT, related_name="student_records"
      — **não** OneToOne, ADR-007 decisão 2), `registration_number`
      (CharField, max_length=30, null=True, blank=True, unique=True —
      número de matrícula global da UFMG, preenchido só depois que a
      universidade o gera; identifica o **episódio de vínculo**, não a
      pessoa).
- [ ] Campos de dimensão (ADR-007, decisão 1):
      `modality` (TextChoices REGULAR/ISOLATED/ELECTIVE = "Regular"/
      "Isolada"/"Eletiva", default REGULAR) e `status` (TextChoices
      ACTIVE/LEAVE/EXCLUDED = "Ativo"/"Trancado"/"Excluído", default
      ACTIVE).
- [ ] Campos de grau, **todos `null=True, blank=True` no banco**:
      `level` (TextChoices MASTERS/DOCTORATE = "Mestrado"/"Doutorado"),
      `project` (FK para `programs.CollectiveProject`,
      on_delete=PROTECT, related_name="students"), `advisor` (FK para
      `Teacher`, on_delete=PROTECT, related_name="advisees"),
      `admission_date` (DateField), `deadline` (DateField),
      `defense_date` (DateField).
- [ ] Campo de recorte semestral: `term` (FK para
      `programs.AcademicTerm`, on_delete=PROTECT,
      related_name="students", null=True, blank=True).
- [ ] `CheckConstraint` `student_regular_requires_degree_fields`: quando
      `modality = REGULAR`, os campos `level`, `project`,
      `admission_date` e `deadline` são NOT NULL.
- [ ] `CheckConstraint` `student_non_regular_requires_term`: quando
      `modality` é `ISOLATED` ou `ELECTIVE`, `term` é NOT NULL e
      `level`, `project`, `advisor`, `admission_date`, `deadline` e
      `defense_date` são NULL.
- [ ] `CheckConstraint` `student_leave_only_when_regular`: `status =
      LEAVE` ("Trancado") só é permitido quando `modality = REGULAR`.
      Trancar não se aplica a isolada nem a eletiva — o vínculo dura um
      semestre e termina em `EXCLUDED` (confirmado pelo usuário no
      levantamento de isoladas).
- [ ] Regra de `deadline`: quando `modality = REGULAR` e `deadline` não
      for informado, calcular como `admission_date` + 2 anos (`level ==
      MASTERS`) ou + 4 anos (`level == DOCTORATE`); implementar como
      método do próprio model (ex.: `default_deadline()`) chamado em
      `save()` quando `deadline` for `None`. Depois de criado o campo é
      livremente editável (prorrogação = editar o valor).
- [ ] O cálculo usa **aritmética de ano em `datetime.date`**
      (`date.replace(year=...)`, com 29/02 caindo em 28/02), **sem
      adicionar dependência nova** — 24 e 48 meses são 2 e 4 anos
      exatos, então `relativedelta`/`python-dateutil` não é necessário
      (CLAUDE.md, contexto do time: não introduzir biblioteca nova sem
      discutir).
- [ ] Método `clean()` garante `program == person.program` e, quando
      preenchidos, `project.program` e `advisor.program` iguais a
      `program`; levanta `DomainError` (`code="program_mismatch"`).
      **Não** valida `term.program`: `AcademicTerm` é institucional e não
      tem programa (US-003).
- [ ] **O service que cria/edita `Student` chama `full_clean()` antes de
      salvar.** O Django não executa `clean()` em `.save()`/`.create()` —
      só em formulários. Sem essa chamada explícita, o invariante de
      programa acima nunca roda no caminho real (o `services.py`). Vale o
      mesmo para `Teacher` (US-004), `CollectiveProject` (US-002) e
      `AcademicTerm` (US-003).
- [ ] Sem regra de transição bloqueada em `status` (troca livre entre
      quaisquer valores dentro do que a constraint permite) — não
      implementar método de validação de transição para este campo. Toda
      troca é auditada (US-013).
- [ ] Registrado no Django Admin do app `academic` (com `modality` e
      `status` em `list_display` e `list_filter`).
- [ ] Migração criada e revisada.
- [ ] Typecheck passes.
- [ ] Tests pass:
      - em memória, sem banco: `Student` REGULAR sem `deadline` informado
        recebe o prazo calculado (2 anos para MASTERS, 4 para DOCTORATE),
        inclusive o caso de `admission_date` em 29/02;
      - com banco: as três `CheckConstraint` rejeitam os casos inválidos
        (regular sem `project`; isolada com `advisor` preenchido; isolada
        sem `term`; isolada com `status = LEAVE`);
      - com banco: **duas `Student` para a mesma `Person`**, em períodos
        diferentes, são criadas sem violar constraint (é o caso do aluno
        de isolada que volta — ADR-007, decisão 2).

### US-006: Grupos e permissões dos papéis de domínio
**Description:** Como sistema, preciso que os quatro papéis de domínio
existam como Groups com as permissões corretas nos novos models, para
que o padrão de autorização do projeto (`require_perm`) funcione nas
rotas.

**Acceptance Criteria:**
- [ ] Nova data migration (não editar a
      `apps/programs/migrations/0002_programa_inicial_e_papeis.py` já
      aplicada) que **cria os grupos `Docente` e `Discente`**, seguindo o
      padrão da 0002.
- [ ] Os grupos `Docente` e `Discente` nascem **nesta PRD**, e não na de
      acerto de matrícula, porque a US-007 já precisa atribuí-los no
      momento do cadastro. `tasks/prd-matricula.md` apenas **estende** as
      permissões deles.
- [ ] Estende o grupo **Secretaria** com `add`/`change`/`view` em
      `ResearchLine`, `CollectiveProject`, `AcademicTerm`, `Teacher` e
      `Student`.
- [ ] Estende o grupo **Coordenação** com `view` nos mesmos cinco models.
- [ ] Nenhum grupo recebe permissão de `delete` — cadastro errado é
      corrigido por edição, e registro histórico não se apaga (decisão
      desta PRD; ver Open Questions se isso mudar).
- [ ] Nenhum grupo recebe `is_staff` nem `is_superuser` (CLAUDE.md,
      Seção 5).
- [ ] Migração de dados revisada (arquivo lido, não só gerado).
- [ ] Typecheck passes.

### US-007: Acesso — professor e aluno aptos a entrar no sistema
**Description:** Como secretaria, preciso que o professor ou aluno que eu
cadastro consiga efetivamente entrar no sistema, para que ele possa usar
as telas do papel dele.

**Contexto:** hoje `create_person_with_user`
(`apps/people/services.py`) cria a conta com `set_unusable_password()` e
o comentário remete o convite a "um módulo futuro"; e nada coloca o
usuário em nenhum grupo. Sem esta US, todo o fluxo de
`tasks/prd-matricula.md` é escrito mas nunca exercível.

**Acceptance Criteria:**
- [ ] Helper `assign_role_group(user, *, group_name)` em
      `apps/accounts/services.py` (e não em `academic`: é operação de
      conta, e `academic` já depende de `accounts`, nunca o contrário):
      adiciona o `User` ao Group indicado,
      idempotente (chamar duas vezes não duplica nem falha). É esta US
      que entrega o helper; **quem o chama** são os services de criação
      das US-012 e US-013 — assim nenhuma US depende de outra posterior.
- [ ] Regra a ser aplicada por quem chama: `Teacher` → grupo **Docente**;
      `Student` com `modality = REGULAR` → grupo **Discente**; aluno de
      `modality` `ISOLATED`/`ELECTIVE` **não** entra em grupo nenhum
      nesta versão, porque o fluxo dele não existe ainda (ADR-007).
- [ ] `POST /api/v1/accounts/users/{id}/set-initial-password` define a
      senha inicial de uma conta. `require_perm(request,
      "accounts.change_user")` na primeira linha (permissão concedida ao
      grupo Secretaria nesta mesma data migration da US-006).
- [ ] **Invariante de segurança**: a rota só funciona quando a conta
      ainda tem senha inutilizável (`user.has_usable_password() is
      False`). Se a conta já tem senha, levanta `InvalidStateTransition`
      (409) — a Secretaria define o primeiro acesso, **nunca** troca a
      senha de uma conta ativa. A regra mora em método do model `User`
      (ex.: `set_initial_password(raw_password)`), não no router
      (ADR-002).
- [ ] Registra `AuditLog` `accounts.user.set_initial_password` (sem a
      senha no payload, obviamente).
- [ ] Sem envio de e-mail: o projeto não tem `EMAIL_BACKEND` configurado
      e a decisão registrada é não adicionar SMTP nesta versão. A senha
      inicial é entregue pela Secretaria por fora do sistema.
- [ ] Tests pass: definir senha em conta nova funciona; repetir a chamada
      na mesma conta retorna 409; usuário sem a permissão retorna 403;
      `assign_role_group` chamado duas vezes deixa o usuário com o grupo
      uma vez só.
- [ ] Typecheck passes.

### US-008: Programa corrente da requisição
**Description:** Como desenvolvedor, preciso de uma forma única de saber
a que programa uma requisição pertence, para que "todos os alunos do
programa" tenha um significado só em todas as rotas.

**Contexto:** hoje só existe `program_id` como query param opcional em
`list_people` (`apps/people/router.py`), o que não escopa nada — qualquer
usuário autenticado pode listar qualquer programa.

**Acceptance Criteria:**
- [ ] Novo helper `current_program(request) -> Program` em
      `apps/core/tenancy.py`, no mesmo espírito de `require_perm`
      (helper único, chamado explicitamente na rota).
- [ ] Resolução: procura as `Person` **ativas** do `request.user`
      (`Person.objects.active().filter(user=request.user)`).
      - exatamente uma → o programa dela;
      - nenhuma → levanta `NoProgramInContext` (`DomainError`,
        `status_code=403`, `code="no_program"`);
      - mais de uma (caso multi-tenant já previsto por
        `Person.user` ser FK) → exige `program_id` explícito na
        requisição e valida que o usuário tem `Person` ativa nele; sem
        isso levanta `DomainError` (`code="program_required"`, 400).
- [ ] Superusuário sem `Person` passa `program_id` explícito e é
      atendido (é o caso do sysadmin operando).
- [ ] Nova exceção `NoProgramInContext` em `apps/core/exceptions.py`,
      herdando de `DomainError`.
- [ ] `list_people` (`apps/people/router.py`) passa a escopar por
      `current_program(request)` em vez de aceitar `program_id` como
      filtro livre — é correção de escopo, não regressão de
      funcionalidade.
- [ ] Toda rota de listagem criada desta PRD em diante escopa por
      `current_program(request)`.
- [ ] Tests pass: usuário com uma `Person` lista só o programa dele;
      usuário sem `Person` recebe 403 com `code="no_program"`; usuário
      com duas `Person` sem `program_id` recebe 400.
- [ ] Typecheck passes.

### US-009: Endpoints — Linha de Pesquisa
**Description:** Como secretaria, quero cadastrar e editar linhas de
pesquisa pela API, para popular a estrutura que professores e projetos
vão referenciar.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `ResearchLineIn`/`ResearchLineOut` em
      `apps/programs/schemas.py` (nunca serializar o model direto).
- [ ] `GET /api/v1/programs/research-lines/` (paginado, escopado por
      `current_program(request)`, `require_perm` com
      `programs.view_researchline`).
- [ ] `POST /api/v1/programs/research-lines/` (`require_perm` com
      `programs.add_researchline`; o `program` vem de
      `current_program(request)`, **não** do payload; registra `AuditLog`
      `programs.research_line.create`).
- [ ] `PATCH /api/v1/programs/research-lines/{id}/` (`require_perm` com
      `programs.change_researchline`; registra `AuditLog`
      `programs.research_line.update`).
- [ ] Router registrado na `NinjaAPI` raiz (`backend/api.py`).
- [ ] Typecheck passes.
- [ ] Tests pass.

### US-010: Endpoints — Projeto Coletivo
**Description:** Como secretaria, quero cadastrar e editar projetos
coletivos vinculados a uma linha de pesquisa pela API.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `CollectiveProjectIn`/`CollectiveProjectOut`
      em `apps/programs/schemas.py`.
- [ ] `GET /api/v1/programs/collective-projects/` (paginado, escopado por
      `current_program(request)`, filtro opcional por `research_line_id`,
      `require_perm` com `programs.view_collectiveproject`).
- [ ] `POST /api/v1/programs/collective-projects/` (`require_perm` com
      `programs.add_collectiveproject`; `program` vem de
      `current_program(request)`; registra `AuditLog`
      `programs.collective_project.create`).
- [ ] `PATCH /api/v1/programs/collective-projects/{id}/` (`require_perm`
      com `programs.change_collectiveproject`; registra `AuditLog`
      `programs.collective_project.update`).
- [ ] Typecheck passes.
- [ ] Tests pass (inclusive: criar projeto com `research_line` de outro
      programa é recusado).

### US-011: Endpoints — Período Letivo
**Description:** Como secretaria, quero cadastrar e editar os períodos
letivos pela API.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `AcademicTermIn`/`AcademicTermOut` em
      `apps/programs/schemas.py` (`AcademicTermOut` inclui o rótulo
      canônico `"2026/1"` como campo `label`).
- [ ] `GET /api/v1/programs/terms/` (paginado, **sem escopo de programa**
      — `AcademicTerm` é institucional, US-003 —, `require_perm` com
      `programs.view_academicterm`).
- [ ] `POST /api/v1/programs/terms/` (`require_perm` com
      `programs.add_academicterm`; registra `AuditLog`
      `programs.academic_term.create`).
- [ ] `PATCH /api/v1/programs/terms/{id}/` (`require_perm` com
      `programs.change_academicterm`; registra `AuditLog`
      `programs.academic_term.update`).
- [ ] Typecheck passes.
- [ ] Tests pass.

### US-012: Endpoints — Professor
**Description:** Como secretaria, quero cadastrar e editar professores
pela API, incluindo seus vínculos de linha de pesquisa e projeto.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `TeacherIn`/`TeacherOut` em
      `apps/academic/schemas.py` (`TeacherOut` inclui `person` embutido —
      nome, e-mail — sem serializar `Person` direto).
- [ ] `GET /api/v1/academic/teachers/` (paginado, escopado por
      `current_program(request)`, filtro opcional por `category`,
      `require_perm` com `academic.view_teacher`).
- [ ] `POST /api/v1/academic/teachers/` cria `Teacher` numa
      `transaction.atomic()` via `services.py` — operação multi-model,
      seguindo o padrão de `create_person_with_user`
      (`apps/people/services.py`). O payload aceita **ou** `person_id`
      (pessoa que já existe no programa) **ou** os dados de uma pessoa
      nova (`full_name`, `primary_email`, `phone_number`); nunca os dois.
- [ ] O service chama `assign_role_group(user, group_name="Docente")`
      (US-007) dentro da mesma transação.
- [ ] `require_perm` com `academic.add_teacher`; registra `AuditLog`
      `academic.teacher.create`.
- [ ] `PATCH /api/v1/academic/teachers/{id}/` (`require_perm` com
      `academic.change_teacher`; registra `AuditLog`
      `academic.teacher.update`).
- [ ] Router registrado na `NinjaAPI` raiz.
- [ ] Typecheck passes.
- [ ] Tests pass (inclusive: criar professor com `person_id` de outro
      programa é recusado).

### US-013: Endpoints — Aluno
**Description:** Como secretaria, quero cadastrar e editar alunos pela
API, informando a modalidade e só os campos que ela exige.

**Acceptance Criteria:**
- [ ] Schemas Ninja explícitos `StudentIn`/`StudentOut` em
      `apps/academic/schemas.py` (`StudentOut` inclui `person` embutido,
      sem serializar `Person` direto, e expõe `modality` e `status` como
      campos separados).
- [ ] `StudentIn` valida no schema o que o `CheckConstraint` garante no
      banco: `modality = REGULAR` exige `level`, `project_id` e
      `admission_date` (com `deadline` opcional, calculado se ausente);
      `ISOLATED`/`ELECTIVE` exigem `term_id` e recusam os campos de grau.
      A validação do banco continua sendo a que vale.
- [ ] `GET /api/v1/academic/students/` (paginado, escopado por
      `current_program(request)`, filtros opcionais por `modality`,
      `status`, `level`, `term_id`, `advisor_id`; `require_perm` com
      `academic.view_student`).
- [ ] `POST /api/v1/academic/students/` cria o aluno numa
      `transaction.atomic()` via `services.py`, aceitando **ou**
      `person_id` **ou** os dados de uma pessoa nova (mesma regra da
      US-012); chama `assign_role_group(user, group_name="Discente")`
      (US-007) quando `modality = REGULAR`, e não chama nas demais
      modalidades; `require_perm` com `academic.add_student`; registra
      `AuditLog` `academic.student.create`.
- [ ] `PATCH /api/v1/academic/students/{id}/` (`require_perm` com
      `academic.change_student`; registra `AuditLog`
      `academic.student.update`; quando o `status` muda, o payload do
      `AuditLog` traz o valor anterior e o novo).
- [ ] **Busca de pessoa por e-mail**: `list_people`
      (`apps/people/router.py`) ganha filtro opcional `email`, para a
      tela poder encontrar uma `Person` que já existe antes de tentar
      criar outra. Sem isso a Secretaria bate na `UniqueConstraint
      (program, primary_email)` ao recadastrar quem volta em outro
      semestre (ADR-007, consequências).
- [ ] Typecheck passes.
- [ ] Tests pass (inclusive: criar dois `Student` para a mesma `Person`
      em períodos diferentes funciona pela API).

### US-014: Tela Svelte — Estrutura do programa
**Description:** Como secretaria, quero uma tela para cadastrar e editar
linhas de pesquisa, seus projetos coletivos e os períodos letivos.

**Acceptance Criteria:**
- [ ] `make gen-api` rodado (backend de pé) antes de tipar a tela.
- [ ] Lista de linhas de pesquisa com seus projetos coletivos agrupados
      (linha 1 → N projetos, visualmente claro).
- [ ] Formulário de criar/editar linha e criar/editar projeto (com
      seletor de linha).
- [ ] Seção de períodos letivos: lista e formulário de criar/editar
      (`year`, `half`, `starts_on`, `ends_on`), com o rótulo canônico
      "2026/1" visível.
- [ ] Coordenação vê a tela em modo somente leitura (ações de
      criar/editar ocultas se o usuário não tiver a permissão de
      `change`).
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-015: Tela Svelte — Cadastro de Professores
**Description:** Como secretaria, quero uma tela para cadastrar e editar
professores, incluindo categoria, credenciamento, titulação e vínculos
de linha/projeto.

**Acceptance Criteria:**
- [ ] Lista de professores com filtro por categoria (Permanente/
      Colaborador/Visitante).
- [ ] Formulário de criar/editar com todos os campos de `Teacher`
      (incluindo seleção múltipla de linhas de pesquisa e projetos).
- [ ] **Busca por e-mail antes de criar**: ao informar o e-mail, a tela
      consulta `GET /api/v1/people/?email=...`; se a pessoa já existir,
      oferece reaproveitá-la (`person_id`) em vez de criar outra.
- [ ] Ação de **definir senha inicial** (US-007) visível para a
      Secretaria enquanto a conta não tiver senha; some depois.
- [ ] Coordenação vê a tela em modo somente leitura.
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

### US-016: Tela Svelte — Cadastro de Alunos
**Description:** Como secretaria, quero uma tela para cadastrar e editar
alunos, com o formulário se adaptando à modalidade do vínculo.

**Acceptance Criteria:**
- [ ] Lista de alunos com filtros por modalidade, situação, nível e
      período letivo; colunas de `modality` e `status` **separadas**.
- [ ] O seletor de **modalidade** é a primeira decisão do formulário; ele
      governa quais campos aparecem: `REGULAR` mostra nível, projeto,
      orientador, data de ingresso, prazo e data de defesa; `ISOLADA`/
      `ELETIVA` mostram o período letivo e escondem os campos de grau.
      Este é o único caso em que esconder campo por regra de UI é
      correto, porque a regra existe como `CheckConstraint` no banco
      (contrasta com a orientação geral da Seção 6).
- [ ] `deadline` pré-preenchido com o valor calculado (2/4 anos) mas
      editável.
- [ ] **Busca por e-mail antes de criar**, igual à US-015 — é o caminho
      normal para quem volta a cursar isolada em outro semestre.
- [ ] Ação de **definir senha inicial** (US-007), nas mesmas condições da
      US-015.
- [ ] Coordenação vê a tela em modo somente leitura.
- [ ] Toda chamada via `lib/api/client.ts` tipado.
- [ ] Typecheck (svelte-check) passes.
- [ ] Verify in browser using dev-browser skill.

## 4. Functional Requirements

1. O sistema deve permitir cadastrar linhas de pesquisa, projetos
   coletivos e períodos letivos vinculados a um programa.
2. O sistema deve permitir cadastrar um projeto coletivo vinculado a
   exatamente uma linha de pesquisa, do mesmo programa.
3. O sistema deve permitir cadastrar um professor com categoria CAPES,
   data de credenciamento (e opcionalmente descredenciamento),
   titulação, e vínculo com múltiplas linhas de pesquisa e múltiplos
   projetos coletivos.
4. O sistema deve registrar a **modalidade** do vínculo do aluno
   (Regular, Isolada, Eletiva) separada da sua **situação** (Ativo,
   Trancado, Excluído), de forma que a modalidade continue conhecida
   depois que o aluno for excluído.
5. O sistema deve exigir nível, projeto coletivo, data de ingresso e
   prazo apenas de alunos de modalidade Regular, e exigir período letivo
   apenas de alunos de Isolada e Eletiva — garantido por constraint no
   banco, não só por validação de formulário.
6. O sistema deve permitir que a **mesma pessoa tenha vários registros de
   aluno** ao longo do tempo, cada um com seu próprio número de
   matrícula.
7. O sistema deve calcular automaticamente o prazo regimental do aluno
   regular (2 anos para mestrado, 4 para doutorado, a partir da data de
   ingresso) quando não informado na criação, permanecendo editável
   depois.
8. O sistema deve permitir trocar a situação do aluno livremente entre
   Ativo, Trancado e Excluído, sem validação de transição, registrando
   cada troca em `AuditLog` — com a única restrição de que **Trancado só
   vale para a modalidade Regular**.
9. O sistema deve permitir que o número de matrícula fique em branco na
   criação e seja preenchido depois, quando a UFMG o gerar.
10. O sistema deve colocar o professor no grupo Docente e o aluno regular
    no grupo Discente no momento do cadastro, e permitir à Secretaria
    definir a senha inicial da conta — mas apenas enquanto a conta não
    tiver senha.
11. O sistema deve determinar o programa da requisição a partir da
    pessoa vinculada ao usuário autenticado, e escopar toda listagem por
    ele.
12. Apenas a Secretaria pode criar e editar; a Coordenação só pode
    visualizar. Nenhum papel recebe permissão de exclusão.
13. Toda criação e edição de professor, aluno e estrutura do programa
    deve gerar um `AuditLog` com a chave de programa preenchida.
14. Nenhuma dessas telas deve ser servida pelo Django Admin — são todas
    telas do front (ADR-006), exceto correção pontual feita por sysadmin
    em modo quebra-vidro.

## 5. Non-Goals (Out of Scope)

- **Fluxo de inscrição em disciplina isolada** — auto-registro público,
  escolha de disciplinas, upload de documentos (identidade, CPF,
  diploma, currículo, comprovante de endereço, contracheque),
  deferimento pela secretaria e a dimensão de pagamento (GRU, com
  isenção para servidor da UFMG). É módulo próprio, com PRD e
  provavelmente ADR próprios; esta PRD só prepara o modelo de dados
  (`modality`, `AcademicTerm`, `Student.person` como FK) para recebê-lo.
- **Fluxo da modalidade Eletiva** — levantamento adiado explicitamente
  pelo usuário. O valor existe no enum e as regras condicionais valem,
  mas nenhuma tela ou workflow de eletiva é especificado.
- **Registro de quais disciplinas o aluno cursa** — para o aluno regular
  isso vive no sistema da UFMG. Para isolada passará a viver aqui, mas
  junto do fluxo de inscrição, fora desta PRD.
- **Limite de duas disciplinas isoladas por semestre** — regra do fluxo
  de inscrição, não do cadastro.
- **Exclusão automática do aluno de isolada ao fim do semestre** — sem
  tarefa agendada nesta versão; a Secretaria muda o `status` pela tela.
- CPF, data de nascimento e demais dados pessoais sensíveis como campos
  indexados (LGPD) — fora de escopo até um módulo concreto precisar.
- Dados de bolsa (agência, tipo, valor).
- Coorientador — só um orientador por aluno nesta versão.
- Histórico de mudança de categoria docente ao longo do tempo — só o
  estado atual (`category`, `accredited_since`, `accredited_until`).
- Envio de e-mail (SMTP) — nenhuma notificação nesta versão; a senha
  inicial é entregue pela Secretaria fora do sistema.
- Workflow de "acerto de matrícula" — `tasks/prd-matricula.md`, que
  **depende** desta PRD.
- Processo seletivo (inscrição de candidato, documentos, aprovação,
  conversão em aluno) — módulo de negócio futuro. Nesta versão, o
  cadastro de `Student` é feito diretamente pela Secretaria via tela.
- Import de dados de sistema legado — não foi identificado nenhum
  sistema anterior com dados para migrar.
- Regras de transição bloqueada para `Student.status` — troca é livre por
  decisão explícita.

## 6. Design Considerations

- Seguir o padrão visual e de formulário já usado nas telas Svelte
  existentes (Tailwind v4, runas do Svelte 5).
- Campos que só se aplicam de forma *convencional* (ex.:
  `home_institution` mais relevante para Colaborador/Visitante)
  continuam visíveis para todas as categorias — não esconder campo por
  regra de UI que não existe no backend.
- A **única exceção** a essa regra é o formulário de aluno (US-016), onde
  a modalidade governa quais campos aparecem. Ali a regra existe como
  `CheckConstraint`, então a UI está refletindo o backend, não
  inventando comportamento.
- `modality` e `status` são colunas separadas nas listagens, e não um
  rótulo combinado — é a diferença que o ADR-007 existe para preservar.

## 7. Technical Considerations

- Novo app `academic`, com a estrutura padrão do projeto (ver
  `apps/people/` como referência de app completo).
- `ResearchLine`, `CollectiveProject` e `AcademicTerm` entram no app
  `programs` (estrutura do programa, junto de `Program`), não em
  `academic` — `academic` depende de `programs`, nunca o contrário.
- **Todo model de negócio novo carrega FK `program` direta**, mesmo
  quando alcançável por navegação (ADR-007, decisão 5). Sem isso,
  `apps.core.audit.record()` — que infere o programa com
  `getattr(target, "program", None)` — gravaria `AuditLog` com
  `program=None` em todos eles.
  **Exceção única e deliberada: `AcademicTerm`**, que é institucional
  (o calendário é o da UFMG inteira, não de um programa). Ali o
  `program=None` no `AuditLog` é a resposta correta, não uma perda.
- `Teacher.person` é `OneToOneField`; `Student.person` é `ForeignKey`
  (ADR-007, decisão 2). Nenhum dos dois substitui os campos que já vivem
  em `Person` (`full_name`, `primary_email`, `phone_number`, `status`
  genérico continuam sendo a fonte desses dados).
- Criação de `Teacher`/`Student` atravessa vários models (`Person`,
  `User`, `Group`, perfil, `AuditLog`) numa única operação atômica —
  usar `services.py` do app `academic`, no padrão de
  `create_person_with_user` (`apps/people/services.py`), com
  `@transaction.atomic` e `audit.record(...)` dentro da mesma transação.
  Edição (`PATCH`), por tocar só o model do perfil, fica direto no
  router, seguindo `archive_person` (`apps/people/router.py`).
- `AuditLog` sempre via `apps.core.audit.record(event, request=,
  target=)` — nunca instanciar `AuditLog` direto.
- Regra de cálculo do `deadline` e o invariante de senha inicial moram em
  método do próprio model (ADR-002) — não em service nem em validação de
  schema.
- `current_program()` fica em `apps/core/tenancy.py`, ao lado de
  `permissions.py` e `audit.py` — é helper transversal, no mesmo padrão
  de "um jeito só de fazer" desses dois.
- O cálculo de prazo **não adiciona dependência**: 24 e 48 meses são 2 e
  4 anos exatos, resolvidos com `date.replace(year=...)` e uma guarda
  para 29/02.
- Grupos "Secretaria" e "Coordenação" já existem
  (`apps/programs/migrations/0002_programa_inicial_e_papeis.py`); esta
  PRD cria "Docente" e "Discente" e estende os quatro numa migração
  nova, sem tocar na já aplicada.

## 8. Success Metrics

- Secretaria consegue cadastrar um professor e um aluno completos sem
  precisar do Django Admin, e o professor/aluno consegue **fazer login**
  em seguida.
- Um aluno de isolada pode ser cadastrado duas vezes, em semestres
  diferentes, para a mesma pessoa, sem erro de constraint e sem cadastro
  duplicado de pessoa.
- A consulta "quantos alunos de modalidade Isolada tivemos em 2026/1"
  tem resposta mesmo depois de todos terem sido excluídos.
- Todo aluno regular criado sem `deadline` explícito recebe o prazo
  calculado corretamente.
- Nenhum `AuditLog` dos models desta PRD é gravado com `program` nulo.
- `tasks/prd-matricula.md` deixa de ter dependências bloqueantes: existem
  `Teacher`, `Student`, os grupos Docente/Discente, contas com senha e
  `current_program()`.

## 9. Open Questions

- **Troca de senha no primeiro acesso.** A US-007 deixa a Secretaria
  definir a senha inicial, o que significa que ela conhece a senha da
  pessoa até a primeira troca. Sem SMTP não há alternativa óbvia. Vale
  forçar troca no primeiro login (flag no `User` + interceptação no
  front)? Recomendação: sim, mas como incremento, depois que esta PRD
  rodar — não bloqueia.
- **`delete` para a Secretaria.** Esta PRD assume **sem delete** — só
  add/change/view. Se cadastro errado precisar sumir de verdade (e não
  virar `EXCLUDED`), é decisão a tomar antes de rodar a US-006.
- ~~**`AcademicTerm` por programa ou institucional.**~~ **RESOLVIDO**: é
  institucional, sem FK `program` (US-003). O calendário 2026/1 é o mesmo
  da UFMG inteira.
- ~~**`TRANCADO` para Isolada/Eletiva.**~~ **RESOLVIDO**: só vale para
  Regular, garantido por `CheckConstraint` (US-005).
- **Retenção dos documentos e quem pode baixá-los** — pertence ao módulo
  de inscrição em isolada, mas precisa estar decidido antes dele: os
  anexos incluem identidade e CPF, mais sensíveis que os campos que esta
  PRD deliberadamente deixou de fora.

## Apêndice A — O que mudou nesta revisão

Mudanças em relação à versão de 2026-08-05 (commit `a4852cc`), motivadas
pelo ADR-007 e pela revisão cruzada com o código:

| # | Mudança | Origem |
|---|---|---|
| 1 | `Student.person` passa de `OneToOneField` para `ForeignKey` | ADR-007 / grill isoladas Q2-Q3 |
| 2 | `Student.status` de 5 valores vira `modality` (3) + `status` (3) | ADR-007 / grill isoladas Q5 |
| 3 | `level`, `project`, `admission_date`, `deadline` viram condicionais por modalidade, com `CheckConstraint` | ADR-007 |
| 4 | Nova entidade `AcademicTerm` (US-003) | ADR-007 / grill isoladas Q4 |
| 5 | FK `program` direta em `CollectiveProject`, `Teacher` e `Student` (não em `AcademicTerm`) | corrige `AuditLog` com `program=None` |
| 5b | `AcademicTerm` é **institucional**, sem FK `program` | grill isoladas Q19–22 (resposta direta do usuário) |
| 13 | `CheckConstraint` restringindo `LEAVE` à modalidade Regular | grill isoladas Q19–22 |
| 14 | Service chama `full_clean()` antes de salvar | `clean()` não roda em `.save()`/`.create()` |
| 6 | Nova US-007: grupo automático + senha inicial | usuários criados não conseguiam logar |
| 7 | Nova US-008: `current_program()` | "todas do programa" não tinha implementação possível |
| 8 | Grupos Docente/Discente passam a ser criados aqui, não em `prd-matricula` | a US-007 precisa deles no cadastro |
| 9 | Busca de `Person` por e-mail (endpoint + telas) | evita bater na `UniqueConstraint (program, primary_email)` |
| 10 | Cálculo do prazo explicitamente sem `python-dateutil` | 2/4 anos exatos; não introduzir dependência |
| 11 | `academic_degree` confirmado como Doutor/Pós-doutor/Livre-docente | confirmado pelo usuário em 2026-08-05 |
| 12 | Numeração de US refeita (12 → 16) | inserção das US-003, US-007 e US-008 |
