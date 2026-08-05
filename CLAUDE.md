
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
| Subir tudo (dev, com Nginx) | `make up` — abrir **http://localhost:8080** (abrir `:5173` direto quebra login/CSRF) |
| Backend nativo com reload | `make run` (`uv run python manage.py runserver`) |
| Front nativo com reload | `make web` (`npm run dev`) — só junto do Nginx de dev |
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
  é FK e não OneToOne; período letivo é entidade; **todo model de negócio
  carrega FK `program` direta**, mesmo quando alcançável por navegação —
  sem ela o `AuditLog` perde a chave de tenant.

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