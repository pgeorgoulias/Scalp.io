#!/usr/bin/env sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 public_gui.py
elif command -v python >/dev/null 2>&1; then
  python public_gui.py
else
  echo "Python 3 is required. Install Python, then run this script again."
  exit 1
fi
