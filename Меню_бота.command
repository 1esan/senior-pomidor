#!/bin/zsh
cd -- "${0:A:h}" || exit 1
exec /usr/bin/arch -arm64 .venv/bin/python bot_cli.py menu
