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
    Agent wrapper supporting both agy CLI (default, usability-first) and agentapi (Remote Control UI sync),
    with intelligent fallback on authentication/CSRF expiration.
    """

    def __init__(self, config: SidecarConfig):
        self.config = config
        self._agy_bin = self._find_agy_binary()
        self._agentapi_bin = self._find_agentapi_binary()

        # Engine selection: "agy" (default) | "agentapi" | "auto"
        engine_pref = (getattr(config, "engine", "") or os.environ.get("WECHAT_AGENT_ENGINE", "agy")).lower()
        self.engine = engine_pref if engine_pref in ["agy", "agentapi", "auto"] else "agy"

        if self.engine == "agentapi" and self._agentapi_bin:
            self._agent_bin = self._agentapi_bin
        else:
            self._agent_bin = self._agy_bin or self._agentapi_bin

        logger.info(
            f"Initialized AntigravityAgent (engine={self.engine}, binary={self._agent_bin}, is_agy={self.is_agy})"
        )

    @property
    def agent_bin(self) -> Optional[str]:
        return self._agent_bin

    @agent_bin.setter
    def agent_bin(self, value: Optional[str]) -> None:
        self._agent_bin = value

    @property
    def agentapi_bin(self) -> Optional[str]:
        return self._agent_bin

    @agentapi_bin.setter
    def agentapi_bin(self, value: Optional[str]) -> None:
        self._agent_bin = value

    @property
    def agy_bin(self) -> Optional[str]:
        return self._agy_bin

    @agy_bin.setter
    def agy_bin(self, value: Optional[str]) -> None:
        self._agy_bin = value

    @property
    def is_agy(self) -> bool:
        if self._agent_bin:
            name = Path(self._agent_bin).name.lower()
            if "agentapi" in name:
                return False
            if "agy" in name:
                return True
        return self.engine != "agentapi"

    def _find_agy_binary(self) -> Optional[str]:
        """Finds the agy CLI executable."""
        candidates = [
            os.environ.get("ANTIGRAVITY_AGY_EXE"),
            shutil.which("agy"),
            str(Path.home() / ".local" / "bin" / "agy"),
            "/usr/local/bin/agy",
            "/usr/bin/agy",
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def _find_agentapi_binary(self) -> Optional[str]:
        """Finds the agentapi executable."""
        candidates = [
            os.environ.get("ANTIGRAVITY_AGENTAPI_EXE"),
            shutil.which("agentapi"),
            str(Path.home() / ".gemini" / "antigravity-cli" / "bin" / "agentapi"),
            str(Path.home() / ".local" / "bin" / "agentapi"),
            "/usr/local/bin/agentapi",
            "/usr/bin/agentapi"
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                if Path(c).name == "agy":
                    continue
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

    def _find_default_project_id(self) -> str:
        """Fallback helper to auto-discover project ID from ~/.gemini/config/projects/."""
        projects_dir = Path.home() / ".gemini" / "config" / "projects"
        if projects_dir.exists():
            for p_file in projects_dir.glob("*.json"):
                if p_file.name == "default-cli-project.json":
                    continue
                try:
                    data = json.loads(p_file.read_text(encoding="utf-8"))
                    p_id = data.get("id")
                    if p_id:
                        return p_id
                except Exception:
                    continue
        return "default-cli-project"

    def _get_csrf_token(self, ls_address: str = "localhost:4400") -> str:
        token = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")
        if token:
            return token

        token_file = Path.home() / ".gemini" / "antigravity_csrf_token"
        if token_file.exists():
            try:
                val = token_file.read_text(encoding="utf-8").strip()
                if val:
                    return val
            except Exception:
                pass

        try:
            import urllib.request
            import re
            url = f"http://{ls_address}/"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                match = re.search(r'csrfToken["\']?\s*[:=]\s*["\']([^"\']+)["\']', html)
                if not match:
                    match = re.search(r'csrfToken[\":\s]+([a-zA-Z0-9_\-]+)', html)
                if match:
                    return match.group(1)
        except Exception as e:
            logger.debug(f"Failed to fetch CSRF token from {ls_address}: {e}")
        return ""

    def _prepare_agentapi_env(self) -> dict:
        """Constructs a clean environment for agentapi child process, stripping parent caller scoping."""
        env = os.environ.copy()
        for var in [
            "ANTIGRAVITY_AGENT",
            "ANTIGRAVITY_CONVERSATION_ID",
            "ANTIGRAVITY_SOURCE_METADATA",
            "ANTIGRAVITY_TRAJECTORY_ID",
            "INVOCATION_ID",
            "ANTIGRAVITY_PROJECT_ID",
            "AGENTAPI_PROJECT_ID",
        ]:
            env.pop(var, None)

        project_id = (
            self.config.project_id
            or os.environ.get("WECHAT_SIDECAR_PROJECT_ID", "")
            or self._find_default_project_id()
        )
        if project_id:
            env["AGENTAPI_PROJECT_ID"] = project_id
            env["ANTIGRAVITY_PROJECT_ID"] = project_id
            logger.info(f"Using project ID: {project_id}")

        ls_address = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "localhost:4400")
        env["ANTIGRAVITY_LS_ADDRESS"] = ls_address

        csrf_token = self._get_csrf_token(ls_address)
        if csrf_token:
            env["ANTIGRAVITY_CSRF_TOKEN"] = csrf_token

        return env



    async def _execute_agy(self, prompt: str, conversation_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
        """
        Executes a user prompt using agy CLI with non-interactive --print mode and JSON output.
        """
        cmd = [
            self.agent_bin,
            "--dangerously-skip-permissions",
            "--output-format", "json",
        ]
        project_id = (
            self.config.project_id
            or os.environ.get("WECHAT_SIDECAR_PROJECT_ID", "")
            or self._find_default_project_id()
        )
        if project_id and project_id != "default-cli-project":
            cmd.append(f"--project={project_id}")

        if conversation_id:
            cmd.append(f"--conversation={conversation_id}")

        cmd.append(f"--print={prompt}")

        env = self._prepare_agentapi_env()

        logger.info(f"Executing agy CLI (conv={conversation_id})...")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        stdout, stderr = await proc.communicate()
        out_str = stdout.decode("utf-8", errors="replace").strip()
        err_str = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            logger.error(f"agy execution failed ({proc.returncode}): stdout={out_str}, stderr={err_str}")
            if conversation_id:
                logger.warning(f"Continuation of conversation {conversation_id} failed, falling back to new conversation...")
                return await self._execute_agy(prompt, conversation_id=None)
            err_msg = (out_str + "\n" + err_str).strip()
            return f"❌ [Antigravity 执行失败]\n{err_msg}", None

        try:
            data = json.loads(out_str)
            if data.get("status") == "ERROR":
                err = data.get("error", "Unknown error")
                logger.error(f"agy returned status ERROR: {err}")
                if conversation_id:
                    logger.warning("Falling back to new conversation after status ERROR...")
                    return await self._execute_agy(prompt, conversation_id=None)
                return f"❌ [Antigravity 执行错误]\n{err}", None

            resp_val = data.get("response", "")
            if isinstance(resp_val, dict):
                new_id = resp_val.get("newConversation", {}).get("conversationId")
                if new_id:
                    new_conv_id = new_id
                    reply = await self._wait_for_response(new_conv_id, start_line=0, timeout=10.0)
                else:
                    reply = ""
            elif isinstance(resp_val, str):
                reply = resp_val.strip()
            else:
                reply = str(resp_val) if resp_val is not None else ""

            new_conv_id = data.get("conversation_id") or conversation_id or (resp_val.get("newConversation", {}).get("conversationId") if isinstance(resp_val, dict) else None)
            if not reply and new_conv_id:
                reply = await self._wait_for_response(new_conv_id, start_line=0, timeout=10.0)
            return reply or "（Antigravity 已处理该请求）", new_conv_id
        except Exception as e:
            logger.error(f"Failed to parse agy JSON output: {out_str}, err: {e}")
            return out_str or err_str, conversation_id

    async def execute(self, prompt: str, conversation_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
        """
        Executes a user prompt using agy CLI or agentapi with intelligent fallback.
        """
        if not self.agent_bin:
            return "❌ [未找到 agentapi 可执行文件，请确保 Antigravity 环境已就绪]", conversation_id

        try:
            if self.is_agy:
                reply, new_id = await self._execute_agy(prompt, conversation_id=conversation_id)
                # If agy fails completely and agentapi is available, attempt fallback
                if reply.startswith("❌") and self._find_agentapi_binary():
                    logger.warning("agy execution failed; attempting fallback to agentapi...")
                    fb_agent = self._find_agentapi_binary()
                    orig_bin = self._agent_bin
                    try:
                        self._agent_bin = fb_agent
                        fb_reply, fb_id = await self._execute_agentapi(prompt, conversation_id=conversation_id)
                        if not fb_reply.startswith("❌"):
                            return fb_reply, fb_id
                    finally:
                        self._agent_bin = orig_bin
                return reply, new_id
            else:
                reply, new_id = await self._execute_agentapi(prompt, conversation_id=conversation_id)
                # If agentapi failed due to CSRF or auth error, automatically fallback to agy
                is_auth_error = any(x in reply for x in ["missing CSRF token", "Unauthenticated", "CSRF"])
                if is_auth_error and (self.agy_bin or self._find_agy_binary()):
                    logger.warning("agentapi failed with CSRF/auth error; automatically falling back to agy engine...")
                    orig_bin = self._agent_bin
                    try:
                        self._agent_bin = self.agy_bin or self._find_agy_binary()
                        return await self._execute_agy(prompt, conversation_id=conversation_id)
                    finally:
                        self._agent_bin = orig_bin
                return reply, new_id
        except Exception as e:
            logger.error(f"Failed to execute agent: {e}", exc_info=True)
            # If agentapi crashed or raised exception, fallback to agy if available
            if not self.is_agy and (self.agy_bin or self._find_agy_binary()):
                logger.warning(f"agentapi raised exception {e}; falling back to agy engine...")
                orig_bin = self._agent_bin
                try:
                    self._agent_bin = self.agy_bin or self._find_agy_binary()
                    return await self._execute_agy(prompt, conversation_id=conversation_id)
                except Exception as fb_err:
                    logger.error(f"Fallback to agy also failed: {fb_err}")
                finally:
                    self._agent_bin = orig_bin
            return f"❌ [Antigravity 执行异常]\n{e!s}", conversation_id

    async def _execute_agentapi(self, prompt: str, conversation_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
        """
        Executes a user prompt using legacy agentapi.
        """
        try:
            if conversation_id:
                start_line = self._count_transcript_lines(conversation_id)
                logger.info(f"Sending message to conversation {conversation_id} via agentapi...")
                cmd = [self.agent_bin, "send-message", conversation_id, prompt]
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
                    if any(x in err_msg for x in ["missing CSRF token", "Unauthenticated", "CSRF"]):
                        return f"❌ [CSRF Token 失效]\n{err_msg}", conversation_id
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
            err_msg = (stdout.decode("utf-8", errors="replace") + "\n" + stderr.decode("utf-8", errors="replace")).strip()
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
