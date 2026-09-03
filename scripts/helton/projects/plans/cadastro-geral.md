# Plano — Cadastro geral com validação da secretaria

> Destino após aprovação: `scripts/helton/projects/plans/cadastro-geral.md`
> (→ worktree `../simple_ppg_manager-cadastro-geral`, branch
> `helton/cadastro-geral`, projeto Compose
> `simple_ppg_manager-cadastro-geral`). Sem spec de `/grill-me`: nasceu de
> conversa direta, e as decisões foram fechadas por perguntas em plan mode,
> registradas abaixo.

## Contexto

O único autocadastro do sistema hoje é o da disciplina isolada. A tela de
login oferece "Vai cursar disciplina isolada e ainda não tem conta?", e o
`POST /academic/isolated/signup` cria conta, `Person` e grupo `Candidato`.
Quem não é candidato de isolada — docente, aluno, colaborador externo — não
tem porta de entrada: a secretaria cadastra à mão, que é exatamente o
trabalho que este módulo existe para tirar dela.

O objetivo é uma **tela de cadastro geral**, alcançável do login, onde a
pessoa escolhe perfil e programa:

- **Candidato** entra direto. Conta única, grupo `Candidato`, serve tanto ao
  edital de seleção quanto ao de disciplina isolada.
- **Docente e aluno** ficam **pendentes**. Entram, veem "seu cadastro aguarda
  confirmação da secretaria", e só ganham papel quando a secretaria valida —
  e validar significa **criar a ficha** (`Teacher` ou `Student`), não apenas
  liberar acesso.

O sistema é multiprograma desde o início, então o cadastro precisa dizer a
qual programa a pessoa se vincula — e essa é a decisão mais delicada do
plano, porque hoje o tenant da única rota pública sai do edital aberto, e
não do chamador.

## Decisões fechadas nesta sessão (não reabrir)

1. **Candidato é conta única.** Um caminho só, sem aprovação, servindo aos
   dois editais. Não há escolha "candidato de seleção" × "candidato de
   isolada" na tela.
2. **O programa é escolhido numa lista pública.** Exige endpoint público
   novo — hoje `GET /programs/` pede `programs.view_program`.
3. **Pendente entra e vê tela de espera.** Login funciona; o sistema mostra
   só "seu cadastro aguarda confirmação da secretaria". Sem menu, sem dados.
   Não foi escolhido barrar o login.
4. **"Colaborador externo" não é perfil próprio.** É docente com categoria: a
   pessoa declara `Teacher.Category` (Permanente, Colaborador, Visitante,
   Externo de banca) e `Teacher.AcademicDegree`, mais `home_institution`
   quando a categoria é `external`.
5. **Validar cria a ficha.** Docente: aprovar cria o `Teacher` com o
   declarado. Aluno: a tela de análise pede à secretaria nível, projeto
   coletivo, orientador e data de ingresso, e cria o `Student` REGULAR.
   Ninguém fica com papel de domínio sem ficha.
6. **Interruptor de autocadastro por programa.** `Program` ganha
   `accepts_self_signup`; programa desligado não aparece na lista pública e
   recusa cadastro. É o que substitui a trava de "só com edital aberto".

### Assunções (marcar em docstring; o humano confirma no merge)

- `accredited_since` do docente aprovado: a secretaria informa na aprovação,
  com hoje como default.
- Aluno aprovado nasce `modality=REGULAR`, `status=ACTIVE`. Isolada e eletiva
  continuam nascendo do fluxo do edital, não daqui.
- O `seed_demo` liga o interruptor nos dois programas semeados; sem isso a
  tela de cadastro nasce vazia no canteiro e parece quebrada.

---

## 0. As duas decisões estruturais (leia antes do resto)

### 0.1 Onde mora o `AccessRequest`: em `academic`

`backend/apps/people/models.py:26-30` proíbe transformar "tipo de pessoa" em
campo de `Person` — o vínculo é derivado das relações e dos Groups. Logo a
solicitação é **model próprio**, com histórico, e não um `status="pendente"`.

Onde ele mora é ditado pela direção das dependências:

- **`people` não pode** — importaria `academic`, a direção proibida.
- **`accounts` não pode** — `accounts/services.py:1-5` diz explicitamente que
  "academic já depende de accounts, e a dependência nunca se inverte".
