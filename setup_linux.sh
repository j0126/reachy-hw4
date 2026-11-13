#!/usr/bin/env bash
# Reachy HW4 Motion Lab - first-time setup on Linux (needs internet once). Run it in a terminal: ./setup_linux.sh
# Creates .venv in this folder with the exact versions of constraints.txt (reachy-mini 1.11.0, no upgrades) and,
# if you agree, an app-menu entry "Reachy HW4 Motion Lab" that starts run_gui.sh (the double-click launcher).
# Needs Ubuntu 22.04+ / Debian 12+ or similar: the PySide6 6.12.0 wheels need glibc >= 2.34 (2.39 on aarch64), and
# PyPI has only a source package of PyGObject (needed by reachy-mini 1.11.0 on Linux), so it is compiled here and
# needs a C compiler with the cairo / gobject-introspection headers (PyPI, checked 2026-11-14).
# Not tested on Linux yet (the tool was built and tested on Windows 11).
cd "$(dirname "$(readlink -f "$0")")" || exit 1
HERE=$(pwd)

finish() {
  if [ -t 0 ]; then echo; read -r -p "Press Enter to close..." _; fi
  exit "$1"
}
fail() { echo; echo "[setup] FAILED - $1"; finish 1; }

APT_LINE="sudo apt install -y build-essential pkg-config libffi-dev libcairo2-dev libgirepository1.0-dev libxcb-cursor0 fonts-nanum pulseaudio-utils"

need=2.34
if [ "$(uname -m)" = "aarch64" ]; then need=2.39; fi
glibc=$(ldd --version 2>/dev/null | head -n1 | grep -oE '[0-9]+\.[0-9]+$')
if [ -n "$glibc" ] && ! printf '%s\n%s\n' "$need" "$glibc" | sort -V -C; then
  fail "glibc $glibc is too old: the PySide6 6.12.0 wheels need glibc >= $need (Ubuntu 22.04 or later)."
fi

missing=0
command -v cc >/dev/null 2>&1 || missing=1
command -v pkg-config >/dev/null 2>&1 || missing=1
if [ "$missing" -eq 0 ]; then
  pkg-config --exists cairo gobject-introspection-1.0 libffi || missing=1
fi
if [ "$missing" -eq 1 ]; then
  echo "[setup] System packages are missing (C compiler, pkg-config, cairo / gobject-introspection / libffi headers)."
  echo "        On Ubuntu / Debian install them with:"
  echo "    $APT_LINE"
  echo "        (Fedora: sudo dnf install gcc pkgconf-pkg-config libffi-devel cairo-devel gobject-introspection-devel xcb-util-cursor google-noto-sans-cjk-fonts)"
  echo "        Then run ./setup_linux.sh again."
  finish 1
fi
if ! fc-list 2>/dev/null | grep -qiE "nanum|noto sans cjk|noto sans kr"; then
  echo "[setup] Note: no Korean font found - Korean GUI text would show as boxes. Install fonts-nanum (see the apt line in this file)."
fi

for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
  if [ -x "$d/uv" ]; then PATH="$d:$PATH"; fi
done
if ! command -v uv >/dev/null 2>&1; then
  echo "[setup] uv is not installed. Install it with:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "Then open a NEW terminal and run ./setup_linux.sh again."
  finish 1
fi

[ -x .venv/bin/python ] || uv venv --python 3.12 .venv || fail "could not create .venv - read the messages above."
uv pip install --python .venv/bin/python -c constraints.txt -e ".[sim,analysis,gui]" av \
  || fail "the install failed - read the messages above (a PyGObject / pycairo build error means the apt packages are missing)."
.venv/bin/python -m reachy_motion env || fail "the environment check failed - read the messages above."
chmod +x run_gui.sh setup_linux.sh 2>/dev/null

if [ -t 0 ]; then
  read -r -p "Add 'Reachy HW4 Motion Lab' to the app menu (a launcher you can click)? [Y/n] " ans
  case "$ans" in
    [Nn]*) ;;
    *)
      apps="$HOME/.local/share/applications"
      mkdir -p "$apps"
      cat > "$apps/reachy-hw4-motion-lab.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Reachy HW4 Motion Lab
Comment=DGIST HRI HW4 expressive-motion lab (Reachy Mini)
Exec="$HERE/run_gui.sh"
Path=$HERE
Terminal=true
Categories=Education;Science;
EOF
      chmod +x "$apps/reachy-hw4-motion-lab.desktop"
      echo "[setup] Added $apps/reachy-hw4-motion-lab.desktop - search 'Reachy' in the app menu."
      ;;
  esac
fi
echo
echo '[setup] Done. The environment check above must say "pins OK". Start the GUI with ./run_gui.sh or from the app menu.'
finish 0
