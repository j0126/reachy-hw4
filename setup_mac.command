#!/bin/bash
# Reachy HW4 Motion Lab - first-time setup on macOS (needs internet once). Double-click this file in Finder.
# Creates .venv in this folder with the exact versions of constraints.txt (reachy-mini 1.11.0, no upgrades).
# Needs an Apple Silicon Mac (M1 or later) with macOS 14 or later: reachy-mini 1.11.0 pulls in onnxruntime 1.27.0
# and the GUI uses PySide6 6.12.0; both ship macOS wheels only for that (PyPI, checked 2026-11-14).
# Not tested on a Mac yet (the tool was built and tested on Windows 11).
cd "$(dirname "$0")" || exit 1

finish() {  # keep the Terminal window readable after a double-click
  echo
  read -r -p "Press Enter to close this window..." _
  exit "$1"
}
fail() { echo; echo "[setup] FAILED - $1"; finish 1; }

[ "$(uname -m)" = "arm64" ] || fail "this Mac is $(uname -m). onnxruntime 1.27.0 (needed by reachy-mini 1.11.0) has macOS wheels only for Apple Silicon (arm64). Use a Windows PC or an Apple Silicon Mac."
major=$(sw_vers -productVersion | cut -d. -f1)
[ "${major:-0}" -ge 14 ] || fail "macOS $(sw_vers -productVersion) is too old: PySide6 6.12.0 and onnxruntime 1.27.0 need macOS 14 (Sonoma) or later."

for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
  if [ -x "$d/uv" ]; then PATH="$d:$PATH"; fi
done
if ! command -v uv >/dev/null 2>&1; then
  echo "[setup] uv is not installed. Install it with this one line in Terminal:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "Then double-click setup_mac.command again."
  finish 1
fi

[ -x .venv/bin/python ] || uv venv --python 3.12 .venv || fail "could not create .venv - read the messages above."
uv pip install --python .venv/bin/python -c constraints.txt -e ".[sim,analysis,gui]" av \
  || fail "the install failed - read the messages above."
.venv/bin/python -m reachy_motion env || fail "the environment check failed - read the messages above."
chmod +x run_gui.command setup_mac.command 2>/dev/null
echo
echo '[setup] Done. The last line above must say "pins OK". Start the GUI by double-clicking run_gui.command'
finish 0
