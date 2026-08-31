"""
Command line interface for the WeChat Antigravity Sidecar.
"""

from __future__ import annotations

import sys
import logging
import argparse
from pathlib import Path

from wechat_agy_sidecar import __version__
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.sidecar import WeChatSidecar


def main():
    parser = argparse.ArgumentParser(
        prog="wechat-agy-sidecar",
        description="WeChat Bridge Sidecar for Google Antigravity SDK"
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=None,
        help="Path to configuration JSON file (defaults to ~/.gemini/wechat_sidecar_config.json)"
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Force interactive QR code onboarding login"
    )
    parser.add_argument(
        "--system-prompt",
        type=str,
        default=None,
        help="Custom system instructions for Antigravity Agent"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging level"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    args = parser.parse_args()

    # Logging setup
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    config = SidecarConfig.load(args.config)
    if args.system_prompt:
        config.system_instructions = args.system_prompt

    sidecar = WeChatSidecar(config)

    if args.login:
        success = sidecar.run_onboarding_login()
        sys.exit(0 if success else 1)
    else:
        sidecar.start()


if __name__ == "__main__":
    main()
