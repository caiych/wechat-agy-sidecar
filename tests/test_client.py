"""
Unit tests for WeChat iLink Client protocol, endpoint interactions, and payload handling.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.mocks.mock_ilink import (
    MockIlinkAdapter,
    create_file_message,
    create_text_message,
    create_video_message,
    create_voice_message,
)
from wechat_agy_sidecar.client import TerminalQR, WeChatIlinkClient
from wechat_agy_sidecar.config import SidecarConfig


class TestWeChatIlinkClient(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config = SidecarConfig.load(self.config_path)
        self.config.bot_token = "test_bot_token"
        self.config.bot_id = "test_bot_id"
        self.client = WeChatIlinkClient(self.config)

        self.mock_adapter = MockIlinkAdapter(self.config.ilink_base_url)
        self.client.session.mount("https://", self.mock_adapter)
        self.client.session.mount("http://", self.mock_adapter)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_login_qrcode_success(self):
        self.mock_adapter.qrcode_id = "qr_12345"
        self.mock_adapter.qrcode_url = "https://ilinkai.weixin.qq.com/qr/12345"
        ok, qrcode_id, qrcode_url = self.client.get_login_qrcode()
        self.assertTrue(ok)
        self.assertEqual(qrcode_id, "qr_12345")
        self.assertEqual(qrcode_url, "https://ilinkai.weixin.qq.com/qr/12345")

    def test_poll_qrcode_status_transitions(self):
        self.mock_adapter.qrcode_status_sequence = [
            ("waiting", {}),
            ("scanned", {}),
            ("confirmed", {"bot_token": "new_token_789", "bot_id": "bot_456"}),
        ]
        self.mock_adapter.qrcode_status_index = 0

        st1, _ = self.client.poll_qrcode_status("qr_12345")
        self.assertEqual(st1, "waiting")

        st2, _ = self.client.poll_qrcode_status("qr_12345")
        self.assertEqual(st2, "scanned")

        st3, data3 = self.client.poll_qrcode_status("qr_12345")
        self.assertEqual(st3, "confirmed")
        self.assertEqual(data3.get("bot_token"), "new_token_789")

    def test_get_updates_text_message(self):
        msg = create_text_message("msg_001", "wx_user_a", "Hello Antigravity", "ctx_001")
        self.mock_adapter.queue_update([msg], next_cursor="cursor_002")

        res = self.client.get_updates(timeout=5)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.new_cursor, "cursor_002")
        self.assertEqual(len(res.messages), 1)
        self.assertEqual(res.messages[0].msg_id, "msg_001")
        self.assertEqual(res.messages[0].from_user_id, "wx_user_a")
        self.assertEqual(res.messages[0].text, "Hello Antigravity")
        self.assertEqual(res.messages[0].context_token, "ctx_001")

    def test_get_updates_multimedia_messages(self):
        # File and Video items
        file_msg = create_file_message("msg_002", "wx_user_b", "report.pdf")
        video_msg = create_video_message("msg_003", "wx_user_c")
        self.mock_adapter.queue_update([file_msg, video_msg], next_cursor="cursor_003")

        res = self.client.get_updates(timeout=5)
        self.assertEqual(len(res.messages), 2)
        self.assertIn("report.pdf", res.messages[0].text)
        self.assertIn("视频", res.messages[1].text)

    def test_get_updates_voice_message_with_registry(self):
        voice_msg = create_voice_message(
            msg_id="msg_004",
            from_user_id="wx_user_d",
            transcription="请帮我写一段Python代码",
            cdn_url="https://wx.qq.com/voice/download/123",
            aes_key="abcdef0123456789abcdef0123456789",
        )
        self.mock_adapter.queue_update([voice_msg], next_cursor="cursor_004")

        res = self.client.get_updates(timeout=5)
        self.assertEqual(len(res.messages), 1)
        inbound = res.messages[0]
        self.assertIn("语音消息", inbound.text)
        self.assertIn("请帮我写一段Python代码", inbound.text)
        self.assertIn("wechat-agy-sidecar download-media", inbound.text)

    def test_send_typing(self):
        self.client.send_typing("wx_user_a", typing=True)
        self.assertEqual(len(self.mock_adapter.sent_typing), 1)
        self.assertEqual(self.mock_adapter.sent_typing[0]["to_user_id"], "wx_user_a")
        self.assertTrue(self.mock_adapter.sent_typing[0]["typing"])

    def test_send_message_short(self):
        ok = self.client.send_message("wx_user_a", "ctx_001", "Antigravity response")
        self.assertTrue(ok)
        self.assertEqual(len(self.mock_adapter.sent_messages), 1)

        sent = self.mock_adapter.sent_messages[0]["msg"]
        self.assertEqual(sent["to_user_id"], "wx_user_a")
        self.assertEqual(sent["context_token"], "ctx_001")
        self.assertEqual(sent["message_type"], 2)  # BOT
        self.assertEqual(sent["message_state"], 2)  # FINISH
        self.assertTrue(sent["client_id"].startswith("msg_"))
        self.assertEqual(sent["item_list"][0]["text_item"]["text"], "Antigravity response")

    def test_send_message_chunking(self):
        long_text = "A" * 3700  # Should split into 3 chunks: 1800, 1800, 100
        ok = self.client.send_message("wx_user_a", "ctx_001", long_text)
        self.assertTrue(ok)
        self.assertEqual(len(self.mock_adapter.sent_messages), 3)
        self.assertEqual(len(self.mock_adapter.sent_messages[0]["msg"]["item_list"][0]["text_item"]["text"]), 1800)
        self.assertEqual(len(self.mock_adapter.sent_messages[1]["msg"]["item_list"][0]["text_item"]["text"]), 1800)
        self.assertEqual(len(self.mock_adapter.sent_messages[2]["msg"]["item_list"][0]["text_item"]["text"]), 100)

    def test_terminal_qr_display(self):
        # 1. Test normal execution with qrcode module
        try:
            TerminalQR.display("https://example.com/qr")
        except Exception as e:
            self.fail(f"TerminalQR.display raised exception: {e}")

        # 2. Test fallback when qrcode is not available
        with patch.dict("sys.modules", {"qrcode": None}):
            with patch("requests.get", return_value=type("Resp", (), {"status_code": 200, "text": "ASCII_ART"})()):
                with patch("builtins.print") as mock_print:
                    TerminalQR.display("https://example.com/qr")
                    self.assertTrue(mock_print.called)



if __name__ == "__main__":
    unittest.main()
