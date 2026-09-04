# Manual do dev — como esta máquina está montada

Síntese do que foi construído até **03/09/2026**, para retomar o trabalho em
outro computador sem reconstruir o raciocínio. Começou em 11/08 e foi
revisado a cada empreitada da esteira.

Este arquivo é um mapa, não uma fonte de verdade. Quando divergir de
[`CLAUDE.md`](CLAUDE.md), do [`README.md`](README.md) ou de
[`docs/adr/`](docs/adr/), **eles vencem** — este aqui só diz onde as coisas
estão e por que estão assim.

---

## 1. As duas peças, e por que são separadas

| Onde | O que é |
| --- | --- |
| `dso.direito.ufmg.br/ati/ppgd-manager` (GitLab da faculdade, `origin`) | **este projeto** — Django + SvelteKit + Postgres + Nginx. O `github.com/rvnovaes/simple_ppg_manager` ficou como `old-origin`, só histórico |
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
git clone https://dso.direito.ufmg.br/ati/ppgd-manager.git
cd ppgd-manager
cp .env.example .env          # ajuste se precisar
cd frontend && npm ci && cd ..
cd backend  && uv sync --locked && cd ..
make up                       # sobe os CINCO serviços
```

Abra **http://localhost:8080**. Só isso — o antigo segundo terminal com
`make web` não existe mais.

| Serviço | O que é | Porta no host |
| --- | --- | --- |
| `db` | Postgres 17.5 | `DB_PORT`, 5433 |
| `backend` | Django, `runserver` | nenhuma (só pelo nginx) |
| `frontend` | Vite dev server (`node:25-slim`) | nenhuma (rede interna) |
| `mailpit` | captura todo e-mail do canteiro (ver seção 5) | nenhuma (`docker compose port mailpit 8025` para abrir a UI) |
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
./scripts/helton/obra/arquivar-plano.sh <nome>     move plano, spec e prd para .../implemented/
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
  variáveis são obrigatórias no script — nada escuta nelas no host, e o
  rótulo avisa. O Mailpit existe, mas só na rede interna da stack (8025 do
  container); a `PORT_MAIL` do relatório continua sem publicação.
- `instalar_dependencias()` roda `npm ci` e `uv sync --locked` — nunca `npm
  install`/`uv sync`, que reescrevem o lockfile e fazem o canteiro nascer com a
  árvore suja (o primeiro commit do loop usa `git add -A` e varreria o ruído).

### Human gates e `review_required`

O `CLAUDE.md` separa **dois** campos do `prd.json`, e a diferença é o que
decide se a esteira anda:

- **`human_gate: true`** — o loop **não executa**. Só para efeito que **escapa
  do canteiro**: (1) efeito irreversível sobre terceiro — hoje o projeto não
  tem nenhum, e-mail vai para o Mailpit; (2) segredos e o que roda fora daqui
  (`.env*` reais, `prod.py`, nginx de produção, `.github/workflows/`);
  (3) enfraquecer a maquinaria de verificação (apagar asserção, afrouxar
  `ruff`/`mypy`/`svelte-check`, mexer em `.claude/` ou em `scripts/helton/`).
- **`review_required: true`** — o loop **executa**, e a story aparece no índice
  do `desmontar-canteiro.sh` para o humano conferir antes do merge. É aqui que
  ficam migrations, decisão sobre a vida acadêmica, regra de classificação e
  vaga, permissões/tenant/autenticação, contrato de API publicado e os
  arquivos de infra de dev.

O teste é: *o estrago sobrevive a `desmontar-canteiro.sh --volumes` e a um
`git revert`?* Não sobrevive → `review_required`. **Na dúvida, é aí** — a
regra antiga de "na dúvida, gate" foi aposentada porque travava a
empreitada cedo e levava as stories dependentes junto.

---

## 5. O processo seletivo, ponta a ponta

O app `backend/apps/selection/` é o módulo de edital: da criação do processo
até o candidato aprovado virar `Student`. Vale a pena conhecer o caminho
inteiro antes de mexer em qualquer pedaço dele — cada etapa trava a seguinte,
e a trava costuma ser a resposta para "por que este botão está desabilitado?".

### Quem faz o quê

Os papéis são Groups do Django, criados/estendidos em
`apps/selection/migrations/0006_papeis_da_selecao.py`:

| Papel | O que pode |
| --- | --- |
| **Secretaria** | opera o edital: processo, etapas, vagas, bancas; homologa ou indefere inscrição; **único** que baixa anexo do candidato; dispara convocação |
| **Docente** | compõe banca: lança nota, monta/congela ata e assina. Lê edital, banca e inscrição — **não** baixa documento |
| **Comissão de Seleção** | lê tudo e é o único que **realoca vaga** entre alvos (decisão colegiada, não expediente da secretaria) |
| **Coordenação** | só acompanha (leitura) |

Ninguém recebe `delete_*`, `is_staff` ou `is_superuser`. Ata assinada não se
apaga: retifica-se com versão nova (`ExaminationRecord.supersedes`).

### O caminho

1. **Edital** — secretaria em `/selecao/editais`: cria o `SelectionProcess`
   (Regular ou Suplementar), as `SelectionStage` em ordem, a grade de `Vacancy`
   e o template de convocação; anexa o PDF do edital. **Publicar é
   `publish_process`**, nunca `status = "published"` na mão — é o service que
   cobra etapa, vaga e template. Depois de publicado, etapa e vaga não mudam
   mais (escrita só em `draft`).
2. **Bancas** — ainda a secretaria, em `/selecao/bancas`: uma `Board` por chave
   avaliada (nível × alvo × etapa). Examinador de fora da casa é um `Teacher`
   com `category = EXTERNAL` e `home_institution` obrigatória — ele existe só
   para compor banca, **não é categoria CAPES**, e normalmente nem tem conta:
   é por isso que assina por token.
3. **Inscrição pública** — o candidato, **sem login**, em `/selecao/inscricao`:
   escolhe edital aberto, preenche e sobe os anexos que
   `required_document_kinds()` exige. Recebe um **protocolo**, que é a chave
   para consultar em `/selecao/protocolo`. As rotas são `/public/*`, com
   `auth=None`, rate limit e `csrf_protect` explícitos; o tenant sai do edital
   encontrado, nunca de `program_id` do chamador.
4. **Homologação** — secretaria em `/selecao/inscricoes`: lista filtrável,
   detalhe com os documentos, homologa ou indefere (com nota). Só inscrição
   homologada entra em banca.
5. **Notas** — o docente em `/selecao/minhas-bancas`: `GET /boards/mine` lista
   as bancas dele; a tela do id lança as notas da etapa em lote. Enquanto a ata
   está `frozen` ou `signed`, o lançamento recusa com `record_frozen`.
6. **Ata** — presidente da banca: `generate_record` monta o conteúdo a partir
   das notas, `refresh_record` reconstrói enquanto está em rascunho,
   `freeze_record` congela (calcula o hash, emite os tokens e **manda e-mail ao
   examinador externo**). `reopen_record` desfaz o congelamento enquanto
   ninguém assinou.
7. **Assinaturas** — quem tem conta assina logado, pela própria tela da banca
   (`sign_record`); o externo assina pelo link do e-mail, em
   `/selecao/assinatura/<token>` (`sign_record_with_token`). A secretaria
   acompanha em `/selecao/atas`, reenvia token e baixa o PDF. **Quando a última
   assinatura entra**, `_close_stage` roda: promove quem passou, elimina quem
   ficou abaixo da nota de corte, aprova na etapa final e gera o PDF.
8. **Convocação** — secretaria em `/selecao/convocacoes`: os convocáveis de cada
   edital × etapa, envio em lote, status por destinatário e reenvio das falhas.
   O lote e as linhas `pending` são gravados **dentro** da transação; o envio
   acontece **fora** dela, um destinatário por vez — falha de SMTP vira
   `ConvocationEmail` com status `failed`, nunca 500 nem rollback do que já saiu.
9. **Resultado** — `/selecao/resultado`: `compute_ranking` (POST) classifica e
   grava; exige a ata da etapa final assinada. A Comissão pode `reallocate_vacancy`
   (o que invalida a classificação e obriga recalcular), e a secretaria converte
   o aprovado em aluno com `convert_to_student` (`POST /applications/{id}/enroll`),
   que cria ou reaproveita a `Person` e o `Student`. Daí em diante ele aparece em
   `/alunos`.

### Exercitar isso no canteiro

`make seed` já deixa o caminho quase todo andado nos **dois** programas: dois
editais publicados, quatro bancas (uma com externo), dez inscrições cobrindo
todos os status, uma ata assinada com PDF, um lote de convocação enviado e uma
matrícula feita. As contas e a senha saem em `CONTAS-DEMO.txt`, na raiz do
repositório (gitignored — some com o banco do canteiro).

O **PPGA** é o tenant limpo: é lá que a carga aparece como nasce. O PPGD do seu
canteiro pode ter dado antigo de stories anteriores, porque `_edital` é
`get_or_create` por (programa, tipo, ano) e **adota** o edital que já existia.

### O Mailpit

Todo e-mail deste projeto — token de assinatura e convocação — sai por
`django.core.mail`, síncrono, sem fila (ADR-009). No canteiro o destino é o
serviço `mailpit` do Compose: ele recebe SMTP em 1025, guarda em memória
(`MP_MAX_MESSAGES=500`, sem volume — o histórico some no `down`) e **nada sai
para a internet**. É isso que torna seguro exercitar convocação e link de
assinatura aqui dentro.

Para ler as mensagens sem UI publicada — **a imagem do backend não tem `curl`**:

```bash
docker compose exec -T backend python -c "
import json, urllib.request
d = json.load(urllib.request.urlopen('http://mailpit:8025/api/v1/messages'))
print(d['total'])
for m in d['messages'][:5]:
    print(m['From']['Address'], '->', [t['Address'] for t in m['To']], '|', m['Subject'])
"
```

O corpo de uma mensagem (é dele que se colhe o link de assinatura) sai em
`/api/v1/message/<ID>`. Para abrir a UI no navegador, `docker compose port
mailpit 8025` — publicar `MAILPIT_UI_PORT` por canteiro é story gate à parte.

Fora do canteiro, quem manda são as variáveis de ambiente: `EMAIL_BACKEND`
(default **console**, para que ambiente sem configuração nenhuma não tente
falar com servidor de e-mail), `EMAIL_HOST/PORT/USE_TLS/HOST_USER/HOST_PASSWORD`,
`DEFAULT_FROM_EMAIL` e **`SITE_URL`**. Em teste, o `pytest-django` troca o
backend por `locmem` sozinho: teste de e-mail se escreve com
`django.core.mail.outbox`, sem mock — e precisa de
`django_capture_on_commit_callbacks(execute=True)`, senão o `on_commit` não roda
e a caixa fica vazia em silêncio.

---

## 6. O edital de bolsas

O app `backend/apps/scholarships/` (24 stories em 01/09, ADR-010) é a
distribuição anual de bolsas por barema. É irmão do processo seletivo, mas
**não** reaproveita a comissão dele: a **Comissão de Bolsas** é Group próprio
(`migrations/0008_papeis_da_bolsa.py`), com composição por edição em
`CommitteeMember`. Juntar as duas daria a quem julga recurso de bolsa o poder
de realocar vaga do processo seletivo.

### Quem faz o quê

| Papel | O que pode |
| --- | --- |
| **Secretaria** | monta a `ScholarshipEdition`, o barema (`BaremeItem`) e a comissão; publica (`publish_scholarshipedition`); nos inscritos alheios escreve só dois campos, com permissão própria cada um: `set_fump_level` e `override_band`. Não pontua e não julga |
| **Discente** | inscreve-se (`ScholarshipApplication`), lança os itens do barema (`BaremeEntry`) com comprovante, interpõe recurso (`ScholarshipAppeal`) |
| **Comissão de Bolsas** | avalia lançamento a lançamento (`review_baremeentry`, separada de `change_` para não confundir a nota do candidato com a da comissão), baixa comprovante, julga recurso |
| **Coordenação** | leitura de todo o app |

### O caminho

A edição anda **só para frente** — `ScholarshipEditionStatus`: `draft` →
`submissions_open` → `under_review` → `preliminary_result` →
`appeals_under_review` → `final_result`. Correção de rumo é quebra-vidro no
Admin, não transição. Cada passo é um `POST /scholarships/editions/{id}/...`
(`open-submissions`, `start-review`, `publish-preliminary`, `open-appeals`,
`publish-final`) que chama o método do model de mesmo nome.

1. **Edição e barema** — secretaria em `/bolsas/edital`: cria a edição do ano,
   monta o barema item a item ou **clona** o do ano anterior
   (`clone_bareme`), e compõe a comissão. Publicar congela o ano.
2. **Inscrição** — o discente em `/bolsas/inscricao`: a inscrição copia o nível
   do aluno (`ScholarshipLevel`, mestrado/doutorado) e o congela; ele lança
   cada item do barema com o comprovante. Upload é `POST .../entries/{id}/proof`
   (o `PATCH` fica para os demais campos — ver armadilha no `CLAUDE.md`).
3. **Análise** — a comissão em `/bolsas/analise`: fila de inscrições, revisão
   item a item (`ItemReview`) com observação. A secretaria lança o nível FUMP
   e, se preciso, força a faixa (`override_band`).
4. **Classificação** — nota final e **faixa de prioridade** (`PriorityBand`:
   2.1-I, 2.1-II, 2.4-I … 2.4-IX, residual), ordenação e desempate dentro da
   faixa. É regra de negócio no model (`ScholarshipEdition.result(level)`) e
   é `review_required`: teste verde não prova critério certo.
5. **Resultado preliminar e recurso** — `publish_preliminary` grava um
   **snapshot** das faixas (é ele que a tela e o PDF mostram, não o cálculo ao
   vivo); o discente interpõe recurso em `/bolsas/recurso`; a comissão julga
   (`judge`: deferido, parcialmente deferido, indeferido).
6. **Resultado final** — `publish_final` grava o snapshot definitivo. Tela em
   `/bolsas/resultado`; PDF em `GET .../editions/{id}/result.pdf`, montado em
   `apps/scholarships/pdf.py` no mesmo desenho da ata (ADR-010, ReportLab).
   Valor em real no papel usa `force_grouping=True` — sem isso sai `3200,00`.

`make seed` cria, em **cada** programa, duas edições de bolsa — a do ano
anterior e a do ano, com o barema clonado da primeira — e candidatos em vários
estágios (`_bolsas` e `_edicao_de_bolsa` no `seed_demo.py`).

---

## 7. Cadastro geral e autocadastro

Entregue em 03/09 (plano `cadastro-geral`). Antes, toda conta nascia pela
secretaria. Agora quem tem vínculo com o programa pode **se cadastrar sozinho**
e esperar a secretaria confirmar. Mora no app `academic` (model
`AccessRequest`, migrations `0013` e `0014`), com rotas em `/api/v1/access/`.

### O caminho

1. **O programa opta** — `Program.accepts_self_signup` (default `False`). A
   rota pública `GET /programs/public` (`auth=None`) lista só os que aceitam;
   é dela que a tela de cadastro monta o `<select>` de programa.
2. **Cadastro** — em `/cadastro`, sem login: nome, e-mail, senha, programa e
   **perfil declarado** (docente, discente ou candidato). Docente informa
   categoria CAPES, titulação, Lattes e, se externo, instituição de origem
   (constraints no banco cobram isso). `POST /access/signup` chama
   `signup_access_request`.
   - **Candidato** sai pronto para entrar: Group "Candidato", sem
     `AccessRequest`. É o mesmo perfil da inscrição em isolada.
   - **Docente e discente** nascem com uma `AccessRequest` `pending` e o Group
     marcador **"Cadastro pendente"**, que tem lista de permissões **vazia** de
     propósito — quem faz de porteiro é o deferimento.
   - A resposta é a **mesma para e-mail novo e já cadastrado** (anti-enumeração),
     e por isso a senha é validada *antes* da consulta ao banco: mensagem de
     senha fraca só para e-mail inédito denunciaria quem já tem conta.
3. **Espera** — `GET /access/me` diz ao front se a sessão está pendente; o
   `+layout.svelte` do grupo `(app)` desvia para `/aguardando-confirmacao`, que
   mostra o status e, se recusado, o motivo.
4. **Fila da secretaria** — `/solicitacoes` (menu Pessoas): `GET
   /access/requests/`, com aprovação e recusa por linha.
   - **Aprovar** (`approve_access_request`) cria o vínculo na mesma transação:
     `create_teacher` com a data de credenciamento que a secretaria informa, ou
     `create_student` com nível, projeto, orientador e data de admissão — o
     aluno nasce **regular e ativo**; isolada e eletiva entram por edital, não
     por esta fila. A ficha nasce antes do papel: nunca há conta "Docente" sem
     `Teacher`.
   - **Recusar** (`reject_access_request`) grava o motivo e **arquiva a
     `Person`**. É o arquivamento que tranca, não o Group: `current_program()`
     só enxerga pessoa ativa. **O recusado não se recadastra** — a
     `unique_email_por_programa` barra e o signup responde o mesmo corpo
     silencioso. Reverter é a secretaria reativar a pessoa.

`make seed` liga `accepts_self_signup` nos dois programas.

O commit `23870a0` (também 03/09) reorganizou os menus da barra lateral e
passou a associar professores ao projeto coletivo — se você lembra de outro
agrupamento de itens, é isso.

---

## 8. Armadilhas já pagas

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

## 9. Pendências

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

- **A marca é PPGM, mas o README e o `CLAUDE.md` ainda abrem com "PPGD
  Manager".** O sistema foi renomeado nas telas em 03/09 (commit `2e63fb4`);
  os dois documentos não acompanharam.

- **Publicar `MAILPIT_UI_PORT` por canteiro** continua story à parte. Hoje a
  UI só abre por `docker compose port mailpit 8025`.
