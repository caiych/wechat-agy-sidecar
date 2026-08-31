# WeChat Antigravity Sidecar (`wechat-agy-sidecar`)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

A lightweight, robust native sidecar daemon that connects **WeChat** directly with **Google Antigravity** using the native `agentapi` CLI and WeChat iLink Bot Protocol.

---

## 🏗️ Architecture

```
+-------------------+        HTTP Long-Polling (/getupdates)        +-----------------------------------+
|                   | <-------------------------------------------- |  WeChat Antigravity Sidecar       |
|  WeChat iLink API |                                               |  (wechat-agy-sidecar)             |
| (ilinkai.weixin)  | --------------------------------------------> |  - Inbound Parser (msgs/images)   |
|                   |        HTTP POST (/sendmessage)               |  - Multi-Turn Thread Manager      |
|                   | <-------------------------------------------- |  - Proactive Background Watcher   |
+-------------------+                                               +-----------------+-----------------+
                                                                                      |
                                                                                      | Native agentapi CLI (IPC)
                                                                                      v
                                                                    +-----------------------------------+
                                                                    |     Google Antigravity Engine     |
                                                                    |        (agentapi / brain)         |
                                                                    +-----------------------------------+
```

---

## ✨ Features

- **Native `agentapi` Bridge**: Direct integration via `agentapi new-conversation` and `agentapi send-message` for fast, headless multi-turn execution.
- **Proactive Background Streaming**: Real-time trajectory watcher automatically relays Antigravity-initiated background events (e.g. scheduled timers via `schedule`, background subagent completions) directly to WeChat without requiring inbound user messages.
- **Multi-Turn Persistent Threading**: Automatically preserves multi-turn conversation context per WeChat user across messages and daemon restarts.
- **Thread Control Commands**:
  - `/new` (or `/reset`): Resets the conversation thread and starts fresh.
  - `/new <prompt>`: Resets thread and immediately executes `<prompt>` in the new conversation.
- **Multimodal CDN Decryption**:
  - **Images**: Automatically downloads and decrypts Tencent CDN encrypted payloads (AES-128-ECB) so Antigravity can directly view and analyze user-submitted images.
  - **Voice (Silk v3)**: Extracts WeChat ASR transcriptions and provides on-demand `download-media` CLI commands for raw audio inspection when needed.
- **Native Antigravity Sidecar**: Configured via standard `sidecar.json` for discovery and lifecycle management by Antigravity runtime.
- **Incremental Cursor Sync**: Persists `get_updates_buf` to ensure zero message loss and no duplicate responses.
- **Typing Indicator**: Automatically sends `sendtyping` events while Antigravity generates code and reasoning steps.

---

## 📦 Installation

### Option 1: Modern Editable Install (Recommended)

```bash
git clone https://github.com/caiych/wechat-agy-sidecar.git
cd wechat-agy-sidecar

# Install dependencies in venv
python3 -m venv .venv
.venv/bin/pip install -e .
```

### Option 2: Using requirements.txt

```bash
pip install -r requirements.txt
```

---

## 🚀 Quickstart

### 1. One-Time Onboarding (QR Login)

Run the daemon in onboarding mode or start it directly:

```bash
# Start the sidecar
wechat-agy-sidecar

# Or force re-login via CLI argument
wechat-agy-sidecar --login
```

* Scan the generated QR code in your terminal using the WeChat mobile app.
* Tap **Confirm** on your phone.
* Credentials are securely saved to `~/.gemini/wechat_sidecar_config.json`.

### 2. Antigravity Native Sidecar (`sidecar.json`)

To enable native Antigravity lifecycle management, copy or symlink `sidecar.json` to `.agents/sidecars/wechat-agy-sidecar/sidecar.json` or `~/.gemini/config/sidecars/wechat-agy-sidecar/sidecar.json`.

```json
{
  "$schema": "https://antigravity.google/schemas/sidecar.json",
  "name": "wechat-agy-sidecar",
  "description": "WeChat Antigravity Bridge Sidecar Daemon for iLink Bot Protocol",
  "command": "/path/to/wechat-agy-sidecar/.venv/bin/wechat-agy-sidecar",
  "args": [],
  "restart_policy": "always",
  "enabled": true
}
```

---

## 💬 WeChat Interactive Commands

| Command | Action | Example |
| :--- | :--- | :--- |
| *(Any text)* | Continues the active multi-turn conversation thread. | `帮我把刚才的函数改成异步版本` |
| `/new` | Resets conversation thread and waits for new input. | `/new` |
| `/new <prompt>` | Resets thread and immediately executes prompt in the new thread. | `/new 用 Go 写一个 HTTP 客户端` |
| `/resume` (or `/history`) | Lists recent conversations with titles to select by replying with a number. | `/resume` |
| `/resume <index\|id>` | Switches directly to the specified conversation number or UUID. | `/resume 2` |
| `/reset` | Alias for `/new`. | `/reset` |
| *(Image)* | Uploads image; automatically decrypted for agent inspection. | `[Image Attachment]` |
| *(Voice)* | Voice input; passed with transcribed text and registered `media_id` for on-demand inspection. | `[Voice Input]` |
| *(y / n / 同意 / 拒绝)* | Approves or rejects remote tool execution / permission requests. | `y` |

---

## 🧪 Development & Testing

```bash
# Run unit tests
.venv/bin/python -m unittest discover -s tests -p "test_*.py"

# Download & inspect media by registry ID
wechat-agy-sidecar download-media voice_1001

# Or direct URL/key mode (backward compatible)
wechat-agy-sidecar download-media --url "<CDN_URL>" --key "<AES_KEY>" --output "/tmp/media.silk"
```

---

## 📌 Status & Roadmap

- ✅ **Sidebar & Conversation Discovery**: Fully resolved with `agentapi` integration — conversations created via `agentapi new-conversation` are first-class Antigravity sessions and immediately accessible.
- ✅ **Proactive Timer & Subagent Push**: Resolved via `proactive_event_watcher` reading real-time conversation trajectories.
- ✅ **Interactive Permission & Question Cards**: Relays permission prompts and questions directly to WeChat for remote `y`/`n` authorization.
- ✅ **Voice Media Registry & CLI**: Clean metadata registry (`~/.gemini/wechat_media/registry.json`) for lazy audio inspection with zero token/arg clutter.
- ✅ **Multi-Session Switcher (`/resume`)**: View recent conversation history and switch active threads seamlessly.
- ✅ **Project ID Routing**: Configure `WECHAT_SIDECAR_PROJECT_ID` or config `project_id` to route conversations to specific workspaces.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
