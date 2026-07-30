"""Ambiente de desenvolvimento.

Acesso sempre por http://localhost:8080 (Nginx). Abrir o Vite direto em
:5173 quebra login e CSRF — ver ADR-004.
"""

from .base import *  # noqa: F403
from .base import env_list

DEBUG = True

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS", "localhost,127.0.0.1,backend,host.docker.internal"
)

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080"
)
