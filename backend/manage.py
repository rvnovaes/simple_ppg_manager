#!/usr/bin/env python
"""Utilitário de linha de comando do Django."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Django não encontrado. Rode `make install` (uv sync) antes."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
