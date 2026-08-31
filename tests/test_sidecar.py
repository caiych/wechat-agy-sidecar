"""
Unit tests for WeChat Antigravity Sidecar configuration, client protocol, and threading.
"""

import unittest
import tempfile
from pathlib import Path
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.client import InboundMessage, GetUpdatesResult


class TestWeChatSidecar(unittest.TestCase):
    def test_config_load_and_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "test_config.json"
            cfg = SidecarConfig.load(cfg_file)
            cfg.bot_token = "test_token_123"
            cfg.bot_id = "test_bot"
            cfg.save()

            loaded = SidecarConfig.load(cfg_file)
            self.assertEqual(loaded.bot_token, "test_token_123")
            self.assertEqual(loaded.bot_id, "test_bot")
            self.assertTrue(bool(loaded.uin))
            self.assertTrue(len(loaded.system_instructions) > 0)
            self.assertIn("Authorization", loaded.get_auth_headers())
            self.assertEqual(loaded.get_auth_headers()["AuthorizationType"], "ilink_bot_token")

    def test_conversation_threading_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "test_config.json"
            cfg = SidecarConfig.load(cfg_file)
            
            user_a = "user_wx_1"
            conv_id_1 = "conv-uuid-12345"
            cfg.set_conversation_id(user_a, conv_id_1)
            self.assertEqual(cfg.get_conversation_id(user_a), conv_id_1)

            # Reload from disk
            loaded = SidecarConfig.load(cfg_file)
            self.assertEqual(loaded.get_conversation_id(user_a), conv_id_1)

            # Reset conversation
            cfg.reset_conversation(user_a)
            self.assertIsNone(cfg.get_conversation_id(user_a))

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
