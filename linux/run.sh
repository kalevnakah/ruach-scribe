#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    echo "Virtual environment (.venv) not found. Running ./install.sh first..."
    "$APP_DIR/install.sh"
fi

# Migrate any local config.json or history.json to ~/.config/ruach-scribe/ outside the Git repo
USER_CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ruach-scribe"
mkdir -p "$USER_CFG_DIR"
chmod 700 "$USER_CFG_DIR"

for f in config.json history.json; do
    if [ -f "$APP_DIR/.private_local/$f" ]; then
        if [ ! -f "$USER_CFG_DIR/$f" ]; then
            mv "$APP_DIR/.private_local/$f" "$USER_CFG_DIR/$f"
            chmod 600 "$USER_CFG_DIR/$f"
        else
            rm -f "$APP_DIR/.private_local/$f"
        fi
    fi
    if [ -f "$APP_DIR/$f" ]; then
        if [ ! -f "$USER_CFG_DIR/$f" ]; then
            mv "$APP_DIR/$f" "$USER_CFG_DIR/$f"
            chmod 600 "$USER_CFG_DIR/$f"
        else
            rm -f "$APP_DIR/$f"
        fi
    fi
done
rmdir "$APP_DIR/.private_local" 2>/dev/null || true

# Install app icon and update App Drawer launcher (~/.local/share/applications/ruach-scribe.desktop)
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
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# Ensure login autostart entry is installed unless explicitly disabled in config.json
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
if [ ! -f "$USER_CFG_DIR/config.json" ] || ! grep -q '"autostart": *false' "$USER_CFG_DIR/config.json" 2>/dev/null; then
    mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_DIR/ruach-scribe.desktop" <<EOF
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
    chmod +x "$AUTOSTART_DIR/ruach-scribe.desktop"
fi

# Stop any previously running Ruach Scribe instance so hotkeys don't conflict
pkill -f "$APP_DIR/main.py" 2>/dev/null || true

# Auto-detect DISPLAY if launched by desktop autostart before DISPLAY was exported
if [ -z "$DISPLAY" ]; then
    for sock in /tmp/.X11-unix/X*; do
        if [ -e "$sock" ]; then
            export DISPLAY=":${sock##*/X}"
            break
        fi
    done
fi

# Use XWayland (xcb) when DISPLAY is present so Monitor 1 & Monitor 2 placement is respected
if [ "$XDG_SESSION_TYPE" = "wayland" ] && [ -n "$DISPLAY" ]; then
    export QT_QPA_PLATFORM=xcb
fi

if [ "$1" = "--foreground" ]; then
    exec "$APP_DIR/.venv/bin/python" "$APP_DIR/main.py"
else
    nohup "$APP_DIR/.venv/bin/python" "$APP_DIR/main.py" >/dev/null 2>&1 &
    BG_PID=$!
    disown "$BG_PID" 2>/dev/null || true
    echo "Ruach Scribe is now running in the background (PID: $BG_PID)."
    echo "App Drawer icon & Login autostart updated!"
fi
