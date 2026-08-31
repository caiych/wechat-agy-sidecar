"""
Antigravity Agent Execution Bridge using native agentapi CLI.
Enables programmatic multi-turn conversation threading, real-time response capture,
and background event/timer streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional, Tuple

from wechat_agy_sidecar.config import SidecarConfig

logger = logging.getLogger("wechat_agy_sidecar.agent")

BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"


class AntigravityAgent:
    """
    Agent wrapper using native agentapi CLI for conversation lifecycle and messaging.
    """

    def __init__(self, config: SidecarConfig):
        self.config = config
        self.agentapi_bin = self._find_agentapi_binary()
        logger.info(f"Initialized AntigravityAgent with binary: {self.agentapi_bin}")

    def _find_agentapi_binary(self) -> Optional[str]:
        """Finds the agentapi executable."""
        candidates = [
            shutil.which("agentapi"),
            str(Path.home() / ".gemini" / "antigravity-cli" / "bin" / "agentapi"),
            os.environ.get("ANTIGRAVITY_AGENTAPI_EXE"),
            str(Path.home() / ".local" / "bin" / "agentapi"),
            "/usr/local/bin/agentapi",
            "/usr/bin/agentapi"
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def _get_transcript_path(self, conversation_id: str) -> Path:
        return BRAIN_DIR / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"

    def extract_conversation_title(self, conversation_id: str) -> str:
        """Extracts a short, human-readable title from the first turn of the transcript."""
        t_file = self._get_transcript_path(conversation_id)
        if not t_file.exists():
            return f"会话 ({conversation_id[:8]})"
        try:
            for line in t_file.read_text(encoding="utf-8").strip().splitlines()[:10]:
                step = json.loads(line)
                if step.get("type") == "USER_INPUT" and step.get("content"):
                    raw = step["content"]
                    # Strip XML/HTML wrapper tags if any
                    import re
                    clean = re.sub(r"<SYSTEM_MESSAGE>.*?</SYSTEM_MESSAGE>", "", raw, flags=re.DOTALL)
                    clean = re.sub(r"<system>.*?</system>", "", clean, flags=re.DOTALL)
                    clean = re.sub(r"<[^>]+>", "", clean).strip()
                    first_line = clean.splitlines()[0].strip() if clean.splitlines() else ""
                    if first_line:
                        return first_line[:36] + ("..." if len(first_line) > 36 else "")

        except Exception as e:
            logger.debug(f"Error extracting title for {conversation_id}: {e}")
        return f"会话 ({conversation_id[:8]})"

    def extract_last_message_preview(self, conversation_id: str, max_chars: int = 200) -> str:
        """Extracts a preview snippet of the last meaningful message in the conversation."""
        t_file = self._get_transcript_path(conversation_id)
        if not t_file.exists():
            return ""
        try:
            lines = t_file.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines):
                step = json.loads(line)
                step_type = step.get("type", "")
                content = step.get("content", "").strip()
                if not content or step_type not in ["PLANNER_RESPONSE", "USER_INPUT"]:
                    continue

                # Remove system wrappers / metadata tags
                import re
                clean = re.sub(r"<SYSTEM_MESSAGE>.*?</SYSTEM_MESSAGE>", "", content, flags=re.DOTALL)
                clean = re.sub(r"<[^>]+>", "", clean).strip()
                clean = re.sub(r"^Created At:.*?Completed At:.*?\n", "", clean, flags=re.DOTALL).strip()
                if not clean:
                    continue

                role = "🤖 AI" if step_type == "PLANNER_RESPONSE" else "👤 用户"
                snippet = " ".join(clean.split())
                if len(snippet) > max_chars:
                    snippet = snippet[:max_chars] + "..."
                return f"{role}: {snippet}"
        except Exception as e:
            logger.debug(f"Error extracting last message preview for {conversation_id}: {e}")
        return ""

    def list_all_recent_conversations(self, limit: int = 8) -> list[dict]:
        """
        Discovers all Antigravity conversations across IDE, CLI, and WeChat by scanning
        the ambient brain directory, sorted by most recent activity timestamp.
        """
        if not BRAIN_DIR.exists():
            return []

        conv_candidates = []
        try:
            for item in BRAIN_DIR.iterdir():
                if not item.is_dir() or item.name.startswith("."):
                    continue
                t_file = item / ".system_generated" / "logs" / "transcript.jsonl"
                if not t_file.exists():
                    continue
                try:
                    mtime = t_file.stat().st_mtime
                    conv_candidates.append((mtime, item.name))
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Error scanning brain directory: {e}")
            return []

        conv_candidates.sort(key=lambda x: x[0], reverse=True)

        results = []
        for mtime, c_id in conv_candidates:
            title = self.extract_conversation_title(c_id)
            results.append({
                "conv_id": c_id,
                "title": title,
                "updated_at": int(mtime)
            })
            if len(results) >= limit:
                break
        return results

    def _count_transcript_lines(self, conversation_id: str) -> int:
        t_file = self._get_transcript_path(conversation_id)
        if not t_file.exists():
            return 0
        try:
            return len(t_file.read_text(encoding="utf-8").strip().splitlines())
        except Exception:
            return 0

    async def _wait_for_response(
        self,
        conversation_id: str,
        start_line: int,
        timeout: float = 60.0
    ) -> str:
        """
        Waits for and extracts the assistant's planner response from transcript.jsonl.
        """
        t_file = self._get_transcript_path(conversation_id)
        start_time = time.time()
        last_content = ""

        while time.time() - start_time < timeout:
            await asyncio.sleep(0.5)
            if not t_file.exists():
                continue
            try:
                lines = t_file.read_text(encoding="utf-8").strip().splitlines()
                if len(lines) > start_line:
                    for line in lines[start_line:]:
                        step = json.loads(line)
                        if step.get("type") == "PLANNER_RESPONSE" and step.get("content"):
                            content = step.get("content", "").strip()
                            if content:
                                last_content = content
                                # If there are no active tool calls, this is the turn's final response
                                if not step.get("tool_calls"):
                                    return last_content
            except Exception as e:
                logger.debug(f"Error reading transcript: {e}")

        return last_content or "（Antigravity 已处理该请求）"

    def _prepare_agentapi_env(self) -> dict:
        """Constructs a clean environment for agentapi child process, stripping parent caller scoping."""
        env = os.environ.copy()
        for var in [
            "ANTIGRAVITY_CONVERSATION_ID",
            "ANTIGRAVITY_SOURCE_METADATA",
            "ANTIGRAVITY_TRAJECTORY_ID",
            "ANTIGRAVITY_PROJECT_ID",
            "AGENTAPI_PROJECT_ID",
        ]:
            env.pop(var, None)

        project_id = self.config.project_id or os.environ.get("WECHAT_SIDECAR_PROJECT_ID", "")
        if project_id:
            env["AGENTAPI_PROJECT_ID"] = project_id
            env["ANTIGRAVITY_PROJECT_ID"] = project_id
            logger.info(f"Using project ID: {project_id}")
        return env

    async def execute(self, prompt: str, conversation_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
        """
        Executes a user prompt using agentapi.
        If conversation_id is provided, calls `agentapi send-message`.
        Otherwise, calls `agentapi new-conversation`.
        """
        if not self.agentapi_bin:
            return "❌ [未找到 agentapi 可执行文件，请确保 Antigravity 环境已就绪]", conversation_id

        try:
            if conversation_id:
                start_line = self._count_transcript_lines(conversation_id)
                logger.info(f"Sending message to conversation {conversation_id} via agentapi...")
                cmd = [self.agentapi_bin, "send-message", conversation_id, prompt]
                env = self._prepare_agentapi_env()

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    err_msg = stderr.decode("utf-8", errors="replace").strip()
                    logger.error(f"agentapi send-message failed ({proc.returncode}): {err_msg}")
                    # Fallback to creating a new conversation
                    return await self._create_new_conversation(prompt)

                reply = await self._wait_for_response(conversation_id, start_line)
                return reply, conversation_id
            else:
                return await self._create_new_conversation(prompt)

        except Exception as e:
            logger.error(f"Failed to execute agentapi: {e}", exc_info=True)
            return f"❌ [Antigravity 执行异常]\n{e!s}", conversation_id

    async def _create_new_conversation(self, prompt: str) -> Tuple[str, Optional[str]]:
        """
        Creates a new conversation thread via `agentapi new-conversation`.
        """
        logger.info("Creating new conversation via agentapi...")
        cmd = [self.agentapi_bin, "new-conversation", prompt]
        env = self._prepare_agentapi_env()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        stdout, stderr = await proc.communicate()
        out_str = stdout.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.error(f"agentapi new-conversation failed ({proc.returncode}): {err_msg}")
            return f"❌ [创建会话失败]\n{err_msg}", None

        try:
            data = json.loads(out_str)
            new_id = data["response"]["newConversation"]["conversationId"]
            logger.info(f"New conversation created: {new_id}")
            reply = await self._wait_for_response(new_id, 0)
            return reply, new_id
        except Exception as e:
            logger.error(f"Failed to parse new-conversation output: {out_str}, err: {e}")
            return out_str, None
