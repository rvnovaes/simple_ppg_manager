# Manual do dev — como esta máquina está montada

Síntese do que foi construído em **11/08/2026**, para retomar o trabalho em
outro computador sem reconstruir o raciocínio.

Este arquivo é um mapa, não uma fonte de verdade. Quando divergir de
[`CLAUDE.md`](CLAUDE.md), do [`README.md`](README.md) ou de
[`docs/adr/`](docs/adr/), **eles vencem** — este aqui só diz onde as coisas
estão e por que estão assim.

---

## 1. As duas peças, e por que são separadas

| Onde | O que é |
| --- | --- |
| `github.com/rvnovaes/simple_ppg_manager` | **este projeto** — Django + SvelteKit + Postgres + Nginx |
| `github.com/rvnovaes/helton` (clonado em `/opt/helton`) | **a esteira** — o kit que instala o loop autônomo em qualquer projeto |

A esteira é genérica de propósito. O que ela sabe deste projeto está todo em
`scripts/helton/obra/obra.conf` e em `.env.worktree`, os dois versionados aqui. Para
instalar em outro repositório, é o kit que se roda:

```bash
/opt/helton/scripts/instalar-esteira.sh /caminho/do/projeto
```

Ele copia as peças, funde o `deny` de permissões e **para com uma lista de
pendências** naquilo que depende do domínio — não inventa configuração.
Reinstalar é seguro: `obra.conf`, `.env.worktree` e `.env.example` são
preservados.

