"""
Unit tests for WeChat Antigravity Sidecar configuration and client protocol.
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
            self.assertIn("Authorization", loaded.get_auth_headers())
            self.assertEqual(loaded.get_auth_headers()["AuthorizationType"], "ilink_bot_token")

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
