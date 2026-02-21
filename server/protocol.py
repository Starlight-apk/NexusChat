"""
NexusChat 协议处理模块
=====================

定义轻量级的 JSON 行协议，类似于 XMPP 但更简洁。

协议格式:
- 每条消息为独立的 JSON 对象
- 消息之间用换行符分隔
- 支持批量发送（多个 JSON 用换行分隔）

消息类型:
- 认证：auth, register, auth_success, register_success
- 消息：message, room_message
- 房间：room_create, room_join, room_leave, room_created, room_joined, room_left
- 状态：presence, ping, pong
- 错误：error
"""

import json
import time
import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional


class MessageType(str, Enum):
    """消息类型枚举"""
    # 认证
    AUTH = "auth"
    REGISTER = "register"
    AUTH_SUCCESS = "auth_success"
    REGISTER_SUCCESS = "register_success"
    
    # 消息
    MESSAGE = "message"
    
    # 房间
    ROOM_CREATE = "room_create"
    ROOM_JOIN = "room_join"
    ROOM_LEAVE = "room_leave"
    ROOM_CREATED = "room_created"
    ROOM_JOINED = "room_joined"
    ROOM_LEFT = "room_left"
    ROOM_MESSAGE = "room_message"
    ROOM_MESSAGE_SENT = "room_message_sent"
    ROOM_MEMBER_JOIN = "room_member_join"
    ROOM_MEMBER_LEAVE = "room_member_leave"
    ROOM_LIST = "room_list"
    
    # 状态
    PRESENCE = "presence"
    PING = "ping"
    PONG = "pong"
    WHOAMI = "whoami"
    USERS = "users"
    
    # 系统
    WELCOME = "welcome"
    ERROR = "error"


@dataclass
class Message:
    """消息数据类"""
    type: str
    content: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
            **self.extra
        }
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class ProtocolHandler:
    """
    协议处理器
    
    负责消息的编码和解码
    """
    
    def __init__(self):
        self.buffer: Dict[int, bytes] = {}  # 按连接 ID 缓冲不完整的数据
    
    def encode(self, data: Dict) -> bytes:
        """
        编码消息为字节

        Args:
            data: 消息字典

        Returns:
            编码后的字节数据（带换行符）
        """
        data["timestamp"] = data.get("timestamp", time.time())
        
        # 自定义 JSON 编码器，处理 set 等特殊类型
        def json_default(obj):
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, bytes):
                return obj.decode("utf-8", errors="replace")
            return str(obj)
        
        json_str = json.dumps(data, ensure_ascii=False, default=json_default)
        return (json_str + "\n").encode("utf-8")
    
    def decode(self, data: bytes) -> List[Dict]:
        """
        解码字节数据为消息列表
        
        Args:
            data: 原始字节数据
            
        Returns:
            消息字典列表
        """
        messages = []
        
        # 处理可能的缓冲数据
        text = data.decode("utf-8")
        lines = text.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            try:
                msg = json.loads(line)
                messages.append(msg)
            except json.JSONDecodeError as e:
                raise ValueError(f"无效的 JSON 格式：{e}")
        
        return messages
    
    def error(self, message: str) -> bytes:
        """生成错误消息"""
        return self.encode({
            "type": "error",
            "message": message,
            "timestamp": time.time()
        })
    
    def create_message(
        self,
        msg_type: MessageType,
        content: Optional[str] = None,
        **kwargs
    ) -> bytes:
        """创建指定类型的消息"""
        data = {
            "type": msg_type.value,
            "timestamp": time.time()
        }
        if content:
            data["content"] = content
        data.update(kwargs)
        return self.encode(data)
