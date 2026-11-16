#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "=== Ruach Scribe Installer ==="

echo "[1/5] Installing Debian/Ubuntu system dependencies (requires sudo)..."
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3.12-venv \
    python3-gi \
    gir1.2-atspi-2.0 \
    python3-evdev \
    portaudio19-dev \
    libportaudio2 \
    xdotool \
    xclip \
    wl-clipboard \
    acl \
    libnotify-bin \
    libxcb-cursor0 \
    libegl1

echo "[2/5] Granting Linux input & virtual keyboard permissions for Wayland/X11..."
sudo usermod -aG input "$USER" || true
sudo setfacl -m "u:$USER:rw" /dev/input/event* /dev/uinput 2>/dev/null || true
sudo bash -c 'cat > /etc/udev/rules.d/99-ruach-scribe.rules <<EOF
KERNEL=="event*", SUBSYSTEM=="input", MODE="0660", GROUP="input", TAG+="uaccess"
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", TAG+="uaccess"
EOF' || true

echo "[3/5] Creating Python virtual environment (.venv)..."
rm -rf "$APP_DIR/.venv"
python3 -m venv "$APP_DIR/.venv"

SITE_PKG=$("$APP_DIR/.venv/bin/python" -c "import site; print(site.getsitepackages()[0])")
ln -sf /usr/lib/python3/dist-packages/evdev "$SITE_PKG/evdev" 2>/dev/null || true
ln -sf /usr/lib/python3/dist-packages/gi "$SITE_PKG/gi" 2>/dev/null || true

echo "[4/5] Installing Python packages from requirements.txt..."
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

echo "[5/5] Creating Linux desktop launcher & installing app icon..."
ICON_PATH="$APP_DIR/assets/ruach-scribe.png"
mkdir -p "$HOME/.local/share/icons/hicolor/512x512/apps"
mkdir -p "$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$HOME/.local/share/icons/hicolor/64x64/apps"
cp -f "$APP_DIR/assets/ruach-scribe.png" "$HOME/.local/share/icons/hicolor/512x512/apps/ruach-scribe.png" 2>/dev/null || true
cp -f "$APP_DIR/assets/ruach-scribe-256.png" "$HOME/.local/share/icons/hicolor/256x256/apps/ruach-scribe.png" 2>/dev/null || true
cp -f "$APP_DIR/assets/ruach-scribe-64.png" "$HOME/.local/share/icons/hicolor/64x64/apps/ruach-scribe.png" 2>/dev/null || true

mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/ruach-scribe.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ruach Scribe
Comment=Ethereal Voice Dictation & AI Transcription
Exec="$APP_DIR/run.sh" --foreground
Icon=$ICON_PATH
Path=$APP_DIR
Terminal=false
Categories=Utility;AudioVideo;Accessibility;
StartupNotify=false
EOF

chmod +x "$HOME/.local/share/applications/ruach-scribe.desktop"

mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/ruach-scribe.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ruach Scribe
Comment=Ethereal Voice Dictation & AI Transcription
Exec="$APP_DIR/run.sh" --foreground
Icon=$ICON_PATH
Path=$APP_DIR
Terminal=false
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
StartupNotify=false
EOF
chmod +x "$HOME/.config/autostart/ruach-scribe.desktop"

echo ""
echo "Installation complete!"
echo "You can now launch Ruach Scribe by running:"
echo "  ./run.sh"
