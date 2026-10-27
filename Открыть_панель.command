#!/bin/zsh
cd -- "$(dirname "$0")"
exec /usr/bin/arch -arm64 .venv/bin/python personal_launcher.py
