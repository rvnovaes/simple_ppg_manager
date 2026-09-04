# projects/ — o que alimenta a esteira

Os três artefatos do ciclo, lado a lado. Em todos vale a mesma regra: **a raiz é
o que está pendente, `implemented/` é o que já foi entregue.**

```
scripts/helton/projects/
├── specs/          saída do /grill-me — o material bruto
│   └── implemented/
├── plans/          saída do plan mode — o que vira canteiro
│   ├── manifest.json    (saída do /compatibilizar)
│   └── implemented/
└── prds/           saída do /cronograma — o que o loop executa
    ├── prd.json
    ├── progress.txt
    └── implemented/<AAAA-MM-DD>-<fatia>/
```

Sem subpasta de domínio em lugar nenhum: tema costuma cruzar domínios, e a
subpasta só cria a dúvida de onde procurar. Para o que **não** vira plano —
conferências, checklists, transcrições avulsas — use `notes/` na raiz do
repositório.

**O nome do arquivo do plano é a chave primária de tudo.** Ele precisa ser
kebab-case (minúsculas, dígitos e hífen simples), porque vira, sem tradução:

| a partir de `plans/onda-2.md` | vira |
|---|---|
| worktree | `../<projeto>-onda-2` |
| branch | `helton/onda-2` |
| projeto Compose | `<projeto>-onda-2` |

## Como um arquivo chega aqui

O começo são **três sessões distintas**, e a separação é a parte que mais se
perde ao contar a história rápido:

1. **Sessão de descoberta** — `/grill-me` sobre o problema. A saída é a spec,
   gravada em `scripts/helton/projects/specs/<tema>.md` a cada resposta. O grill extrai; ele não redige
   entregável.
2. **Sessão nova em plan mode, apontada para a spec.** Não é continuação da
   anterior: sessão limpa, e o primeiro pedido é literalmente *"leia
   `scripts/helton/projects/specs/<tema>.md` e faça o plano"*. O humano julga o resultado — arquivos
   certos? premissas explícitas? o que está faltando? — e o plano aprovado é
   salvo aqui. **Commit e push**: a guarda do `montar-canteiro.sh` procura o
   plano em `origin/main` (o `BASE_BRANCH` do `obra.conf`), não no seu diretório.
3. `/compatibilizar` cruza os planos entre si e grava `scripts/helton/projects/plans/manifest.json`.
4. `./scripts/helton/obra/montar-canteiro.sh <nome>` provisiona o canteiro —
   ou `--todos`, que monta em série todos os planos que o manifesto liberou
   como `parallel` (e diz o motivo de cada um que pulou).
5. `/cronograma`, **de dentro da worktree**, vira o plano em
   `scripts/helton/projects/prds/prd.json`.

   > Com vários planos liberados, `/mobilizar-obras` faz os passos 4 e 5 de uma
   > vez — monta cada canteiro, gera o cronograma de cada um e entrega o roteiro
   > dos terminais a abrir. O ensaio e o cap continuam sendo seus.
6. `./scripts/helton/helton.sh --tool claude 1` — ensaio vigiado — e só então o
   cap real.
7. `./scripts/helton/obra/desmontar-canteiro.sh <nome>` imprime o índice de revisão e
   desmonta, preservando a branch para o merge.
8. Merge à mão em `main` (`git merge --no-ff helton/<nome>`), e então
   `./scripts/helton/obra/arquivar-plano.sh <nome>`, que move o plano para
   `plans/implemented/`.

### Por que o passo 8 não é opcional

Plano entregue que fica em `scripts/helton/projects/plans/` volta a ser montado. Depois do merge a
branch `helton/<nome>` é apagada e a worktree já foi no desmonte — de modo que
**nenhuma** das três guardas do `montar-canteiro.sh --todos` dispara (canteiro
montado? não; branch existe? não; status no manifesto? ainda `parallel`). O
plano ganha canteiro novo e o loop refaz do zero o que já está na `main`.

