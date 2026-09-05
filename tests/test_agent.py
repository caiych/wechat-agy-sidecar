"""
Unit tests for AntigravityAgent in wechat_agy_sidecar.agent.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

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


def test_find_default_project_id(mock_config, temp_dir):
    agent = AntigravityAgent(mock_config)
    mock_projects_dir = temp_dir / ".gemini" / "config" / "projects"
    mock_projects_dir.mkdir(parents=True, exist_ok=True)

    with patch("pathlib.Path.home", return_value=temp_dir):
        # Case 1: Empty projects dir -> default
        assert agent._find_default_project_id() == "default-cli-project"

        # Case 2: Only default-cli-project.json -> ignored, returns default
        (mock_projects_dir / "default-cli-project.json").write_text('{"id": "ignored-id"}', encoding="utf-8")
        assert agent._find_default_project_id() == "default-cli-project"

        # Case 3: Malformed json -> ignored
        (mock_projects_dir / "bad.json").write_text("invalid json", encoding="utf-8")
        assert agent._find_default_project_id() == "default-cli-project"

        # Case 4: Valid project json -> returns its id
        (mock_projects_dir / "my_proj.json").write_text('{"id": "discovered-project-123"}', encoding="utf-8")
        assert agent._find_default_project_id() == "discovered-project-123"


def test_get_csrf_token(mock_config, temp_dir):
    agent = AntigravityAgent(mock_config)

    # 1. When ANTIGRAVITY_CSRF_TOKEN is in environment
    with patch.dict("os.environ", {"ANTIGRAVITY_CSRF_TOKEN": "token-from-env"}):
        assert agent._get_csrf_token() == "token-from-env"

    # 2. When token file exists in ~/.gemini/antigravity_csrf_token
    mock_gemini = temp_dir / ".gemini"
    mock_gemini.mkdir(parents=True, exist_ok=True)
    (mock_gemini / "antigravity_csrf_token").write_text("token-from-file-5678", encoding="utf-8")
    with patch.dict("os.environ", {}, clear=True), patch("pathlib.Path.home", return_value=temp_dir):
        assert agent._get_csrf_token() == "token-from-file-5678"

    # 3. When token file does not exist, fetch from HTTP
    (mock_gemini / "antigravity_csrf_token").unlink()
    html_payload = b'<html><script>window.__APP_CONFIG__ = {"csrfToken":"token-from-http-1234-abcd"};</script></html>'
    mock_response = MagicMock()
    mock_response.read.return_value = html_payload
    mock_response.__enter__.return_value = mock_response

    with patch.dict("os.environ", {}, clear=True), \
         patch("pathlib.Path.home", return_value=temp_dir), \
         patch("urllib.request.urlopen", return_value=mock_response):
        assert agent._get_csrf_token("localhost:4400") == "token-from-http-1234-abcd"

    # 4. When fetch fails (e.g. urllib raises Exception)
    with patch.dict("os.environ", {}, clear=True), \
         patch("pathlib.Path.home", return_value=temp_dir), \
         patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert agent._get_csrf_token("localhost:4400") == ""


def test_prepare_agentapi_env(mock_config):
    agent = AntigravityAgent(mock_config)

    with patch.dict("os.environ", {
        "ANTIGRAVITY_AGENT": "1",
        "ANTIGRAVITY_CONVERSATION_ID": "conv_parent",
        "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:4400",
        "ANTIGRAVITY_CSRF_TOKEN": "csrf-secret-999"
    }):
        env = agent._prepare_agentapi_env()
        # Ensure parent scoping variables are stripped
        assert "ANTIGRAVITY_AGENT" not in env
        assert "ANTIGRAVITY_CONVERSATION_ID" not in env
        # Ensure project and CSRF variables are set
        assert env["AGENTAPI_PROJECT_ID"] == "test-project-alpha"
        assert env["ANTIGRAVITY_LS_ADDRESS"] == "127.0.0.1:4400"
        assert env["ANTIGRAVITY_CSRF_TOKEN"] == "csrf-secret-999"


@pytest.mark.asyncio
async def test_execute_agy_new_conversation(mock_config):
    agent = AntigravityAgent(mock_config)
    agent.agent_bin = "/usr/local/bin/agy"

    agy_output = json.dumps({
        "conversation_id": "conv_agy_test_100",
        "status": "SUCCESS",
        "response": "Hello from native agy CLI!"
    })
    mock_proc = FakeProcess(returncode=0, stdout=agy_output.encode("utf-8"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_subproc:
        reply, conv_id = await agent.execute("Hi there", conversation_id=None)
        assert conv_id == "conv_agy_test_100"
        assert reply == "Hello from native agy CLI!"

        mock_subproc.assert_called_once()
        args, kwargs = mock_subproc.call_args
        assert args[0] == "/usr/local/bin/agy"
        assert "--dangerously-skip-permissions" in args
        assert "--output-format" in args
        assert "json" in args
        assert "--print=Hi there" in args


@pytest.mark.asyncio
async def test_execute_agy_continuation(mock_config):
    agent = AntigravityAgent(mock_config)
    agent.agent_bin = "/usr/local/bin/agy"

    agy_output = json.dumps({
        "conversation_id": "conv_agy_test_100",
        "status": "SUCCESS",
        "response": "Turn 2 continued response!"
    })
    mock_proc = FakeProcess(returncode=0, stdout=agy_output.encode("utf-8"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_subproc:
        reply, conv_id = await agent.execute("Turn 2 prompt", conversation_id="conv_agy_test_100")
        assert conv_id == "conv_agy_test_100"
        assert reply == "Turn 2 continued response!"

        mock_subproc.assert_called_once()
        args, kwargs = mock_subproc.call_args
        assert "--conversation=conv_agy_test_100" in args
        assert "--print=Turn 2 prompt" in args


@pytest.mark.asyncio
async def test_execute_agy_fallback_on_error(mock_config):
    agent = AntigravityAgent(mock_config)
    agent.agent_bin = "/usr/local/bin/agy"

    fail_proc = FakeProcess(returncode=1, stderr=b"Conversation not found")
    new_proc = FakeProcess(
        returncode=0,
        stdout=json.dumps({
            "conversation_id": "conv_agy_fallback_200",
            "status": "SUCCESS",
            "response": "Recovered into new conversation!"
        }).encode("utf-8")
    )

    with patch("asyncio.create_subprocess_exec", side_effect=[fail_proc, new_proc]):
        reply, conv_id = await agent.execute("Recover prompt", conversation_id="stale_conv_id")
        assert conv_id == "conv_agy_fallback_200"
        assert reply == "Recovered into new conversation!"


def test_dual_engine_config_selection(mock_config, temp_dir):
    fake_agy = temp_dir / "fake_agy"
    fake_agy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_agy.chmod(0o755)

    fake_agentapi = temp_dir / "fake_agentapi"
    fake_agentapi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_agentapi.chmod(0o755)

    with patch.dict("os.environ", {
        "ANTIGRAVITY_AGY_EXE": str(fake_agy),
        "ANTIGRAVITY_AGENTAPI_EXE": str(fake_agentapi)
    }):
        # 1. Default engine is agy
        mock_config.engine = "agy"
        agent = AntigravityAgent(mock_config)
        assert agent.is_agy is True
        assert agent.agent_bin == str(fake_agy)

        # 2. Configured for agentapi
        mock_config.engine = "agentapi"
        agent2 = AntigravityAgent(mock_config)
        assert agent2.is_agy is False
        assert agent2.agent_bin == str(fake_agentapi)


@pytest.mark.asyncio
async def test_execute_agentapi_csrf_failure_fallback_to_agy(mock_config, temp_dir):
    fake_agy = temp_dir / "fake_agy"
    fake_agy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_agy.chmod(0o755)

    mock_config.engine = "agentapi"
    agent = AntigravityAgent(mock_config)
    agent.agentapi_bin = "/mock/bin/agentapi"
    agent.agy_bin = str(fake_agy)

    # agentapi fails with missing CSRF token
    csrf_fail_proc = FakeProcess(
        returncode=1,
        stderr=b"failed to fetch available models: rpc error: code = Unauthenticated desc = missing CSRF token"
    )
    # agy succeeds
    agy_success_proc = FakeProcess(
        returncode=0,
        stdout=json.dumps({
            "conversation_id": "conv_recovered_agy_1",
            "status": "SUCCESS",
            "response": "Fallback response from agy engine!"
        }).encode("utf-8")
    )

    with patch("asyncio.create_subprocess_exec", side_effect=[csrf_fail_proc, agy_success_proc]):
        reply, conv_id = await agent.execute("Hello after restart", conversation_id=None)
        assert conv_id == "conv_recovered_agy_1"
        assert reply == "Fallback response from agy engine!"


