
# PPGD Manager

Guia normativo do projeto para agentes de código e para o time de dev.
Em caso de conflito entre este arquivo e código existente, este arquivo
vence — abra um PR corrigindo o código ou propondo mudança aqui.

> **Contexto do time**: o time é forte em infraestrutura (Proxmox,
> servidores, backup, redes) e com experiência iniciante/desconhecida em desenvolvimento. 
> Toda decisão deste documento favorece **menos decisões em aberto** e **menos peças
> móveis**, mesmo quando existe alternativa tecnicamente mais sofisticada.
> Não introduza padrões, camadas ou bibliotecas novas sem discutir antes.

---

## 1. Visão geral

Sistema de gestão para programa de pós-graduação (PPGD). Criado para uma Instituição, mas devemos fazer já multi-tenant com chave para "programa de pós" tem todas as tabelas porque futuramente será usado em outros cursos. Primeiro módulo: identidade e acesso (pessoas,
usuários, papéis, permissões, auditoria). Módulos de negócio virão depois
sobre a mesma fundação.

## 2. Stack — decidida, não reabrir sem ADR

| Camada | Escolha | O que NÃO usar |
|---|---|---|
| Linguagem backend | Python 3.12+ | — |
| Framework web | **Django 5.x** (síncrono) | FastAPI, Litestar, Flask; views async |
| API | **Django Ninja** (`/api/v1/...`) | DRF, GraphQL |
| Validação/DTO | Pydantic v2 via schemas do Ninja | msgspec, marshmallow |
| ORM | **Django ORM** + migrações do Django | SQLAlchemy, SQL cru (salvo relatório pontual via `.raw()` justificado em comentário) |
| Banco | PostgreSQL 16+ | SQLite fora de teste local |
| Auth | **Sessão do Django** (cookie httpOnly) + CSRF do Django | JWT, tokens próprios, OAuth caseiro |
| Autorização | Grupos e permissões nativos do Django | Sistema de RBAC próprio |
| Admin interno | **Django Admin** restrito a superusuários (sysadmin) | Dar acesso ao Admin a usuário de negócio; resolver no Admin o que é tela de usuário final |
| Frontend | **SvelteKit (Svelte 5, runas) + `adapter-static`** — SPA pura, `ssr = false` | `adapter-node`, SSR, processo Node em produção |
| CSS | Tailwind v4 | CSS-in-JS |
| Tipos de API no front | `openapi-typescript` + `openapi-fetch` a partir do OpenAPI do Ninja | Tipar respostas à mão |
| Deps Python | `uv` (`pyproject.toml` + lockfile) | pip/requirements.txt, poetry |
| Deps front | `npm` | yarn, pnpm, bun |
| Proxy | **Nginx** unificando front e API em **uma origem só** | Front e API em portas/origens separadas |
| Testes | `pytest` + `pytest-django` | unittest puro |
| Lint/format | `ruff` (lint + format) backend; `prettier` + `eslint` front | black, isort separados |
| Typecheck | `mypy` (backend), `svelte-check` (front) | — |

### Política de versões
**Django: sempre a LTS vigente.** Hoje é a 5.2 (segurança até abr/2028).
Versão não-LTS entra em suporte só de segurança em poucos meses e obriga
upgrade a cada ciclo — custo recorrente que este time não deve pagar. O
próximo salto é para a **6.2 LTS (abr/2027)**, direto: um upgrade em vez
de três. Sair da LTS exige ADR com o recurso concreto que justifica.

**Python: a mais recente que a LTS do Django suportar.** Hoje é a 3.14.
Aqui a lógica é oposta à do Django — versões do Python têm cinco anos de
suporte e não criam obrigação de upgrade, então ficar para trás só
acumula dívida sem contrapartida.

**PostgreSQL: 16+.** Trocar a *major* invalida o volume de dados; o
caminho é `pg_dump`, recriar o volume e restaurar (ver comentário no
`docker-compose.yml`).

### Por que síncrono
Carga de uma instituição única não justifica async. Django síncrono
elimina classes inteiras de bug (`await` esquecido, objeto fora de event
loop) que são venenosas para quem está aprendendo. Se um dia houver
gargalo real de I/O, mede-se primeiro; não se antecipa.

