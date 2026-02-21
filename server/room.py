"""
NexusChat 房间/群组管理模块
=========================

实现聊天室和群组功能。
"""

import time
import secrets
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from .auth import User
from .storage import StorageManager


@dataclass
class Room:
    """房间数据类"""
    id: str
    name: str
    owner_id: str
    created_at: float = field(default_factory=time.time)
    is_public: bool = True
    members: Set[str] = field(default_factory=set)
    max_members: int = 500
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
            "is_public": self.is_public,
            "members": list(self.members),
            "member_count": len(self.members),
            "max_members": self.max_members,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Room":
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            owner_id=data.get("owner_id", ""),
            created_at=data.get("created_at", time.time()),
            is_public=data.get("is_public", True),
            members=set(data.get("members", [])),
            max_members=data.get("max_members", 500),
            metadata=data.get("metadata", {})
        )


class RoomManager:
    """
    房间管理器
    
    功能:
    - 创建房间
    - 加入/离开房间
    - 房间列表
    - 成员管理
    """
    
    def __init__(self, storage: StorageManager):
        self.storage = storage
        self.rooms: Dict[str, Room] = {}  # 内存缓存
    
    async def create_room(
        self,
        name: str,
        owner: User,
        is_public: bool = True,
        max_members: int = 500
    ) -> Optional[Room]:
        """
        创建房间
        
        Args:
            name: 房间名称
            owner: 创建者
            is_public: 是否公开
            max_members: 最大成员数
            
        Returns:
            成功返回 Room，失败返回 None
        """
        room_id = self._generate_room_id(name, owner.id)
        
        room = Room(
            id=room_id,
            name=name,
            owner_id=owner.id,
            is_public=is_public,
            max_members=max_members,
            members={owner.id}  # 创建者自动加入
        )
        
        # 保存到存储
        await self.storage.save_room(room)
        self.rooms[room_id] = room
        
        return room
    
    async def get_room(self, room_id: str) -> Optional[Room]:
        """获取房间信息"""
        # 先查缓存
        if room_id in self.rooms:
            return self.rooms[room_id]
        
        # 查存储
        room = await self.storage.get_room(room_id)
        if room:
            self.rooms[room_id] = room
        
        return room
    
    async def join_room(self, room: Room, user: User) -> bool:
        """
        加入房间
        
        Args:
            room: 房间
            user: 用户
            
        Returns:
            成功返回 True
        """
        if user.id in room.members:
            return True  # 已在房间内
        
        if len(room.members) >= room.max_members:
            return False  # 房间已满
        
        room.members.add(user.id)
        await self.storage.save_room(room)
        
        return True
    
    async def leave_room(self, room: Room, user_id: str) -> bool:
        """
        离开房间
        
        Args:
            room: 房间
            user_id: 用户 ID
            
        Returns:
            成功返回 True
        """
        if user_id not in room.members:
            return False
        
        room.members.discard(user_id)
        await self.storage.save_room(room)
        
        # 如果房间为空且不是持久化的，可以删除
        if len(room.members) == 0:
            del self.rooms[room.id]
        
        return True
    
    async def list_rooms(
        self,
        public_only: bool = True
    ) -> List[Room]:
        """获取房间列表"""
        rooms = await self.storage.list_rooms()
        
        if public_only:
            rooms = [r for r in rooms if r.is_public]
        
        return rooms
    
    async def get_room_members(self, room: Room) -> List[User]:
        """获取房间成员列表"""
        members = []
        for member_id in room.members:
            user = await self.storage.get_user(member_id)
            if user:
                members.append(user)
        return members
    
    def _generate_room_id(self, name: str, owner_id: str) -> str:
        """生成房间 ID"""
        unique = f"{name}{owner_id}{time.time()}{secrets.token_hex(4)}"
        return "room_" + hashlib.sha256(unique.encode("utf-8")).hexdigest()[:12]