- **`academic` pode**: já importa `people`, `accounts`, `programs` e `core`, e
  é onde estão as choices de `Teacher` e os services `create_teacher` /
  `create_student` que a aprovação chama.

**Router separado no mesmo app**, com precedente: `accounts/router.py` exporta
`router` e `users_router`, montados em dois prefixos por `backend/api.py:70-76`.
Faz-se igual — `access_router` em `academic/router.py`, montado em
`/api/v1/access/`. URL limpa sem inventar app novo.

### 0.2 Como o pendente é reconhecido: Group marcador `Cadastro pendente`

O caminho óbvio — devolver o estado no `GET /auth/me` — obrigaria `accounts` a
importar `academic`, invertendo a dependência. **Descartado.**

A saída dentro do idioma do projeto ("papel de domínio é Group", Seção 5): a
data migration cria o Group **`Cadastro pendente` com ZERO permissões**. Ele já
viaja em `UserOut.groups` (`accounts/schemas.py:44-49`), então
`sessao.temPapel('Cadastro pendente')` funciona **sem tocar em `accounts` e sem
requisição extra**. Na aprovação, `revoke_role_group` tira o marcador e
`create_teacher`/`create_student` põem Docente/Discente — o mesmo par que
`enroll_isolated_request` já usa.

> ⚠️ **O furo deste desenho, e a mitigação obrigatória.** O Group é do `User`,
> que é **global**; a `Person` é por programa. Quem já é docente ativo no PPGE e
> se cadastra no PPGD ganharia o marcador e seria mandado para a tela de espera
> **no programa em que já trabalha**. Mitigação no front:
> `pendenteDeConfirmacao = temPapel('Cadastro pendente') && permissions.length === 0`.
> No backend nada quebra: o marcador não retira permissão nenhuma. A
> alternativa sem furo exigiria `accounts` importar `academic` (proibido).
> Registrar o trade-off no docstring do marcador.

---

## 1. Interruptor por programa e lista pública

**`backend/apps/programs/models.py`** — em `Program`:
`accepts_self_signup = models.BooleanField("aceita autocadastro", default=False)`,
mais `ProgramQuerySet.accepting_self_signup()` →
`self.active().filter(accepts_self_signup=True)`. Query no `models.py`, como
manda a Seção 8.

**`backend/apps/programs/migrations/0007_program_aceita_autocadastro.py`** —
`AddField` com default **+ um `RunPython`** ligando o flag nos programas
`is_active=True`. Sem o backfill, o deploy derruba **em silêncio** o
autocadastro que hoje funciona pelo edital de isolada. `desfazer` = no-op
documentado.

**`backend/apps/programs/admin.py`** — flag em `list_display` e no form. É
exceção legítima ao ADR-006: criar programa já é ato de Admin, e o interruptor
nasce com o programa.

**`backend/apps/programs/schemas.py`** — `accepts_self_signup` em `ProgramOut`
(a secretaria enxerga o estado) e um `PublicProgramOut` **separado** com só
`id`, `name`, `acronym`. Schema à parte, e não reúso: rota pública não devolve
`is_active` nem o próprio flag.

**`backend/apps/programs/router.py`** — `GET /api/v1/programs/public`,
`auth=None`, com bloco `# público:` no espírito de `selection/router.py:1228-1240`
e `enforce_rate_limit(scope="programs-public-read", ...)`. Corpo:
`Program.objects.accepting_self_signup()`. A rota `GET /programs/` existente
(`:44`) fica intacta.

## 2. O model `AccessRequest`

**`backend/apps/academic/models.py`**, no fim do arquivo.

Dois enums **fora do model e com nome único**, pela armadilha já documentada em
`IsolatedRequestStatus` (`:1102-1108`): o OpenAPI batiza o schema pelo
`__name__`, e dois `Status` aninhados se sobrescrevem em silêncio.

```
AccessProfile        TEACHER="teacher" · STUDENT="student" · CANDIDATE="candidate"
AccessRequestStatus  PENDING · APPROVED · REJECTED
```

"Colaborador externo" **não** é valor de `AccessProfile` (decisão 4): é
`TEACHER` + `teacher_category=EXTERNAL`.

