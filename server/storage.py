"""
NexusChat 存储管理模块
=====================

支持多种存储后端：
- JSON 文件存储（默认，零依赖）
- SQLite 存储（可选）

提供统一的接口用于存储用户、房间、消息等数据。
"""

import json
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from dataclasses import asdict

if TYPE_CHECKING:
    from .auth import User
    from .room import Room


class StorageManager:
    """
    存储管理器
    
    功能:
    - 用户数据存储
    - 密码存储
    - 房间数据存储
    - 消息历史存储
    - 离线消息存储
    """
    
    def __init__(self, config: Dict):
        # 延迟导入避免循环引用
        from .auth import User
        from .room import Room
        self.User = User
        self.Room = Room
        self.config = config
        storage_config = config.get("storage", {})
        self.data_dir = Path(storage_config.get("data_dir", "data"))
        self.storage_type = storage_config.get("type", "json")
        
        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件路径
        self.users_file = self.data_dir / "users.json"
        self.passwords_file = self.data_dir / "passwords.json"
        self.rooms_file = self.data_dir / "rooms.json"
        self.messages_dir = self.data_dir / "messages"
        self.offline_dir = self.data_dir / "offline"
        self.room_messages_dir = self.data_dir / "room_messages"
        
        # 创建目录
        self.messages_dir.mkdir(exist_ok=True)
        self.offline_dir.mkdir(exist_ok=True)
        self.room_messages_dir.mkdir(exist_ok=True)
        
        # 内存缓存
        self._users: Dict[str, Dict] = {}
        self._passwords: Dict[str, str] = {}
        self._rooms: Dict[str, Dict] = {}
        
        # 锁
        self._lock = asyncio.Lock()
        
        # 加载数据
        self._load_all()
    
    def _load_all(self) -> None:
        """加载所有数据"""
        self._users = self._load_json(self.users_file)
        self._passwords = self._load_json(self.passwords_file)
        self._rooms = self._load_json(self.rooms_file)
    
    def _load_json(self, path: Path) -> Dict:
        """加载 JSON 文件"""
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    
    def _save_json(self, path: Path, data: Dict) -> None:
        """保存 JSON 文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    async def save_all(self) -> None:
        """保存所有数据"""
        async with self._lock:
            self._save_json(self.users_file, self._users)
            self._save_json(self.passwords_file, self._passwords)
            self._save_json(self.rooms_file, self._rooms)
    
    # ========== 用户操作 ==========

    async def save_user(self, user: "User") -> None:
        """保存用户"""
        async with self._lock:
            self._users[user.id] = user.to_dict()
            self._save_json(self.users_file, self._users)

    async def get_user(self, user_id: str) -> Optional["User"]:
        """获取用户"""
        if user_id in self._users:
            return self.User.from_dict(self._users[user_id])
        return None

    async def get_user_by_username(self, username: str) -> Optional["User"]:
        """通过用户名获取用户"""
        for user_data in self._users.values():
            if user_data.get("username") == username:
                return self.User.from_dict(user_data)
        return None
    
    # ========== 密码操作 ==========
    
    async def save_password(self, user_id: str, hashed: str) -> None:
        """保存密码哈希"""
        async with self._lock:
            self._passwords[user_id] = hashed
            self._save_json(self.passwords_file, self._passwords)
    
    async def get_password(self, user_id: str) -> Optional[str]:
        """获取密码哈希"""
        return self._passwords.get(user_id)
    
    # ========== 房间操作 ==========
    
    async def save_room(self, room: "Room") -> None:
        """保存房间"""
        async with self._lock:
            room_data = room.to_dict()
            # 转换 set 为 list 以便 JSON 序列化
            room_data["members"] = list(room.members)
            self._rooms[room.id] = room_data
            self._save_json(self.rooms_file, self._rooms)

    async def get_room(self, room_id: str) -> Optional["Room"]:
        """获取房间"""
        if room_id in self._rooms:
            # 复制字典避免修改原始数据
            room_data = self._rooms[room_id].copy()
            room_data["members"] = set(room_data.get("members", []))
            return self.Room.from_dict(room_data)
        return None

    async def list_rooms(self) -> List["Room"]:
        """列出所有房间"""
        rooms = []
        for room_data in self._rooms.values():
            # 复制字典避免修改原始数据
            room_data_copy = room_data.copy()
            room_data_copy["members"] = set(room_data_copy.get("members", []))
            rooms.append(self.Room.from_dict(room_data_copy))
        return rooms
    
    # ========== 消息操作 ==========
    
    async def save_message(
        self,
        from_user: str,
        to_user: str,
        message: Dict
    ) -> None:
        """保存私聊消息"""
        # 为每对用户创建消息文件
        pair_id = "_".join(sorted([from_user, to_user]))
        messages_file = self.messages_dir / f"{pair_id}.json"
        
        messages = self._load_json(messages_file)
        if "messages" not in messages:
            messages["messages"] = []
        
        messages["messages"].append(message)
        
        # 限制历史消息数量
        max_history = self.config.get("message", {}).get("history_size", 100)
        messages["messages"] = messages["messages"][-max_history:]
        
        self._save_json(messages_file, messages)
    
    async def get_message_history(
        self,
        user1: str,
        user2: str,
        limit: int = 50
    ) -> List[Dict]:
        """获取消息历史"""
        pair_id = "_".join(sorted([user1, user2]))
        messages_file = self.messages_dir / f"{pair_id}.json"
        
        messages = self._load_json(messages_file)
        return messages.get("messages", [])[-limit:]
    
    # ========== 离线消息 ==========
    
    async def save_offline_message(self, user_id: str, message: Dict) -> None:
        """保存离线消息"""
        offline_file = self.offline_dir / f"{user_id}.json"
        
        messages = self._load_json(offline_file)
        if "messages" not in messages:
            messages["messages"] = []
        
        messages["messages"].append(message)
        self._save_json(offline_file, messages)
    
    async def get_offline_messages(self, user_id: str) -> List[Dict]:
        """获取离线消息"""
        offline_file = self.offline_dir / f"{user_id}.json"
        
        messages = self._load_json(offline_file)
        return messages.get("messages", [])
    
    async def clear_offline_messages(self, user_id: str) -> None:
        """清除已读取的离线消息"""
        offline_file = self.offline_dir / f"{user_id}.json"
        if offline_file.exists():
            offline_file.unlink()
    
    # ========== 房间消息 ==========
    
    async def save_room_message(self, room_id: str, message: Dict) -> None:
        """保存房间消息"""
        room_file = self.room_messages_dir / f"{room_id}.json"
        
        messages = self._load_json(room_file)
        if "messages" not in messages:
            messages["messages"] = []
        
        messages["messages"].append(message)
        
        # 限制历史消息数量
        max_history = self.config.get("message", {}).get("history_size", 100)
        messages["messages"] = messages["messages"][-max_history:]
        
        self._save_json(room_file, messages)
    
    async def get_room_history(
        self,
        room_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """获取房间消息历史"""
        room_file = self.room_messages_dir / f"{room_id}.json"
        
        messages = self._load_json(room_file)
        return messages.get("messages", [])[-limit:]