### Por que o Admin é só para sysadmin
O Django Admin é ferramenta de **operação da plataforma**, não de uso do
programa. Quem entra nele somos nós, sysadmins, como superusuários. Ver
ADR-006.

Dois motivos, nesta ordem:

1. **O Admin desvia do domínio.** Ele edita campos direto no banco: lá,
   arquivar uma pessoa é trocar o `status` num `<select>` — o método
   `Person.archive()` nunca roda e o invariante que ele protege não
   existe naquele caminho. Duas portas para o mesmo dado, e uma ignora as
   regras.
2. **Duas interfaces parecem dois sistemas.** Para quem não é
   desenvolvedor, a troca de linguagem visual entre o Admin e o Svelte
   confunde e destrói a noção de um produto só.

O que fazemos no Admin: **criar programas** (novos tenants), **ler a
auditoria** e **corrigir dados** quando o sistema errou. Correção é
quebra-vidro, não rotina — e é sempre auditada.

**Todo o resto é tela Svelte.** Regra prática, que substitui a anterior:
se a pessoa que vai usar a tela é usuário do programa — secretaria,
coordenação, docente, discente —, a tela é no front, com endpoint,
permissão e auditoria. Não existe "mando ela usar o Admin".

Isso tem preço: entidade nova custa uma fatia vertical inteira, e não um
`ModelAdmin` de três linhas. O preço é conhecido e aceito.

---

## 3. Arquitetura — duas camadas, sem cerimônia extra

```
Navegador (SPA Svelte, arquivos estáticos servidos pelo Nginx)
   │  fetch() same-origin → /api/v1/...
   ▼
Nginx (origem única, :8080 em dev)
   ├── /            → arquivos estáticos do build do SvelteKit
   ├── /api/        → gunicorn/Django (Ninja)
   ├── /admin/      → Django Admin
   └── /static/ e /media/ → estáticos do Django (admin, uploads)
   ▼
Django
   ├── api.py / routers por app (borda HTTP: schemas Ninja, auth, permissão)
   ├── models.py (dados + REGRA DE NEGÓCIO nos métodos do model)
   └── services.py (opcional, só quando a operação cruza vários models)
   ▼
PostgreSQL
```

### Onde mora cada coisa

1. **Model = entidade de domínio.** Regra de negócio que protege
   invariante fica em **método do próprio model**:

   ```python
   class Person(models.Model):
       class Status(models.TextChoices):
           ACTIVE = "active"
           ARCHIVED = "archived"

       status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)

       def archive(self) -> None:
           if self.status == self.Status.ARCHIVED:
               raise InvalidStateTransition("Pessoa já está arquivada.")
           self.status = self.Status.ARCHIVED
   ```

   Teste de invariante = instanciar o model em memória e chamar o método.
   Sem banco, sem mock.

2. **Router (Ninja) = borda.** Recebe schema de entrada, checa permissão,
   chama model/service, devolve schema de saída. **Nunca** contém regra
   de negócio. **Nunca** serializa model direto — sempre via schema de
   resposta explícito (o contrato da API não pode mudar por acidente
   quando uma coluna muda).

3. **`services.py` (por app, opcional).** Só existe quando uma operação
   escreve em **mais de um** model e precisa ser atômica. Função simples
   com `transaction.atomic()`:

   ```python
   @transaction.atomic
   def create_person_with_user(*, full_name: str, email: str) -> Person:
       person = Person.objects.create(full_name=full_name, primary_email=email)
       User.objects.create_user(username=email, email=email)
       AuditLog.objects.create(event="people.create", target=person)
       return person
   ```

   Se a operação toca um model só, chame o manager/método do model
   direto do router. Não crie service "por simetria".

4. **Sem camadas além dessas.** Sem Repository, sem Mapper, sem Unit of
   Work, sem entidade paralela ao model, sem interfaces/Protocols. O ORM
   do Django já é o repositório e o mapper. 

### Auditoria
Toda escrita relevante (criar/alterar/arquivar pessoa, mudar permissão,
login/logout) registra um `AuditLog` (app `audit`): quem, quando, o quê,
alvo. Nas operações multi-model isso acontece dentro do service; nas
simples, no router logo após a escrita, dentro do mesmo
`transaction.atomic()`.

