"""Compatibility entry point for the safe first-run setup UI."""
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent

if __name__ == "__main__":
    from first_run import PORT_IN_USE_MESSAGE, panel_port_available

    if not panel_port_available():
        print(PORT_IN_USE_MESSAGE, file=sys.stderr)
        raise SystemExit(1)
    python = BASE / ".venv/bin/python"
    if not python.is_file():
        print("Сначала запусти Первичная_настройка.command.", file=sys.stderr)
        raise SystemExit(1)
    from first_run import initialize_profile

    created = initialize_profile()
    print("Создан пустой профиль." if created else "Существующий профиль сохранён.")
    env = {**os.environ, "BOT_SETUP_ONLY": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    if not panel_port_available():
        print(PORT_IN_USE_MESSAGE, file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(subprocess.call([str(python), str(BASE / "setup_console.py")], cwd=BASE, env=env))
