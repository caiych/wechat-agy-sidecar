"""
Unit tests for WeChat media decryption, CDN downloads, format detection, and media registry.
"""

from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from tests.mocks.mock_ilink import MockIlinkAdapter, encrypt_aes_ecb
from wechat_agy_sidecar import media
from wechat_agy_sidecar.media import (
    decrypt_and_save_media,
    decrypt_bytes,
    download_and_decrypt_media,
    lookup_media,
    register_media,
)


class TestMediaCryptoAndRegistry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_media_dir = Path(self.temp_dir.name) / "media"
        self.test_media_dir.mkdir(parents=True, exist_ok=True)
        self.patcher1 = patch.object(media, "MEDIA_DIR", self.test_media_dir)
        self.patcher2 = patch.object(media, "MEDIA_REGISTRY_FILE", self.test_media_dir / "registry.json")
        self.patcher1.start()
        self.patcher2.start()

        self.key_16 = b"0123456789abcdef"
        self.key_hex = self.key_16.hex()
        self.key_b64 = base64.b64encode(self.key_16).decode()

    def tearDown(self):
        self.patcher2.stop()
        self.patcher1.stop()
        self.temp_dir.cleanup()

    def test_decrypt_bytes_success(self):
        original_plain = b"Hello WeChat CDN Image Content"
        ciphertext = encrypt_aes_ecb(original_plain, self.key_16)

        # 1. Raw bytes key
        decrypted_raw = decrypt_bytes(ciphertext, self.key_16)
        self.assertEqual(decrypted_raw, original_plain)

        # 2. Hex string key
        decrypted_hex = decrypt_bytes(ciphertext, self.key_hex)
        self.assertEqual(decrypted_hex, original_plain)

        # 3. Base64 string key
        decrypted_b64 = decrypt_bytes(ciphertext, self.key_b64)
        self.assertEqual(decrypted_b64, original_plain)

    def test_decrypt_bytes_invalid_key_format(self):
        ciphertext = encrypt_aes_ecb(b"data", self.key_16)
        with self.assertRaises(ValueError):
            decrypt_bytes(ciphertext, "short_key")

    def test_format_detection_and_download(self):
        test_cases = [
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, ".png"),
            (b"\xff\xd8\xff\xe0" + b"\x00" * 20, ".jpg"),
            (b"GIF89a" + b"\x00" * 20, ".gif"),
            (b"#!SILK_V3" + b"\x00" * 20, ".silk"),
            (b"#!AMR\n" + b"\x00" * 20, ".amr"),
            (b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20, ".webp"),
            (b"RandomBinaryData" + b"\x00" * 20, ".bin"),
        ]

        mock_adapter = MockIlinkAdapter()
        for idx, (raw_data, expected_ext) in enumerate(test_cases):
            url = f"https://cdn.weixin.qq.com/file_{idx}"
            mock_adapter.add_cdn_file(url, raw_data, self.key_16)

            with patch("requests.get", side_effect=lambda u, timeout=25: mock_adapter.send(requests.Request("GET", u).prepare())):
                saved_path = download_and_decrypt_media(url, self.key_hex, default_prefix=f"test_{idx}")
                self.assertIsNotNone(saved_path)
                self.assertEqual(saved_path.suffix, expected_ext)
                self.assertEqual(saved_path.read_bytes(), raw_data)

    def test_decrypt_and_save_media_helper(self):
        raw_png = b"\x89PNG\r\n\x1a\n" + b"image_payload"
        cdn_url = "https://cdn.weixin.qq.com/img_sample"
        mock_adapter = MockIlinkAdapter()
        mock_adapter.add_cdn_file(cdn_url, raw_png, self.key_16)

        item_dict = {
            "media": {
                "full_url": cdn_url,
                "aes_key": self.key_hex
            }
        }

        with patch("requests.get", side_effect=lambda u, timeout=25: mock_adapter.send(requests.Request("GET", u).prepare())):
            saved = decrypt_and_save_media(item_dict, "msg_img_1", media_type="img")
            self.assertIsNotNone(saved)
            self.assertTrue(saved.exists())
            self.assertEqual(saved.suffix, ".png")
            self.assertEqual(saved.read_bytes(), raw_png)

    def test_media_registry_operations(self):
        mid = "voice_sample_999"
        res_id = register_media(
            media_id=mid,
            media_type="voice",
            url="https://cdn.weixin.qq.com/voice_sample",
            key=self.key_hex,
            metadata={"transcription": "这是一条语音转写文本", "duration_ms": 3500}
        )
        self.assertEqual(res_id, mid)

        entry = lookup_media(mid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["type"], "voice")
        self.assertEqual(entry["url"], "https://cdn.weixin.qq.com/voice_sample")
        self.assertEqual(entry["key"], self.key_hex)
        self.assertEqual(entry["transcription"], "这是一条语音转写文本")
        self.assertEqual(entry["duration_ms"], 3500)

        # Lookup non-existent
        self.assertIsNone(lookup_media("non_existent_id"))


if __name__ == "__main__":
    unittest.main()
