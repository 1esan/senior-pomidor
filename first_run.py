"""Create a local environment/profile and open the setup-only UI."""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

BASE = Path(__file__).resolve().parent
VENV = BASE / ".venv"
PROFILE = BASE / "giga_profile.json"
TEMPLATE = BASE / "profile-template.example.json"
COVER_SETTINGS = BASE / "cover_letter_settings.json"
COVER_TEMPLATE = BASE / "cover-letter-settings.example.json"
PANEL_PORT = 8768
PORT_IN_USE_MESSAGE = (
    f"Порт панели {PANEL_PORT} уже занят. Новая панель не запущена; "
    "проверь существующее приложение вручную."
)


def panel_port_available(port: int = PANEL_PORT) -> bool:
    """Probe availability by binding locally; never connect to the occupant."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                return False
            raise
    return True


def initialize_json_file(destination: Path, template: Path) -> bool:
    """Create a private local JSON copy; never overwrite existing data."""
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(template.read_text(encoding="utf-8"))
    descriptor = None
    created = False
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        return False
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return True


def initialize_profile(profile: Path = PROFILE, template: Path = TEMPLATE) -> bool:
    return initialize_json_file(profile, template)


def blocks_setup_action(method: str, path: str, setup_only: bool = True) -> bool:
    """Keep first-run requests read-only except for resume and profile editing."""
    return (setup_only and method.upper() not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/")
            and path not in ("/api/profile", "/api/resume/extract"))


def prepare_environment() -> Path:
    if sys.version_info < (3, 11):
        raise RuntimeError("Нужен Python 3.11 или новее.")
    python = VENV / "bin" / "python"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(BASE / "requirements-lock.txt")], check=True)
    return python


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true", help="использовать уже созданное .venv")
    parser.add_argument("--no-open", action="store_true", help="не открывать UI автоматически")
    args = parser.parse_args(argv)
    try:
        if not panel_port_available():
            print(PORT_IN_USE_MESSAGE, file=sys.stderr)
            return 1
        python = VENV / "bin" / "python" if args.skip_install else prepare_environment()
        if not python.is_file():
            raise RuntimeError("Не найдена .venv. Запусти настройку без --skip-install.")
        if not panel_port_available():
            print(PORT_IN_USE_MESSAGE, file=sys.stderr)
            return 1
        created = initialize_profile()
        initialize_json_file(COVER_SETTINGS, COVER_TEMPLATE)
    except (OSError, ValueError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Первичная настройка не завершена: {error}", file=sys.stderr)
        return 1

    print("Создан пустой локальный профиль." if created else "Профиль уже существует; его содержимое сохранено.")
    env = {**os.environ, "BOT_SETUP_ONLY": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    if args.no_open:
        env["BOT_SETUP_NO_OPEN"] = "1"
    if not panel_port_available():
        print(PORT_IN_USE_MESSAGE, file=sys.stderr)
        return 1
    command = [str(python), str(BASE / "setup_console.py")]
    return subprocess.call(command, cwd=BASE, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
