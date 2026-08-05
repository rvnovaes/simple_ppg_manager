# Ralph Agent Instructions

You are an autonomous coding agent working on a software project.

## Your Task

1. Read the PRD at `prd.json` (in the same directory as this file)
2. Read the progress log at `progress.txt` (check Codebase Patterns section first)
3. Check you're on the correct branch from PRD `branchName`. If not, check it out; if it
   doesn't exist, create it following the project's git rules (see **Project rules** below).
4. Pick the **highest priority** user story where `passes: false`
5. Implement that single user story
6. Run `make ready` na raiz do projeto (lint + typecheck + test) — Seção 7 do `CLAUDE.md` raiz
7. Update CLAUDE.md files if you discover reusable patterns (see below)
8. If checks pass, commit the story's changes with message: `feat: [Story ID] - [Story Title]`
9. Update the PRD to set `passes: true` for the completed story
10. Append your progress to `progress.txt`

## Project rules

The repository root `CLAUDE.md` (`/opt/simple_ppg_manager/CLAUDE.md`) is the single source of
truth for stack, arquitetura, convenções e comandos de qualidade. Read it and follow it. Do not
restate its rules here — a copy would drift.

Three adjustments, because you run inside an autonomous loop:

- **Base branch é `main`.** Se a branch de `branchName` não existir, crie a partir de `main`.
  Não existe `develop` neste projeto.
- **Você trabalha no checkout principal**, `/opt/simple_ppg_manager` — não há worktree separada.
  Não crie uma.
- **Commit narrowly.** NUNCA `git add -A`: o checkout é compartilhado e a raiz tem arquivos
  soltos que não são seus. Faça `git add` só dos arquivos que você tocou.

## Progress Report Format

APPEND to progress.txt (never replace, always append):
```
## [Date/Time] - [Story ID]
- What was implemented
- Files changed
- **Learnings for future iterations:**
  - Patterns discovered (e.g., "this codebase uses X for Y")
  - Gotchas encountered (e.g., "don't forget to update Z when changing W")
  - Useful context (e.g., "the evaluation panel is in component X")
---
```

The learnings section is critical - it helps future iterations avoid repeating mistakes and understand the codebase better.

## Consolidate Patterns

If you discover a **reusable pattern** that future iterations should know, add it to the `## Codebase Patterns` section at the TOP of progress.txt (create it if it doesn't exist). This section should consolidate the most important learnings:

```
## Codebase Patterns
- Example: Use `sql<number>` template for aggregations
- Example: Always use `IF NOT EXISTS` for migrations
- Example: Export types from actions.ts for UI components
```

Only add patterns that are **general and reusable**, not story-specific details.

## Update CLAUDE.md Files

Before committing, check if any edited files have learnings worth preserving in nearby CLAUDE.md files:

1. **Identify directories with edited files** - Look at which directories you modified
2. **Check for existing CLAUDE.md** - Look for CLAUDE.md in those directories or parent directories
3. **Add valuable learnings** - If you discovered something future developers/agents should know:
   - API patterns or conventions specific to that module
   - Gotchas or non-obvious requirements
   - Dependencies between files
   - Testing approaches for that area
   - Configuration or environment requirements

**Examples of good CLAUDE.md additions:**
- "When modifying X, also update Y to keep them in sync"
- "This module uses pattern Z for all API calls"
- "Tests require the dev server running on PORT 3000"
- "Field names must match the template exactly"

**Do NOT add:**
- Story-specific implementation details
- Temporary debugging notes
- Information already in progress.txt

Only update CLAUDE.md if you have **genuinely reusable knowledge** that would help future work in that directory.

## Quality Requirements

- ALL commits must pass `make ready` (lint + typecheck + test)
- Migração gerada é sempre lida antes do commit — não confie só no autogenerate
- Endpoint de escrita sem `require_perm` e sem `AuditLog` não é entregável (Seção 5 do raiz)
- Do NOT commit broken code
- Keep changes focused and minimal
- Follow existing code patterns

## Browser Testing (If Available)

For any story that changes UI, verify it in the browser em **http://localhost:8080** — nunca em
`:5173` direto, que quebra login e CSRF (ADR-004, origem única). Ferramentas disponíveis:
`mcp__claude-in-chrome__*` ou o plugin `browser-use`. Ambas exigem consentimento manual do
usuário; se ele não vier, siga para o passo abaixo sobre verificação manual.

1. Navigate to the relevant page
2. Verify the UI changes work as expected
3. Take a screenshot if helpful for the progress log

If no browser tools are available, note in your progress report that manual browser verification is needed.

## Stop Condition

After completing a user story, check if ALL stories have `passes: true`.

If ALL stories are complete and passing, reply with:
<promise>COMPLETE</promise>

If there are still stories with `passes: false`, end your response normally (another iteration will pick up the next story).

## Important

- Work on ONE story per iteration
- Commit frequently
- Keep CI green
- Read the Codebase Patterns section in progress.txt before starting

## Ambiente deste projeto

Raiz: `/opt/simple_ppg_manager`. Rode tudo a partir dela (o `Makefile` está lá).

- **Front + API, origem única (nginx): http://localhost:8080** — é onde a UI se verifica.
  O front fala com a API por `/api/v1`, caminho relativo, via proxy do nginx
- Vite (`make web`): :5173 — NÃO abra direto, quebra login e CSRF
- Django nativo (`make run`, sem container): :8000
- Banco: Postgres 17 em `localhost:5433` (`ppg`/`ppg`/`ppg`). Volume nomeado `pgdata`,
  não some sozinho
- Django Admin: http://localhost:8080/admin/ — só superusuário (ADR-006)

Regras:
- `docker compose` puro, sem `-f`. Nome do projeto fixado como `simple_ppg_manager` no
  próprio `docker-compose.yml`
- `docker compose exec <serviço>`, NUNCA `docker exec <nome>`: os containers não têm nome fixo
- Serviços do compose: `db`, `backend`, `nginx`. Não há worker, scheduler nem serviço de e-mail
- Comandos são sempre via `make` (Seção 7 do CLAUDE.md raiz): `make up` sobe db + backend +
  nginx; `make web` roda o Vite; `make migrations` / `make migrate`; `make gen-api` regenera
  `frontend/src/lib/api/schema.d.ts` (backend precisa estar de pé); `make ready`
  (lint + typecheck + test) é pré-condição de qualquer commit
- Mudou schema da API: rode `make gen-api` antes de mexer nas telas Svelte. Sem isso os tipos
  do front ficam velhos e o `svelte-check` do `make ready` acusa
- O front em dev é servido pelo Vite atrás do nginx — não há build a refazer para ver a tela;
  basta o `make web` rodando
