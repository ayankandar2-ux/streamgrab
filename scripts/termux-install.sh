#!/data/data/com.termux/files/usr/bin/bash
# Install streamgrab inside Termux on Android.
#
#   bash termux-install.sh
#
# No root, proot or desktop environment required. Override the defaults with:
#   STREAMGRAB_REPO=... STREAMGRAB_DIR=... bash termux-install.sh
set -euo pipefail

if [ ! -d /data/data/com.termux ]; then
  echo "warning: this script targets Termux on Android; continuing anyway." >&2
fi

echo "==> updating package index"
pkg update -y

echo "==> installing python, ffmpeg and git"
pkg install -y python ffmpeg git

echo "==> installing an AES backend"
# Prefer Termux's prebuilt build; compiling cryptography needs Rust on-device.
if python -c "import cryptography" >/dev/null 2>&1; then
  echo "    cryptography already available"
elif pkg install -y python-cryptography >/dev/null 2>&1; then
  echo "    installed python-cryptography"
else
  echo "    falling back to pure-Python AES (slower, still correct)"
fi

REPO="${STREAMGRAB_REPO:-https://github.com/ayankandar2-ux/streamgrab}"
DEST="${STREAMGRAB_DIR:-$HOME/streamgrab}"

if [ -d "$DEST/.git" ]; then
  echo "==> updating $DEST"
  git -C "$DEST" pull --ff-only
else
  echo "==> cloning into $DEST"
  git clone --depth 1 "$REPO" "$DEST"
fi

echo "==> installing streamgrab"
pip install --upgrade -e "$DEST"

echo "==> enabling shared storage (approve the Android prompt)"
termux-setup-storage || true

cat <<'EOF'

Installed. Examples:

  streamgrab --list "https://cdn.example.com/master.m3u8"
  streamgrab -j 4 -o ~/storage/downloads/ "https://cdn.example.com/master.m3u8"
  streamgrab --audio --mp3 -o ~/storage/downloads/ "https://cdn.example.com/v.m3u8"

For long downloads:

  pkg install termux-api
  termux-wake-lock
  streamgrab -j 4 -o ~/storage/downloads/ "$URL"
  termux-wake-unlock
EOF
