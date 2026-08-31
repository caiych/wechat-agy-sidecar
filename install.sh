#!/usr/bin/env bash
# ==============================================================================
# WeChat Antigravity Sidecar Installer
# Sets up virtualenv, installs package, registers sidecar, and links CLI to PATH.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.local/bin:$PATH"

echo "========================================================"
echo "  WeChat Antigravity Sidecar Installer"
echo "========================================================"

# 1. Check Python & Installer tools
VENV_DIR="$SCRIPT_DIR/.venv"

if command -v uv >/dev/null 2>&1; then
    INSTALLER="uv"
    echo "⚡ Using installer: uv ($(uv --version))"
elif [ -f "$VENV_DIR/bin/pip" ]; then
    INSTALLER="venv_pip"
    echo "📦 Using installer: venv pip"
elif command -v pip3 >/dev/null 2>&1; then
    INSTALLER="pip3"
    echo "📦 Using installer: pip3"
else
    INSTALLER="python_pip"
    echo "📦 Using installer: python3 -m pip"
fi

# 2. Setup Virtual Environment if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment at .venv..."
    if [ "$INSTALLER" = "uv" ]; then
        uv venv "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

# 3. Install Package & Dependencies
echo "📥 Installing dependencies and package in editable mode..."
if [ "$INSTALLER" = "uv" ]; then
    VIRTUAL_ENV="$VENV_DIR" uv pip install -e .
elif [ "$INSTALLER" = "venv_pip" ]; then
    "$VENV_DIR/bin/pip" install -e .
elif [ "$INSTALLER" = "pip3" ]; then
    pip3 install -e .
else
    python3 -m pip install -e .
fi

# 4. Link CLI to ~/.local/bin for PATH availability (crucial for media downloading & AGY tools)
USER_BIN_DIR="$HOME/.local/bin"
mkdir -p "$USER_BIN_DIR"
TARGET_CLI="$VENV_DIR/bin/wechat-agy-sidecar"
LINK_PATH="$USER_BIN_DIR/wechat-agy-sidecar"

if [ -f "$TARGET_CLI" ]; then
    ln -sf "$TARGET_CLI" "$LINK_PATH"
    chmod +x "$LINK_PATH"
    echo "🔗 Symlinked CLI to: $LINK_PATH"
else
    echo "⚠️ Warning: $TARGET_CLI not found after installation." >&2
fi

# 5. Register Antigravity Global Sidecar Manifest
SIDECAR_CONFIG_DIR="$HOME/.gemini/config/sidecars/wechat-agy-sidecar"
mkdir -p "$SIDECAR_CONFIG_DIR"
cat > "$SIDECAR_CONFIG_DIR/sidecar.json" <<EOF
{
  "\$schema": "https://antigravity.google/schemas/sidecar.json",
  "name": "wechat-agy-sidecar",
  "description": "WeChat Antigravity Bridge Sidecar Daemon for iLink Bot Protocol",
  "command": "$TARGET_CLI",
  "args": [],
  "cwd": "$SCRIPT_DIR",
  "restart_policy": "always",
  "env": {
    "PATH": "$USER_BIN_DIR:/usr/local/bin:/usr/bin:/bin",
    "HOME": "$HOME",
    "ANTIGRAVITY_AGENTAPI_EXE": "$USER_BIN_DIR/agy",
    "WECHAT_SIDECAR_CONFIG": "$HOME/.gemini/wechat_sidecar_config.json",
    "WECHAT_SIDECAR_PROJECT_ID": ""
  },
  "enabled": true
}
EOF
echo "⚙️  Registered Antigravity Sidecar at: $SIDECAR_CONFIG_DIR/sidecar.json"

# 6. Enable Sidecar in Antigravity Global User Config (~/.gemini/config/config.json)
python3 -c "
import json
from pathlib import Path
cfg_path = Path.home() / '.gemini' / 'config' / 'config.json'
if cfg_path.exists():
    try:
        data = json.loads(cfg_path.read_text(encoding='utf-8'))
    except Exception:
        data = {}
else:
    data = {}
sidecars = data.setdefault('sidecars', {})
sidecars['wechat-agy-sidecar'] = {'enabled': True}
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
"
echo "⚙️  Enabled sidecar in: ~/.gemini/config/config.json"


echo ""
echo "========================================================"
echo "✅ Installation complete!"
echo "========================================================"
echo ""
echo "Quick Commands:"
echo "  1. Onboarding Login:  wechat-agy-sidecar --login"
echo "  2. Start Sidecar:     wechat-agy-sidecar"
echo "  3. Download Media:    wechat-agy-sidecar download-media <media_id>"
echo ""
echo "Make sure '$USER_BIN_DIR' is in your PATH."
echo ""