O `arquivar-plano.sh` recusa arquivar enquanto a branch existir e não estiver
contida em `origin/main`: arquivar antes do merge marcaria como
entregue um trabalho que ainda pode mudar, ou ser abandonado. Para plano
descartado de propósito, `--force`.

## implemented/

O que já foi entregue, fora do caminho da esteira. Existe em `plans/`, `specs/` e
`prds/`, sempre com o mesmo papel. É pasta versionada, e a enumeração não a
enxerga: o `--todos` lista `scripts/helton/projects/plans/` sem recursão e filtra
por `scripts/helton/projects/plans/<nome>.md`, e o `/compatibilizar` lê
`scripts/helton/projects/plans/*.md` — nada aqui dentro é confundido com trabalho
pendente.

O `arquivar-plano.sh` grava sempre na raiz de `plans/implemented/`, com o mesmo
nome de arquivo que o plano tinha. Em `prds/implemented/` o agrupamento é por
empreitada, em pastas `<AAAA-MM-DD>-<fatia>/` com o `prd.json` e o `progress.txt`
juntos — é o que o `helton.sh` faz sozinho ao detectar troca de branch.

### Por que a sessão do plano tem de ser nova

Plano nascido dentro da sessão do grill herda a conversa inteira — inclusive o
que foi dito e **não** foi parar no arquivo. Ele sai melhor que a spec, e
ninguém percebe: a spec segue incompleta para as etapas seguintes, que só têm o
arquivo, e o buraco aparece lá adiante, quando o `/cronograma` traduz mal
alguma coisa. Lendo de uma sessão fria, a spec é submetida ao mesmo teste que
tudo o mais nesta esteira — **o disco é o contrato, o contexto não é**. É a
regra da worktree, que só enxerga o commitado; a do `montar-canteiro.sh`, que
confere o plano na base; e a do próprio Helton, que zera o contexto a cada
iteração e relê `prd.json` e `progress.txt`. Se a spec não se sustenta sozinha,
é melhor descobrir no plan mode, onde custa uma pergunta.

Contando direito, uma fatia atravessa quatro sessões frias: grill → plano →
`/cronograma` → cada iteração do loop. Nenhuma delas depende da memória da
anterior.

## manifest.json

Gerado pelo `/compatibilizar`, não escrito à mão. Diz, por plano, quais arquivos
ele reivindica, se cria migration, e se pode rodar em paralelo
(`parallel`), se precisa esperar outro (`serialized_after:<plano>`) ou se
precisa ser reescrito (`needs_reslicing`). Guarda também o sha256 de cada plano
— é assim que o `/cronograma` percebe que o texto mudou depois da decisão.

## O que **não** entra aqui

- Specs — inclusive a saída do `/grill-me` → `scripts/helton/projects/specs/`.
- O que não vira plano (conferências, checklists, transcrições avulsas) →
  `notes/`, onde também ficam as capturas de grill anteriores a 09/08/2026.
- PRDs de execução → `scripts/helton/projects/prds/prd.json` (o corrente) e
  `scripts/helton/projects/prds/implemented/` (os encerrados).

---

## A esteira nesta máquina — o que está fora de `projects/`

O que vem abaixo estava em `manual_dev.md` (raiz) até 04/09/2026 e migrou para
cá quando aquele arquivo foi fundido ao `README.md`. É um mapa, não fonte de
verdade: quando divergir do `CLAUDE.md` da raiz ou do `obra.conf`, eles vencem.

### As duas peças, e por que são separadas

| Onde | O que é |
| --- | --- |
| este repositório | o projeto — Django + SvelteKit + Postgres + Nginx |
| `github.com/rvnovaes/helton` (clonado em `/opt/helton`) | **a esteira** — o kit que instala o loop autônomo em qualquer projeto |

A esteira é genérica de propósito. O que ela sabe deste projeto está todo em
`scripts/helton/obra/obra.conf` e em `.env.worktree`, os dois versionados aqui.
Para instalar em outro repositório, é o kit que se roda:

