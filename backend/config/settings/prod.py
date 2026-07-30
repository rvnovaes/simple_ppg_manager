"""Ambiente de produção.

Tudo que é sensível vem de variável de ambiente (.env nunca commitado).
O TLS termina no Nginx; o Django confia no X-Forwarded-Proto que ele envia.
"""

import os

from .base import *  # noqa: F403

DEBUG = False

if os.getenv("SECRET_KEY") in (None, "", "dev-inseguro-nao-usar-em-producao"):
    raise RuntimeError("SECRET_KEY precisa estar definida no ambiente de produção.")

# TLS termina no Nginx (ADR-004); é ele quem informa o esquema original.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
