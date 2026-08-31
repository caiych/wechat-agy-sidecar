# WeChat Antigravity Sidecar (`wechat-agy-sidecar`)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

A lightweight, robust sidecar daemon that connects **WeChat** directly with **Google Antigravity** (taps into ambient logged-in AGY instance or Python SDK).

It implements the native WeChat **iLink Bot Protocol** (the exact same protocol utilized by OpenClaw's official WeChat channel) without requiring the full OpenClaw agent stack.

---

## 🏗️ Architecture

```
+-------------------+        HTTP Long-Polling (/getupdates)        +-----------------------------------+
|                   | <-------------------------------------------- |  WeChat Antigravity Sidecar       |
|  WeChat iLink API |                                               |  (wechat-agy-sidecar)             |
| (ilinkai.weixin)  | --------------------------------------------> |  - Inbound Parser (msgs/item_list)|
|                   |        HTTP POST (/sendmessage)               |  - Multi-Turn Thread Manager      |
+-------------------+ <-------------------------------------------- +-----------------+-----------------+
                                                                                      |
                                                                                      | Active AGY Instance / SDK
                                                                                      v
                                                                    +-----------------------------------+
                                                                    |     Google Antigravity Engine     |
                                                                    |      (agy CLI / Python SDK)       |
                                                                    +-----------------------------------+
```

---

## ✨ Features

- **Multi-Turn Persistent Threading**: Automatically preserves multi-turn conversation context per WeChat user across messages and daemon restarts.
- **Thread Control Commands**:
  - `/new` (or `/reset`): Resets the conversation thread and starts fresh.
  - `/new <prompt>` (or `/reset <prompt>`): Resets the conversation thread and immediately executes `<prompt>` in the new thread.
- **Native Protocol Fidelity**: Implements the Tencent iLink Bot API (`ilink_bot_token`, `bot_agent`, `X-WECHAT-UIN`, `message_state: 2`).
- **Interactive QR Onboarding**: Displays an in-terminal ASCII QR code on initial launch for seamless zero-config WeChat authorization.
- **Ambient AGY Instance Integration**: Seamlessly taps into the logged-in local AGY instance (OAuth / personal login) with zero required API keys.
- **Incremental Cursor Sync**: Persists `get_updates_buf` to ensure zero message loss and no duplicate responses.
- **Typing Indicator**: Automatically sends `sendtyping` events while Antigravity generates code and reasoning steps.

---

## 📦 Installation

### Option 1: Modern Editable Install (Recommended)

```bash
git clone https://github.com/caiych/wechat-agy-sidecar.git
cd wechat-agy-sidecar

# Install with uv / pip
pip install -e .
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

### 2. Run as a Background Daemon

```bash
# Run with custom config or debug logs
wechat-agy-sidecar --debug

# Background execution via nohup / systemd
nohup wechat-agy-sidecar > ~/.gemini/wechat_sidecar.log 2>&1 &
```

---

## 💬 WeChat Interactive Commands

| Command | Action | Example |
| :--- | :--- | :--- |
| *(Any text)* | Continues the active multi-turn conversation thread. | `帮我把刚才的函数改成异步版本` |
| `/new` | Resets conversation thread and waits for new input. | `/new` |
| `/new <prompt>` | Resets thread and immediately executes prompt in the new thread. | `/new 用 Go 写一个 HTTP 客户端` |
| `/reset` | Alias for `/new`. | `/reset` |

---

## 🧪 Development & Testing

```bash
# Run tests
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

## 📌 Known Issues & Roadmap

- **Sidebar Project Visibility**:
  - *Current Behavior*: WeChat-initiated conversations default to the global `CLI project` (`default-cli-project`) scope in Antigravity. To view past conversations in the Antigravity UI sidebar, select the **CLI project** from the left-hand Projects list, or navigate directly via `conversation://<conversation_id>` links.
  - *TODO / Roadmap*: Add configurable workspace binding (`--workspace-dir` / `workspace_path` in `wechat_sidecar_config.json`) so WeChat conversations can automatically bind to a specific project workspace.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
