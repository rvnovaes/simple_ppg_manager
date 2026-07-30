# Comandos do projeto. Comando novo entra aqui, não só no README
# (Seção 7 do CLAUDE.md).
#
# Regra de ouro do dia a dia: `make up` + `make web`, e abra
# http://localhost:8080. Abrir :5173 direto quebra login e CSRF.

.DEFAULT_GOAL := ajuda

BACKEND := backend
FRONTEND := frontend
UV := cd $(BACKEND) && uv run
NPM := cd $(FRONTEND) && npm

.PHONY: ajuda install install-web db up down run web migrations migrate \
        superuser gen-api test lint typecheck ready

ajuda:  ## Lista os comandos disponíveis
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Instala as dependências do backend
	@echo "==> uv sync (backend)"
	cd $(BACKEND) && uv sync

install-web:  ## Instala as dependências do frontend
	@echo "==> npm install (frontend)"
	$(NPM) install

db:  ## Sobe apenas o Postgres
	@echo "==> subindo o banco (porta 5433 no host)"
	docker compose up -d db

up:  ## Sobe db + backend + nginx; abra http://localhost:8080
	@echo "==> subindo db, backend e nginx"
	docker compose up -d --build
	@echo "==> pronto: http://localhost:8080 (rode 'make web' em outro terminal)"

down:  ## Derruba os containers do projeto
	docker compose down

run:  ## Roda o Django nativo com reload (precisa de 'make db')
	@echo "==> runserver em :8000"
	$(UV) python manage.py runserver

web:  ## Roda o Vite com reload; acesse pelo Nginx em :8080
	@echo "==> vite em :5173 — NÃO abra essa porta direto, use :8080"
	$(NPM) run dev

migrations:  ## Gera migrações (leia o arquivo gerado antes de commitar)
	$(UV) python manage.py makemigrations

migrate:  ## Aplica as migrações
	$(UV) python manage.py migrate

superuser:  ## Cria um superusuário
	$(UV) python manage.py createsuperuser

gen-api:  ## Regenera os tipos TS a partir do OpenAPI do backend
	@echo "==> exportando o OpenAPI"
	$(UV) python manage.py export_openapi_schema --api api.api --indent 2 \
		--output ../$(FRONTEND)/src/lib/api/openapi.json
	@echo "==> gerando schema.d.ts"
	$(NPM) run gen:api

test:  ## Roda os testes do backend (Postgres precisa estar de pé)
	$(UV) pytest

lint:  ## Formata e linta backend e frontend
	$(UV) ruff format .
	$(UV) ruff check --fix .
	$(NPM) run format
	$(NPM) run lint

typecheck:  ## Checa tipos no backend (mypy) e no frontend (svelte-check)
	$(UV) mypy .
	$(NPM) run check

ready: lint typecheck test  ## Pré-condição de qualquer commit
	@echo "==> make ready verde: pode commitar"
