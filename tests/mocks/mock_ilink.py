"""
Mock WeChat iLink server and payload generators for testing.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def encrypt_aes_ecb(data: bytes, key: bytes) -> bytes:
    """Encrypts bytes with AES-128-ECB and PKCS7 padding for mock CDN testing."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def create_text_message(
    msg_id: str,
    from_user_id: str,
    text: str,
    context_token: str = "ctx_test_123"
) -> Dict[str, Any]:
    """Creates a raw iLink inbound text message item."""
    return {
        "msg_id": msg_id,
        "from_user_id": from_user_id,
        "context_token": context_token,
        "item_list": [
            {
                "type": 1,
                "text_item": {
                    "text": text
                }
            }
        ]
    }


def create_image_message(
    msg_id: str,
    from_user_id: str,
    cdn_url: str,
    aes_key: str,
    context_token: str = "ctx_test_img"
) -> Dict[str, Any]:
    """Creates a raw iLink inbound image message item."""
    return {
        "msg_id": msg_id,
        "from_user_id": from_user_id,
        "context_token": context_token,
        "item_list": [
            {
                "type": 2,
                "image_item": {
                    "media": {
                        "full_url": cdn_url,
                        "aes_key": aes_key
                    }
                }
            }
        ]
    }


def create_voice_message(
    msg_id: str,
    from_user_id: str,
    transcription: str,
    cdn_url: str = "",
    aes_key: str = "",
    context_token: str = "ctx_test_voice"
) -> Dict[str, Any]:
    """Creates a raw iLink inbound voice message item with transcription and optional CDN audio."""
    voice_item: Dict[str, Any] = {
        "text": transcription
    }
    if cdn_url and aes_key:
        voice_item["media"] = {
            "full_url": cdn_url,
            "aes_key": aes_key
        }
    return {
        "msg_id": msg_id,
        "from_user_id": from_user_id,
        "context_token": context_token,
        "item_list": [
            {
                "type": 3,
                "voice_item": voice_item
            }
        ]
    }


def create_file_message(
    msg_id: str,
    from_user_id: str,
    file_name: str,
    context_token: str = "ctx_test_file"
) -> Dict[str, Any]:
    """Creates a raw iLink inbound file message item."""
    return {
        "msg_id": msg_id,
        "from_user_id": from_user_id,
        "context_token": context_token,
        "item_list": [
            {
                "type": 4,
                "file_item": {
                    "file_name": file_name
                }
            }
        ]
    }


def create_video_message(
    msg_id: str,
    from_user_id: str,
    context_token: str = "ctx_test_video"
) -> Dict[str, Any]:
    """Creates a raw iLink inbound video message item."""
    return {
        "msg_id": msg_id,
        "from_user_id": from_user_id,
        "context_token": context_token,
        "item_list": [
            {
                "type": 5,
                "video_item": {
                    "video_url": "https://example.com/video.mp4"
                }
            }
        ]
    }


class MockIlinkAdapter(requests.adapters.HTTPAdapter):
    """Custom requests HTTPAdapter that intercepts requests to iLink and CDN endpoints."""

    def __init__(self, base_url: str = "https://ilinkai.weixin.qq.com"):
        super().__init__()
        self.base_url = base_url
        self.sent_messages: List[Dict[str, Any]] = []
        self.sent_typing: List[Dict[str, Any]] = []
        self.get_updates_responses: List[Dict[str, Any]] = []
        self.cdn_files: Dict[str, bytes] = {}
        self.qrcode_id = "test_qr_code_xyz"
        self.qrcode_url = "https://ilinkai.weixin.qq.com/qr/render/xyz"
        self.qrcode_status_sequence: List[Tuple[str, Dict[str, Any]]] = [
            ("waiting", {}),
            ("scanned", {}),
            ("confirmed", {"bot_token": "mock_token_abc_123", "bot_id": "mock_bot_999"})
        ]
        self.qrcode_status_index = 0
        self.force_updates_status_code: Optional[int] = None
        self.next_cursor = "cursor_001"

    def queue_update(self, raw_msgs: List[Dict[str, Any]], next_cursor: Optional[str] = None):
        """Queues a list of inbound messages for getupdates long-poll."""
        if next_cursor:
            self.next_cursor = next_cursor
        self.get_updates_responses.append({
            "get_updates_buf": self.next_cursor,
            "msgs": raw_msgs
        })

    def add_cdn_file(self, url: str, raw_content: bytes, aes_key: bytes) -> str:
        """Stores an encrypted file in mock CDN and returns the URL."""
        encrypted = encrypt_aes_ecb(raw_content, aes_key)
        self.cdn_files[url] = encrypted
        return url

    def send(self, request, **kwargs):
        parsed = urllib.parse.urlparse(request.url)
        path = parsed.path

        # Mock CDN download
        if request.url in self.cdn_files:
            resp = requests.Response()
            resp.status_code = 200
            resp._content = self.cdn_files[request.url]
            resp.url = request.url
            return resp

        # 1. /ilink/bot/get_bot_qrcode
        if path.endswith("/ilink/bot/get_bot_qrcode"):
            resp = requests.Response()
            resp.status_code = 200
            resp._content = json.dumps({
                "qrcode": self.qrcode_id,
                "qrcode_img_url": self.qrcode_url
            }).encode("utf-8")
            return resp

        # 2. /ilink/bot/get_qrcode_status
        if path.endswith("/ilink/bot/get_qrcode_status"):
            resp = requests.Response()
            resp.status_code = 200
            if self.qrcode_status_index < len(self.qrcode_status_sequence):
                st, extra = self.qrcode_status_sequence[self.qrcode_status_index]
                self.qrcode_status_index += 1
                payload = {"status": st, **extra}
            else:
                st, extra = self.qrcode_status_sequence[-1]
                payload = {"status": st, **extra}
            resp._content = json.dumps(payload).encode("utf-8")
            return resp

        # 3. /ilink/bot/getupdates
        if path.endswith("/ilink/bot/getupdates"):
            resp = requests.Response()
            if self.force_updates_status_code:
                resp.status_code = self.force_updates_status_code
                resp._content = b'{"error": "forced status"}'
                return resp

            resp.status_code = 200
            if self.get_updates_responses:
                resp_payload = self.get_updates_responses.pop(0)
            else:
                resp_payload = {"get_updates_buf": self.next_cursor, "msgs": []}
            resp._content = json.dumps(resp_payload).encode("utf-8")
            return resp

        # 4. /ilink/bot/sendtyping
        if path.endswith("/ilink/bot/sendtyping"):
            payload = json.loads(request.body.decode("utf-8")) if request.body else {}
            self.sent_typing.append(payload)
            resp = requests.Response()
            resp.status_code = 200
            resp._content = b'{"ret": 0}'
            return resp

        # 5. /ilink/bot/sendmessage
        if path.endswith("/ilink/bot/sendmessage"):
            payload = json.loads(request.body.decode("utf-8")) if request.body else {}
            self.sent_messages.append(payload)
            resp = requests.Response()
            resp.status_code = 200
            resp._content = json.dumps({"ret": 0, "msg": "ok"}).encode("utf-8")
            return resp

        # Default 404
        resp = requests.Response()
        resp.status_code = 404
        resp._content = b'{"error": "not found"}'
        return resp
