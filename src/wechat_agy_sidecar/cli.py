"""
Command line interface for the WeChat Antigravity Sidecar.
Supports daemon execution and media downloading/decryption.
"""

from __future__ import annotations

import sys
import logging
import argparse
from pathlib import Path

from wechat_agy_sidecar import __version__
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.sidecar import WeChatSidecar
from wechat_agy_sidecar.media import download_and_decrypt_media


def main():
    parser = argparse.ArgumentParser(
        prog="wechat-agy-sidecar",
        description="WeChat Bridge Sidecar for Google Antigravity"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # 1. Daemon / run options (also top-level defaults)
    daemon_parser = subparsers.add_parser("run", help="Run the WeChat sidecar daemon (default)")
    for p in [parser, daemon_parser]:
        p.add_argument(
            "--config", "-c",
            type=Path,
            default=None,
            help="Path to configuration JSON file (defaults to ~/.gemini/wechat_sidecar_config.json)"
        )
        p.add_argument(
            "--login",
            action="store_true",
            help="Force interactive QR code onboarding login"
        )
        p.add_argument(
            "--system-prompt",
            type=str,
            default=None,
            help="Custom system instructions for Antigravity Agent"
        )
        p.add_argument(
            "--debug",
            action="store_true",
            help="Enable debug logging level"
        )

    # 2. download-media subcommand
    dl_parser = subparsers.add_parser("download-media", help="Download and decrypt WeChat CDN media payload")
    dl_parser.add_argument("--url", "-u", required=True, help="Encrypted media URL from Tencent CDN")
    dl_parser.add_argument("--key", "-k", required=True, help="AES decryption key (hex or base64)")
    dl_parser.add_argument("--output", "-o", required=False, default=None, help="Output destination file path")

    args = parser.parse_args()

    # Logging setup
    log_level = logging.DEBUG if getattr(args, "debug", False) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if args.subcommand == "download-media":
        print(f"Downloading and decrypting media from {args.url[:60]}...")
        saved = download_and_decrypt_media(args.url, args.key, args.output)
        if saved:
            print(f"✅ Successfully decrypted and saved media to: {saved.resolve()}")
            sys.exit(0)
        else:
            print("❌ Failed to download or decrypt media.", file=sys.stderr)
            sys.exit(1)

    # Default to running sidecar daemon
    config = SidecarConfig.load(getattr(args, "config", None))
    if getattr(args, "system_prompt", None):
        config.system_instructions = args.system_prompt

    sidecar = WeChatSidecar(config)

    if getattr(args, "login", False):
        success = sidecar.run_onboarding_login()
        sys.exit(0 if success else 1)
    else:
        sidecar.start()


if __name__ == "__main__":
    main()