---

## 4. Estrutura de diretórios

```
ppgd/
├── CLAUDE.md
├── docker-compose.yml          # db + backend + nginx (perfil dev)
├── nginx/nginx.conf            # origem única
├── backend/
│   ├── pyproject.toml          # uv
│   ├── manage.py
│   ├── config/                 # settings, urls, wsgi
│   │   ├── settings/base.py | dev.py | prod.py
│   │   └── urls.py             # inclui api.urls e admin
│   ├── api.py                  # NinjaAPI raiz (versão, auth, exception handlers)
│   └── apps/
│       ├── people/             # models, admin, router, schemas, services, tests/
│       ├── accounts/           # usuários, papéis (em cima do auth do Django)
│       └── audit/
└── frontend/
    ├── package.json
    ├── svelte.config.js        # adapter-static, fallback: 'index.html'
    └── src/
        ├── routes/+layout.ts   # export const ssr = false
        ├── routes/(app)/...    # telas
        └── lib/
            ├── api/client.ts   # openapi-fetch, baseUrl '/api/v1' (RELATIVA — nunca URL absoluta)
            └── api/schema.d.ts # GERADO — não editar à mão
```

Cada app Django tem: `models.py`, `admin.py`, `router.py`, `schemas.py`,
`services.py` (se precisar), `migrations/`, `tests/`.

---

## 5. Autenticação, CSRF e permissões

- **Login** via endpoint Ninja (`POST /api/v1/auth/login`) usando
  `django.contrib.auth.authenticate/login`. Sessão em cookie httpOnly
  gerido pelo Django. Logout revoga a sessão no servidor.
- **CSRF**: o do Django, sempre ativo. O client do front lê o cookie
  `csrftoken` e envia `X-CSRFToken` em toda escrita (isso fica resolvido
  **uma vez** dentro de `lib/api/client.ts`; nenhuma tela lida com CSRF).
- **Origem única é inegociável.** Front e API sempre atrás do mesmo
  Nginx, mesma origem. `baseUrl` do client é **relativa** (`/api/v1`).
  Nunca configurar CORS — se você sentiu necessidade de CORS, o deploy
  está errado, não o código.
- **Permissões**: usar `Permission`/`Group` nativos. Papéis do domínio
  (ex.: "Secretaria", "Coordenação") = Groups criados por data migration.
  Na rota, checagem explícita e visível:

  ```python
  @router.post("/", response=PersonOut)
  def create_person(request, payload: PersonIn):
      require_perm(request, "people.add_person")   # helper único do projeto
      ...
  ```

  Rota sem checagem explícita de permissão **não passa em review**
  (exceto as marcadas `# público` com justificativa).
- **Escopo de tenant**: toda listagem/consulta de dado de negócio escopa
  por `current_program(request)` (`apps/core/tenancy.py`), o segundo
  helper único do projeto, chamado logo depois do `require_perm`. O
  programa sai da(s) `Person` ativa(s) do usuário; nunca de um
  `program_id` que o chamador escolhe livremente — filtro opcional vaza o
  tenant inteiro para quem omitir o parâmetro.
- **Admin restrito a superusuários** (ADR-006). A trava é de código, não
  de combinado: `admin.site.has_permission` exige `is_superuser`, então
  `is_staff` sozinho não abre a porta. Sempre atrás de VPN/rede interna em
  produção (alinhar com infra).
- **Nenhum usuário de negócio recebe `is_superuser`.** Papel de domínio é
  Group; `is_superuser` é para quem opera a plataforma. Data migration ou
  script que dê superusuário a papel de negócio não passa em review.
- **Escrita feita no Admin também gera `AuditLog`.** É onde o rastro mais
  importa: quem escreve por ali tem poder total e desvia das regras do
  model.

---

## 6. Fluxo de trabalho — campo novo, da tela ao banco

Exemplo: `phone_number` opcional em `Person`.

1. `apps/people/models.py` — campo no model.
2. `uv run python manage.py makemigrations && uv run python manage.py migrate`
3. `apps/people/schemas.py` — campo em `PersonIn` e `PersonOut`.
4. Router: normalmente sem alteração (payload validado entra, schema de
   saída já cita o campo).
