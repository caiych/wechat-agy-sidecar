# WeChat Antigravity Sidecar (`wechat-agy-sidecar`)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

A lightweight, robust sidecar daemon that connects **WeChat** directly with the **Google Antigravity Python SDK (`google-antigravity`)**.

It implements the native WeChat **iLink Bot Protocol** (the exact same protocol utilized by OpenClaw's official WeChat channel) without requiring the full OpenClaw agent stack, enabling personal WeChat accounts to interact with Google Antigravity.

---

## 🏗️ Architecture

```
+-------------------+        HTTP Long-Polling (/getupdates)        +-----------------------------------+
|                   | <-------------------------------------------- |  WeChat Antigravity Sidecar       |
|  WeChat iLink API |                                               |  (wechat-agy-sidecar)             |
| (ilinkai.weixin)  | --------------------------------------------> |  - Inbound Parser (msgs/item_list)|
|                   |        HTTP POST (/sendmessage)               |  - Session & Cursor Management    |
+-------------------+ <-------------------------------------------- +-----------------+-----------------+
                                                                                      |
                                                                                      | google.antigravity SDK
                                                                                      v
                                                                    +-----------------------------------+
                                                                    |     Google Antigravity Agent      |
                                                                    |    (google.antigravity.Agent)     |
                                                                    +-----------------------------------+
```

---

## ✨ Features

- **Native Protocol Fidelity**: Implements the Tencent iLink Bot API (`ilink_bot_token`, `bot_agent`, `X-WECHAT-UIN`).
- **Interactive QR Onboarding**: Displays an in-terminal ASCII QR code on initial launch for seamless zero-config WeChat authorization.
- **Pure SDK Driven**: Directly interfaces with `google-antigravity` via the official Python async context manager without subprocess wrappers.
- **Incremental Cursor Sync**: Persists `get_updates_buf` to ensure zero message loss and no duplicate responses across restarts.
- **Typing Indicator**: Automatically sends `sendtyping` events while Antigravity generates code and reasoning steps.
- **Context Routing**: Maintains conversation context via WeChat `context_token` propagation.

---

## 📦 Installation

### Option 1: Modern Editable Install (Recommended)

```bash
git clone https://github.com/caiych/wechat-agy-sidecar.git
cd wechat-agy-sidecar

# Install with pip / uv
pip install -e .
```

### Option 2: Using requirements.txt

```bash
pip install -r requirements.txt
```

---

## 🚀 Quickstart

### 1. One-Time Onboarding (QR Login)

Run the daemon in onboarding mode or start it directly (it will automatically prompt for login if no saved session is found):

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

## ⚙️ Configuration

Configurations can be customized via CLI flags, environment variables, or by editing `~/.gemini/wechat_sidecar_config.json`:

| Parameter | Environment Variable / Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `config_path` | `--config` / `WECHAT_SIDECAR_CONFIG` | `~/.gemini/wechat_sidecar_config.json` | Path to credentials and cursor store. |
| `system_instructions` | `--system-prompt` | Markdown coding assistant | System instructions passed to Antigravity Agent. |
| `enable_write_tools` | Config file | `true` | Enables Antigravity write capabilities (`run_command`, etc.). |

---

## 🧪 Development & Testing

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
