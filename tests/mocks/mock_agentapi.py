"""
Mock Antigravity agentapi CLI and brain directory workspace.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class MockBrainWorkspace:
    """Simulates the local ~/.gemini/antigravity-cli/brain directory for testing."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._step_counters: Dict[str, int] = {}

    def get_transcript_path(self, conversation_id: str) -> Path:
        return self.base_dir / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"

    def create_conversation(
        self,
        conversation_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        initial_response: Optional[str] = None,
        mtime: Optional[float] = None
    ) -> str:
        """Initializes a conversation directory structure with optional initial turns."""
        conv_id = conversation_id or str(uuid.uuid4())
        t_file = self.get_transcript_path(conv_id)
        t_file.parent.mkdir(parents=True, exist_ok=True)
        self._step_counters[conv_id] = 0

        if initial_prompt:
            self.append_user_input(conv_id, initial_prompt)
        if initial_response:
            self.append_planner_response(conv_id, initial_response)

        if mtime is not None:
            os.utime(t_file, (mtime, mtime))

        return conv_id

    def append_user_input(self, conversation_id: str, content: str) -> int:
        """Appends a USER_INPUT step to transcript.jsonl."""
        t_file = self.get_transcript_path(conversation_id)
        t_file.parent.mkdir(parents=True, exist_ok=True)
        step_idx = self._step_counters.get(conversation_id, 0) + 1
        self._step_counters[conversation_id] = step_idx

        entry = {
            "step_index": step_idx,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": "2026-08-31T12:00:00Z",
            "content": content
        }
        with open(t_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return step_idx

    def append_planner_response(
        self,
        conversation_id: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None
    ) -> int:
        """Appends a PLANNER_RESPONSE step to transcript.jsonl."""
        t_file = self.get_transcript_path(conversation_id)
        t_file.parent.mkdir(parents=True, exist_ok=True)
        step_idx = self._step_counters.get(conversation_id, 0) + 1
        self._step_counters[conversation_id] = step_idx

        entry = {
            "step_index": step_idx,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-08-31T12:00:01Z",
            "content": content,
            "tool_calls": tool_calls or []
        }
        with open(t_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return step_idx


class MockSubprocess:
    """Mock for asyncio.subprocess.Process."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> Tuple[bytes, bytes]:
        return self._stdout, self._stderr


class MockAgentApi:
    """Mocks agentapi subprocess execution and handles conversation lifecycle."""

    def __init__(self, workspace: MockBrainWorkspace):
        self.workspace = workspace
        self.invocations: List[Dict[str, Any]] = []
        self.default_responses: Dict[str, str] = {}  # prompt substr -> response
        self.fail_next: bool = False
        self.fail_exit_code: int = 1
        self.fail_stderr: str = "Command failed"

    async def handle_exec(self, *cmd, **kwargs) -> MockSubprocess:
        """Handler to replace asyncio.create_subprocess_exec."""
        args = list(cmd)
        env = kwargs.get("env", {})
        self.invocations.append({
            "cmd": args,
            "env": env,
            "time": time.time()
        })

        if self.fail_next:
            self.fail_next = False
            return MockSubprocess(stdout=b"", stderr=self.fail_stderr.encode(), returncode=self.fail_exit_code)

        subcmd = args[1] if len(args) > 1 else ""

        if subcmd == "new-conversation":
            prompt = args[2] if len(args) > 2 else ""
            new_conv_id = f"mock-conv-{uuid.uuid4().hex[:8]}"

            # Determine response content
            response_text = self._match_response(prompt)
            # Create transcript with prompt and response
            self.workspace.create_conversation(new_conv_id, initial_prompt=prompt, initial_response=response_text)

            stdout_json = json.dumps({
                "response": {
                    "newConversation": {
                        "conversationId": new_conv_id
                    }
                }
            })
            return MockSubprocess(stdout=stdout_json.encode("utf-8"), returncode=0)

        elif subcmd == "send-message":
            conv_id = args[2] if len(args) > 2 else ""
            prompt = args[3] if len(args) > 3 else ""

            response_text = self._match_response(prompt)
            self.workspace.append_user_input(conv_id, prompt)
            self.workspace.append_planner_response(conv_id, response_text)

            return MockSubprocess(stdout=b'{"status": "ok"}', returncode=0)

        return MockSubprocess(stdout=b"", stderr=b"Unknown command", returncode=127)

    def _match_response(self, prompt: str) -> str:
        for k, v in self.default_responses.items():
            if k in prompt:
                return v
        return f"Echo from Antigravity: {prompt}"