5. `apps/people/admin.py` — adicionar em `list_display`/`fields` se fizer
   sentido.
6. `npm run gen:api` (backend rodando) — regenera `schema.d.ts`.
7. Telas Svelte que usam o campo.
8. Teste: se o campo carrega regra, teste no model; senão, um assert no
   teste de API existente basta.

**Total esperado: ~6 arquivos.** Se um campo simples está exigindo mais
que isso, algo está errado na arquitetura — pare e discuta.

---

## 7. Comandos

Tudo via `Makefile` na raiz (manter atualizado — comando novo entra aqui,
não só no README).

| Ação | Comando |
|---|---|
| Instalar deps backend | `make install` (`cd backend && uv sync`) |
| Instalar deps front | `make install-web` |
| Subir só o banco | `make db` (`docker compose up -d db`) |
| Subir tudo (dev, com Nginx) | `make up` — sobe db, backend, frontend e nginx; abrir **http://localhost:8080** (a porta do Vite não é publicada) |
| Backend nativo com reload | `make run` (`uv run python manage.py runserver`) |
| Log do Vite | `make web` (`docker compose logs -f frontend`) — o Vite é serviço do Compose e sobe no `make up` |
| Criar migrações | `make migrations` |
| Aplicar migrações | `make migrate` |
| Criar superusuário | `make superuser` |
| Gerar tipos TS | `make gen-api` (backend precisa estar de pé) |
| Testes backend | `make test` (`uv run pytest`) |
| Lint + format tudo | `make lint` |
| Typecheck tudo | `make typecheck` (mypy + svelte-check) |
| Tudo antes de commit | `make ready` (lint + typecheck + test) |

**`make ready` verde é pré-condição de qualquer commit.**

---

## 8. Convenções de código

**Backend**
- Nomes de model no singular (`Person`), tabelas com prefixo do app
  (padrão do Django — não sobrescrever `db_table` sem motivo).
- Queries fora de `models.py`/managers precisam de justificativa;
  preferir métodos de manager nomeados (`Person.objects.active()`).
- Dinheiro/notas: `DecimalField`, nunca `FloatField`.
- Datas sempre com timezone (`USE_TZ = True`); `models.DateTimeField`
  com `auto_now*` só para carimbo técnico, nunca para dado de negócio.
- Exceções de negócio herdam de `DomainError` (app `core`); o
  exception handler central do Ninja as mapeia para 4xx com corpo
  padronizado `{"detail": ..., "code": ...}`. Router não faz try/except
  de negócio.
- Migração gerada é **sempre revisada** antes do commit (ler o arquivo,
  não só confiar no autogenerate).

**Frontend**
- Svelte 5 com runas (`$state`, `$derived`, `$props`); não usar sintaxe
  legada de stores para estado local.
- Toda chamada de API via `lib/api/client.ts` tipado; `fetch` cru é
  proibido nas telas.
- `schema.d.ts` é gerado; PR que o edita à mão é recusado.
- Navegação interna sempre por `resolve()` de `$app/paths` — o lint
  `svelte/no-navigation-without-resolve` recusa `href` literal, e a rota
  tipada do SvelteKit só conhece o que já existe em `src/routes/`. Link
  para tela ainda não escrita exige criar a rota (nem que seja um
  `+page.svelte` marcador). URL de `/api/` e de `/media/` **não** é rota da
  SPA: ali `resolve()` não se aplica e o `eslint-disable` local da regra é
  o padrão do projeto.
- Formulários: validação de UX no front, mas a validação que vale é a do
  schema Ninja no backend. Nunca confiar só no front.

**Geral**
- Commits pequenos, mensagem em português, modo imperativo
  ("adiciona campo phone_number em Person").
- PR precisa de: `make ready` verde, migração revisada (se houver),
  screenshot para mudança visual.

## 9. Testes

- `pytest-django` com banco Postgres de teste (não SQLite — paridade com
  produção).
- Pirâmide simples: (a) invariantes → teste de model sem banco quando
  possível; (b) fluxo → teste de API com `django.test.Client`/client do
  Ninja batendo no endpoint real; (c) sem teste de "camada service"
  isolada com mock de ORM — teste o comportamento pela API.
- Todo bug corrigido ganha um teste que o reproduz antes do fix.

