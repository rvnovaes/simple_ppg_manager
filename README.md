# PPGD Manager

Sistema de gestão para programa de pós-graduação. Multi-tenant desde a
primeira migração: todo dado de negócio carrega a chave do programa.

Backend em Django + Django Ninja, frontend em SvelteKit como SPA estática,
tudo servido por um Nginx em **uma origem só**.

> **As regras do projeto estão no [CLAUDE.md](CLAUDE.md)**, não aqui. Este
> arquivo é o "como rodar"; aquele é o "como fazer". Em caso de conflito,
> o CLAUDE.md vence. As decisões de arquitetura estão em
> [`docs/adr/`](docs/adr/).

---

## A regra que economiza mais tempo

**Acesse sempre `http://localhost:8080`.**

Abrir o Vite direto em `:5173` faz o login e o CSRF quebrarem de um jeito
que o navegador reporta de forma enigmática. Não é bug: front e API
precisam compartilhar a mesma origem, e quem garante isso é o Nginx na
8080. Ver [ADR-004](docs/adr/004-origem-unica-sem-cors.md).

---

## O que você precisa ter instalado

| | Para quê |
|---|---|
| [`uv`](https://docs.astral.sh/uv/) | dependências do backend — **instala o Python sozinho**, você não precisa ter Python |
| Node 20+ e `npm` | dependências e build do frontend |
| Docker + Compose v2 | banco, backend e Nginx |
| `make` | atalho para tudo |

## Subindo pela primeira vez

```bash
cp .env.example .env      # ajuste se precisar; o .env nunca vai pro git
make install              # dependências do backend
make install-web          # dependências do frontend
make up                   # sobe db + backend + nginx
make migrate              # cria as tabelas
make superuser            # crie a SUA conta de sysadmin
```

Em outro terminal:

```bash
make web                  # servidor de desenvolvimento do frontend
```

Pronto:

- **Sistema** → http://localhost:8080
- **Admin** → http://localhost:8080/admin/ (só superusuário — veja abaixo)
- **Documentação da API** → http://localhost:8080/api/v1/docs

## Quem entra onde

O Django Admin é ferramenta de **operação da plataforma**: criar programas
novos, ler auditoria e corrigir dado quando o sistema errou. Só
superusuário entra, e a trava é de código.

Todo usuário do programa — secretaria, coordenação, docentes, discentes —
é atendido **pelo frontend**. Se falta tela para alguma coisa, o trabalho
é escrever a tela, não dar acesso ao Admin. Ver
[ADR-006](docs/adr/006-admin-so-para-sysadmin.md).

## Comandos

O `Makefile` é a fonte da verdade — comando novo entra lá, não só aqui.
`make` sozinho lista tudo.

| Comando | O que faz |
|---|---|
| `make up` / `make down` | sobe / derruba os containers |
| `make web` | frontend com reload (acesse pela 8080) |
| `make run` | backend nativo com reload, sem container |
| `make db` | só o Postgres |
| `make migrations` | gera migrações — **leia o arquivo gerado** antes de commitar |
| `make migrate` | aplica as migrações |
| `make superuser` | cria um superusuário |
| `make gen-api` | regenera os tipos TypeScript a partir do OpenAPI |
| `make test` | testes do backend |
| `make lint` / `make typecheck` | formatação e tipos, nas duas pontas |
| **`make ready`** | **lint + typecheck + test — verde é pré-condição de qualquer commit** |

## Organização

```
backend/apps/     apps Django: accounts, programs, people, audit, core
frontend/src/     rotas e componentes Svelte
nginx/            configuração da origem única
docs/adr/         decisões de arquitetura
```

Cada app do Django tem `models.py`, `admin.py`, `router.py`, `schemas.py`,
`migrations/` e `tests/`. "App" aqui é o termo do Django — um módulo do
backend, sem relação com as telas do frontend.

O `people` é o exemplo de referência: se você vai escrever um app novo,
copie a estrutura dele.

---

## Armadilhas conhecidas

Todas estas já custaram tempo a alguém. Comece por aqui quando algo não
funcionar.

**A tela não carrega, ou o login falha sem motivo aparente.**
Você abriu `:5173`. Use `:8080`.

**`/admin` devolve a SPA ou uma página estranha.**
Falta a barra final: `/admin/`.

**Mudei o `nginx.conf` e nada aconteceu.**
O arquivo é montado, mas o Nginx só relê a configuração ao recarregar:

```bash
docker compose up -d --force-recreate nginx
```

**O Postgres não sobe, erro de porta já alocada.**
A 5432 desta máquina costuma estar ocupada por outro projeto. O nosso usa
a **5433** no host (`DB_HOST_PORT` no `.env`); dentro do Compose continua
sendo `db:5432`.

**Trocar a versão *major* do Postgres quebra o banco.**
O Postgres não lê um data dir criado por outra major. O caminho é
`pg_dump` → remover o volume → subir a nova imagem → restaurar. Nunca só
trocar a tag.

**`ModuleNotFoundError: No module named 'django'` dentro do container.**
O `python` do container é o do sistema; o ambiente do projeto está em
outro lugar. Use `uv run python ...`.

**`make test` falha sem conseguir conectar no banco.**
O Postgres precisa estar de pé: `make db`.