| campo | tipo | nota |
|---|---|---|
| `program` | FK `programs.Program`, PROTECT | ADR-007: direta, senão o `AuditLog` perde a chave de tenant |
| `person` | FK `people.Person`, PROTECT, `related_name="access_requests"` | FK e não OneToOne, pelo motivo de `Student.person` |
| `profile` | choices `AccessProfile` | só TEACHER/STUDENT viram linha |
| `teacher_category` | choices `Teacher.Category`, `blank=True` | declarado |
| `academic_degree` | choices `Teacher.AcademicDegree`, `blank=True` | declarado |
| `home_institution` | CharField(200), `blank=True` | obrigatória quando categoria = EXTERNAL |
| `lattes_url` | URLField, `blank=True` | |
| `status` | choices `AccessRequestStatus`, default PENDING | |
| `decision_note` | TextField, `blank=True` | motivo da recusa |
| `decided_at` | DateTimeField, null | |
| `created_at`/`updated_at` | carimbos técnicos | |

**Sem `decided_by`**: quem decidiu é o `actor` do `AuditLog`, como em
`IsolatedEnrollmentRequest`. Duplicar cria segunda verdade.

`CheckConstraint`, e não só `clean()` — a razão está escrita em `Student.Meta`:
não há caminho de escrita que as contorne.

1. `unique_solicitacao_pendente_por_pessoa` — `UniqueConstraint(fields=["person"],
   condition=Q(status="pending"))`. Índice **parcial**: uma pendente por pessoa,
   histórico livre. Como `Person` já é única por `(program, primary_email)`, isso
   é por pessoa **e** por programa.
2. `access_teacher_requires_category_and_degree`.
3. `access_external_requires_home_institution` — espelho no banco do
   `Teacher.clean()` (`:132-141`).
4. `access_non_teacher_has_no_teacher_fields` — simetria com
   `student_non_regular_requires_term`.

Métodos (a regra mora aqui; nenhum salva — quem persiste é o service, no mesmo
`atomic` do audit): `clean()` (`program_mismatch` e `home_institution_required`,
reusando os códigos que já existem), `ensure_decidable()`
(`InvalidStateTransition`, `code="already_decided"`), `approve()`,
`reject(*, note)` (`rejection_requires_note`), `campos_do_professor(accredited_since)`
devolvendo o dict pronto para `create_teacher`, e
`AccessRequestQuerySet.for_program()/.pending()`.

**Migrations** — `academic/0013_accessrequest.py` (model + constraints) e
`academic/0014_papeis_do_autocadastro.py`, no molde de `0011_papeis_da_isolada.py`:

- `"Cadastro pendente": []` — grupo novo, **lista vazia de propósito**, com
  docstring dizendo que é marcador de estado e não concede nada (ajustar o laço
  para criar Group com lista vazia);
- `"Secretaria": ["academic.view_accessrequest", "academic.change_accessrequest"]`;
- `"Coordenação": ["academic.view_accessrequest"]` — só acompanha.

Nenhum `delete_*`, nenhum `is_staff`/`is_superuser`. Ler as três migrations
antes do commit.

## 3. Cadastro público, e a aposentadoria do endpoint atual

**`academic/services.py`** — `signup_access_request`, `@transaction.atomic`,
adaptado de `signup_isolated_candidate` (`:313-376`) **preservando a ordem que
importa**:

1. `validar_senha(...)` **antes** de qualquer consulta de e-mail — senão "senha
   fraca" denuncia e-mail inédito (`:352-354`).
2. `email.strip().lower()`.
3. `Person` já existe no programa → `audit.record(created=False)` e **return
   silencioso**.
4. `create_person_with_user(...)` (`people/services.py:21-64`).
5. `if not user.has_usable_password(): user.set_initial_password(...)` — nunca
   tomar a conta de quem já existe em outro programa.
6. Ramo por perfil: `CANDIDATE` → `assign_role_group("Candidato")` e **nenhuma
   linha de `AccessRequest`**; `TEACHER`/`STUDENT` → monta o `AccessRequest`,
   `clean()`, `save()`, `assign_role_group("Cadastro pendente")`.
7. `audit.record("academic.access.signup", profile=..., created=True)`.

Resolução do tenant, substituindo `programa_com_inscricao_aberta` (`:213-241`):