## 10. Deploy (alinhado com o time de infra)

Produção é o mesmo desenho do dev, sem surpresas:

- **1 Nginx** (TLS, origem única): estáticos do front (build do
  `adapter-static`), proxy para o Django em `/api/` e `/admin/`,
  `/static/` e `/media/` do Django.
- **1 processo Python**: `gunicorn` servindo o WSGI do Django (systemd ou
  container — decidir com infra; sem processo Node em produção, em
  nenhuma hipótese).
- **1 PostgreSQL** com backup no esquema que a infra já domina
  (`pg_dump` diário no mínimo; testar restore periodicamente).
- Deploy do front = `npm run build` + copiar artefatos pro diretório do
  Nginx. Deploy do back = migrar (`manage.py migrate`) + recarregar
  gunicorn. Ordem: migração primeiro, sempre retrocompatível com o
  código anterior (campo novo entra `null=True` ou com default).
- Variáveis de ambiente via `.env` (nunca commitado); `SECRET_KEY`,
  `DATABASE_URL`, `ALLOWED_HOSTS`, `DEBUG=False` em prod.

## 11. Decisões registradas (ADRs curtos)

Mudança de stack, camada nova, biblioteca nova ou padrão novo exige um
ADR de meia página em `docs/adr/NNN-titulo.md`: contexto, decisão,
consequências. Já valem como decididos:

- **ADR-001**: Django síncrono + Ninja; sem async (ver Seção 2).
- **ADR-002**: Model = entidade; sem Repository/Mapper/UoW/Protocol
  (ver Seção 3).
- **ADR-003**: Sessão + CSRF do Django; sem JWT (ver Seção 5).
- **ADR-004**: Origem única via Nginx; CORS proibido (ver Seção 5).
- **ADR-005**: Front `adapter-static`; sem SSR e sem Node em produção
  (ver Seção 2). Se um dia SSR for necessário, é ADR novo com
  aprovação da infra, porque cria um processo novo para operar.
- **ADR-006**: Admin só para sysadmin; todo usuário de negócio é servido
  pelo front (ver Seções 2 e 5). Substitui a orientação anterior de
  "tente o Admin primeiro para tela de operador interno".
- **ADR-007**: no aluno, modalidade do vínculo (Regular/Isolada/Eletiva)
  é campo separado da situação (Ativo/Trancado/Excluído); `Student.person`
  é FK e não OneToOne; período letivo é entidade **institucional** (sem
  FK de programa — única exceção, o calendário é o da UFMG inteira);
  **todo o resto dos models de negócio carrega FK `program` direta**,
  mesmo quando alcançável por navegação — sem ela o `AuditLog` perde a
  chave de tenant.
- **ADR-008**: o PDF da ata do processo seletivo sai do **ReportLab**, montado
  em `apps/selection/pdf.py`; sem HTML-para-PDF e sem binário externo. O texto
  da ata continua sendo o `content` congelado no banco — o PDF é renderização,
  nunca a fonte.
- **ADR-009**: e-mail (token de assinatura, convocação) vai por
  `django.core.mail`, **síncrono e sem fila** — nada de Celery, retry automático
  ou broker. Falha de envio vira linha visível e reenviável pela secretaria
  (`ConvocationEmail` com status), não exceção engolida. O envio fica **fora**
  do `transaction.atomic`. SPF/DKIM/relay de produção se alinham com a infra;
  ambiente que envia precisa de `SITE_URL`.

## 12. O que este projeto NÃO faz (anti-padrões)

- Regra de negócio em router ou em tela Svelte.
- Serializar model direto na resposta da API.
- Camada/abstração "para o futuro" sem caso de uso presente.
- URL absoluta de API no front; qualquer configuração de CORS.
- `FloatField` para dinheiro/nota.
- Editar `schema.d.ts` ou arquivos de migração aplicados à mão.
- Endpoint de escrita sem permissão checada e sem auditoria.
- Async "porque é moderno".
- Mandar usuário de negócio para o Django Admin porque a tela ainda não
  existe. Se falta tela, o trabalho é escrever a tela.
- Dar `is_staff` ou `is_superuser` a papel de domínio.
- Escrita no Admin sem `AuditLog`.

---

## Human gates

