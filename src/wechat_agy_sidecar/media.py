"""
Media decryptor & downloader for WeChat iLink CDN attachments.
Handles AES-128-ECB CDN payload decryption for inbound images, audio, and files.
"""

from __future__ import annotations

import time
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, Any

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

logger = logging.getLogger("wechat_agy_sidecar.media")

MEDIA_DIR = Path.home() / ".gemini" / "wechat_media"


def decrypt_and_save_media(image_item: Dict[str, Any], msg_id: str) -> Optional[Path]:
    """
    Downloads encrypted media from Tencent CDN, decrypts with AES-128-ECB, and saves to disk.
    """
    try:
        media = image_item.get("media", {})
        url = media.get("full_url") or image_item.get("url") or image_item.get("full_url")
        if not url:
            logger.warning(f"No media download URL found in image_item: {image_item}")
            return None

        # Determine AES key
        raw_key = (
            image_item.get("aeskey")
            or media.get("aes_key")
            or image_item.get("aes_key")
            or media.get("aeskey")
        )
        if not raw_key:
            logger.warning("No AES key found in media payload.")
            return None

        key: Optional[bytes] = None
        if len(raw_key) == 32:  # Hex-encoded string
            try:
                key = bytes.fromhex(raw_key)
            except Exception:
                pass

        if not key:
            try:
                decoded = base64.b64decode(raw_key)
                if len(decoded) == 16:
                    key = decoded
                elif len(decoded) == 32:
                    key = bytes.fromhex(decoded.decode("utf-8", errors="ignore"))
            except Exception:
                pass

        if not key or len(key) != 16:
            logger.warning(f"Invalid AES key: {raw_key}")
            return None

        # Download encrypted payload
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            logger.error(f"Failed to download media from CDN: HTTP {resp.status_code}")
            return None

        # Decrypt AES-128-ECB
        cipher = Cipher(algorithms.AES(key), modes.ECB())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(resp.content) + decryptor.finalize()

        # Unpad PKCS7 if padded
        try:
            unpadder = padding.PKCS7(128).unpadder()
            unpadded = unpadder.update(decrypted) + unpadder.finalize()
        except Exception:
            unpadded = decrypted

        # Determine file extension
        ext = ".jpg"
        if unpadded.startswith(b"\x89PNG"):
            ext = ".png"
        elif unpadded.startswith(b"GIF8"):
            ext = ".gif"
        elif unpadded.startswith(b"\xff\xd8\xff"):
            ext = ".jpg"
        elif unpadded.startswith(b"RIFF") and b"WEBP" in unpadded[:16]:
            ext = ".webp"

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        file_path = MEDIA_DIR / f"img_{msg_id or int(time.time())}{ext}"
        with open(file_path, "wb") as f:
            f.write(unpadded)

        logger.info(f"Successfully decrypted and saved WeChat image ({len(unpadded)} bytes) to: {file_path}")
        return file_path

    except Exception as e:
        logger.error(f"Failed to decrypt and save WeChat media: {e}", exc_info=True)
        return None
