#!/bin/bash
# Reachy HW4 Motion Lab (GUI) on macOS - double-click this file in Finder. Results are written in this folder: results/lab
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "[run] .venv not found - double-click setup_mac.command first."
  read -r -p "Press Enter to close this window..." _
  exit 1
fi
if ! .venv/bin/python -m reachy_motion gui; then
  echo
  echo "[run] The GUI stopped with an error - read the messages above."
  read -r -p "Press Enter to close this window..." _
  exit 1
fi
