"""Unified profile UI compatibility launcher."""
import runpy,urllib.request,webbrowser
from common import BASE
if __name__=='__main__':
    try:
        with urllib.request.urlopen('http://127.0.0.1:8768/',timeout=2) as r:pass
    except Exception:runpy.run_path(str(BASE/'setup_console.py'),run_name='__main__')
    else:webbrowser.open('http://127.0.0.1:8768/')
