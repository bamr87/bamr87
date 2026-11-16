#!/usr/bin/env python3
"""Django's command line for the console's backend (ADR 0006).

Run it with the console's interpreter, from anywhere:

    .venv-console/bin/python tools/console/backend/manage.py migrate
    .venv-console/bin/python tools/console/backend/manage.py createsuperuser
    .venv-console/bin/python tools/console/backend/manage.py showmigrations

run.sh applies `migrate --noinput` before every start. The settings read the
same environment the console does (backend/settings.py).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    # tools/console, so `backend` is importable as a package; not this
    # directory, so its modules never shadow a top-level name.
    here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != here]
    sys.path.insert(0, str(here.parent))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
