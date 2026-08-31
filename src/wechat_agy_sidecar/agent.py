"""
Google Antigravity SDK Agent Executor.
Directly interfaces with google-antigravity Python SDK.
"""

from __future__ import annotations

import logging
from typing import Optional, AsyncIterator
from wechat_agy_sidecar.config import SidecarConfig

logger = logging.getLogger("wechat_agy_sidecar.agent")

try:
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
    HAS_SDK = True
except ImportError:
    HAS_SDK = False


class AntigravityAgent:
    """Agent wrapper using the official google-antigravity Python SDK."""

    def __init__(self, config: SidecarConfig):
        self.config = config
        if not HAS_SDK:
            raise RuntimeError(
                "google-antigravity package is required. "
                "Install it with: pip install google-antigravity"
            )

    async def execute(self, prompt: str) -> str:
        """
        Executes a user prompt using Antigravity Agent and returns the full response string.
        """
        logger.info(f"Invoking Antigravity SDK Agent with prompt: {prompt[:50]}...")
        agent_config = LocalAgentConfig(
            system_instructions=self.config.system_instructions,
            capabilities=CapabilitiesConfig() if self.config.enable_write_tools else None
        )

        try:
            async with Agent(agent_config) as agent:
                response = await agent.chat(prompt)
                tokens = []
                async for token in response:
                    tokens.append(token)
                full_reply = "".join(tokens).strip()
                return full_reply or "（Antigravity 执行完成，无输出）"
        except Exception as e:
            logger.error(f"Antigravity SDK execution error: {e}", exc_info=True)
            return f"❌ [Antigravity SDK 错误]\n{str(e)}"
