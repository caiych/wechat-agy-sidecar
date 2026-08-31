"""
Unit tests for AntigravityAgent in wechat_agy_sidecar.agent.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import pytest

from tests.conftest import FakeProcess
from wechat_agy_sidecar.agent import AntigravityAgent


def test_find_agentapi_binary(mock_config, temp_dir):
    agent = AntigravityAgent(mock_config)

    fake_bin = temp_dir / "fake_agentapi"
    fake_bin.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    # 1. Test when ANTIGRAVITY_AGENTAPI_EXE is explicitly set
    with patch.dict("os.environ", {"ANTIGRAVITY_AGENTAPI_EXE": str(fake_bin)}):
        found = agent._find_agentapi_binary()
        assert found == str(fake_bin)

    # 2. Test when ANTIGRAVITY_AGENTAPI_EXE is empty and shutil.which finds binary
    with patch.dict("os.environ", {}, clear=True), \
         patch("shutil.which", return_value=str(fake_bin)):
        found = agent._find_agentapi_binary()
        assert found == str(fake_bin)

    # 3. Test when nothing exists
    with patch.dict("os.environ", {}, clear=True), \
         patch("shutil.which", return_value=None), \
         patch("os.path.isfile", return_value=False):
        found = agent._find_agentapi_binary()
        assert found is None


def test_extract_conversation_title(mock_config, mock_brain_dir, transcript_builder):
    agent = AntigravityAgent(mock_config)
    conv_id = "conv_test_title"

    # Case 1: Non-existent transcript
    assert agent.extract_conversation_title("non_existent") == "会话 (non_exis)"

    # Case 2: Clean user input
    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nImplement a REST API in Python\n</USER_REQUEST>"
            }
        ]
    )
    title = agent.extract_conversation_title(conv_id)
    assert title == "Implement a REST API in Python"

    # Case 3: Long prompt gets truncated to 36 chars + "..."
    long_prompt = "A" * 50
    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": long_prompt}
        ]
    )
    title_long = agent.extract_conversation_title(conv_id)
    assert len(title_long) == 39  # 36 + '...'
    assert title_long.endswith("...")


def test_extract_last_message_preview(mock_config, mock_brain_dir, transcript_builder):
    agent = AntigravityAgent(mock_config)
    conv_id = "conv_test_preview"

    # Case 1: Non-existent transcript
    assert agent.extract_last_message_preview("non_existent") == ""

    # Case 2: Extract last AI response
    steps = [
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "content": "What is 2+2?"
        },
        {
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "content": "<SYSTEM_MESSAGE>Internal metadata</SYSTEM_MESSAGE>Created At: 2026-08-31\nCompleted At: 2026-08-31\n2 + 2 equals 4.",
            "tool_calls": []
        }
    ]
    transcript_builder.create_transcript(mock_brain_dir, conv_id, steps)

    preview = agent.extract_last_message_preview(conv_id)
    assert preview == "🤖 AI: 2 + 2 equals 4."

    # Case 3: Extract last user input when model hasn't responded
    steps_user_only = [
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "content": "Just asking a question."
        }
    ]
    transcript_builder.create_transcript(mock_brain_dir, "conv_user_only", steps_user_only)
    preview_user = agent.extract_last_message_preview("conv_user_only")
    assert preview_user == "👤 用户: Just asking a question."


def test_list_all_recent_conversations(mock_config, mock_brain_dir, transcript_builder):
    agent = AntigravityAgent(mock_config)

    now = time.time()
    # Create 3 conversations with different timestamps
    transcript_builder.create_transcript(
        mock_brain_dir,
        "conv_old",
        [{"step_index": 0, "type": "USER_INPUT", "content": "Old Conversation"}],
        mtime=now - 200
    )
    transcript_builder.create_transcript(
        mock_brain_dir,
        "conv_mid",
        [{"step_index": 0, "type": "USER_INPUT", "content": "Mid Conversation"}],
        mtime=now - 100
    )
    transcript_builder.create_transcript(
        mock_brain_dir,
        "conv_new",
        [{"step_index": 0, "type": "USER_INPUT", "content": "New Conversation"}],
        mtime=now
    )

    convs = agent.list_all_recent_conversations(limit=2)
    assert len(convs) == 2
    assert convs[0]["conv_id"] == "conv_new"
    assert convs[0]["title"] == "New Conversation"
    assert convs[1]["conv_id"] == "conv_mid"
    assert convs[1]["title"] == "Mid Conversation"


@pytest.mark.asyncio
async def test_wait_for_response(mock_config, mock_brain_dir, transcript_builder):
    agent = AntigravityAgent(mock_config)
    conv_id = "conv_test_wait"

    # Step 0 is user input
    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [{"step_index": 0, "type": "USER_INPUT", "content": "Hello"}]
    )

    async def append_response_later():
        await asyncio.sleep(0.1)
        # Step 1 is intermediate tool call
        transcript_builder.append_step(
            mock_brain_dir,
            conv_id,
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "I am thinking...", "tool_calls": [{"name": "tool_1"}]}
        )
        await asyncio.sleep(0.1)
        # Step 2 is final response
        transcript_builder.append_step(
            mock_brain_dir,
            conv_id,
            {"step_index": 2, "type": "PLANNER_RESPONSE", "content": "Here is your final answer.", "tool_calls": []}
        )

    asyncio.create_task(append_response_later())

    reply = await agent._wait_for_response(conv_id, start_line=1, timeout=5.0)
    assert reply == "Here is your final answer."


@pytest.mark.asyncio
async def test_execute_new_conversation_success(mock_config, mock_brain_dir, transcript_builder):
    agent = AntigravityAgent(mock_config)
    agent.agentapi_bin = "/mock/bin/agentapi"

    new_conv_id = "conv_uuid_new_123"
    api_output = json.dumps({
        "response": {
            "newConversation": {
                "conversationId": new_conv_id
            }
        }
    })

    # Prepare transcript for the new conversation
    transcript_builder.create_transcript(
        mock_brain_dir,
        new_conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "New prompt"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Created new response!", "tool_calls": []}
        ]
    )

    mock_proc = FakeProcess(returncode=0, stdout=api_output.encode("utf-8"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_subproc:
        reply, conv_id = await agent.execute("New prompt", conversation_id=None)

        assert conv_id == new_conv_id
        assert reply == "Created new response!"

        # Verify command and project ID env injection
        mock_subproc.assert_called_once()
        args, kwargs = mock_subproc.call_args
        assert args == ("/mock/bin/agentapi", "new-conversation", "New prompt")
        assert kwargs["env"]["AGENTAPI_PROJECT_ID"] == "test-project-alpha"


@pytest.mark.asyncio
async def test_execute_send_message_success(mock_config, mock_brain_dir, transcript_builder):
    agent = AntigravityAgent(mock_config)
    agent.agentapi_bin = "/mock/bin/agentapi"
    conv_id = "conv_existing_456"

    # Initial turn (line count = 2)
    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "Turn 1"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Reply 1", "tool_calls": []}
        ]
    )

    mock_proc = FakeProcess(returncode=0, stdout=b'{"status": "ok"}')

    async def append_turn_2():
        await asyncio.sleep(0.05)
        transcript_builder.append_step(
            mock_brain_dir,
            conv_id,
            {"step_index": 2, "type": "USER_INPUT", "content": "Turn 2"}
        )
        transcript_builder.append_step(
            mock_brain_dir,
            conv_id,
            {"step_index": 3, "type": "PLANNER_RESPONSE", "content": "Reply 2 for multi-turn!", "tool_calls": []}
        )

    asyncio.create_task(append_turn_2())

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_subproc:
        reply, returned_conv_id = await agent.execute("Turn 2", conversation_id=conv_id)

        assert returned_conv_id == conv_id
        assert reply == "Reply 2 for multi-turn!"

        mock_subproc.assert_called_once()
        args, kwargs = mock_subproc.call_args
        assert args == ("/mock/bin/agentapi", "send-message", conv_id, "Turn 2")
        assert kwargs["env"]["AGENTAPI_PROJECT_ID"] == "test-project-alpha"


@pytest.mark.asyncio
async def test_execute_send_message_failure_fallback_to_new(mock_config, mock_brain_dir, transcript_builder):
    agent = AntigravityAgent(mock_config)
    agent.agentapi_bin = "/mock/bin/agentapi"
    failed_conv_id = "conv_stale_789"
    new_conv_id = "conv_fallback_999"

    transcript_builder.create_transcript(
        mock_brain_dir,
        new_conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "Fallback prompt"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Fallback successful!", "tool_calls": []}
        ]
    )

    # First call fails (send-message), second call succeeds (new-conversation)
    fail_proc = FakeProcess(returncode=1, stderr=b"Conversation closed or not found")
    new_proc = FakeProcess(
        returncode=0,
        stdout=json.dumps({"response": {"newConversation": {"conversationId": new_conv_id}}}).encode("utf-8")
    )

    with patch("asyncio.create_subprocess_exec", side_effect=[fail_proc, new_proc]):
        reply, returned_conv_id = await agent.execute("Fallback prompt", conversation_id=failed_conv_id)
        assert returned_conv_id == new_conv_id
        assert reply == "Fallback successful!"


@pytest.mark.asyncio
async def test_execute_missing_binary(mock_config):
    agent = AntigravityAgent(mock_config)
    agent.agentapi_bin = None

    reply, conv_id = await agent.execute("Hello", conversation_id="conv_123")
    assert "未找到 agentapi 可执行文件" in reply
    assert conv_id == "conv_123"
