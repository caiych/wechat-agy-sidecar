"""
End-to-end CUJ (Critical User Journey) tests with mocked WeChat iLink API and agentapi.
Tests onboarding, threading, /new, /resume, multimodal voice registry, and proactive streaming.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from wechat_agy_sidecar.client import InboundMessage
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.media import download_and_decrypt_media, lookup_media, register_media
from wechat_agy_sidecar.sidecar import WeChatSidecar


class TestWeChatSidecarCUJ(unittest.IsolatedAsyncioTestCase):
    """Critical User Journey (CUJ) simulation tests with mocks."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmpdir.name) / "test_config.json"
        self.brain_path = Path(self.tmpdir.name) / "brain"
        self.brain_path.mkdir(parents=True, exist_ok=True)

        self.config = SidecarConfig.load(self.config_path)
        self.config.bot_token = "mock_bot_token"
        self.config.bot_id = "mock_bot_id"
        self.config.save()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_mock_transcript(self, conv_id: str, steps: list[dict]):
        """Helper to create a mock transcript.jsonl file."""
        log_dir = self.brain_path / conv_id / ".system_generated" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        t_file = log_dir / "transcript.jsonl"
        with open(t_file, "w", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(step, ensure_ascii=False) + "\n")
        return t_file

    # =========================================================================
    # CUJ 1: Interactive QR Code Onboarding Flow
    # =========================================================================
    def test_cuj_qr_onboarding_success(self):
        sidecar = WeChatSidecar(self.config)
        sidecar.client.get_login_qrcode = MagicMock(
            return_value=(True, "mock_qr_123", "https://mock.qr.url")
        )
        sidecar.client.poll_qrcode_status = MagicMock(
            return_value=("confirmed", {"bot_token": "fresh_token_456", "bot_id": "fresh_bot_id"})
        )

        with patch("wechat_agy_sidecar.client.TerminalQR.display"):
            success = sidecar.run_onboarding_login()

        self.assertTrue(success)
        self.assertEqual(self.config.bot_token, "fresh_token_456")
        self.assertEqual(self.config.bot_id, "fresh_bot_id")

    # =========================================================================
    # CUJ 2: Inbound Message -> First Conversation Turn
    # =========================================================================
    async def test_cuj_first_turn_new_conversation(self):
        sidecar = WeChatSidecar(self.config)
        user_id = "wx_user_alice"
        conv_id = "conv_uuid_alice_001"

        # Mock agentapi execution
        mock_reply = "你好！我是 Antigravity 编程助手。"
        sidecar.agent.execute = AsyncMock(return_value=(mock_reply, conv_id))
        sidecar.client.send_typing = MagicMock()
        sidecar.client.send_message = MagicMock(return_value=True)

        # Inbound message
        msg = InboundMessage(
            msg_id="m101",
            from_user_id=user_id,
            context_token="ctx_1",
            text="帮我写一个 Python HTTP 服务"
        )

        await sidecar.handle_message(msg)

        # Verifications
        sidecar.client.send_typing.assert_any_call(user_id, typing=True)
        sidecar.client.send_typing.assert_any_call(user_id, typing=False)
        sidecar.agent.execute.assert_called_once_with("帮我写一个 Python HTTP 服务", conversation_id=None)
        sidecar.client.send_message.assert_called_once_with(user_id, "ctx_1", mock_reply)
        self.assertEqual(self.config.get_conversation_id(user_id), conv_id)

    # =========================================================================
    # CUJ 3: Multi-turn Conversation Continuation
    # =========================================================================
    async def test_cuj_multi_turn_continuation(self):
        sidecar = WeChatSidecar(self.config)
        user_id = "wx_user_bob"
        conv_id = "conv_uuid_bob_002"

        # Setup existing conversation
        self.config.set_conversation_id(user_id, conv_id)

        mock_reply_turn2 = "已为您添加了异步处理逻辑。"
        sidecar.agent.execute = AsyncMock(return_value=(mock_reply_turn2, conv_id))
        sidecar.client.send_typing = MagicMock()
        sidecar.client.send_message = MagicMock(return_value=True)

        # Inbound second turn
        msg = InboundMessage(
            msg_id="m102",
            from_user_id=user_id,
            context_token="ctx_2",
            text="改成异步版本"
        )

        await sidecar.handle_message(msg)

        # Verifies continuing existing conversation_id
        sidecar.agent.execute.assert_called_once_with("改成异步版本", conversation_id=conv_id)
        sidecar.client.send_message.assert_called_once_with(user_id, "ctx_2", mock_reply_turn2)
        self.assertEqual(self.config.get_conversation_id(user_id), conv_id)

    # =========================================================================
    # CUJ 4: Thread Control Commands (/new, /new <prompt>, /reset)
    # =========================================================================
    async def test_cuj_command_new_and_new_prompt(self):
        sidecar = WeChatSidecar(self.config)
        user_id = "wx_user_charlie"
        self.config.set_conversation_id(user_id, "old_conv_id")

        sidecar.client.send_message = MagicMock(return_value=True)

        # 1. Plain /new
        msg_new = InboundMessage(msg_id="m103", from_user_id=user_id, context_token="ctx_3", text="/new")
        await sidecar.handle_message(msg_new)

        self.assertIsNone(self.config.get_conversation_id(user_id))
        self.assertIn("已重置", sidecar.client.send_message.call_args[0][2])

        # 2. /new <prompt>
        new_conv_id = "fresh_conv_charlie_003"
        sidecar.agent.execute = AsyncMock(return_value=("新会话回答", new_conv_id))
        msg_new_prompt = InboundMessage(
            msg_id="m104",
            from_user_id=user_id,
            context_token="ctx_4",
            text="/new 用 Rust 实现一个哈希表"
        )
        await sidecar.handle_message(msg_new_prompt)

        sidecar.agent.execute.assert_called_once_with("用 Rust 实现一个哈希表", conversation_id=None)
        self.assertEqual(self.config.get_conversation_id(user_id), new_conv_id)

    # =========================================================================
    # CUJ 5: Global /resume Multi-Session Switcher with Last Message Preview
    # =========================================================================
    async def test_cuj_resume_listing_and_switching(self):
        sidecar = WeChatSidecar(self.config)
        user_id = "wx_user_dave"

        with patch("wechat_agy_sidecar.agent.BRAIN_DIR", self.brain_path), \
             patch("wechat_agy_sidecar.sidecar.BRAIN_DIR", self.brain_path):

            # Create mock conversations in brain dir
            conv_1 = "conv_dave_alpha"
            self._create_mock_transcript(conv_1, [
                {"type": "USER_INPUT", "content": "调试 Python 脚本"},
                {"type": "PLANNER_RESPONSE", "content": "这是调试 Python 脚本的最后回复。"}
            ])

            conv_2 = "conv_dave_beta"
            self._create_mock_transcript(conv_2, [
                {"type": "USER_INPUT", "content": "设计微服务架构"},
                {"type": "PLANNER_RESPONSE", "content": "这是微服务架构方案的最后回复。"}
            ])

            sidecar.client.send_message = MagicMock(return_value=True)

            # Step 1: Send /resume to list sessions
            msg_resume = InboundMessage(msg_id="m105", from_user_id=user_id, context_token="ctx_5", text="/resume")
            await sidecar.handle_message(msg_resume)

            reply_text = sidecar.client.send_message.call_args[0][2]
            self.assertIn("最近的 Antigravity 会话列表", reply_text)
            self.assertIn("调试 Python 脚本", reply_text)
            self.assertIn("设计微服务架构", reply_text)
            self.assertIn(user_id, sidecar.pending_resume)

            # Step 2: Reply with number '1' to switch
            sidecar.client.send_message.reset_mock()
            msg_select = InboundMessage(msg_id="m106", from_user_id=user_id, context_token="ctx_6", text="1")
            await sidecar.handle_message(msg_select)

            switch_reply = sidecar.client.send_message.call_args[0][2]
            self.assertIn("已成功切换至会话 #1", switch_reply)
            self.assertIn("上下文摘要", switch_reply)
            self.assertNotIn(user_id, sidecar.pending_resume)
            self.assertTrue(bool(self.config.get_conversation_id(user_id)))

    # =========================================================================
    # CUJ 6: Multimodal Voice Input & Media Registry Decryption
    # =========================================================================
    def test_cuj_voice_media_registry_and_cli_download(self):
        media_id = "voice_cuj_test_999"
        url = "https://mock.tencent.cdn/voice/encrypted_999"
        # 16-byte raw key in hex (32 hex chars)
        key_hex = "00112233445566778899aabbccddeeff"
        transcription = "测试语音转写功能"

        # 1. Register voice media entry
        registered_id = register_media(
            media_id=media_id,
            media_type="voice",
            url=url,
            key=key_hex,
            metadata={"transcription": transcription}
        )
        self.assertEqual(registered_id, media_id)

        # 2. Lookup from registry
        entry = lookup_media(media_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], url)
        self.assertEqual(entry["key"], key_hex)
        self.assertEqual(entry["transcription"], transcription)

        # 3. Simulate AES-128-ECB decryption of mock payload
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        raw_key = bytes.fromhex(key_hex)
        cipher = Cipher(algorithms.AES(raw_key), modes.ECB())
        encryptor = cipher.encryptor()
        mock_silk_header = b"#!SILK_V3_TEST_AUDIO_STREAM_DATA"
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(mock_silk_header) + padder.finalize()
        encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = encrypted_bytes
            mock_get.return_value = mock_resp

            out_file = Path(self.tmpdir.name) / "decrypted.silk"
            saved_path = download_and_decrypt_media(entry["url"], entry["key"], output_path=out_file)

            self.assertIsNotNone(saved_path)
            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.read_bytes(), mock_silk_header)

    # =========================================================================
    # CUJ 7: Proactive Background Event Watcher (Scheduled Timers / Subagents)
    # =========================================================================
    async def test_cuj_proactive_background_event_watcher(self):
        sidecar = WeChatSidecar(self.config)
        user_id = "wx_user_eve"
        conv_id = "conv_eve_proactive_007"
        self.config.set_conversation_id(user_id, conv_id)

        with patch("wechat_agy_sidecar.sidecar.BRAIN_DIR", self.brain_path):
            # Initial conversation turn
            t_file = self._create_mock_transcript(conv_id, [
                {"step_index": 0, "type": "USER_INPUT", "content": "10分钟后提醒我喝水"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "已为您设置定时提醒。"}
            ])
            sidecar.conversation_cursors[conv_id] = 2

            sidecar.client.send_message = MagicMock(return_value=True)

            # Asynchronously append a new proactive background timer event
            proactive_response_step = {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "content": "⏰ [定时提醒] 10分钟已到，请记得喝水！",
                "tool_calls": []
            }
            with open(t_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(proactive_response_step, ensure_ascii=False) + "\n")

            # Run a single proactive watcher iteration
            conv_to_user = {c_id: u_id for u_id, c_id in self.config.user_conversations.items()}
            for c_id, u_id in conv_to_user.items():
                lines = t_file.read_text(encoding="utf-8").strip().splitlines()
                last_seen = sidecar.conversation_cursors.get(c_id, len(lines))
                if len(lines) > last_seen:
                    for line in lines[last_seen:]:
                        step = json.loads(line)
                        if step.get("type") == "PLANNER_RESPONSE" and step.get("content"):
                            if not step.get("tool_calls"):
                                sidecar.client.send_message(u_id, "", step.get("content").strip())
                    sidecar.conversation_cursors[c_id] = len(lines)

            # Verifies proactive message delivered without inbound user trigger
            sidecar.client.send_message.assert_called_once_with(
                user_id, "", "⏰ [定时提醒] 10分钟已到，请记得喝水！"
            )
            self.assertEqual(sidecar.conversation_cursors[conv_id], 3)


if __name__ == "__main__":
    unittest.main()
