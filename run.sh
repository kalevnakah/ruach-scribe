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

# Stop any previously running Ruach Scribe instance so hotkeys don't conflict
pkill -f "$APP_DIR/main.py" 2>/dev/null || true

# Use XWayland (xcb) when DISPLAY is present so Monitor 1 & Monitor 2 placement is respected
if [ "$XDG_SESSION_TYPE" = "wayland" ] && [ -n "$DISPLAY" ]; then
    export QT_QPA_PLATFORM=xcb
fi

exec "$APP_DIR/.venv/bin/python" "$APP_DIR/main.py" "$@"