**A régua é o canteiro, não o arquivo.** A pergunta não é "este arquivo é
sensível?", é **"o efeito escapa da worktree?"**. Cada agente roda numa worktree
própria, com stack Compose e volume de banco próprios — o que acontece lá dentro
se desfaz com `git` e com `desmontar-canteiro.sh --volumes`. Barrar o que o
canteiro contém não protege nada: trava a empreitada cedo, e o `blocked_by_gate`
transitivo leva as dependentes junto.

Os campos do `prd.json` são dois:

- **`human_gate: true`** — o loop **não executa**. Só para o efeito que escapa.
- **`review_required: true`** — o loop **executa**, e a story aparece no índice
  do `desmontar-canteiro.sh` para o humano conferir antes do merge.

Teste concreto: *o estrago sobrevive a `desmontar-canteiro.sh --volumes` e a um
`git revert`?* Não sobrevive → `review_required`. **Na dúvida, é aí.**

### O que é gate (o efeito escapa)

1. **Efeito sobre terceiro, irreversível.** Hoje este projeto **não tem
   nenhum**: não envia e-mail, não chama serviço externo, e o que a secretaria
   comunica (resultado de ciclo de isolada, deferimento de matrícula) é
   comunicado por ela, fora do sistema. `close_isolated_cycle`,
   `enroll_isolated_request` e `create_enrollment_adjustment`
   (`apps/academic/services.py`) escrevem no banco do próprio canteiro, e só.
   No dia em que entrar envio de e-mail, notificação ou integração com sistema
   da UFMG, **a chamada que sai** vira gate — e só ela; DTO, template, fila e
   tela continuam `review_required`.
2. **Segredos e o que roda fora daqui** — `.env*` (exceto o `.env` que o
   `montar-canteiro.sh` gera para o canteiro), `backend/config/settings/prod.py`,
   `nginx/` de produção, `.github/workflows/` (executa no push) e qualquer
   credencial, chave ou `SECRET_KEY`. **`docker-compose.yml` não entra**: só
   molda a stack do próprio canteiro. Trocar a *major* do
   `image: postgres:...` também não é gate — o volume que ela invalida é o do
   canteiro; em produção o caminho continua sendo `pg_dump` antes.
3. **Enfraquecer a maquinaria de verificação** — remover ou afrouxar asserção em
   `backend/apps/*/tests/`, tirar passo de `make ready` (`lint`, `typecheck`,
   `test`), afrouxar `ruff`/`mypy`/`svelte-check` no `pyproject.toml` ou no
   `package.json`, mexer em `.claude/skills/`, `.claude/settings.json` ou em
   `scripts/helton/`. Tarefa cujo caminho mais curto é apagar asserção é sempre
   gate. **Estender** a verificação — teste novo, alvo novo no `Makefile`, check
   a mais — não é gate: é o resultado desejado. O `deny` do
   `.claude/settings.json` resolve boa parte disto mecanicamente.

### O que NÃO é gate, e sim `review_required`

- **Migrations** — `backend/apps/*/migrations/` aplica-se ao banco do próprio
  canteiro, e o arquivo é revertível. Merece olho no merge, não parada.
- **Decisão sobre a vida acadêmica** — as funções de `apps/academic/services.py`
  citadas acima, e os anexos em `backend/media/` (`FileField` de
  `RequestDocument`): tudo dentro do canteiro.
- **Regra de classificação e contagem de vaga** — pontuação, ordenação,
  desempate e arredondamento de candidatos de isolada
  (`apps/academic/services.py`, `schemas.py`, models de edital/ciclo). Teste
  verde não prova critério certo: é o humano que confere, no merge.
- **Permissões, tenant e autenticação** — `apps/core/permissions.py`
  (`require_perm`), `apps/core/tenancy.py` (`current_program`),
  `apps/accounts/` e qualquer query que mude escopo de `Program`. Vazamento entre
  programas não aparece em lint, e com um só programa semeado nem em teste — é
  por isso que o `seed_demo` semeia dois.
- **Contrato de API publicado** — `backend/api.py`, os `router.py`/`schemas.py`
  de cada app, e os gerados `frontend/src/lib/api/openapi.json` e `schema.d.ts`.
