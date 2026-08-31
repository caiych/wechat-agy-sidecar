"""
Critical User Journey (CUJ) end-to-end integration and daemon tests.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from tests.mocks.mock_agentapi import MockAgentApi, MockBrainWorkspace
from tests.mocks.mock_ilink import (
    MockIlinkAdapter,
    create_image_message,
    create_voice_message,
)
from wechat_agy_sidecar import agent, media, sidecar
from wechat_agy_sidecar.cli import main as cli_main
from wechat_agy_sidecar.client import InboundMessage
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.media import lookup_media
from wechat_agy_sidecar.sidecar import WeChatSidecar


class TestCriticalUserJourneys(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.brain_dir = self.base_dir / "brain"
        self.config_file = self.base_dir / "config.json"
        self.media_dir = self.base_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # Patch directories
        self.patchers = [
            patch.object(sidecar, "BRAIN_DIR", self.brain_dir),
            patch.object(agent, "BRAIN_DIR", self.brain_dir),
            patch.object(media, "MEDIA_DIR", self.media_dir),
            patch.object(media, "MEDIA_REGISTRY_FILE", self.media_dir / "registry.json"),
        ]
        for p in self.patchers:
            p.start()

        self.workspace = MockBrainWorkspace(self.brain_dir)
        self.mock_api = MockAgentApi(self.workspace)
        self.config = SidecarConfig.load(self.config_file)
        self.config.bot_token = "valid_token"
        self.config.bot_id = "bot_test"
        self.sidecar = WeChatSidecar(self.config)
        self.sidecar.agent.agentapi_bin = "/mock/bin/agentapi"

        self.mock_ilink = MockIlinkAdapter(self.config.ilink_base_url)
        self.sidecar.client.session.mount("https://", self.mock_ilink)
        self.sidecar.client.session.mount("http://", self.mock_ilink)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # CUJ 1: Onboarding Login Flow
    # --------------------------------------------------------------------------
    def test_cuj_1_onboarding_login_flow(self):
        self.sidecar.config.bot_token = ""
        self.mock_ilink.qrcode_status_sequence = [
            ("waiting", {}),
            ("scanned", {}),
            ("confirmed", {"bot_token": "onboarded_token_999", "bot_id": "onboarded_bot_1"}),
        ]
        self.mock_ilink.qrcode_status_index = 0

        with patch("time.sleep", return_value=None):
            success = self.sidecar.run_onboarding_login()

        self.assertTrue(success)
        self.assertEqual(self.sidecar.config.bot_token, "onboarded_token_999")
        self.assertEqual(self.sidecar.config.bot_id, "onboarded_bot_1")

        # Verify persisted to disk
        reloaded = SidecarConfig.load(self.config_file)
        self.assertEqual(reloaded.bot_token, "onboarded_token_999")

    # --------------------------------------------------------------------------
    # CUJ 2: Multi-turn Chat Threading Journey
    # --------------------------------------------------------------------------
    async def test_cuj_2_multi_turn_conversation(self):
        user_id = "user_wx_alpha"
        self.mock_api.default_responses["Turn 1 Question"] = "Turn 1 Answer from AGY"
        self.mock_api.default_responses["Turn 2 Question"] = "Turn 2 Answer from AGY"

        with patch("asyncio.create_subprocess_exec", side_effect=self.mock_api.handle_exec):
            # Turn 1: User sends first question
            msg1 = InboundMessage(
                msg_id="m1",
                from_user_id=user_id,
                context_token="ctx1",
                text="Turn 1 Question"
            )
            await self.sidecar.handle_message(msg1)

            # Check that a new thread was created
            conv_id = self.sidecar.config.get_conversation_id(user_id)
            self.assertIsNotNone(conv_id)
            self.assertTrue(conv_id.startswith("mock-conv-"))

            # Check that typing indicator and reply were sent
            self.assertEqual(len(self.mock_ilink.sent_typing), 2)  # True then False
            self.assertEqual(len(self.mock_ilink.sent_messages), 1)
            self.assertEqual(
                self.mock_ilink.sent_messages[0]["msg"]["item_list"][0]["text_item"]["text"],
                "Turn 1 Answer from AGY"
            )

            # Turn 2: User follows up in the same thread
            msg2 = InboundMessage(
                msg_id="m2",
                from_user_id=user_id,
                context_token="ctx2",
                text="Turn 2 Question"
            )
            await self.sidecar.handle_message(msg2)

            # Check that the same conversation ID is retained
            self.assertEqual(self.sidecar.config.get_conversation_id(user_id), conv_id)
            self.assertEqual(len(self.mock_ilink.sent_messages), 2)
            self.assertEqual(
                self.mock_ilink.sent_messages[1]["msg"]["item_list"][0]["text_item"]["text"],
                "Turn 2 Answer from AGY"
            )

            # Check history tracking
            history = self.sidecar.config.get_recent_conversations(user_id)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["conv_id"], conv_id)

    # --------------------------------------------------------------------------
    # CUJ 3: Commands & Conversation Management (/new, /reset, /resume)
    # --------------------------------------------------------------------------
    async def test_cuj_3_commands_and_resume(self):
        user_id = "user_wx_beta"
        conv_old = self.workspace.create_conversation(
            initial_prompt="Previous topic on Golang",
            initial_response="Golang is fast.",
            mtime=time.time() - 50
        )
        self.sidecar.config.set_conversation_id(user_id, conv_old)
        self.sidecar.config.record_conversation(user_id, conv_old, "Previous topic on Golang")

        with patch("asyncio.create_subprocess_exec", side_effect=self.mock_api.handle_exec):
            # 1. Test /new (reset thread)
            await self.sidecar.handle_message(InboundMessage("cmd1", user_id, "c1", "/new"))
            self.assertIsNone(self.sidecar.config.get_conversation_id(user_id))
            self.assertIn("已开启全新的对话线程", self.mock_ilink.sent_messages[-1]["msg"]["item_list"][0]["text_item"]["text"])

            # 2. Test /new with prompt
            await self.sidecar.handle_message(InboundMessage("cmd2", user_id, "c2", "/new Explain Rust lifetimes"))
            new_conv = self.sidecar.config.get_conversation_id(user_id)
            self.assertIsNotNone(new_conv)
            self.assertNotEqual(new_conv, conv_old)
            self.assertIn("Explain Rust lifetimes", self.mock_ilink.sent_messages[-1]["msg"]["item_list"][0]["text_item"]["text"])

            # 3. Test /resume menu
            await self.sidecar.handle_message(InboundMessage("cmd3", user_id, "c3", "/resume"))
            resume_menu = self.mock_ilink.sent_messages[-1]["msg"]["item_list"][0]["text_item"]["text"]
            self.assertIn("最近的 Antigravity 会话列表", resume_menu)
            self.assertIn(user_id, self.sidecar.pending_resume)

            # 4. Select #2 from pending menu (or switch back to older conversation)
            await self.sidecar.handle_message(InboundMessage("cmd4", user_id, "c4", "2"))
            self.assertEqual(self.sidecar.config.get_conversation_id(user_id), conv_old)
            self.assertIn("已成功切换至会话", self.mock_ilink.sent_messages[-1]["msg"]["item_list"][0]["text_item"]["text"])

            # 5. Direct /resume <id>
            await self.sidecar.handle_message(InboundMessage("cmd5", user_id, "c5", f"/resume {new_conv}"))
            self.assertEqual(self.sidecar.config.get_conversation_id(user_id), new_conv)

    # --------------------------------------------------------------------------
    # CUJ 4: Multimodal Inbound Attachments (Image, Voice, File, Video)
    # --------------------------------------------------------------------------
    async def test_cuj_4_multimodal_inbound(self):
        user_id = "user_wx_gamma"
        key_16 = b"0123456789abcdef"
        key_hex = key_16.hex()

        with patch("asyncio.create_subprocess_exec", side_effect=self.mock_api.handle_exec):
            # 1. Inbound Image with CDN decryption
            img_bytes = b"\x89PNG\r\n\x1a\n" + b"sample_mock_image"
            img_url = "https://cdn.weixin.qq.com/img_cuj_1"
            self.mock_ilink.add_cdn_file(img_url, img_bytes, key_16)

            with patch("requests.get", side_effect=lambda u, timeout=25: self.mock_ilink.send(requests.Request("GET", u).prepare())):
                img_msg = create_image_message("img_1", user_id, img_url, key_hex)
                self.mock_ilink.queue_update([img_msg])
                res = self.sidecar.client.get_updates(timeout=1)
                self.assertEqual(len(res.messages), 1)

                await self.sidecar.handle_message(res.messages[0])
                inv_cmd = self.mock_api.invocations[-1]["cmd"]
                self.assertIn("用户发送了一张图片", inv_cmd[-1])
                self.assertIn("file://", inv_cmd[-1])

            # 2. Inbound Voice with Media Registry
            voice_msg = create_voice_message(
                "voice_1",
                user_id,
                transcription="帮我重构一下Python代码",
                cdn_url="https://cdn.weixin.qq.com/voice_cuj_1",
                aes_key=key_hex
            )
            self.mock_ilink.queue_update([voice_msg])
            res_v = self.sidecar.client.get_updates(timeout=1)
            await self.sidecar.handle_message(res_v.messages[0])

            # Verify registered in media registry
            reg = lookup_media("voice_voice_1")
            self.assertIsNotNone(reg)
            self.assertEqual(reg["type"], "voice")
            self.assertEqual(reg["transcription"], "帮我重构一下Python代码")

            # Check prompt passed to Antigravity
            inv_cmd_v = self.mock_api.invocations[-1]["cmd"]
            self.assertIn("wechat-agy-sidecar download-media voice_voice_1", inv_cmd_v[-1])
            self.assertIn("帮我重构一下Python代码", inv_cmd_v[-1])

    # --------------------------------------------------------------------------
    # CUJ 5: Proactive Background Event Streaming
    # --------------------------------------------------------------------------
    async def test_cuj_5_proactive_background_event_watcher(self):
        user_id = "user_wx_delta"
        conv_id = self.workspace.create_conversation(
            initial_prompt="Run a long simulation",
            initial_response="Simulation started..."
        )
        self.sidecar.config.set_conversation_id(user_id, conv_id)
        # Set cursor to initial lines
        self.sidecar.conversation_cursors[conv_id] = self.workspace._step_counters[conv_id]

        # Start proactive watcher task
        watcher_task = asyncio.create_task(self.sidecar.proactive_event_watcher())

        try:
            # Simulate a background timer / subagent writing a new response asynchronously
            await asyncio.sleep(0.1)
            self.workspace.append_planner_response(
                conv_id,
                "⏰ [Background Notification] Your simulation completed successfully! Results: 100% PASS."
            )

            # Wait briefly for watcher loop to detect and push
            await asyncio.sleep(2.5)

            # Verify message was pushed to WeChat
            pushed_msgs = [m for m in self.mock_ilink.sent_messages if "Background Notification" in m["msg"]["item_list"][0]["text_item"]["text"]]
            self.assertEqual(len(pushed_msgs), 1)
            self.assertEqual(pushed_msgs[0]["msg"]["to_user_id"], user_id)
        finally:
            self.sidecar.running = False
            watcher_task.cancel()

    # --------------------------------------------------------------------------
    # CUJ 6: Daemon 401 Expiry Auto-Recovery in Polling Loop
    # --------------------------------------------------------------------------
    async def test_cuj_6_polling_loop_401_recovery(self):
        self.mock_ilink.force_updates_status_code = 401
        self.mock_ilink.qrcode_status_sequence = [
            ("confirmed", {"bot_token": "refreshed_token_555", "bot_id": "bot_test"})
        ]
        self.mock_ilink.qrcode_status_index = 0

        # We test that get_updates returns 401, run_onboarding_login is invoked and refreshes token
        res = self.sidecar.client.get_updates(timeout=1)
        self.assertEqual(res.status_code, 401)

        with patch("time.sleep", return_value=None):
            ok = self.sidecar.run_onboarding_login()
            self.assertTrue(ok)
            self.assertEqual(self.sidecar.config.bot_token, "refreshed_token_555")

    # --------------------------------------------------------------------------
    # CUJ 7: CLI Subcommands Execution
    # --------------------------------------------------------------------------
    def test_cuj_7_cli_download_media_and_options(self):
        key_16 = b"0123456789abcdef"
        key_hex = key_16.hex()
        raw_silk = b"#!SILK_V3" + b"audio_content_test"
        cdn_url = "https://cdn.weixin.qq.com/voice_test_cli"
        self.mock_ilink.add_cdn_file(cdn_url, raw_silk, key_16)

        # Register in media registry
        media.register_media("voice_cli_test", "voice", cdn_url, key_hex, {"transcription": "CLI测试语音"})

        with patch("requests.get", side_effect=lambda u, timeout=25: self.mock_ilink.send(requests.Request("GET", u).prepare())):
            # 1. Download via registry ID
            with patch("sys.argv", ["wechat-agy-sidecar", "download-media", "voice_cli_test"]):
                with self.assertRaises(SystemExit) as cm:
                    cli_main()
                self.assertEqual(cm.exception.code, 0)

            # 2. Download via direct URL + key
            with patch("sys.argv", ["wechat-agy-sidecar", "download-media", "--url", cdn_url, "--key", key_hex]):
                with self.assertRaises(SystemExit) as cm:
                    cli_main()
                self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
