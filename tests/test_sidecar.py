"""
Unit tests for WeChat Antigravity Sidecar configuration, client protocol, media registry, and threading.
"""

import unittest
import tempfile
from pathlib import Path
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.client import InboundMessage
from wechat_agy_sidecar.media import register_media, lookup_media, MEDIA_DIR


class TestWeChatSidecar(unittest.TestCase):
    def test_config_load_and_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "test_config.json"
            cfg = SidecarConfig.load(cfg_file)
            cfg.bot_token = "test_token_123"
            cfg.bot_id = "test_bot"
            cfg.project_id = "my-test-project"
            cfg.save()

            loaded = SidecarConfig.load(cfg_file)
            self.assertEqual(loaded.bot_token, "test_token_123")
            self.assertEqual(loaded.bot_id, "test_bot")
            self.assertEqual(loaded.project_id, "my-test-project")
            self.assertTrue(bool(loaded.uin))
            self.assertTrue(len(loaded.system_instructions) > 0)
            self.assertIn("Authorization", loaded.get_auth_headers())
            self.assertEqual(loaded.get_auth_headers()["AuthorizationType"], "ilink_bot_token")

    def test_conversation_threading_and_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "test_config.json"
            cfg = SidecarConfig.load(cfg_file)
            
            user_a = "user_wx_1"
            conv_id_1 = "conv-uuid-12345"
            cfg.set_conversation_id(user_a, conv_id_1)
            cfg.record_conversation(user_a, conv_id_1, "Go HTTP Client")
            self.assertEqual(cfg.get_conversation_id(user_a), conv_id_1)

            # Record a second conversation
            conv_id_2 = "conv-uuid-67890"
            cfg.set_conversation_id(user_a, conv_id_2)
            cfg.record_conversation(user_a, conv_id_2, "Refactor Python sidecar")

            # Reload from disk
            loaded = SidecarConfig.load(cfg_file)
            self.assertEqual(loaded.get_conversation_id(user_a), conv_id_2)

            recent = loaded.get_recent_conversations(user_a, n=5)
            self.assertEqual(len(recent), 2)
            self.assertEqual(recent[0]["conv_id"], conv_id_2)
            self.assertEqual(recent[0]["title"], "Refactor Python sidecar")
            self.assertEqual(recent[1]["conv_id"], conv_id_1)
            self.assertEqual(recent[1]["title"], "Go HTTP Client")

            # Reset conversation
            cfg.reset_conversation(user_a)
            self.assertIsNone(cfg.get_conversation_id(user_a))

    def test_media_registry(self):
        media_id = "voice_test_123456"
        register_media(
            media_id=media_id,
            media_type="voice",
            url="https://wx.qq.com/media/download?id=123",
            key="abcdef0123456789abcdef0123456789",
            metadata={"transcription": "测试微信转写"}
        )

        entry = lookup_media(media_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["type"], "voice")
        self.assertEqual(entry["transcription"], "测试微信转写")
        self.assertEqual(entry["key"], "abcdef0123456789abcdef0123456789")

    def test_inbound_message_dataclass(self):
        msg = InboundMessage(
            msg_id="1001",
            from_user_id="wx_user_1",
            context_token="ctx_token_abc",
            text="Hello Antigravity"
        )
        self.assertEqual(msg.from_user_id, "wx_user_1")
        self.assertEqual(msg.text, "Hello Antigravity")


if __name__ == "__main__":
    unittest.main()