```python
def programa_que_aceita_autocadastro(*, program_id: int) -> Program:
    # O tenant vem da lista pública, e a trava passa a ser o flag — não mais
    # a janela do edital. Continua não sendo escolha livre do chamador.
    ...raise DomainError("Este programa não está aceitando cadastros.",
                         code="signup_closed")
```

**Mesmo `code` para programa inexistente, inativo e flag desligada** —
distinguir contaria a quem chuta id quais programas existem.

**`academic/schemas.py`**, substituindo `IsolatedSignupIn/Out` (`:840-864`):
`AccessSignupIn` (`program_id: int` obrigatório, `profile`, `full_name`,
`email: EmailStr`, `phone_number`, `password`, e os declarados do docente),
`AccessSignupOut` (`detail: str`, `requires_confirmation: bool`),
`AccessRequestOut`, `AccessApproveIn`, `AccessRejectIn`, `AccessStatusOut`.

**`academic/router.py`** — `POST /api/v1/access/signup`, `auth=None`,
`@decorate_view(csrf_protect)`. Travas no molde do bloco `# público:` de
`:1465-1476`: `enforce_rate_limit(scope="access-signup", limit=5, window=3600)`,
`csrf_protect` explícito (`auth=None` desliga junto o CSRF do `SessionAuth` —
mesma armadilha do login) e o tenant nunca livre. Texto por perfil: candidato
recebe "use seu e-mail e sua senha para entrar"; docente e discente recebem
**"Cadastro recebido. Este cadastro deve ser confirmado pela secretaria."**

**`backend/api.py`** — `api.add_router("/access/", access_router)`.

### O endpoint antigo: substituir, no mesmo PR

Com `profile=candidate` a rota nova faz exatamente o que a antiga fazia, e a
trava que muda é a decisão 6. Manter as duas dobraria a superfície pública e
deixaria viva a trava que foi mandada aposentar. Então: remover
`isolated_signup` (`router.py:1462-1500`), `IsolatedSignupIn/Out`,
`signup_isolated_candidate` e `programa_com_inscricao_aberta`. **Não** tocar em
`ciclo_com_inscricao_aberta` (`services.py:243-265`), que é outra coisa e
continua servindo à inscrição. É mudança de contrato publicado →
`review_required` e `make gen-api` obrigatório.

**Duas docstrings que este plano revoga**, e que precisam ser reescritas junto
com o código — docstring que mente é pior que docstring nenhuma:

1. `IsolatedSignupIn` diz que `program_id` é opcional porque "o tenant não é
   escolha livre de quem chama". Agora é obrigatório, mas **continua não sendo
   livre**: só programa com o flag ligado é aceito, e é a lista pública que o
   alimenta. A trava mudou de lugar, não sumiu.
2. `IsolatedSignupOut` diz que o corpo é fixo. Passa a variar **por perfil**,
   nunca por existência de conta — o perfil vem do próprio pedido.

**`test_isolada_signup.py` → `test_autocadastro.py`**, teste a teste:

| teste atual | vira |
|---|---|
| cria conta/pessoa/papel Candidato | idem, com `profile=candidate` |
| e-mail repetido devolve o mesmo corpo | **mantido intacto** — é o teste mais valioso do arquivo |
| conta existente não tem senha trocada | mantido |
| senha fraca recusada | mantido |
| limite por IP | mantido (`scope` novo) |
| sem CSRF é 403 | mantido |
| fora da janela / sem edital | flag desligada → 400 `signup_closed` |
| `program_id` desempata dois editais | some; vira `program_id` sem flag → `signup_closed` |
| grupo Candidato sem acesso a negócio | mantido, **+ o mesmo para `Cadastro pendente`** |

## 4. Login do pendente e tela de espera

**`GET /api/v1/access/me`** no `access_router`, autenticado e **sem
`require_perm`**, com o comentário no molde de `/auth/me`
(`accounts/router.py:88-91`): devolve apenas o estado do próprio cadastro. Não
usa `current_program` — o recusado tem a `Person` arquivada e o helper
devolveria 403. Responde `AccessStatusOut`; 404 quando não há solicitação.

**`frontend/src/lib/sessao.svelte.ts`**:

