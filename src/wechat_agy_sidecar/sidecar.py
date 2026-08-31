"""
WeChat Antigravity Sidecar Orchestrator & Daemon.
Handles persistent user conversation threading, /new command routing,
and proactive background event streaming via agentapi & transcript monitoring.
"""

from __future__ import annotations

import os
import json
import time
import signal
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict

from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.client import WeChatIlinkClient, InboundMessage, TerminalQR
from wechat_agy_sidecar.agent import AntigravityAgent

logger = logging.getLogger("wechat_agy_sidecar.daemon")

BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"


class WeChatSidecar:
    """Main daemon managing WeChat iLink event polling, agentapi routing, and proactive streaming."""

    def __init__(self, config: Optional[SidecarConfig] = None):
        self.config = config or SidecarConfig.load()
        self.client = WeChatIlinkClient(self.config)
        self.agent = AntigravityAgent(self.config)
        self.running = True
        self.conversation_cursors: Dict[str, int] = {}  # conv_id -> last_seen_line_count

    def run_onboarding_login(self) -> bool:
        """Runs the interactive QR-code authentication flow."""
        logger.info("Initiating WeChat QR Login Onboarding flow...")
        ok, qrcode_id, qrcode_url = self.client.get_login_qrcode()
        if not ok or not qrcode_id:
            logger.error("Failed to obtain login QR code from WeChat.")
            return False

        print("\n" + "=" * 65)
        print("  [WeChat Onboarding] SCAN QR CODE TO CONNECT ANTIGRAVITY")
        print("=" * 65)
        TerminalQR.display(qrcode_url or qrcode_id)
        print(f"\n👉 Direct Link: {qrcode_url}\n")
        print("Please scan the QR code above with WeChat on your phone.")
        print("Waiting for scan confirmation in WeChat...")
        print("=" * 65 + "\n")

        start_time = time.time()
        while time.time() - start_time < 180:  # 3 minutes
            status, data = self.client.poll_qrcode_status(qrcode_id)
            if status in ["confirmed", "ok", "success"] and data:
                self.config.bot_token = data.get("bot_token", "")
                self.config.bot_id = data.get("bot_id", "")
                self.config.login_time = int(time.time())
                self.config.save()
                print("\n" + "=" * 65)
                logger.info("✅ WeChat Login confirmed successfully! Token saved.")
                print("=" * 65 + "\n")
                return True
            elif status in ["scanned", "scan"]:
                logger.info("QR code scanned! Please tap 'Confirm' on your mobile WeChat...")
            elif status in ["expired", "timeout"]:
                logger.error("QR code expired. Please rerun to generate a new one.")
                return False

            time.sleep(2)

        logger.error("Login timed out after 180s.")
        return False

    async def handle_message(self, msg: InboundMessage):
        """
        Dispatches an incoming WeChat message with user conversation thread continuity.
        Supports:
          - '/new' or '/reset' -> resets thread and replies with confirmation
          - '/new <prompt>' -> resets thread and immediately executes prompt in new thread
        """
        user_id = msg.from_user_id
        text = msg.text.strip()
        force_new_thread = False
        actual_prompt = text

        # Parse command prefixes: /new, /reset, /clear
        for cmd_prefix in ["/new", "/reset", "/clear"]:
            if text.lower() == cmd_prefix or text in ["新对话", "重置会话"]:
                self.config.reset_conversation(user_id)
                logger.info(f"Reset conversation thread for user [{user_id}]")
                self.client.send_message(user_id, msg.context_token, "🔄 会话已重置，已开启全新的对话线程！请输入你的问题：")
                return
            elif text.lower().startswith(f"{cmd_prefix} ") or text.lower().startswith(f"{cmd_prefix}：") or text.lower().startswith(f"{cmd_prefix}:"):
                force_new_thread = True
                sep_idx = text.find(" ")
                if sep_idx == -1:
                    sep_idx = max(text.find("："), text.find(":"))
                actual_prompt = text[sep_idx + 1:].strip()
                self.config.reset_conversation(user_id)
                logger.info(f"Resetting thread and executing prompt for user [{user_id}]: {actual_prompt}")
                break

        if not actual_prompt:
            self.client.send_message(user_id, msg.context_token, "🔄 会话已重置，已开启全新的对话线程！请输入你的问题：")
            return

        logger.info(f"Incoming message from [{user_id}]: {actual_prompt[:60]} (force_new={force_new_thread})")
        
        # 1. Determine conversation ID for this user
        conv_id = None if force_new_thread else self.config.get_conversation_id(user_id)
        if conv_id:
            logger.info(f"Continuing thread [{conv_id}] for user [{user_id}]")
        else:
            logger.info(f"Starting new thread for user [{user_id}] via agentapi")

        # 2. Send typing status
        self.client.send_typing(user_id, typing=True)

        # 3. Execute via Antigravity agentapi
        start_t = time.time()
        reply_text, new_conv_id = await self.agent.execute(actual_prompt, conversation_id=conv_id)
        elapsed = time.time() - start_t
        logger.info(f"Antigravity reply generated in {elapsed:.2f}s (conv={new_conv_id}) for [{user_id}]")

        # 4. Save updated thread ID and update cursor
        if new_conv_id:
            self.config.set_conversation_id(user_id, new_conv_id)
            # Update cursor to current line count so proactive watcher doesn't duplicate this reply
            t_file = BRAIN_DIR / new_conv_id / ".system_generated" / "logs" / "transcript.jsonl"
            if t_file.exists():
                try:
                    self.conversation_cursors[new_conv_id] = len(t_file.read_text(encoding="utf-8").strip().splitlines())
                except Exception:
                    pass

        # 5. Cancel typing & send reply
        self.client.send_typing(user_id, typing=False)
        self.client.send_message(user_id, msg.context_token, reply_text)

    async def proactive_event_watcher(self):
        """
        Background task continuously monitoring active user conversation transcripts.
        Pushes any new Assistant responses (e.g. background timers, subagents) to WeChat.
        """
        logger.info("Proactive event watcher started.")
        while self.running:
            await asyncio.sleep(2.0)
            try:
                # Invert mapping: conv_id -> user_id
                conv_to_user = {c_id: u_id for u_id, c_id in self.config.user_conversations.items()}

                for conv_id, user_id in conv_to_user.items():
                    t_file = BRAIN_DIR / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
                    if not t_file.exists():
                        continue

                    try:
                        lines = t_file.read_text(encoding="utf-8").strip().splitlines()
                    except Exception:
                        continue

                    last_seen = self.conversation_cursors.get(conv_id, len(lines))
                    if len(lines) > last_seen:
                        for line in lines[last_seen:]:
                            try:
                                step = json.loads(line)
                                # Check if it is an async assistant response
                                if step.get("type") == "PLANNER_RESPONSE" and step.get("content"):
                                    content = step.get("content", "").strip()
                                    if content and not step.get("tool_calls"):
                                        logger.info(f"Pushing proactive background message to user [{user_id}] from conv [{conv_id}]")
                                        self.client.send_message(user_id, "", content)
                            except Exception as e:
                                logger.debug(f"Error parsing proactive step: {e}")

                        self.conversation_cursors[conv_id] = len(lines)

            except Exception as e:
                logger.error(f"Proactive watcher error: {e}", exc_info=True)

    async def poll_loop(self):
        """Long-polling main event loop with proactive background watcher."""
        logger.info("Starting WeChat Long-Polling daemon (getupdates)...")
        loop = asyncio.get_event_loop()

        # Initialize existing transcript cursors
        for u_id, c_id in self.config.user_conversations.items():
            t_file = BRAIN_DIR / c_id / ".system_generated" / "logs" / "transcript.jsonl"
            if t_file.exists():
                try:
                    self.conversation_cursors[c_id] = len(t_file.read_text(encoding="utf-8").strip().splitlines())
                except Exception:
                    pass

        # Start proactive watcher concurrently
        asyncio.create_task(self.proactive_event_watcher())

        while self.running:
            try:
                result = await loop.run_in_executor(None, lambda: self.client.get_updates(timeout=35))
                
                if result.status_code == 401:
                    logger.warning("Session token unauthorized (401). Triggering onboarding...")
                    if self.run_onboarding_login():
                        continue
                    else:
                        await asyncio.sleep(5)
                        continue

                if result.status_code == 200:
                    if result.new_cursor != self.config.get_updates_buf:
                        self.config.get_updates_buf = result.new_cursor
                        self.config.save()

                    if result.messages:
                        logger.info(f"Received {len(result.messages)} new message(s).")
                    for msg in result.messages:
                        asyncio.create_task(self.handle_message(msg))

                elif result.status_code != 200 and result.status_code != 0:
                    logger.warning(f"getupdates returned HTTP {result.status_code}: {result.raw_response}")
                    await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Polling loop exception: {e}", exc_info=True)
                await asyncio.sleep(3)

    def start(self):
        """Starts the sidecar daemon."""
        if not self.config.bot_token:
            logger.info("No active token found. Initiating onboarding login...")
            if not self.run_onboarding_login():
                logger.error("Onboarding failed. Exiting.")
                return

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda s, f: self.stop())

        asyncio.run(self.poll_loop())

    def stop(self):
        logger.info("Stopping WeChat Antigravity Sidecar...")
        self.running = False
