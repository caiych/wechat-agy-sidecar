"""
Unit tests for CLI commands in wechat_agy_sidecar.cli.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from wechat_agy_sidecar.cli import main
from wechat_agy_sidecar.media import register_media


def test_cli_version(capsys):
    with patch.object(sys, "argv", ["wechat-agy-sidecar", "--version"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "wechat-agy-sidecar" in captured.out


def test_cli_download_media_by_registry_id(mock_media_dir, capsys, temp_dir):
    media_id = "voice_cli_test_101"
    register_media(media_id, "voice", "https://cdn.wechat.com/media101", "0123456789abcdef", {"transcription": "CLI测试"})

    fake_saved = temp_dir / "saved_audio.silk"
    fake_saved.write_bytes(b"SILK_DATA")

    with patch.object(sys, "argv", ["wechat-agy-sidecar", "download-media", media_id]), \
         patch("wechat_agy_sidecar.media.download_and_decrypt_media", return_value=fake_saved):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "CLI测试" in captured.out
        assert "Successfully decrypted" in captured.out


def test_cli_download_media_registry_not_found(mock_media_dir, capsys):
    with patch.object(sys, "argv", ["wechat-agy-sidecar", "download-media", "non_existent_id"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "not found in registry" in captured.err


def test_cli_download_media_direct_url_and_key(temp_dir, capsys):
    fake_saved = temp_dir / "direct_download.png"
    fake_saved.write_bytes(b"PNG_DATA")

    with patch.object(sys, "argv", [
        "wechat-agy-sidecar", "download-media",
        "--url", "https://cdn.wechat.com/img",
        "--key", "0123456789abcdef",
        "--output", str(fake_saved)
    ]), patch("wechat_agy_sidecar.media.download_and_decrypt_media", return_value=fake_saved):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Successfully decrypted" in captured.out


def test_cli_download_media_missing_args(capsys):
    with patch.object(sys, "argv", ["wechat-agy-sidecar", "download-media"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Provide either a <media_id> or --url + --key" in captured.err


def test_cli_run_login_flag(mock_config):
    with patch.object(sys, "argv", ["wechat-agy-sidecar", "--login"]), \
         patch("wechat_agy_sidecar.config.SidecarConfig.load", return_value=mock_config), \
         patch("wechat_agy_sidecar.sidecar.WeChatSidecar.run_onboarding_login", return_value=True):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


def test_cli_run_custom_system_prompt(mock_config):
    with patch.object(sys, "argv", ["wechat-agy-sidecar", "--system-prompt", "You are a specialized Python assistant."]), \
         patch("wechat_agy_sidecar.config.SidecarConfig.load", return_value=mock_config), \
         patch("wechat_agy_sidecar.sidecar.WeChatSidecar.start") as mock_start:
        main()
        assert mock_config.system_instructions == "You are a specialized Python assistant."
        mock_start.assert_called_once()