- **`docker-compose.yml`, `backend/Dockerfile`, `nginx/nginx.conf` de dev** e
  `docs/adr/` — decisão já registrada muda com ADR, mas o arquivo é revertível.

### O preço de destravar migration

Dois canteiros criando migration no mesmo app em paralelo produzem dois
*leaf nodes*, e o `migrate` seguinte para com "Conflicting migrations detected"
— na base, depois do merge, quando o portão de testes de cada canteiro já
passou verde. Quem resolve é o `/compatibilizar`, pelo `creates_migration` do
manifesto (plano-zero de schema, e os demais `serialized_after`). **Sem
manifesto, não monte dois canteiros que mexam em schema.** Vale também a regra
de sempre: migração gerada é lida antes do commit, e entra retrocompatível
(`null=True` ou default).

O outro preço é retrabalho: o loop constrói em cima do schema que ele mesmo
escreveu. Mitigação barata: manter a story de migration cedo no cronograma e
olhar só ela depois da primeira iteração vigiada.

Fora dessas listas, o padrão é `human_gate: false`.

---

## Além dos gates

Vale registrar no mesmo `CLAUDE.md`, porque o loop relê a cada iteração e não tem
memória entre elas:

- **Os comandos de verificação** — o alvo único que roda lint, tipos e testes.
  O loop chama o que estiver escrito aqui.
- **As armadilhas que quebram em silêncio.** É o que mais economiza iteração:
  build que não reflete mudança sem rebuild, arquivo gerado que não é versionado,
  regra de `.gitignore` herdada de template que engole peça do projeto. Cada uma
  dessas custa uma iteração inteira quando o agente descobre sozinho — e às vezes
  ele não descobre, e conclui que o código está errado.
- **O glossário do domínio**, se a conversa é num idioma e o código em outro.

As que já custaram iteração aqui:

- **Dependência nova só entra no container com rebuild.** `uv add <pacote>`
  atualiza `pyproject.toml` e o lockfile, mas a imagem continua a antiga: o
  `pytest` do host passa e o container quebra com `ModuleNotFoundError` em
  runtime. `docker compose up -d --build backend` (e `docker compose restart
  nginx` junto, porque o `upstream django` resolve `backend:8000` uma vez e o
  container novo ganha IP novo).
- **E-mail em canteiro não sai para a internet** — vai para o serviço `mailpit`
  do Compose (SMTP em 1025, API HTTP em `http://mailpit:8025`), e em `pytest` o
  backend é `locmem` (`django.core.mail.outbox`). Nenhum dos dois falha visível
  quando algo está errado: sem
  `django_capture_on_commit_callbacks(execute=True)` o `on_commit` não roda e a
  caixa fica vazia **em silêncio**. Como ler a caixa do canteiro está na Seção 5
  do `manual_dev.md` — a imagem do backend não tem `curl`.
- **Link que vai em e-mail se monta com `settings.SITE_URL`, nunca com
  `request.build_absolute_uri()`.** O e-mail é aberto no navegador do
  destinatário, fora de qualquer request: o `build_absolute_uri` traria o host
  interno do container (`backend:8000`) ou o de quem disparou, e o link chegaria
  quebrado. `SITE_URL` já vem sem barra final (`rstrip("/")` no settings) —
  monte como `f"{settings.SITE_URL}/selecao/assinatura/{token}"`.
- **Duas fixtures que fazem `force_login` na fixture `client` do pytest-django
  disputam a MESMA sessão**, e a última a ser resolvida vence — em silêncio. O
  teste de "papel X não pode" então roda como o papel Y e passa por 200 onde
  devia dar 403 (ou o contrário). Fixture que só precisa do dado grava pelo ORM;
  quando dois papéis precisam mesmo agir no mesmo teste, cada um recebe um
  `Client()` próprio.
- **Upload só funciona em `POST`: o Django não parseia `multipart/form-data` em
  `PUT` nem em `PATCH`.** `HttpRequest._load_post_and_files` devolve `POST` e
  `FILES` vazios quando o método não é POST, então uma rota Ninja com
  `Form(...)`/`File(...)` sob `@router.patch` recebe corpo vazio — 422 por campo
  faltando, ou pior, os defaults aplicados como se o cliente tivesse mandado.
  Não há erro que aponte a causa. Rota que recebe arquivo é `POST`, sempre; a
  retificação dos demais campos fica no `PATCH` em JSON, ao lado
  (`POST .../entries/{id}/proof` × `PATCH .../entries/{id}/`).
