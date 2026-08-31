"""
WeChat iLink Bot API Client.
Implements the exact protocol utilized by OpenClaw's WeChat channel.
"""

from __future__ import annotations

import time
import json
import random
import logging
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

import requests
from wechat_agy_sidecar.config import SidecarConfig

logger = logging.getLogger("wechat_agy_sidecar.client")


class TerminalQR:
    """Utility to render QR codes in console using multiple fallbacks."""

    @staticmethod
    def display(text_or_url: str):
        # 1. Try local qrcode library first
        try:
            import qrcode
            qr = qrcode.QRCode(border=1)
            qr.add_data(text_or_url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
            return
        except ImportError:
            pass

        # 2. Try qrenco.de web service
        try:
            encoded_url = urllib.parse.quote(text_or_url, safe=":/=&?")
            resp = requests.get(f"https://qrenco.de/{encoded_url}", headers={"User-Agent": "curl/7.68.0"}, timeout=5)
            if resp.status_code == 200:
                print("\n" + resp.text)
                return
        except Exception:
            pass

        # 3. Plain URL fallback
        print("\n" + "=" * 60)
        print("Please scan or open the following link to authenticate:")
        print(text_or_url)
        print("=" * 60 + "\n")


@dataclass
class InboundMessage:
    msg_id: str
    from_user_id: str
    context_token: str
    text: str
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GetUpdatesResult:
    status_code: int
    new_cursor: str
    messages: List[InboundMessage]
    raw_response: Dict[str, Any] = field(default_factory=dict)


class WeChatIlinkClient:
    """Client for Tencent WeChat iLink Bot Protocol."""

    def __init__(self, config: SidecarConfig):
        self.config = config
        self.session = requests.Session()

    def get_login_qrcode(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Fetches QR code data for onboarding.
        Returns (success, qrcode_id, qrcode_render_url)
        """
        url = f"{self.config.ilink_base_url}/ilink/bot/get_bot_qrcode?bot_type=3"
        try:
            resp = self.session.get(url, headers={"bot_agent": self.config.bot_agent}, timeout=10)
            if resp.status_code != 200:
                logger.error(f"get_bot_qrcode failed with HTTP {resp.status_code}: {resp.text}")
                return False, None, None
            
            data = resp.json()
            qrcode_id = data.get("qrcode") or data.get("qrcode_id")
            qrcode_render_url = data.get("qrcode_img_content") or data.get("qrcode_img_url") or qrcode_id
            return True, qrcode_id, qrcode_render_url
        except Exception as e:
            logger.error(f"Exception requesting QR code: {e}")
            return False, None, None

    def poll_qrcode_status(self, qrcode_id: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Polls QR scan status: 'waiting', 'scanned', 'confirmed', 'expired', 'error'.
        """
        url = f"{self.config.ilink_base_url}/ilink/bot/get_qrcode_status"
        try:
            resp = self.session.get(url, params={"qrcode": qrcode_id}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                status = str(data.get("status", "")).lower()
                return status, data
            return "error", None
        except Exception as e:
            logger.debug(f"Polling QR error: {e}")
            return "error", None

    def get_updates(self, timeout: int = 35) -> GetUpdatesResult:
        """
        Long-polls /ilink/bot/getupdates for new messages.
        """
        url = f"{self.config.ilink_base_url}/ilink/bot/getupdates"
        payload = {
            "get_updates_buf": self.config.get_updates_buf,
            "timeout": timeout
        }
        try:
            resp = self.session.post(
                url,
                headers=self.config.get_auth_headers(),
                json=payload,
                timeout=timeout + 10
            )

            if resp.status_code != 200:
                return GetUpdatesResult(
                    status_code=resp.status_code,
                    new_cursor=self.config.get_updates_buf,
                    messages=[],
                    raw_response={"error": resp.text}
                )

            data = resp.json()
            new_cursor = data.get("get_updates_buf") or self.config.get_updates_buf
            raw_msgs = data.get("msgs") or data.get("messages") or []
            
            inbound_list: List[InboundMessage] = []
            for item in raw_msgs:
                msg_id = str(item.get("msg_id") or item.get("id") or "")
                from_user = str(item.get("from_user_id") or item.get("from_user") or "")
                context_token = str(item.get("context_token") or "")
                
                # Extract content from item_list (text, image, voice, file, video)
                text = ""
                item_list = item.get("item_list", [])
                has_media = False
                for sub_item in item_list:
                    item_type = sub_item.get("type")
                    text_item = sub_item.get("text_item", {})
                    image_item = sub_item.get("image_item", {})
                    file_item = sub_item.get("file_item", {})
                    voice_item = sub_item.get("voice_item", {})
                    video_item = sub_item.get("video_item", {})

                    if item_type == 1 or (text_item and "text" in text_item):
                        text += (text_item.get("text") or sub_item.get("text", "")) + "\n"
                    elif item_type == 2 or image_item:
                        has_media = True
                        logger.info(f"Received Image attachment: {image_item}")
                        from wechat_agy_sidecar.media import decrypt_and_save_media
                        saved_path = decrypt_and_save_media(image_item, msg_id)
                        if saved_path:
                            text += f"[用户发送了一张图片，已解密保存至本地文件: file://{saved_path.resolve()}]\n请分析并查看此图片内容。\n"
                        else:
                            text += "[用户发送了一张图片 (Image)]\n"
                    elif item_type == 3 or voice_item:
                        has_media = True
                        logger.info(f"Received Voice message: {voice_item}")
                        from wechat_agy_sidecar.media import decrypt_and_save_media
                        transcribed_text = (voice_item.get("text") or item.get("text") or "").strip()
                        media_info = voice_item.get("media", {})
                        media_url = media_info.get("full_url") or voice_item.get("url") or ""
                        raw_key = voice_item.get("aeskey") or media_info.get("aes_key") or voice_item.get("aes_key") or media_info.get("aeskey") or ""
                        saved_audio = decrypt_and_save_media(voice_item, msg_id, media_type="voice")
                        saved_str = f"file://{saved_audio.resolve()}" if saved_audio else "下载失败"
                        out_path_str = str(saved_audio.resolve()) if saved_audio else "/tmp/voice.silk"
                        cli_cmd = f'wechat-agy-sidecar download-media --url "{media_url}" --key "{raw_key}" --output "{out_path_str}"'

                        voice_prompt = (
                            f"[用户发送了一条语音消息 (Voice Input)]\n"
                            f"微信默认转写文本: \"{transcribed_text or '（微信未返回自动转写文本）'}\"\n"
                            f"原始语音文件已保存至: {saved_str}\n"
                            f"CLI 检视命令: `{cli_cmd}`\n"
                            f"（提示：若用户要求复核原始语音或转写疑似有误，可运行上述 CLI 命令检查 raw data 音频文件。）\n\n"
                            f"用户语音内容: {transcribed_text or '请提示用户微信未提供自动语音转写，并提示已保存原始语音文件。'}\n"
                        )
                        text += voice_prompt
                    elif item_type == 4 or file_item:
                        has_media = True
                        file_name = file_item.get("file_name", "未知文件")
                        logger.info(f"Received File attachment: {file_name}")
                        text += f"[用户发送了一个文件: {file_name}]\n"
                    elif item_type == 5 or video_item:
                        has_media = True
                        logger.info(f"Received Video attachment: {video_item}")
                        text += "[用户发送了一个视频 (Video)]\n"
                    elif "text" in sub_item:
                        text += str(sub_item["text"]) + "\n"

                # Fallback to direct content/text
                if not text:
                    content = item.get("content", {})
                    if isinstance(content, dict):
                        text = content.get("text", "")
                    elif isinstance(content, str):
                        text = content
                    elif "text" in item:
                        text = str(item["text"])

                text = text.strip()
                if (text or has_media) and from_user:
                    inbound_list.append(
                        InboundMessage(
                            msg_id=msg_id,
                            from_user_id=from_user,
                            context_token=context_token,
                            text=text or "[用户发送了一条多媒体消息]",
                            raw_payload=item
                        )
                    )

            return GetUpdatesResult(
                status_code=200,
                new_cursor=new_cursor,
                messages=inbound_list,
                raw_response=data
            )

        except requests.exceptions.Timeout:
            # Normal long-polling timeout
            return GetUpdatesResult(status_code=200, new_cursor=self.config.get_updates_buf, messages=[])
        except Exception as e:
            logger.error(f"get_updates exception: {e}")
            return GetUpdatesResult(status_code=0, new_cursor=self.config.get_updates_buf, messages=[])

    def send_typing(self, to_user_id: str, typing: bool = True):
        """Sends typing status indicator."""
        url = f"{self.config.ilink_base_url}/ilink/bot/sendtyping"
        payload = {"to_user_id": to_user_id, "to_user": to_user_id, "typing": typing}
        try:
            self.session.post(url, headers=self.config.get_auth_headers(), json=payload, timeout=5)
        except Exception:
            pass

    def send_message(self, to_user_id: str, context_token: str, text: str) -> bool:
        """
        Sends text message chunks conforming to official iLink SendMessage schema.
        Includes message_type: 2 (BOT), message_state: 2 (FINISH), and client_id.
        """
        url = f"{self.config.ilink_base_url}/ilink/bot/sendmessage"
        chunks = [text[i:i + 1800] for i in range(0, len(text), 1800)]
        all_success = True

        for i, chunk in enumerate(chunks):
            client_msg_id = f"msg_{int(time.time() * 1000)}_{random.randint(1000, 9999)}_{i}"
            msg_payload: Dict[str, Any] = {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_msg_id,
                "message_type": 2,  # 2 = BOT outbound
                "message_state": 2, # 2 = FINISH (render in WeChat UI)
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {
                            "text": chunk
                        }
                    }
                ]
            }
            if context_token:
                msg_payload["context_token"] = context_token

            payload = {"msg": msg_payload}
            try:
                resp = self.session.post(
                    url,
                    headers=self.config.get_auth_headers(),
                    json=payload,
                    timeout=10
                )
                if resp.status_code == 200:
                    logger.info(f"Successfully sent reply to [{to_user_id}] (len={len(chunk)}): {resp.text}")
                else:
                    logger.error(f"send_message failed HTTP {resp.status_code}: {resp.text}")
                    all_success = False
            except Exception as e:
                logger.error(f"send_message exception: {e}")
                all_success = False

        return all_success

