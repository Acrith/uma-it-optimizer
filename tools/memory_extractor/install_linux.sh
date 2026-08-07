#!/usr/bin/env bash
# One-shot Linux bootstrap for uma-it-extract.
#
# The wine-based launcher (linux_launch.py) runs the Windows .exe
# under Proton's wine, which has frida bundled inside via PyInstaller.
# So the ONLY thing Linux users need up-front is the .exe itself —
# no venv, no pip install, no Linux frida at all.
#
# Usage: ./install_linux.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

EXE_NAME="uma-it-extract.exe"
EXE_URL="https://github.com/Acrith/uma-it-optimizer/releases/latest/download/${EXE_NAME}"

if [ -f "$EXE_NAME" ]; then
    echo "[+] $EXE_NAME already present in $SCRIPT_DIR"
    echo "    To upgrade to the latest release, run:"
    echo "      python linux_launch.py --update"
else
    echo "[*] Downloading $EXE_NAME from latest release..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$EXE_NAME" "$EXE_URL"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$EXE_NAME" "$EXE_URL"
    else
        echo "[X] Need either curl or wget to download the release. Install one, or"
        echo "    download manually from:"
        echo "      https://github.com/Acrith/uma-it-optimizer/releases"
        echo "    and place $EXE_NAME in $SCRIPT_DIR"
        exit 1
    fi
    if [ ! -s "$EXE_NAME" ]; then
        echo "[X] Download produced an empty file. Try again, or grab it manually from"
        echo "      https://github.com/Acrith/uma-it-optimizer/releases"
        rm -f "$EXE_NAME"
        exit 1
    fi
    echo "[+] Downloaded $EXE_NAME ($(du -h "$EXE_NAME" | cut -f1))"
fi

echo
echo "[+] Setup complete. Whenever Uma is running in Steam, run:"
echo "      python $SCRIPT_DIR/linux_launch.py"
echo "    Output JSONs land in $SCRIPT_DIR/runs/"
