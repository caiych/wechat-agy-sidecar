"""
Unit tests for SidecarConfig in wechat_agy_sidecar.config.
"""

from __future__ import annotations

from wechat_agy_sidecar.config import (
    DEFAULT_BOT_AGENT,
    DEFAULT_ILINK_BASE_URL,
    DEFAULT_SYSTEM_INSTRUCTIONS,
    SidecarConfig,
)


def test_default_config_initialization(temp_dir):
    cfg_file = temp_dir / "non_existent_config.json"
    cfg = SidecarConfig.load(cfg_file)

    assert cfg.bot_token == ""
    assert cfg.bot_id == ""
    assert cfg.ilink_base_url == DEFAULT_ILINK_BASE_URL
    assert cfg.bot_agent == DEFAULT_BOT_AGENT
    assert cfg.system_instructions == DEFAULT_SYSTEM_INSTRUCTIONS
    assert cfg.enable_write_tools is True
    assert cfg.project_id == ""
    assert cfg.user_conversations == {}
    assert cfg.conversation_history == {}
    assert cfg.config_path == cfg_file
    assert bool(cfg.uin) is True


def test_config_save_and_reload(temp_dir):
    cfg_file = temp_dir / "saved_config.json"
    cfg = SidecarConfig.load(cfg_file)

    cfg.bot_token = "token_abc_123"
    cfg.bot_id = "bot_xyz_999"
    cfg.project_id = "proj-test"
    cfg.system_instructions = "Custom instructions"
    cfg.user_conversations = {"wx_user_1": "conv_111"}
    cfg.save()

    assert cfg_file.exists()

    loaded = SidecarConfig.load(cfg_file)
    assert loaded.bot_token == "token_abc_123"
    assert loaded.bot_id == "bot_xyz_999"
    assert loaded.project_id == "proj-test"
    assert loaded.system_instructions == "Custom instructions"
    assert loaded.user_conversations == {"wx_user_1": "conv_111"}
    assert loaded.uin == cfg.uin


def test_config_load_invalid_json_fallback(temp_dir):
    cfg_file = temp_dir / "corrupted_config.json"
    cfg_file.write_text("{invalid_json: true", encoding="utf-8")

    cfg = SidecarConfig.load(cfg_file)
    assert cfg.bot_token == ""
    assert bool(cfg.uin) is True


def test_config_env_var_path(temp_dir, monkeypatch):
    custom_cfg_file = temp_dir / "env_config.json"
    monkeypatch.setenv("WECHAT_SIDECAR_CONFIG", str(custom_cfg_file))

    cfg = SidecarConfig.load()
    assert cfg.config_path == custom_cfg_file


def test_conversation_management(temp_dir):
    cfg_file = temp_dir / "conv_mgmt.json"
    cfg = SidecarConfig.load(cfg_file)

    assert cfg.get_conversation_id("user_1") is None

    cfg.set_conversation_id("user_1", "conv_abc")
    assert cfg.get_conversation_id("user_1") == "conv_abc"

    # Reload from disk
    reloaded = SidecarConfig.load(cfg_file)
    assert reloaded.get_conversation_id("user_1") == "conv_abc"

    # Reset
    cfg.reset_conversation("user_1")
    assert cfg.get_conversation_id("user_1") is None

    reloaded2 = SidecarConfig.load(cfg_file)
    assert reloaded2.get_conversation_id("user_1") is None


def test_conversation_history_recording_and_ordering(temp_dir):
    cfg_file = temp_dir / "history_config.json"
    cfg = SidecarConfig.load(cfg_file)

    cfg.record_conversation("user_1", "conv_1", "Title 1")
    cfg.record_conversation("user_1", "conv_2", "Title 2")
    cfg.record_conversation("user_1", "conv_3", "Title 3")

    recent = cfg.get_recent_conversations("user_1", n=2)
    assert len(recent) == 2
    assert recent[0]["conv_id"] == "conv_3"
    assert recent[0]["title"] == "Title 3"
    assert recent[1]["conv_id"] == "conv_2"
    assert recent[1]["title"] == "Title 2"

    # Updating title of existing conversation in history
    cfg.record_conversation("user_1", "conv_2", "Updated Title 2")
    recent_all = cfg.get_recent_conversations("user_1", n=5)
    assert len(recent_all) == 3
    conv_2_entry = next(c for c in recent_all if c["conv_id"] == "conv_2")
    assert conv_2_entry["title"] == "Updated Title 2"


def test_auth_headers_generation(temp_dir):
    cfg_file = temp_dir / "auth_config.json"
    cfg = SidecarConfig.load(cfg_file)
    cfg.bot_token = "my_jwt_token"
    cfg.bot_agent = "my-custom-agent/2.0"

    headers = cfg.get_auth_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers["AuthorizationType"] == "ilink_bot_token"
    assert headers["Authorization"] == "Bearer my_jwt_token"
    assert headers["bot_agent"] == "my-custom-agent/2.0"
    assert headers["X-WECHAT-UIN"] == cfg.uin