```ts
get pendenteDeConfirmacao(): boolean {
  // O Group é do User, que é global; a Person é por programa. Quem já
  // trabalha em outro programa e se cadastra aqui carrega o marcador sem
  // estar pendente lá — a ausência de QUALQUER permissão separa os casos.
  return this.temPapel('Cadastro pendente') && (this.usuario?.permissions.length ?? 0) === 0;
}
```

`rotaInicial` ganha o primeiro ramo (e o tipo de retorno inclui
`'/aguardando-confirmacao'`): pendente → `/aguardando-confirmacao`;
`pode('people.view_person')` → `/pessoas/administrativo`; senão `/inscricao`.
Isso conserta de uma vez `routes/+page.svelte` e o `goto` do login, sem tocar
neles.

**`(auth)/aguardando-confirmacao/+page.svelte`** — fica em `(auth)` e **não** em
`(app)`: assim "sem menu, sem dados" é estrutural, e não condicional. Mostra o
perfil declarado via `/access/me`, o motivo quando recusado, e botão Sair.

**`(app)/+layout.svelte`** — no `$effect` da guarda (`:19-22`), antes de tudo,
desviar o pendente.

**A trava que vale é do backend**: o pendente não tem permissão alguma, então
`require_perm` devolve 403 em toda rota de negócio. A tela existe para ele não
ver uma parede de erro.

## 5. Fila da secretaria

Desenho copiado de `academic/router.py:1191-1281` + `(app)/analise/+page.svelte`.

**`_solicitacao_para_decidir(...)`** — espelho de `_requerimento_para_decidir`
(`:1191-1216`), com `raise NotAllowed("Ninguém confirma o próprio cadastro.")`.
**Sem essa linha, uma secretária cadastrando-se como docente aprovaria a si
mesma.**

```
GET  /api/v1/access/requests/                  require_perm academic.view_accessrequest
POST /api/v1/access/requests/{id}/approve      require_perm academic.change_accessrequest
POST /api/v1/access/requests/{id}/reject       require_perm academic.change_accessrequest
```

- **Fila**: `require_perm` → `current_program` → `for_program(program)`, filtro
  de `status` opcional (default `pending`), `@paginate`. Filtro **no servidor**,
  como em `analise/+page.svelte:29-35`.
- **Approve** — `AccessApproveIn`: `accredited_since` (docente) ou `level`,
  `project_id`, `advisor_id`, `admission_date` (discente); `deadline` sai
  sozinho do `Student.save()` (`models.py:369-378`). O router resolve
  `project`/`advisor` **escopados em `for_program(program)`** — id de outro
  programa vira 404 na borda, não `IntegrityError` no service.
- **Reject** — `AccessRejectIn { note }`; a obrigatoriedade é do model.

**Services** (escrevem em mais de um model → ADR-002):

```python
@transaction.atomic
def approve_access_request(*, solicitacao, campos, request=None):
    solicitacao.ensure_decidable()
    create_teacher(...) if TEACHER else create_student(...)   # já existem
    revoke_role_group(user, group_name="Cadastro pendente", request=request)
    solicitacao.approve(); solicitacao.save(update_fields=[...])
    audit.record("academic.access_request.approve", ...)
```

Reúso puro: `create_teacher` (`services.py:58-104`) e `create_student`
(`:107-145`) **já** fazem `clean()` → `save()` → `assign_role_group` no mesmo
atomic. A ficha nasce antes do papel, sem janela — decisão 5 satisfeita.

`reject_access_request` grava o motivo e **arquiva a `Person`**
(`people/models.py:129`), que é o que faz `current_program` recusar o recusado
em toda rota — o marcador sozinho não travaria nada se um dia ganhasse
permissão.

## 6. Telas

- **`(auth)/cadastro/+page.svelte` — reescrita no lugar.** Manter a rota
  `/cadastro` evita a armadilha do `.svelte-kit` para ela e aproveita o link que
  o login já tem. Mantém split screen, `garantirCsrf()`, `mensagemDeErro`,
  `senhasDiferem` e a caixa de sucesso com `data.detail` + link para `/login`
  (sem login automático). Ganha: `select` de programa (de `/programs/public`,
  com recado e formulário desabilitado se a lista vier vazia), `select` de
  perfil com a nota de que **colaborador externo se cadastra como Docente e
  escolhe a categoria**, e o bloco `{#if perfil === 'teacher'}` com categoria,
  titulação, Lattes e `home_institution` — que só aparece, e só é `required`,
  quando a categoria é `external`.
