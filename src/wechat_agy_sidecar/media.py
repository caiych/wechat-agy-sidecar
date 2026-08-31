"""
Media decryptor & downloader for WeChat iLink CDN attachments.
Handles AES-128-ECB CDN payload decryption for inbound images, audio (Silk v3), and files.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger("wechat_agy_sidecar.media")

MEDIA_DIR = Path.home() / ".gemini" / "wechat_media"


def decrypt_bytes(encrypted_data: bytes, raw_key: str | bytes) -> bytes:
    """Decrypts AES-128-ECB encrypted payload from Tencent CDN."""
    key: Optional[bytes] = None

    if isinstance(raw_key, bytes):
        key = raw_key
    elif isinstance(raw_key, str):
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
        raise ValueError(f"Invalid AES key format: {raw_key} (expected 16-byte key)")

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

    # Unpad PKCS7 if padded
    try:
        unpadder = padding.PKCS7(128).unpadder()
        unpadded = unpadder.update(decrypted) + unpadder.finalize()
        return unpadded
    except Exception:
        return decrypted


def download_and_decrypt_media(
    url: str,
    key_str: str,
    output_path: Optional[Path | str] = None,
    default_prefix: str = "media"
) -> Optional[Path]:
    """Downloads encrypted media from URL, decrypts with AES-128-ECB, and saves to output_path."""
    try:
        resp = requests.get(url, timeout=25)
        if resp.status_code != 200:
            logger.error(f"Failed to download media from CDN: HTTP {resp.status_code}")
            return None

        unpadded = decrypt_bytes(resp.content, key_str)

        # Detect extension from magic bytes
        ext = ".bin"
        if b"#!SILK" in unpadded[:16] or unpadded.startswith(b"\x02#!SILK"):
            ext = ".silk"
        elif unpadded.startswith(b"\x89PNG"):
            ext = ".png"
        elif unpadded.startswith(b"GIF8"):
            ext = ".gif"
        elif unpadded.startswith(b"\xff\xd8\xff"):
            ext = ".jpg"
        elif unpadded.startswith(b"RIFF") and b"WEBP" in unpadded[:16]:
            ext = ".webp"
        elif unpadded.startswith(b"#!AMR"):
            ext = ".amr"

        if output_path:
            out_file = Path(output_path)
        else:
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            out_file = MEDIA_DIR / f"{default_prefix}_{int(time.time())}{ext}"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "wb") as f:
            f.write(unpadded)

        logger.info(f"Decrypted media saved ({len(unpadded)} bytes) to: {out_file}")
        return out_file
    except Exception as e:
        logger.error(f"download_and_decrypt_media error: {e}", exc_info=True)
        return None


def decrypt_and_save_media(item_dict: Dict[str, Any], msg_id: str, media_type: str = "img") -> Optional[Path]:
    """Helper to extract URL and AES key from an item payload (image or voice) and save."""
    media = item_dict.get("media", {})
    url = media.get("full_url") or item_dict.get("url") or item_dict.get("full_url")
    raw_key = (
        item_dict.get("aeskey")
        or media.get("aes_key")
        or item_dict.get("aes_key")
        or media.get("aeskey")
    )
    if not url or not raw_key:
        return None

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{media_type}_{msg_id or int(time.time())}"
    return download_and_decrypt_media(url, raw_key, default_prefix=prefix)


MEDIA_REGISTRY_FILE = MEDIA_DIR / "registry.json"

def _load_registry() -> Dict[str, Any]:
    """Loads the media registry from disk."""
    if MEDIA_REGISTRY_FILE.exists():
        try:
            return json.loads(MEDIA_REGISTRY_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def _save_registry(registry: Dict[str, Any]):
    """Saves the media registry to disk."""
    MEDIA_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding='utf-8')

def register_media(media_id: str, media_type: str, url: str, key: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Registers a media entry in the local registry. Returns the media_id."""
    registry = _load_registry()
    registry[media_id] = {
        "type": media_type,
        "url": url,
        "key": key,
        "registered_at": int(time.time()),
        **(metadata or {})
    }
    _save_registry(registry)
    logger.info(f"Registered media: {media_id} (type={media_type})")
    return media_id

def lookup_media(media_id: str) -> Optional[Dict[str, Any]]:
    """Looks up a media entry by ID from the registry."""
    registry = _load_registry()
    return registry.get(media_id)
