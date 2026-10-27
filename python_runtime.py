"""Launch the personal environment natively on Apple Silicon, including under Rosetta."""
from functools import lru_cache
from pathlib import Path
import platform,subprocess
BASE=Path(__file__).resolve().parent

@lru_cache(maxsize=1)
def apple_silicon():
    if platform.system() != 'Darwin': return False
    if platform.machine() == 'arm64': return True
    try:
        return subprocess.check_output(['/usr/sbin/sysctl','-n','hw.optional.arm64'],text=True,stderr=subprocess.DEVNULL,timeout=3).strip() == '1'
    except (OSError,subprocess.SubprocessError): return False

def python_command(*args):
    command=[str(BASE/'.venv/bin/python'),*map(str,args)]
    return ['/usr/bin/arch','-arm64',*command] if apple_silicon() else command
