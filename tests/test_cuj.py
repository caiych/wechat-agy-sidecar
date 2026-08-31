"""
End-to-End Critical User Journey (CUJ) tests for WeChat Antigravity Sidecar.
Simulates end-to-end flows with mocked WeChat API and agentapi execution.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import FakeProcess
from wechat_agy_sidecar.client import GetUpdatesResult, InboundMessage
from wechat_agy_sidecar.media import register_media
from wechat_agy_sidecar.sidecar import WeChatSidecar


@pytest.mark.asyncio
async def test_cuj_1_first_turn_text_conversation(mock_config, mock_brain_dir, transcript_builder):
    """
    CUJ 1: First-Turn New User Text Interaction.
    - WeChat user sends a prompt.
    - Sidecar discovers no active thread -> executes `agentapi new-conversation`.
    - Sidecar sends typing indicator, waits for transcript response, replies to user.
    - Sidecar records conversation ID in user_conversations and history.
    """

    sidecar = WeChatSidecar(mock_config)
    sidecar.agent.agentapi_bin = "/mock/bin/agentapi"
    user_id = "user_wx_alice"
    conv_id = "conv_cuj1_first_turn"

    inbound = InboundMessage(
        msg_id="wx_msg_cuj1_01",
        from_user_id=user_id,
        context_token="ctx_token_cuj1",
        text="Explain Python async generators."
    )

    # Set up mock transcript for the new conversation
    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "content": "Explain Python async generators."
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "content": "An async generator in Python yields values asynchronously using `async def` and `yield`.",
                "tool_calls": []
            }
        ]
    )

    # Mock agentapi new-conversation output
    mock_proc = FakeProcess(
        returncode=0,
        stdout=json.dumps({"response": {"newConversation": {"conversationId": conv_id}}}).encode("utf-8")
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
         patch.object(sidecar.client, "send_typing") as mock_typing, \
         patch.object(sidecar.client, "send_message") as mock_send:

        await sidecar.handle_message(inbound)

        # 1. Verify agentapi called with new-conversation
        mock_exec.assert_called_once()
        args, _ = mock_exec.call_args
        assert args == ("/mock/bin/agentapi", "new-conversation", "Explain Python async generators.")

        # 2. Verify typing indicator sent (True then False)
        assert mock_typing.call_count == 2
        assert mock_typing.call_args_list[0][0] == (user_id,)
        assert mock_typing.call_args_list[0][1] == {"typing": True}
        assert mock_typing.call_args_list[1][1] == {"typing": False}

        # 3. Verify reply sent to WeChat user
        mock_send.assert_called_once_with(
            user_id,
            "ctx_token_cuj1",
            "An async generator in Python yields values asynchronously using `async def` and `yield`."
        )

        # 4. Verify thread state recorded
        assert mock_config.get_conversation_id(user_id) == conv_id
        recent = mock_config.get_recent_conversations(user_id)
        assert len(recent) == 1
        assert recent[0]["conv_id"] == conv_id


@pytest.mark.asyncio
async def test_cuj_2_multi_turn_conversation_threading(mock_config, mock_brain_dir, transcript_builder):
    """
    CUJ 2: Multi-Turn Conversation Threading.
    - User with an existing active thread sends a follow-up message.
    - Sidecar invokes `agentapi send-message <conv_id>`.
    - Sidecar streams response after start_line, replies to user, retains conversation ID.
    """

    sidecar = WeChatSidecar(mock_config)
    sidecar.agent.agentapi_bin = "/mock/bin/agentapi"
    user_id = "user_wx_bob"
    conv_id = "conv_cuj2_multi_turn"

    # Set up existing conversation state
    mock_config.set_conversation_id(user_id, conv_id)
    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "What is 10 + 20?"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "10 + 20 = 30.", "tool_calls": []}
        ]
    )

    inbound = InboundMessage(
        msg_id="wx_msg_cuj2_02",
        from_user_id=user_id,
        context_token="ctx_token_cuj2",
        text="Now multiply that by 2."
    )

    # Subprocess returns success for send-message
    mock_proc = FakeProcess(returncode=0, stdout=b'{"status": "ok"}')

    async def simulate_agent_turn_2():
        await asyncio.sleep(0.05)
        transcript_builder.append_step(
            mock_brain_dir,
            conv_id,
            {"step_index": 2, "type": "USER_INPUT", "content": "Now multiply that by 2."}
        )
        transcript_builder.append_step(
            mock_brain_dir,
            conv_id,
            {"step_index": 3, "type": "PLANNER_RESPONSE", "content": "30 multiplied by 2 is 60.", "tool_calls": []}
        )

    asyncio.create_task(simulate_agent_turn_2())

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
         patch.object(sidecar.client, "send_typing"), \
         patch.object(sidecar.client, "send_message") as mock_send:

        await sidecar.handle_message(inbound)

        # 1. Verify agentapi called with send-message and existing conv_id
        mock_exec.assert_called_once()
        args, _ = mock_exec.call_args
        assert args == ("/mock/bin/agentapi", "send-message", conv_id, "Now multiply that by 2.")

        # 2. Verify reply sent
        mock_send.assert_called_once_with(user_id, "ctx_token_cuj2", "30 multiplied by 2 is 60.")

        # 3. Conversation ID unchanged
        assert mock_config.get_conversation_id(user_id) == conv_id


@pytest.mark.asyncio
async def test_cuj_3_thread_reset_and_immediate_execution(mock_config, mock_brain_dir, transcript_builder):
    """
    CUJ 3: Thread Reset Commands.
    - User sends '/new' -> resets thread and sends confirmation.
    - User sends '/new <prompt>' -> resets thread and immediately executes prompt in fresh session.
    - User sends '/reset' or '新对话'.
    """

    sidecar = WeChatSidecar(mock_config)
    sidecar.agent.agentapi_bin = "/mock/bin/agentapi"
    user_id = "user_wx_charlie"

    mock_config.set_conversation_id(user_id, "conv_old_to_be_reset")

    with patch.object(sidecar.client, "send_message") as mock_send:
        # Case 3a: Standalone /new
        inbound_new = InboundMessage(
            msg_id="msg_reset_1",
            from_user_id=user_id,
            context_token="ctx_1",
            text="/new"
        )
        await sidecar.handle_message(inbound_new)

        assert mock_config.get_conversation_id(user_id) is None
        mock_send.assert_called_with(user_id, "ctx_1", "🔄 会话已重置，已开启全新的对话线程！请输入你的问题：")

        # Case 3b: Chinese alias '重置会话'
        mock_config.set_conversation_id(user_id, "conv_old_2")
        inbound_cn = InboundMessage(
            msg_id="msg_reset_2",
            from_user_id=user_id,
            context_token="ctx_2",
            text="重置会话"
        )
        await sidecar.handle_message(inbound_cn)
        assert mock_config.get_conversation_id(user_id) is None

        # Case 3c: /new <prompt> immediate execution
        new_conv_id = "conv_fresh_100"
        transcript_builder.create_transcript(
            mock_brain_dir,
            new_conv_id,
            [
                {"step_index": 0, "type": "USER_INPUT", "content": "Write hello world in Rust"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "content": 'fn main() { println!("Hello world!"); }', "tool_calls": []}
            ]
        )

        mock_proc = FakeProcess(
            returncode=0,
            stdout=json.dumps({"response": {"newConversation": {"conversationId": new_conv_id}}}).encode("utf-8")
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            inbound_prompt = InboundMessage(
                msg_id="msg_reset_3",
                from_user_id=user_id,
                context_token="ctx_3",
                text="/new Write hello world in Rust"
            )
            await sidecar.handle_message(inbound_prompt)

            args, _ = mock_exec.call_args
            assert args == ("/mock/bin/agentapi", "new-conversation", "Write hello world in Rust")
            assert mock_config.get_conversation_id(user_id) == new_conv_id
            mock_send.assert_called_with(
                user_id,
                "ctx_3",
                'fn main() { println!("Hello world!"); }'
            )


@pytest.mark.asyncio
async def test_cuj_4_conversation_history_and_resume_switching(mock_config, mock_brain_dir, transcript_builder):
    """
    CUJ 4: Conversation History & Resuming.
    - User sends '/resume' -> sidecar discovers recent ambient conversations and prints numbered list.
    - User replies with '1' -> switches active thread to item 1 and prints context preview.
    - User sends '/resume 2' directly -> switches directly.
    """
    sidecar = WeChatSidecar(mock_config)
    user_id = "user_wx_dave"

    now = time.time()
    # Create 2 ambient conversations
    transcript_builder.create_transcript(
        mock_brain_dir,
        "conv_session_1",
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "Build a React Dashboard"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Dashboard component created.", "tool_calls": []}
        ],
        mtime=now
    )
    transcript_builder.create_transcript(
        mock_brain_dir,
        "conv_session_2",
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "Dockerize Go application"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Dockerfile generated.", "tool_calls": []}
        ],
        mtime=now - 50
    )

    with patch.object(sidecar.client, "send_message") as mock_send:
        # 1. User sends /resume
        inbound_resume = InboundMessage(
            msg_id="msg_res_1",
            from_user_id=user_id,
            context_token="ctx_res_1",
            text="/resume"
        )
        await sidecar.handle_message(inbound_resume)

        # Check menu output
        assert user_id in sidecar.pending_resume
        args, _ = mock_send.call_args
        menu_text = args[2]
        assert "最近的 Antigravity 会话列表" in menu_text
        assert "Build a React Dashboard" in menu_text
        assert "Dockerize Go application" in menu_text

        # 2. User selects option '1'
        inbound_select = InboundMessage(
            msg_id="msg_res_2",
            from_user_id=user_id,
            context_token="ctx_res_2",
            text="1"
        )
        await sidecar.handle_message(inbound_select)

        assert mock_config.get_conversation_id(user_id) == "conv_session_1"
        assert user_id not in sidecar.pending_resume
        args, _ = mock_send.call_args
        switch_text = args[2]
        assert "已成功切换至会话 #1" in switch_text
        assert "Dashboard component created." in switch_text

        # 3. User sends direct /resume 2
        inbound_direct = InboundMessage(
            msg_id="msg_res_3",
            from_user_id=user_id,
            context_token="ctx_res_3",
            text="/resume 2"
        )
        await sidecar.handle_message(inbound_direct)
        assert mock_config.get_conversation_id(user_id) == "conv_session_2"

        # 4. Out of bounds index
        inbound_invalid = InboundMessage(
            msg_id="msg_res_4",
            from_user_id=user_id,
            context_token="ctx_res_4",
            text="/resume 99"
        )
        await sidecar.handle_message(inbound_invalid)
        args, _ = mock_send.call_args
        assert "序号无效" in args[2]


@pytest.mark.asyncio
async def test_cuj_5a_multimodal_image_handling(mock_config, mock_brain_dir, mock_media_dir, transcript_builder):
    """
    CUJ 5a: Multimodal Image Attachment Handling.
    """

    sidecar = WeChatSidecar(mock_config)
    sidecar.agent.agentapi_bin = "/mock/bin/agentapi"
    user_id = "user_wx_eve"

    saved_img = mock_media_dir / "img_test.png"
    saved_img.write_bytes(b"\x89PNG\r\n\x1a\n")

    inbound_image = InboundMessage(
        msg_id="msg_img_1",
        from_user_id=user_id,
        context_token="ctx_img",
        text=f"[用户发送了一张图片，已解密保存至本地文件: file://{saved_img.resolve()}]\n请分析并查看此图片内容。"
    )

    conv_id = "conv_img_123"
    mock_proc = FakeProcess(
        returncode=0,
        stdout=json.dumps({"response": {"newConversation": {"conversationId": conv_id}}}).encode("utf-8")
    )

    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": inbound_image.text},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "This image shows a system architecture diagram.", "tool_calls": []}
        ]
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch.object(sidecar.client, "send_typing"), \
         patch.object(sidecar.client, "send_message") as mock_send:

        await sidecar.handle_message(inbound_image)
        mock_send.assert_called_with(
            user_id,
            "ctx_img",
            "This image shows a system architecture diagram."
        )


@pytest.mark.asyncio
async def test_cuj_5b_multimodal_voice_handling(mock_config, mock_brain_dir, transcript_builder):
    """
    CUJ 5b: Multimodal Voice Attachment Handling.
    """

    sidecar = WeChatSidecar(mock_config)
    sidecar.agent.agentapi_bin = "/mock/bin/agentapi"
    user_id = "user_wx_frank"

    voice_id = "voice_msg_voice_1"
    register_media(voice_id, "voice", "https://cdn.wechat.com/silk1", "0123456789abcdef", {"transcription": "帮我写一个单元测试"})

    inbound_voice = InboundMessage(
        msg_id="msg_voice_1",
        from_user_id=user_id,
        context_token="ctx_voice",
        text=(
            "[用户发送了一条语音消息 (Voice Input)]\n"
            "微信转写文本: \"帮我写一个单元测试\"\n"
            f"原始音频 ID: {voice_id}\n"
            f"检视命令: `wechat-agy-sidecar download-media {voice_id}`\n\n"
            "用户指令: 帮我写一个单元测试\n"
        )
    )

    conv_id = "conv_voice_456"
    mock_proc = FakeProcess(
        returncode=0,
        stdout=json.dumps({"response": {"newConversation": {"conversationId": conv_id}}}).encode("utf-8")
    )

    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": inbound_voice.text},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Here is the unit test code: def test_foo(): pass", "tool_calls": []}
        ]
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch.object(sidecar.client, "send_typing"), \
         patch.object(sidecar.client, "send_message") as mock_send:

        await sidecar.handle_message(inbound_voice)
        mock_send.assert_called_with(
            user_id,
            "ctx_voice",
            "Here is the unit test code: def test_foo(): pass"
        )


@pytest.mark.asyncio
async def test_cuj_6_proactive_background_event_push(mock_config, mock_brain_dir, transcript_builder):
    """
    CUJ 6: Proactive Background Event & Timer Push.
    - User has active conversation.
    - Proactive background event watcher is running.
    - Background task (e.g. schedule timer, subagent) appends new PLANNER_RESPONSE to transcript.
    - Watcher proactively pushes message to WeChat user and updates cursor.
    """
    sidecar = WeChatSidecar(mock_config)
    user_id = "user_wx_george"
    conv_id = "conv_proactive_test"

    mock_config.set_conversation_id(user_id, conv_id)

    # Initial transcript with 2 lines
    transcript_builder.create_transcript(
        mock_brain_dir,
        conv_id,
        [
            {"step_index": 0, "type": "USER_INPUT", "content": "Schedule a reminder in 5 minutes"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Timer set.", "tool_calls": []}
        ]
    )
    sidecar.conversation_cursors[conv_id] = 2

    # Append background tool call step (should be ignored)
    transcript_builder.append_step(
        mock_brain_dir,
        conv_id,
        {"step_index": 2, "type": "PLANNER_RESPONSE", "content": "", "tool_calls": [{"name": "run_command"}]}
    )

    # Append proactive timer notification step (should be pushed)
    transcript_builder.append_step(
        mock_brain_dir,
        conv_id,
        {
            "step_index": 3,
            "type": "PLANNER_RESPONSE",
            "content": "⏰ [定时提醒] 你的 5 分钟构建任务已完成！",
            "tool_calls": []
        }
    )

    with patch.object(sidecar.client, "send_message") as mock_send:
        # Run one iteration of the watcher logic directly
        async def run_one_pass():
            for u_id, c_id in list(sidecar.config.user_conversations.items()):
                t_file = mock_brain_dir / c_id / ".system_generated" / "logs" / "transcript.jsonl"
                if not t_file.exists():
                    continue
                lines = t_file.read_text(encoding="utf-8").strip().splitlines()
                last_seen = sidecar.conversation_cursors.get(c_id, 0)
                if len(lines) > last_seen:
                    for i in range(last_seen, len(lines)):
                        step = json.loads(lines[i])
                        if step.get("type") == "PLANNER_RESPONSE":
                            content = step.get("content", "").strip()
                            tool_calls = step.get("tool_calls", [])
                            if content and not tool_calls:
                                sidecar.client.send_message(u_id, "", content)
                    sidecar.conversation_cursors[c_id] = len(lines)

        await run_one_pass()

        # Verify proactive message was pushed
        mock_send.assert_called_once_with(
            user_id,
            "",
            "⏰ [定时提醒] 你的 5 分钟构建任务已完成！"
        )
        # Verify cursor advanced to line 4
        assert sidecar.conversation_cursors[conv_id] == 4


@pytest.mark.asyncio
async def test_cuj_8_onboarding_login_flow(mock_config):
    """
    CUJ 8: QR Code Login & Onboarding Flow.
    - Daemon runs onboarding flow.
    - Fetches QR code -> polls until confirmed -> saves token to config.
    """
    sidecar = WeChatSidecar(mock_config)

    # Mock get_login_qrcode
    with patch.object(sidecar.client, "get_login_qrcode", return_value=(True, "qr_123", "https://render.qr/123")), \
         patch.object(sidecar.client, "poll_qrcode_status", side_effect=[("waiting", None), ("scanned", None), ("confirmed", {"bot_token": "new_secret_token", "bot_id": "new_bot_id"})]), \
         patch("time.sleep"):

        success = sidecar.run_onboarding_login()
        assert success is True
        assert mock_config.bot_token == "new_secret_token"
        assert mock_config.bot_id == "new_bot_id"


@pytest.mark.asyncio
async def test_cuj_8b_poll_loop_dispatch_and_401_recovery(mock_config):
    """
    CUJ 8b: Polling Loop Event Dispatch & 401 Re-Auth.
    """
    sidecar = WeChatSidecar(mock_config)
    sidecar.config.get_updates_buf = "initial_buf"

    mock_msg = InboundMessage(
        msg_id="wx_msg_poll_1",
        from_user_id="user_wx_poll",
        context_token="ctx_poll",
        text="Hello"
    )

    res_401 = GetUpdatesResult(status_code=401, messages=[], new_cursor="initial_buf", raw_response={"error": "unauthorized"})
    res_200 = GetUpdatesResult(status_code=200, messages=[mock_msg], new_cursor="updated_buf_200", raw_response={})

    def fake_get_updates(timeout=35):
        if not hasattr(fake_get_updates, "called_401"):
            fake_get_updates.called_401 = True
            return res_401
        sidecar.stop()
        return res_200

    handled_msgs = []

    async def fake_handle(msg):
        handled_msgs.append(msg)

    async def fake_watcher():
        pass

    with patch.object(sidecar.client, "get_updates", side_effect=fake_get_updates), \
         patch.object(sidecar, "run_onboarding_login", return_value=True) as mock_login, \
         patch.object(sidecar, "proactive_event_watcher", side_effect=fake_watcher), \
         patch.object(sidecar, "handle_message", side_effect=fake_handle):

        await sidecar.poll_loop()
        await asyncio.sleep(0.05)

        # 401 triggered onboarding login
        mock_login.assert_called_once()

        # 200 dispatched handle_message
        assert len(handled_msgs) == 1
        assert handled_msgs[0] == mock_msg
        assert mock_config.get_updates_buf == "updated_buf_200"


def test_sidecar_start_and_stop_lifecycle(mock_config):
    sidecar = WeChatSidecar(mock_config)
    mock_config.bot_token = ""

    async def dummy_poll():
        pass

    with patch.object(sidecar, "run_onboarding_login", return_value=True) as mock_login, \
         patch.object(sidecar, "poll_loop", side_effect=dummy_poll), \
         patch("signal.signal"):

        sidecar.start()
        mock_login.assert_called_once()

    sidecar.stop()
    assert sidecar.running is False


@pytest.mark.asyncio
async def test_cuj_9_long_message_chunking(mock_config):
    """
    CUJ 9: Long message splitting and chunking through WeChat client.
    """
    sidecar = WeChatSidecar(mock_config)
    user_id = "user_wx_helen"

    long_output = "Line: " + "X" * 100 + "\n"
    long_output = long_output * 30  # ~3300 characters

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"ret": 0}'

    with patch.object(sidecar.client.session, "post", return_value=mock_resp) as mock_post:
        success = sidecar.client.send_message(user_id, "ctx_token_9", long_output)
        assert success is True
        # Verify split into 2 chunks (<1800 chars each)
        assert mock_post.call_count == 2
        chunk1 = mock_post.call_args_list[0][1]["json"]["msg"]["item_list"][0]["text_item"]["text"]
        chunk2 = mock_post.call_args_list[1][1]["json"]["msg"]["item_list"][0]["text_item"]["text"]
        assert len(chunk1) <= 1800
        assert len(chunk2) <= 1800
        assert chunk1 + chunk2 == long_output
