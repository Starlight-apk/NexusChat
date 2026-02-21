"""
NexusChat 认证和用户管理模块
==========================

处理用户注册、认证和会话管理。
"""

import hashlib
import time
import secrets
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from .storage import StorageManager


@dataclass
class User:
    """用户数据类"""
    id: str
    username: str
    email: str = ""
    created_at: float = field(default_factory=time.time)
    last_login: float = 0
    is_online: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典（不包含敏感信息）"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at,
            "last_login": self.last_login,
            "is_online": self.is_online,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "User":
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            username=data.get("username", ""),
            email=data.get("email", ""),
            created_at=data.get("created_at", time.time()),
            last_login=data.get("last_login", 0),
            is_online=data.get("is_online", False),
            metadata=data.get("metadata", {})
        )


class AuthManager:
    """
    认证管理器
    
    功能:
    - 用户注册
    - 用户认证
    - 密码哈希
    - 用户查询
    """
    
    def __init__(self, storage: StorageManager):
        self.storage = storage
        self._password_salt = "nexuschat_v1_salt"  # 简单盐值，生产环境应使用随机盐
    
    def _hash_password(self, password: str, salt: Optional[str] = None) -> str:
        """
        哈希密码
        
        使用 SHA-256 + 盐值进行哈希
        生产环境建议使用 bcrypt 或 argon2
        """
        if salt is None:
            salt = self._password_salt
        
        # 尝试使用 bcrypt（如果可用）
        try:
            import bcrypt
            return bcrypt.hashpw(
                password.encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8")
        except ImportError:
            pass
        
        # 降级到 SHA-256
        salted = f"{salt}{password}{salt}"
        return hashlib.sha256(salted.encode("utf-8")).hexdigest()
    
    def _verify_password(
        self,
        password: str,
        hashed: str,
        salt: Optional[str] = None
    ) -> bool:
        """验证密码"""
        # 尝试 bcrypt
        if hashed.startswith("$2"):
            try:
                import bcrypt
                return bcrypt.checkpw(
                    password.encode("utf-8"),
                    hashed.encode("utf-8")
                )
            except ImportError:
                pass
        
        # SHA-256 验证
        return self._hash_password(password, salt) == hashed
    
    async def register(
        self,
        username: str,
        password: str,
        email: str = ""
    ) -> Optional[User]:
        """
        注册新用户
        
        Args:
            username: 用户名
            password: 密码
            email: 邮箱（可选）
            
        Returns:
            成功返回 User，失败返回 None
        """
        # 检查用户名是否存在
        existing = await self.storage.get_user_by_username(username)
        if existing:
            return None
        
        # 生成用户 ID
        user_id = self._generate_user_id(username)
        
        # 创建用户
        user = User(
            id=user_id,
            username=username,
            email=email,
            created_at=time.time()
        )
        
        # 存储用户和密码
        await self.storage.save_user(user)
        await self.storage.save_password(user_id, self._hash_password(password))
        
        return user
    
    async def authenticate(
        self,
        username: str,
        password: str
    ) -> Optional[User]:
        """
        认证用户
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            认证成功返回 User，失败返回 None
        """
        user = await self.storage.get_user_by_username(username)
        if not user:
            return None
        
        # 验证密码
        stored_hash = await self.storage.get_password(user.id)
        if not stored_hash:
            return None
        
        if not self._verify_password(password, stored_hash):
            return None
        
        # 更新最后登录时间
        user.last_login = time.time()
        await self.storage.save_user(user)
        
        return user
    
    async def get_user(self, user_id: str) -> Optional[User]:
        """获取用户信息"""
        return await self.storage.get_user(user_id)
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """通过用户名获取用户"""
        return await self.storage.get_user_by_username(username)
    
    def _generate_user_id(self, username: str) -> str:
        """生成用户 ID"""
        # 使用用户名 + 时间戳生成唯一 ID
        unique = f"{username}{time.time()}{secrets.token_hex(4)}"
        return hashlib.sha256(unique.encode("utf-8")).hexdigest()[:16]
