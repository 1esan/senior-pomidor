"""Local GPT adapter configuration; never store or display the adapter key."""
import json
import os
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent


class AdapterConfigurationError(RuntimeError):
    pass


def _configuration():
    path = BASE / 'personal_launcher.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise AdapterConfigurationError('Не удалось прочитать настройки адаптера ИИ.') from exc
    if not isinstance(value, dict):
        raise AdapterConfigurationError('Настройки адаптера должны быть JSON-объектом.')
    return value


def adapter_dir():
    raw = os.environ.get('SENIOR_POMIDOR_ADAPTER_DIR') or _configuration().get('adapter_dir')
    if not isinstance(raw, str) or not raw.strip():
        raise AdapterConfigurationError('Укажи папку установленного GPT-адаптера в personal_launcher.json или SENIOR_POMIDOR_ADAPTER_DIR.')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise AdapterConfigurationError('Путь к адаптеру ИИ должен быть абсолютным.')
    return path


def adapter_key():
    try:
        value = (adapter_dir() / '.state' / 'adapter-key').read_text(encoding='utf-8').strip()
    except OSError as exc:
        raise AdapterConfigurationError('Не найден ключ локального адаптера ИИ; проверь подключение.') from exc
    if not value:
        raise AdapterConfigurationError('Ключ локального адаптера ИИ пуст.')
    return value


def node_command():
    configured = _configuration().get('node')
    node = configured if isinstance(configured, str) and configured else shutil.which('node')
    if not node:
        raise AdapterConfigurationError('Не найден Node.js для запуска адаптера ИИ.')
    return node