- **`frontend/src/lib/acesso.ts`** (novo, espelho de `lib/isolada.ts`):
  `ROTULO_DO_PERFIL`, `ROTULO_DA_CATEGORIA`, `ROTULO_DA_TITULACAO`,
  `ROTULO_DA_SITUACAO`, compartilhados pelas três telas.
- **`(app)/solicitacoes/+page.svelte`** — decalque de `analise/+page.svelte`:
  filtro no servidor, `abertoId` com um item aberto por vez, painel com o
  declarado. **Confirmar** abre os campos que a secretaria preenche na hora;
  **Recusar** exige motivo. Cuidado com a armadilha do `openapi-fetch`:
  `const falha = resposta.error` **antes** do `if`.
- **`(app)/+layout.svelte`** — "Solicitações de acesso" no submenu Pessoas,
  condicionado por `sessao.pode('academic.view_accessrequest')`. Aqui é `pode()`
  e não `temPapel()`: a permissão é exclusiva de Secretaria e Coordenação, então
  distingue o público sozinha (critério de `sessao.svelte.ts:26-33`).
- **`(auth)/login/+page.svelte:115`** — o link deixa de citar isolada.
- `make gen-api` para `schema.d.ts` e `openapi.json`.

## 7. Testes, por camada

- **Model, sem banco**: transição dupla → `already_decided`; `reject(note="  ")`
  → `rejection_requires_note`; `program` divergente de `person.program` →
  `program_mismatch`; externo sem instituição → `home_institution_required`.
- **Constraints, com banco** (molde de `test_student_constraints.py`): duas
  pendentes da mesma pessoa → `IntegrityError`; pendente + recusada anterior →
  **passa** (o índice é parcial); docente sem categoria/titulação e externo sem
  instituição → `IntegrityError`.
- **API pública**: docente pendente cria `Person` + `User` + `AccessRequest`,
  entra em `Cadastro pendente` e **em mais nenhum**; candidato sem
  `AccessRequest`; **corpo idêntico byte a byte** para e-mail novo e repetido,
  por perfil; `signup_closed` igual para flag desligada, programa inativo e id
  inexistente.
- **API da secretaria**: fila escopada por programa (solicitação de outro tenant
  **não aparece**); aprovar docente cria `Teacher`, entra Docente e sai o
  marcador; aprovar discente cria `Student` REGULAR com `deadline` calculado;
  aprovar duas vezes → `already_decided`; recusar sem motivo → 400, com motivo →
  `Person` arquivada; **quem se cadastrou não decide o próprio cadastro** → 403;
  Docente/Discente/Candidato na fila → 403.
- **Papéis**: `Cadastro pendente` tem **zero** permissões, e o pendente leva 403
  em `/people/`, `/academic/teachers/`, `/academic/students/`.
- Dois papéis agindo no mesmo teste pedem um `Client()` cada — duas fixtures com
  `force_login` na `client` do pytest-django disputam a mesma sessão e a última
  vence, em silêncio.

## 8. Ordem de execução (o cronograma sai daqui)

1. **F1** — flag + migration com backfill + Admin + `/programs/public` + seed.
2. **F2** — model `AccessRequest` + migrations + papéis + testes de model.
3. **F3** — `signup_access_request` + `POST /access/signup` + morte do endpoint
   antigo + testes portados.
4. **F4** — `/access/me`, `pendenteDeConfirmacao`, `rotaInicial`, tela de espera,
   guarda do `(app)`.
5. **F5** — fila, aprovar, recusar.
6. **F6** — telas + menu + `make gen-api`.

As stories de schema (1 e 2) ficam **cedo** de propósito: o loop constrói em
cima do schema que ele mesmo escreveu, e migration tardia custa retrabalho.

## 9. Gates — o que o `prd.json` marca

Pelo critério do `CLAUDE.md` ("o efeito escapa da worktree?"), **nada aqui é
`human_gate`**: não há envio a terceiro, e tudo escreve no banco do próprio
canteiro.

