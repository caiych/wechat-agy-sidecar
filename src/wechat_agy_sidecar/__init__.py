"""
WeChat Antigravity Sidecar
--------------------------
A bridge daemon implementing the WeChat iLink bot protocol to connect
WeChat chats directly with Google Antigravity SDK.
"""

__version__ = "0.1.0"
__all__ = ["AntigravityAgent", "SidecarConfig", "WeChatIlinkClient", "WeChatSidecar"]

from wechat_agy_sidecar.agent import AntigravityAgent
from wechat_agy_sidecar.client import WeChatIlinkClient
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.sidecar import WeChatSidecar
