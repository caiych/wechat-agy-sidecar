"""
WeChat Antigravity Sidecar Orchestrator & Daemon.
Handles persistent user conversation threading and /new command routing.
"""

from __future__ import annotations

import time
import signal
import asyncio
import logging
from pathlib import Path
from typing import Optional

from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.client import WeChatIlinkClient, InboundMessage, TerminalQR
from wechat_agy_sidecar.agent import AntigravityAgent

logger = logging.getLogger("wechat_agy_sidecar.daemon")


class WeChatSidecar:
    """Main daemon managing WeChat iLink event polling and Antigravity SDK routing."""

    def __init__(self, config: Optional[SidecarConfig] = None):
        self.config = config or SidecarConfig.load()
        self.client = WeChatIlinkClient(self.config)
        self.agent = AntigravityAgent(self.config)
        self.running = True

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
                # Remove prefix
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

        logger.info(f"Incoming message from [{user_id}]: {actual_prompt} (force_new={force_new_thread})")
        
        # 1. Determine conversation ID for this user
        conv_id = None if force_new_thread else self.config.get_conversation_id(user_id)
        if conv_id:
            logger.info(f"Continuing thread [{conv_id}] for user [{user_id}]")
        else:
            logger.info(f"Starting new thread for user [{user_id}]")

        # 2. Send typing status
        self.client.send_typing(user_id, typing=True)

        # 3. Execute via Antigravity with conversation ID
        start_t = time.time()
        reply_text, new_conv_id = await self.agent.execute(actual_prompt, conversation_id=conv_id)
        elapsed = time.time() - start_t
        logger.info(f"Antigravity reply generated in {elapsed:.2f}s (conv={new_conv_id}) for [{user_id}]")

        # 4. Save updated thread ID
        if new_conv_id:
            self.config.set_conversation_id(user_id, new_conv_id)

        # 5. Cancel typing & send reply
        self.client.send_typing(user_id, typing=False)
        self.client.send_message(user_id, msg.context_token, reply_text)

    async def poll_loop(self):
        """Long-polling main event loop."""
        logger.info("Starting WeChat Long-Polling daemon (getupdates)...")
        loop = asyncio.get_event_loop()

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