Antes chamava-se `ralph` (de [snarktank/ralph](https://github.com/snarktank/ralph),
de onde o loop veio). Foi renomeado para `helton` em todo lugar; só as citações
ao repositório de origem continuam dizendo `ralph`, porque são links para um
projeto externo real.

---

## 2. Subir para trabalhar

```bash
git clone https://github.com/rvnovaes/simple_ppg_manager.git
cd simple_ppg_manager
cp .env.example .env          # ajuste se precisar
cd frontend && npm ci && cd ..
cd backend  && uv sync --locked && cd ..
make up                       # sobe os QUATRO serviços
```

Abra **http://localhost:8080**. Só isso — o antigo segundo terminal com
`make web` não existe mais.

| Serviço | O que é | Porta no host |
| --- | --- | --- |
| `db` | Postgres 17.5 | `DB_PORT`, 5433 |
| `backend` | Django, `runserver` | nenhuma (só pelo nginx) |
| `frontend` | Vite dev server (`node:25-slim`) | nenhuma (rede interna) |
| `nginx` | origem única | `NGINX_PORT`, 8080 |

**Nunca abra a porta do Vite direto.** Login e CSRF quebram — é o ADR-004. Hoje
isso ficou difícil de fazer por acidente: a 5173 é interna à rede do Compose e
não é publicada.

### Comandos do dia

| Comando | O que faz |
| --- | --- |
| `make up` / `make down` | sobe / derruba a stack (o `down` preserva o volume do banco) |
| `make web` | acompanha o log do Vite |
| `make migrate` / `make migrations` | migrações (rodam no host, via `uv`) |
| `make seed` | carga de demonstração, idempotente |
| `make gen-api` | regenera os tipos TS a partir do OpenAPI — **rode sempre que mexer em schema ou rota** |
| `make ready` | `lint` + `typecheck` + `test`. **Verde é pré-condição de commit.** |

---

## 3. O que mudou no Vite, e por quê

Isto é o que mais provavelmente vai te confundir se você lembrar do arranjo
antigo.

**Antes:** o Vite rodava no host (`make web`), e o nginx o alcançava por
`host.docker.internal:5173`.

**O problema:** com worktrees paralelas, os N nginx apontavam todos para o
**mesmo** Vite do host — que serve o código de uma worktree só. Cada canteiro
exibia o front de outro, sem erro nenhum na tela.

**Agora:** `frontend` é serviço do Compose e o upstream é `frontend:5173`, porta
**interna** da rede da stack. Cada canteiro tem a sua rede, então nada colide e
nada precisou ser parametrizado — o `nginx.conf` continua estático.

Dois detalhes que custam tempo se esquecidos:

- **A imagem é `node:25-slim`, não `node:alpine`.** O `node_modules` montado é o
  mesmo do host (é ele que `make lint` e `make typecheck` usam), e o `npm ci` de
  lá baixa binários `linux-x64-gnu` do rollup e do `@tailwindcss/oxide`. Em musl
  eles não carregam, e o erro aparece como `cannot find module` de um pacote que
  está visivelmente lá.
- **`hmr.clientPort` sai de `NGINX_PORT`.** O WebSocket de hot reload é aberto
  pelo navegador, então precisa da porta *publicada* — a 5173 não existe fora do
  Compose. Estava cravado em `8080`, o que fazia qualquer stack em outra porta
  perder o reload **em silêncio**: a página carrega, só não atualiza. É por isso
  que o `vite.config.ts` lê `process.env`, e é por isso que `@types/node` está
  nas devDependencies (só tipo; não vai para o bundle).

---

## 4. A esteira: o ciclo completo

O loop autônomo trabalha numa **worktree** — um checkout paralelo, com stack
Docker própria e faixa de portas própria. O termo usado nos scripts é
*canteiro*.

```
/grill-me                          extrai a spec        → scripts/helton/projects/specs/<tema>.md
sessão NOVA em plan mode           o plano              → scripts/helton/projects/plans/<nome>.md
                                   (commitar e pushar)
/compatibilizar                    só com mais de um plano
./scripts/helton/obra/montar-canteiro.sh <nome>
                                   cria a worktree, sobe a stack, migra e semeia
  ── dentro da worktree ──
  /cronograma                      converte o plano     → scripts/helton/projects/prds/prd.json
  ./scripts/helton/helton.sh --tool claude 1     ensaio vigiado, UMA iteração
  ./scripts/helton/helton.sh --tool claude 30    AFK
  ── de volta ──
./scripts/helton/obra/desmontar-canteiro.sh <nome>     preserva a branch helton/<nome>
git merge --no-ff helton/<nome>
./scripts/helton/obra/arquivar-plano.sh <nome>
```

O passo a passo com as armadilhas está em [`scripts/helton/projects/README.md`](scripts/helton/projects/README.md).

### Os arquivos que importam

| Arquivo | Papel | Editar? |
| --- | --- | --- |
| `scripts/helton/obra/obra.conf` | **tudo que a esteira sabe deste projeto** | sim, é o único |
| `scripts/helton/helton.sh` | o loop | não |
| `scripts/helton/CLAUDE.md` | **o prompt do loop** (Claude Code), não documentação | não |
| `scripts/helton/prompt.md` | o mesmo prompt para o Amp — gêmeo do anterior | não |
| `scripts/helton/projects/prds/prd.json` | o cronograma corrente, escrito pelo `/cronograma` | não à mão |
| `.env.worktree` | o overlay de ambiente por canteiro | sim |
| `.claude/skills/` | `cronograma`, `compatibilizar`, `mobilizar-obras`, `grill-me` | não |

`CLAUDE.md` e `prompt.md` são gêmeos e **têm de mudar juntos** — toda a máquina
de segurança (o filtro de gates) mora neles. Não os substitua pelos do upstream:
um loop com aquele prompt executa exatamente as stories que alguém barrou.

### O `obra.conf` deste projeto, em resumo

- `SERVICES=(backend frontend nginx)` — `db` sobe antes, sozinho.
- `MIGRATE_SERVICE=""` — **não há serviço de migração**. `docker compose run
  --rm backend` executaria o `runserver`, que nunca sai, e travaria o
  provisionamento. As migrations vão no `SEED_CMD`, antes do `seed_demo`; os
  dois são idempotentes.
- Portas: `DB` 5433 e `WEB` 8080. `APP` e `MAIL` existem só porque as quatro
  variáveis são obrigatórias no script — nada escuta nelas, e o rótulo avisa.
- `instalar_dependencias()` roda `npm ci` e `uv sync --locked` — nunca `npm
  install`/`uv sync`, que reescrevem o lockfile e fazem o canteiro nascer com a
  árvore suja (o primeiro commit do loop usa `git add -A` e varreria o ruído).

### Human gates

As sete categorias que o loop **não** decide sozinho estão no `CLAUDE.md`, com
os caminhos concretos deste repositório. A regra é reversibilidade: *se der
errado e só for notado uma semana depois, dá para voltar usando apenas o git?*
Não → gate. Na dúvida, gate.

Aqui elas são: decisão sobre a vida acadêmica de alguém (fechar ciclo, deferir
matrícula, anexos em `media/`), migrations, regra de classificação e vaga,
permissões/tenant/autenticação, contrato de API publicado, infra e segredos, e
enfraquecer a maquinaria de verificação.

---

## 5. Armadilhas já pagas

Cada uma destas custou tempo. Estão aqui para não custarem de novo.

**A porta do Vite não deve ser aberta.** `:8080`, sempre.

**O front não atualiza ao salvar.** O `hmr.clientPort` e a `NGINX_PORT` estão
divergindo. Nada na tela acusa isso.

**`cannot find module` de algo que está no `node_modules`.** Imagem musl com
`node_modules` compilado para glibc. A imagem é `-slim` de propósito.

**`.env.*` no `.gitignore` engole o `.env.worktree`.** Existe um `!.env.worktree`
logo abaixo. Sem ele, todo canteiro nasce sem overlay — e o git não acusa nada.

**`CSRF_TRUSTED_ORIGINS` precisa estar no `.env.worktree`.** O default do compose
acompanharia a `NGINX_PORT`, mas nunca entra em ação: o `.env` gerado herda do
`.env.example` a linha com a 8080 cravada, e valor explícito vence default. Sem
isso, todo canteiro rejeita o próprio login com 403 — sem mencionar porta
nenhuma na mensagem.

**`DATABASE_URL` também.** No checkout principal o offset é 0 e a 5433 está
certa; numa worktree ela apontaria para o banco do **checkout principal**. O
teste então valida schema alheio, ou escreve no banco de outro agente.

**Regra de `.gitignore` com barra no meio é ancorada na raiz.** Foi o que
aposentou as regras `ralph/...` quando o diretório saiu.

**`git check-ignore -v` não responde "está ignorado".** Com `-v` o status 0
significa "algum padrão casou" — inclusive uma negação. Quem decide é o `-q`.

**No `deny` do `.claude/settings.json`, só `Edit(caminho)` vale.** As checagens
de permissão de arquivo não consultam `Write(...)`; e `Edit` já cobre todas as
ferramentas que escrevem. Para ver os avisos de configuração, que não aparecem
em sessão interativa:

```bash
claude -p 'responda apenas: ok' --max-turns 1
```

Qualquer linha antes do `ok` é problema.

---

## 6. Pendências

- **O ensaio (`--ensaio`) nunca rodou.** É ele que prova a instalação de ponta a
  ponta — monta um canteiro, migra, semeia e desmonta:

  ```bash
  /opt/helton/scripts/instalar-esteira.sh /opt/simple_ppg_manager \
      --ensaio --verify 'make ready'
  ```

- **O workspace precisa ser confiado uma vez** em cada máquina, senão as
  permissões `allow` do `.claude/settings.json` são descartadas com aviso. Basta
  abrir o `claude` interativamente na raiz do projeto e aceitar o diálogo.

- **`docs/adr/` não tem ADR para o Vite no Compose.** A mudança está registrada
  no corpo do commit `d22e1f4` e na seção 7 do README; se virar decisão de
  arquitetura estável, merece ADR próprio.
