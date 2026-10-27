"""Compatible Web entry point; shares the same implementation and profile."""
import runpy
from common import BASE
if __name__=='__main__':runpy.run_path(str(BASE/'giga-bot.py'),run_name='__main__')
