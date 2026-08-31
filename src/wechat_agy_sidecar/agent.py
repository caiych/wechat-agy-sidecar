"""
Antigravity Agent Execution Bridge.
Seamlessly taps into the active logged-in AGY instance (OAuth / Ambient Session)
or falls back to google-antigravity SDK when GEMINI_API_KEY is configured.
"""

from __future__ import annotations

import os
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional

from wechat_agy_sidecar.config import SidecarConfig

logger = logging.getLogger("wechat_agy_sidecar.agent")

# Attempt SDK import
HAS_SDK = False
try:
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
    HAS_SDK = True
except ImportError:
    pass


class AntigravityAgent:
    """Agent wrapper for Antigravity execution."""

    def __init__(self, config: SidecarConfig):
        self.config = config
        self.agy_bin = self._find_agy_binary()

    def _find_agy_binary(self) -> Optional[str]:
        """Finds the local agy executable from environment or standard paths."""
        candidates = [
            os.environ.get("ANTIGRAVITY_AGENTAPI_EXE"),
            str(Path.home() / ".local" / "bin" / "agy"),
            shutil.which("agy"),
            "/usr/local/bin/agy",
            "/usr/bin/agy"
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    async def execute(self, prompt: str, user_id: Optional[str] = None) -> str:
        """
        Executes a user prompt using either:
        1. The ambient logged-in Antigravity instance (agy CLI / OAuth session)
        2. Or google-antigravity SDK (if GEMINI_API_KEY is provided)
        """
        has_api_key = bool(os.environ.get("GEMINI_API_KEY") or getattr(self.config, "api_key", None))

        # Mode A: If GEMINI_API_KEY is explicitly configured, use google-antigravity SDK
        if has_api_key and HAS_SDK:
            try:
                logger.info("Executing prompt via google-antigravity Python SDK (API Key mode)...")
                agent_config = LocalAgentConfig(
                    system_instructions=self.config.system_instructions,
                    capabilities=CapabilitiesConfig() if self.config.enable_write_tools else None
                )
                async with Agent(agent_config) as agent:
                    response = await agent.chat(prompt)
                    tokens = []
                    async for token in response:
                        tokens.append(token)
                    full_reply = "".join(tokens).strip()
                    return full_reply or "（Antigravity 执行完成，无输出）"
            except Exception as e:
                logger.warning(f"SDK execution failed: {e}. Falling back to ambient AGY instance...")

        # Mode B: Ambient logged-in AGY instance (OAuth / Active Session)
        if self.agy_bin:
            try:
                logger.info(f"Executing prompt via logged-in AGY instance: {self.agy_bin}")
                cmd = [
                    self.agy_bin,
                    "--dangerously-skip-permissions",
                    "-p", prompt
                ]
                
                # Pass current process environment so logged-in state & auth are preserved
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=os.environ.copy()
                )
                stdout, stderr = await proc.communicate()
                
                if proc.returncode == 0:
                    output = stdout.decode("utf-8", errors="replace").strip()
                    return output or "（Antigravity 执行完成，无输出）"
                else:
                    err_msg = stderr.decode("utf-8", errors="replace").strip()
                    logger.error(f"AGY process returned non-zero exit code ({proc.returncode}): {err_msg}")
                    return f"❌ [Antigravity 执行错误 (Code {proc.returncode})]\n{err_msg}"
            except Exception as e:
                logger.error(f"Failed to execute local AGY binary: {e}", exc_info=True)
                return f"❌ [Antigravity 执行异常]\n{str(e)}"

        return (
            "❌ [未找到可用的 Antigravity 执行引擎]\n"
            "系统未找到已登录的 agy 二进制文件，也未设置 GEMINI_API_KEY 环境变量。"
        )