`review_required: true` nas stories que tocam: as **três migrations**;
**permissões e tenant** (a data migration de papéis e toda rota da fila —
vazamento entre programas não aparece em lint e, com um programa só, nem em
teste); o **contrato de API publicado** (`academic/router.py`, `schemas.py`,
`programs/router.py`, `openapi.json`, `schema.d.ts`); e a **decisão sobre vida
acadêmica** nos services de aprovação.

## 10. Riscos e armadilhas

1. **Enumeração de contas.** O corpo é função apenas do payload:
   `requires_confirmation` e `detail` saem do `profile` enviado, e o ramo
   "e-mail já existe" retorna em silêncio. `validar_senha` **antes** da consulta.
   Teste byte a byte mantido.
2. **Conta que já existe em outro programa — o risco mais sério do plano.** Ver
   a caixa da Seção 0.2. Mitigação no front (`permissions.length === 0`), nada
   quebra no backend, e a senha não é trocada (teste já existente).
3. **Autodeclarar-se docente não concede nada.** `Cadastro pendente` tem zero
   permissões; só a aprovação — que exige `academic.change_accessrequest`, isto
   é, Secretaria — cria o `Teacher` e com ele o papel. Mais duas travas: ninguém
   decide a própria solicitação, e a fila é escopada por `current_program`.
4. **Group antes de ficha.** `create_teacher`/`create_student` assinam o papel
   **depois** do `save()` da ficha, no mesmo atomic — não há janela. O marcador é
   a única concessão de grupo sem ficha, e é vazia por construção; um teste trava
   isso.
5. **Colisão de enum no OpenAPI** — nomes únicos e fora do model
   (`models.py:1102-1108`).
6. **`make typecheck` com `EACCES`.** Duas rotas novas
   (`(auth)/aguardando-confirmacao`, `(app)/solicitacoes`): o Vite do container
   regenera `.svelte-kit/types` como root. Conserto:
   `docker compose exec -T frontend sh -c 'rm -rf "/app/.svelte-kit/types/src/routes/(app)/solicitacoes"'`
   (e a outra). `find frontend/.svelte-kit -user root` lista o que ficou.
7. **`default=False` sem o `RunPython`** derruba em silêncio o autocadastro que
   hoje funciona por edital aberto. O backfill é parte da migração.
8. **Recusado não se recadastra**: a `unique_email_por_programa` barra e a
   resposta é o mesmo corpo silencioso. Consequência aceita do anti-enumeração;
   a saída é a secretaria reativar a pessoa. Deixar escrito no docstring de
   `reject_access_request` e na tela da fila.
9. **`save(update_fields=[...])`** em toda transição — e `updated_at` precisa
   entrar na lista, senão o `auto_now` não é gravado.
10. **`prefetch_related` só vale com `.all()`** no método do model; qualquer
    `.filter()` no gerente reverso vai ao banco de novo, sem erro e sem
    diferença de resultado.

## 11. Antes de montar o canteiro

Este plano cria **três leaf nodes de migration** (um em `programs`, dois em
`academic`), então precisa entrar no `manifest.json` do `/compatibilizar` antes
de rodar em paralelo com qualquer plano que mexa nesses apps — dois canteiros
criando migration no mesmo app param o `migrate` seguinte com "Conflicting
migrations detected", já na base, depois do merge.

O README de `projects/` também lembra: **commit e push do plano**, porque a
guarda do `montar-canteiro.sh` procura o arquivo em `origin/develop`, não no
diretório de trabalho.

## 12. Verificação

1. `make up` e `make seed` (o seed liga o flag nos dois programas).
2. `make ready` verde — pré-condição de qualquer commit.
3. Manual, em http://localhost:8080 (nunca :5173, que quebra login e CSRF):
   - `/cadastro` → Candidato → login → cai em `/inscricao`, como hoje;
   - `/cadastro` → Docente, categoria Externo **sem** instituição → recusado;
     com instituição → login → cai em `/aguardando-confirmacao`, sem menu;
   - `secretaria@ppgd.test` (senha `demo@ppgd2026`) → Solicitações de acesso →
     confirmar → o docente entra e vê o sistema, e existe `Teacher` com a
     categoria declarada;
   - `secretaria@ppga.test` → a solicitação do PPGD **não** aparece.
4. Conferir o `AuditLog` dos eventos `academic.access.signup`,
   `academic.access_request.approve` e `...reject` pelo shell do backend.
