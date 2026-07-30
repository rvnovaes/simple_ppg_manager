# Imagem de desenvolvimento. Produção usa gunicorn (ver Seção 10 do CLAUDE.md
# e docs/adr/005) — a decisão de systemd vs container fica com a infra.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# uv é o gerenciador de dependências do projeto (nunca pip/requirements.txt).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Camada de dependências separada do código: só reinstala quando o lock muda.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project || uv sync --no-install-project

COPY . .

EXPOSE 8000
CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