- **`filter(<relação>__<campo>__isnull=True)` casa também quem não tem
  relação nenhuma.** O Django promove o join a LEFT OUTER, e a coluna vem
  nula porque a *linha* não existe — não porque o campo esteja vazio. Numa
  fila de "itens ainda não avaliados" isso traz justamente quem não tem item
  algum, que é o caso oposto, e o teste só pega se houver um registro sem
  filhos no cenário. Quando a pergunta é "existe filho com campo nulo", use
  `Exists(Filho.objects.filter(pai=OuterRef("pk"), campo__isnull=True))` — de
  quebra a subconsulta não multiplica linha e dispensa o `distinct()`.
- **`prefetch_related` só vale se o método filho usar `.all()`.** Qualquer
  `.filter()`, `.select_related()` ou `.order_by()` sobre o gerente reverso
  monta um QuerySet novo e vai ao banco de novo — o cache do prefetch fica
  intacto e inútil, sem erro nenhum e sem diferença de resultado. Só a conta
  de consultas muda, e ela não aparece em teste que não a mede: uma lista de
  44 candidatos passa de 1 consulta para 176. Método de model que soma filhos
  lê `self.<related>.all()` e filtra **em Python**; quem carrega usa
  `Prefetch("<related>", queryset=Filho.objects.select_related(...))`, e o
  método cai no `.select_related()` só quando não há cache
  (`"<related>" in self._prefetched_objects_cache`).
- **Procurar texto dentro de um PDF do ReportLab exige desfazer três camadas.**
  O fluxo de página vem comprimido (Flate) e às vezes em ASCII85, e — a parte
  que engana — dentro do operador de texto **o acento é escape octal**
  (`\351` para "é", `\347` para "ç"): a asserção `"décima" in texto` falha com a
  palavra impressa no papel. Pior, `Paragraph` **quebra a linha em `Tj`
  separados**, então frase longa nunca casa como substring contínua. O helper
  que funciona junta só os trechos `(...) Tj` com espaço e converte os escapes
  octais de volta (`texto_do_pdf` em `apps/scholarships/tests/test_bolsas_pdf.py`).
- **Valor em real no papel precisa de `force_grouping=True`.**
  `USE_THOUSAND_SEPARATOR` é falso por padrão no Django, e
  `formats.number_format(v, decimal_pos=2, use_l10n=True)` publica `3200,00` em
  vez de `3.200,00` — sem erro nenhum, só um documento oficial mal escrito.
- **Rota nova no front quebra o `make typecheck` do host com `EACCES` em
  `.svelte-kit/`.** O serviço `frontend` do Compose roda como root sobre o
  mesmo bind mount, e o Vite dele regenera `.svelte-kit/generated/` e
  `.svelte-kit/types/` assim que o arquivo de rota aparece — os artefatos da
  rota nova nascem `root:root`, e o `svelte-kit sync` do host não consegue
  reescrevê-los. A mensagem aponta um `$types.d.ts` ou um `nodes/NN.js` e não
  diz nada sobre Docker. Conserto: apagar os artefatos de dentro do container,
  que é quem tem o dono
  (`docker compose exec -T frontend sh -c 'rm -rf "/app/.svelte-kit/types/src/routes/<rota>"'`),
  e rodar o `make typecheck` de novo. `find frontend/.svelte-kit -user root`
  lista o que ficou.
- **Desestruturar a resposta do `openapi-fetch` no `const` estreita o objeto
  inteiro para `never` dentro do `if (error)`.** `const { data, error,
  response } = await api.GET(...)`, e dentro do ramo de falha o
  `response.status` deixa de existir — a mensagem é
  `Property 'status' does not exist on type 'never'`, e não diz nada sobre
  união discriminada. Quem precisa do código HTTP (o 404 de "ainda não se
  inscreveu", que **não** é erro de tela) guarda a resposta inteira numa
  const e lê `resposta.response.status` **antes** do `if`. Mesmo motivo pelo
  qual `const falha = resposta.error` sai antes do `if` nas telas já
  escritas.
