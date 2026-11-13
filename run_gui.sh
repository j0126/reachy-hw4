#!/usr/bin/env bash
# Reachy HW4 Motion Lab (GUI) on Linux: ./run_gui.sh, or the app-menu entry that setup_linux.sh adds.
# Results are written in this folder: results/lab
cd "$(dirname "$(readlink -f "$0")")" || exit 1
pause() { if [ -t 0 ]; then echo; read -r -p "Press Enter to close..." _; fi; }
if [ ! -x .venv/bin/python ]; then
  echo "[run] .venv not found - run ./setup_linux.sh first."
  pause
  exit 1
fi
if ! .venv/bin/python -m reachy_motion gui; then
  echo
  echo "[run] The GUI stopped with an error - read the messages above."
  pause
  exit 1
fi
