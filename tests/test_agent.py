"""
Unit tests for AntigravityAgent execution bridge, transcript parsing, and brain workspace integration.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.mocks.mock_agentapi import MockAgentApi, MockBrainWorkspace
from wechat_agy_sidecar import agent
from wechat_agy_sidecar.agent import AntigravityAgent
from wechat_agy_sidecar.config import SidecarConfig


class TestAntigravityAgent(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self.temp_dir.name) / "brain"
        self.workspace = MockBrainWorkspace(self.brain_dir)
        self.patcher = patch.object(agent, "BRAIN_DIR", self.brain_dir)
        self.patcher.start()

        self.config = SidecarConfig()
        self.config.project_id = "test-project-123"
        self.agent = AntigravityAgent(self.config)
        self.agent.agentapi_bin = "/mock/bin/agentapi"
        self.mock_api = MockAgentApi(self.workspace)

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_find_agentapi_binary(self):
        with patch("shutil.which", return_value="/usr/local/bin/agentapi"), \
             patch("os.path.isfile", return_value=True), \
             patch("os.access", return_value=True):
            found = self.agent._find_agentapi_binary()
            self.assertEqual(found, "/usr/local/bin/agentapi")

    def test_extract_conversation_title(self):
        conv_id = self.workspace.create_conversation(
            initial_prompt="<system>wrapper</system>Write a fast HTTP server in Go"
        )
        title = self.agent.extract_conversation_title(conv_id)
        self.assertEqual(title, "Write a fast HTTP server in Go")

    def test_extract_last_message_preview(self):
        conv_id = self.workspace.create_conversation(
            initial_prompt="What is the capital of France?",
            initial_response="The capital of France is Paris."
        )
        preview = self.agent.extract_last_message_preview(conv_id)
        self.assertIn("🤖 AI:", preview)
        self.assertIn("Paris", preview)

    def test_list_all_recent_conversations(self):
        now = time.time()
        c1 = self.workspace.create_conversation(
            initial_prompt="Conversation 1", initial_response="Resp 1", mtime=now - 100
        )
        c2 = self.workspace.create_conversation(
            initial_prompt="Conversation 2", initial_response="Resp 2", mtime=now - 10
        )

        recent = self.agent.list_all_recent_conversations(limit=5)
        self.assertEqual(len(recent), 2)
        # c2 is more recent than c1
        self.assertEqual(recent[0]["conv_id"], c2)
        self.assertEqual(recent[0]["title"], "Conversation 2")
        self.assertEqual(recent[1]["conv_id"], c1)

    async def test_execute_new_conversation(self):
        with patch("asyncio.create_subprocess_exec", side_effect=self.mock_api.handle_exec):
            reply, conv_id = await self.agent.execute("Please explain quantum computing")
            self.assertIsNotNone(conv_id)
            self.assertTrue(conv_id.startswith("mock-conv-"))
            self.assertIn("Echo from Antigravity: Please explain quantum computing", reply)

            # Check that AGENTAPI_PROJECT_ID was passed
            self.assertEqual(len(self.mock_api.invocations), 1)
            inv = self.mock_api.invocations[0]
            self.assertEqual(inv["cmd"], ["/mock/bin/agentapi", "new-conversation", "Please explain quantum computing"])
            self.assertEqual(inv["env"].get("AGENTAPI_PROJECT_ID"), "test-project-123")

    async def test_execute_continue_conversation(self):
        conv_id = self.workspace.create_conversation(
            initial_prompt="First turn",
            initial_response="First reply"
        )

        with patch("asyncio.create_subprocess_exec", side_effect=self.mock_api.handle_exec):
            reply, returned_id = await self.agent.execute("Second turn follow-up", conversation_id=conv_id)
            self.assertEqual(returned_id, conv_id)
            self.assertIn("Echo from Antigravity: Second turn follow-up", reply)

            # Verify send-message invocation
            self.assertEqual(len(self.mock_api.invocations), 1)
            inv = self.mock_api.invocations[0]
            self.assertEqual(inv["cmd"], ["/mock/bin/agentapi", "send-message", conv_id, "Second turn follow-up"])

    def test_prepare_agentapi_env_strips_parent_scoping(self):
        with patch.dict(os.environ, {
            "ANTIGRAVITY_CONVERSATION_ID": "parent-conv-123",
            "ANTIGRAVITY_PROJECT_ID": "parent-proj-456",
            "ANTIGRAVITY_SOURCE_METADATA": '{"tool": "call"}',
            "ANTIGRAVITY_TRAJECTORY_ID": "traj-789",
            "CUSTOM_VAR": "keep_me"
        }):
            clean_env = self.agent._prepare_agentapi_env()
            self.assertNotIn("ANTIGRAVITY_CONVERSATION_ID", clean_env)
            self.assertNotIn("ANTIGRAVITY_SOURCE_METADATA", clean_env)
            self.assertNotIn("ANTIGRAVITY_TRAJECTORY_ID", clean_env)
            self.assertEqual(clean_env.get("CUSTOM_VAR"), "keep_me")
            self.assertEqual(clean_env.get("AGENTAPI_PROJECT_ID"), "test-project-123")
            self.assertEqual(clean_env.get("ANTIGRAVITY_PROJECT_ID"), "test-project-123")

    async def test_execute_send_message_failure_fallback_to_new(self):
        conv_id = "non-existent-conv-id"
        self.mock_api.fail_next = True
        self.mock_api.fail_stderr = "Conversation not found"

        with patch("asyncio.create_subprocess_exec", side_effect=self.mock_api.handle_exec):
            reply, returned_id = await self.agent.execute("Fallback test prompt", conversation_id=conv_id)
            # Should have fallen back to creating a new conversation
            self.assertIsNotNone(returned_id)
            self.assertNotEqual(returned_id, conv_id)
            self.assertIn("Echo from Antigravity: Fallback test prompt", reply)



if __name__ == "__main__":
    unittest.main()
