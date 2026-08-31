"""
Configuration management for the WeChat Antigravity Sidecar.
"""

from __future__ import annotations

import os
import json
import base64
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


DEFAULT_CONFIG_PATH = Path.home() / ".gemini" / "wechat_sidecar_config.json"
DEFAULT_ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_BOT_AGENT = "openclaw-agent/1.0.0 (Antigravity-Bridge)"
DEFAULT_SYSTEM_INSTRUCTIONS = (
    "You are connected to the user via WeChat. "
    "Provide direct, concise, and well-structured answers using GitHub-flavored Markdown. "
    "Keep code blocks clear and avoid unnecessary preamble."
)


@dataclass
class SidecarConfig:
    bot_token: str = ""
    bot_id: str = ""
    uin: str = ""
    get_updates_buf: str = ""
    login_time: int = 0
    ilink_base_url: str = DEFAULT_ILINK_BASE_URL
    bot_agent: str = DEFAULT_BOT_AGENT
    system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS
    enable_write_tools: bool = True
    user_conversations: Dict[str, str] = field(default_factory=dict)
    config_path: Path = field(default_factory=lambda: DEFAULT_CONFIG_PATH)

    @classmethod
    def load(cls, path: Optional[Path | str] = None) -> SidecarConfig:
        config_file = Path(path) if path else Path(
            os.getenv("WECHAT_SIDECAR_CONFIG", str(DEFAULT_CONFIG_PATH))
        )
        if not config_file.exists():
            instance = cls(config_path=config_file)
            instance._ensure_uin()
            return instance

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            instance = cls(
                bot_token=data.get("bot_token", ""),
                bot_id=data.get("bot_id", ""),
                uin=data.get("uin", ""),
                get_updates_buf=data.get("get_updates_buf", ""),
                login_time=data.get("login_time", 0),
                ilink_base_url=data.get("ilink_base_url", DEFAULT_ILINK_BASE_URL),
                bot_agent=data.get("bot_agent", DEFAULT_BOT_AGENT),
                system_instructions=data.get("system_instructions") or DEFAULT_SYSTEM_INSTRUCTIONS,
                enable_write_tools=data.get("enable_write_tools", True),
                user_conversations=data.get("user_conversations", {}),
                config_path=config_file
            )
            instance._ensure_uin()
            return instance
        except Exception:
            instance = cls(config_path=config_file)
            instance._ensure_uin()
            return instance

    def _ensure_uin(self):
        if not self.uin:
            rand_val = str(random.randint(100000000, 999999999))
            self.uin = base64.b64encode(rand_val.encode()).decode()

    def save(self):
        self._ensure_uin()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bot_token": self.bot_token,
            "bot_id": self.bot_id,
            "uin": self.uin,
            "get_updates_buf": self.get_updates_buf,
            "login_time": self.login_time,
            "ilink_base_url": self.ilink_base_url,
            "bot_agent": self.bot_agent,
            "system_instructions": self.system_instructions,
            "enable_write_tools": self.enable_write_tools,
            "user_conversations": self.user_conversations
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def get_conversation_id(self, user_id: str) -> Optional[str]:
        return self.user_conversations.get(user_id)

    def set_conversation_id(self, user_id: str, conv_id: str):
        self.user_conversations[user_id] = conv_id
        self.save()

    def reset_conversation(self, user_id: str):
        if user_id in self.user_conversations:
            del self.user_conversations[user_id]
            self.save()

    def get_auth_headers(self) -> Dict[str, str]:
        self._ensure_uin()
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.bot_token}",
            "bot_agent": self.bot_agent,
            "X-WECHAT-UIN": self.uin
        }
