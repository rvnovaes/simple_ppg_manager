"""Configuração comum a todos os ambientes.

Só entra aqui o que vale em dev e em produção. Diferença de ambiente vai
para dev.py ou prod.py — nunca um `if DEBUG:` espalhado.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# backend/config/settings/base.py -> backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# .env fica na raiz do repositório, um nível acima de backend/.
load_dotenv(BASE_DIR.parent / ".env")


def env_list(name: str, default: str = "") -> list[str]:
    """Lê variável de ambiente separada por vírgula, ignorando espaços."""
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


SECRET_KEY = os.getenv("SECRET_KEY", "dev-inseguro-nao-usar-em-producao")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    # No lugar de "django.contrib.admin": troca o site padrão pelo nosso,
    # que só deixa superusuário entrar (ADR-006).
    "config.admin.PPGDAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Só pelo comando export_openapi_schema, usado por `make gen-api`.
    "ninja",
    # Apps do projeto. accounts vem antes por causa de AUTH_USER_MODEL.
    "apps.accounts",
    "apps.core",
    "apps.programs",
    "apps.people",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
# Sem ASGI: o projeto é síncrono por decisão (ADR-001).

DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL", "postgres://ppg:ppg@localhost:5433/ppg"),
        conn_max_age=600,
    )
}

AUTH_USER_MODEL = "accounts.User"

_VALIDACAO = "django.contrib.auth.password_validation"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"{_VALIDACAO}.UserAttributeSimilarityValidator"},
    {"NAME": f"{_VALIDACAO}.MinimumLengthValidator"},
    {"NAME": f"{_VALIDACAO}.CommonPasswordValidator"},
    {"NAME": f"{_VALIDACAO}.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static_root"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessão e CSRF (ADR-003) -------------------------------------------------
# httpOnly impede que JavaScript leia o cookie de sessão; Lax basta porque
# front e API compartilham a origem (ADR-004).
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# O cookie de CSRF precisa ser legível pelo JS — é assim que o client do
# front monta o header X-CSRFToken. Isso não é falha: o valor só serve
# junto da sessão, que continua httpOnly.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:8080")
