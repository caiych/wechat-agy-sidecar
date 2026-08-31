"""
Antigravity Agent Execution Bridge with Multi-Turn Conversation Threading.
Seamlessly taps into the active logged-in AGY instance (OAuth / Ambient Session)
or falls back to google-antigravity SDK when GEMINI_API_KEY is configured.
"""

from __future__ import annotations

import os
import json
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple

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
    """Agent wrapper for Antigravity execution with persistent conversation threading."""

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

    async def execute(self, prompt: str, conversation_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
        """
        Executes a user prompt within a persistent conversation thread.
        Returns:
            (reply_text, conversation_id)
        """
        has_api_key = bool(os.environ.get("GEMINI_API_KEY") or getattr(self.config, "api_key", None))

        # Mode A: If GEMINI_API_KEY is explicitly configured, use google-antigravity SDK
        if has_api_key and HAS_SDK:
            try:
                logger.info(f"Executing prompt via SDK (conversation={conversation_id})...")
                agent_config = LocalAgentConfig(
                    system_instructions=self.config.system_instructions,
                    capabilities=CapabilitiesConfig() if self.config.enable_write_tools else None,
                    conversation_id=conversation_id
                )
                async with Agent(agent_config) as agent:
                    response = await agent.chat(prompt)
                    tokens = []
                    async for token in response:
                        tokens.append(token)
                    full_reply = "".join(tokens).strip()
                    # SDK conversation object maintains ID
                    active_conv_id = getattr(agent, "conversation_id", conversation_id)
                    return full_reply or "（Antigravity 执行完成，无输出）", active_conv_id
            except Exception as e:
                logger.warning(f"SDK execution failed: {e}. Falling back to ambient AGY instance...")

        # Mode B: Ambient logged-in AGY instance (OAuth / Active Session with JSON format)
        if self.agy_bin:
            try:
                logger.info(f"Executing prompt via logged-in AGY instance (conversation={conversation_id}): {self.agy_bin}")
                cmd = [
                    self.agy_bin,
                    "--dangerously-skip-permissions",
                    "--output-format", "json"
                ]
                if conversation_id:
                    cmd.extend(["--conversation", conversation_id])
                cmd.extend(["-p", prompt])
                
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=os.environ.copy()
                )
                stdout, stderr = await proc.communicate()
                stdout_str = stdout.decode("utf-8", errors="replace").strip()
                stderr_str = stderr.decode("utf-8", errors="replace").strip()

                if proc.returncode == 0 and stdout_str:
                    try:
                        data = json.loads(stdout_str)
                        reply = data.get("response", "").strip()
                        new_conv_id = data.get("conversation_id") or conversation_id
                        return reply or "（Antigravity 执行完成，无输出）", new_conv_id
                    except json.JSONDecodeError:
                        return stdout_str, conversation_id
                else:
                    logger.error(f"AGY process exit code {proc.returncode}: {stderr_str}")
                    return f"❌ [Antigravity 执行错误 (Code {proc.returncode})]\n{stderr_str}", conversation_id

            except Exception as e:
                logger.error(f"Failed to execute local AGY binary: {e}", exc_info=True)
                return f"❌ [Antigravity 执行异常]\n{str(e)}", conversation_id

        return (
            "❌ [未找到可用的 Antigravity 执行引擎]\n"
            "系统未找到已登录的 agy 二进制文件，也未设置 GEMINI_API_KEY 环境变量。",
            None
        )