```bash
/opt/helton/scripts/instalar-esteira.sh /caminho/do/projeto
```

Ele copia as peças, funde o `deny` de permissões e **para com uma lista de
pendências** naquilo que depende do domínio — não inventa configuração.
Reinstalar é seguro: `obra.conf`, `.env.worktree` e `.env.example` são
preservados.

Antes chamava-se `ralph` (de [snarktank/ralph](https://github.com/snarktank/ralph),
de onde o loop veio). Foi renomeado para `helton` em todo lugar; só as citações
ao repositório de origem continuam dizendo `ralph`.

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

- `BASE_BRANCH="origin/main"` — o canteiro nasce da `main` e o merge volta
  para ela.
- `SERVICES=(backend frontend nginx)` — `db` sobe antes, sozinho.
- `MIGRATE_SERVICE=""` — **não há serviço de migração**. `docker compose run
  --rm backend` executaria o `runserver`, que nunca sai, e travaria o
  provisionamento. As migrations vão no `SEED_CMD`, antes do `seed_demo`; os
  dois são idempotentes.
- Portas: `DB` 5433 e `WEB` 8080. `APP` e `MAIL` existem só porque as quatro
  variáveis são obrigatórias no script — nada escuta nelas **no host**. O
  Mailpit existe, mas só na rede interna da stack (8025 do container).
- `instalar_dependencias()` roda `npm ci` e `uv sync --locked` — nunca `npm
  install`/`uv sync`, que reescrevem o lockfile e fazem o canteiro nascer com a
  árvore suja (o primeiro commit do loop usa `git add -A` e varreria o ruído).

### Human gates e `review_required`

O `CLAUDE.md` da raiz separa **dois** campos do `prd.json`:

- **`human_gate: true`** — o loop **não executa**. Só para efeito que **escapa
  do canteiro**: efeito irreversível sobre terceiro (hoje não há nenhum — e-mail
  vai para o Mailpit); segredos e o que roda fora daqui (`.env*` reais,
  `prod.py`, nginx de produção, `.gitlab-ci.yml`); enfraquecer a maquinaria de
  verificação (apagar asserção, afrouxar `ruff`/`mypy`/`svelte-check`, mexer em
  `.claude/` ou em `scripts/helton/`).
- **`review_required: true`** — o loop **executa**, e a story aparece no índice
  do `desmontar-canteiro.sh` para o humano conferir antes do merge: migrations,
  decisão sobre a vida acadêmica, regra de classificação e vaga,
  permissões/tenant/autenticação, contrato de API publicado, infra de dev.

O teste é: *o estrago sobrevive a `desmontar-canteiro.sh --volumes` e a um
`git revert`?* Não sobrevive → `review_required`. **Na dúvida, é aí.**

### Armadilhas da esteira, já pagas

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

**O PPGD de um canteiro pode ter dado antigo.** O `seed_demo` adota o que já
existe (`get_or_create` por chave natural); o **PPGA** é o tenant limpo, onde a
carga aparece como nasce.

### Pendências

- **O ensaio (`--ensaio`) nunca rodou.** É ele que prova a instalação de ponta a
  ponta — monta um canteiro, migra, semeia e desmonta:

  ```bash
  /opt/helton/scripts/instalar-esteira.sh /opt/simple_ppg_manager \
      --ensaio --verify 'make ready'
  ```

- **O workspace precisa ser confiado uma vez** em cada máquina, senão as
  permissões `allow` do `.claude/settings.json` são descartadas com aviso. Basta
  abrir o `claude` interativamente na raiz do projeto e aceitar o diálogo.

- **`scripts/helton/CLAUDE.md` e `prompt.md` citam `docs/manual_dev.md`**, que
  não existe mais (o conteúdo está no `README.md` da raiz e aqui). Os dois são
  gate; a correção é do humano.

- **O rótulo `LABEL_MAIL` do `obra.conf`** ainda diz que captura de e-mail não
  existe no projeto. Existe (Mailpit, interno). Também é gate.
