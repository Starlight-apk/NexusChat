"""
NexusChat - 新一代轻量级聊天服务器框架
=====================================

一个高性能、易部署、零依赖的即时通讯服务器框架。
"""

__version__ = "1.0.0"
__author__ = "NexusChat Team"

from .core import NexusChatServer
from .protocol import ProtocolHandler, Message, MessageType
from .auth import AuthManager, User
from .room import RoomManager, Room

__all__ = [
    "NexusChatServer",
    "ProtocolHandler",
    "Message",
    "MessageType",
    "AuthManager",
    "User",
    "RoomManager",
    "Room",
]
