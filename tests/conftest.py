"""
Shared test fixtures and mock helpers for WeChat Antigravity Sidecar tests.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from wechat_agy_sidecar.config import SidecarConfig


@pytest.fixture
def temp_dir():
    """Provides a clean temporary directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def mock_config(temp_dir):
    """Provides a fresh SidecarConfig instance pointing to a temp file."""
    cfg_file = temp_dir / "sidecar_config.json"
    cfg = SidecarConfig.load(cfg_file)
    cfg.bot_token = "test_bot_token_xyz"
    cfg.bot_id = "test_bot_id_123"
    cfg.uin = "dGVzdF91aW5fdmFs"
    cfg.project_id = "test-project-alpha"
    cfg.save()
    return cfg


@pytest.fixture
def mock_brain_dir(temp_dir, monkeypatch):
    """
    Sets up a temporary Antigravity brain directory and monkeypatches
    the BRAIN_DIR constants in both agent and sidecar modules.
    """
    brain_path = temp_dir / "antigravity-cli" / "brain"
    brain_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("wechat_agy_sidecar.agent.BRAIN_DIR", brain_path)
    monkeypatch.setattr("wechat_agy_sidecar.sidecar.BRAIN_DIR", brain_path)

    return brain_path


@pytest.fixture
def mock_media_dir(temp_dir, monkeypatch):
    """
    Sets up a temporary media directory and monkeypatches
    MEDIA_DIR and MEDIA_REGISTRY_FILE in media module.
    """
    media_path = temp_dir / "wechat_media"
    media_path.mkdir(parents=True, exist_ok=True)
    registry_path = media_path / "registry.json"

    monkeypatch.setattr("wechat_agy_sidecar.media.MEDIA_DIR", media_path)
    monkeypatch.setattr("wechat_agy_sidecar.media.MEDIA_REGISTRY_FILE", registry_path)

    return media_path


class FakeTranscriptBuilder:
    """Helper to generate realistic Antigravity transcript.jsonl files for testing."""

    @staticmethod
    def create_transcript(
        brain_dir: Path,
        conversation_id: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        mtime: Optional[float] = None
    ) -> Path:
        t_dir = brain_dir / conversation_id / ".system_generated" / "logs"
        t_dir.mkdir(parents=True, exist_ok=True)
        t_file = t_dir / "transcript.jsonl"

        if steps is None:
            steps = [
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "content": "Hello Antigravity!",
                    "created_at": "2026-08-31T10:00:00Z"
                },
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "source": "MODEL",
                    "content": "Hello! How can I assist you with your code today?",
                    "tool_calls": [],
                    "created_at": "2026-08-31T10:00:02Z"
                }
            ]

        with open(t_file, "w", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(step, ensure_ascii=False) + "\n")

        if mtime is not None:
            import os
            os.utime(t_file, (mtime, mtime))

        return t_file

    @staticmethod
    def append_step(brain_dir: Path, conversation_id: str, step: Dict[str, Any]) -> Path:
        t_file = brain_dir / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
        t_file.parent.mkdir(parents=True, exist_ok=True)
        with open(t_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(step, ensure_ascii=False) + "\n")
        return t_file


class FakeProcess:
    """Mock process for asyncio.create_subprocess_exec."""

    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self, input: Optional[bytes] = None):
        return (self._stdout, self._stderr)


@pytest.fixture
def transcript_builder():
    return FakeTranscriptBuilder
