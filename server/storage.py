"""
NexusChat 存储管理模块
=====================

支持多种存储后端：
- JSON 文件存储（默认，零依赖）
- SQLite 存储（可选，生产推荐）

提供统一的接口用于存储用户、房间、消息等数据。
"""

import json
import asyncio
import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from dataclasses import asdict
from contextlib import contextmanager

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
    
    支持后端:
    - JSON (默认，适合开发和测试)
    - SQLite (推荐用于生产环境，支持事务和并发)
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
        
        # 锁
        self._lock = asyncio.Lock()
        
        if self.storage_type == "sqlite":
            self._init_sqlite()
        else:
            self._init_json()
    
    def _init_json(self) -> None:
        """初始化 JSON 存储"""
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
        
        # 加载数据
        self._load_all()
    
    def _init_sqlite(self) -> None:
        """初始化 SQLite 存储"""
        self.db_path = self.data_dir / "nexuschat.db"
        self._create_tables()
        self._load_to_cache()
    
    @contextmanager
    def _get_db_connection(self):
        """获取数据库连接上下文管理器"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _create_tables(self) -> None:
        """创建数据库表"""
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen REAL,
                    status TEXT DEFAULT 'offline'
                )
            """)
            
            # 密码表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS passwords (
                    user_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            
            # 房间表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    public INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (owner_id) REFERENCES users(id)
                )
            """)
            
            # 房间成员表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS room_members (
                    room_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    joined_at REAL NOT NULL,
                    PRIMARY KEY (room_id, user_id),
                    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            
            # 私聊消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user TEXT NOT NULL,
                    to_user TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    delivered INTEGER DEFAULT 0
                )
            """)
            
            # 房间消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS room_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    from_user TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
                )
            """)
            
            # 离线消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS offline_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    from_user TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            
            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(from_user, to_user)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_messages_room ON room_messages(room_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_offline_messages_user ON offline_messages(user_id)")
    
    def _load_to_cache(self) -> None:
        """从 SQLite 加载数据到内存缓存"""
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 加载用户
            cursor.execute("SELECT * FROM users")
            self._users = {row['id']: dict(row) for row in cursor.fetchall()}
            
            # 加载密码
            cursor.execute("SELECT * FROM passwords")
            self._passwords = {row['user_id']: row['password_hash'] for row in cursor.fetchall()}
            
            # 加载房间
            cursor.execute("SELECT * FROM rooms")
            self._rooms = {row['id']: dict(row) for row in cursor.fetchall()}
    
    def _load_all(self) -> None:
        """加载所有数据 (JSON 后端)"""
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
            if self.storage_type == "sqlite":
                # SQLite 已经实时保存，无需额外操作
                pass
            else:
                self._save_json(self.users_file, self._users)
                self._save_json(self.passwords_file, self._passwords)
                self._save_json(self.rooms_file, self._rooms)
    
    # ========== 用户操作 ==========

    async def save_user(self, user: "User") -> None:
        """保存用户"""
        async with self._lock:
            user_dict = user.to_dict()
            if self.storage_type == "sqlite":
                with self._get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO users (id, username, created_at, last_seen, status)
                        VALUES (?, ?, ?, ?, ?)
                    """, (user.id, user.username, user.created_at, user.last_login, 'online' if user.is_online else 'offline'))
            else:
                self._users[user.id] = user_dict
                self._save_json(self.users_file, self._users)

    async def get_user(self, user_id: str) -> Optional["User"]:
        """获取用户"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                row = cursor.fetchone()
                if row:
                    return self.User.from_dict(dict(row))
            return None
        else:
            if user_id in self._users:
                return self.User.from_dict(self._users[user_id])
            return None

    async def get_user_by_username(self, username: str) -> Optional["User"]:
        """通过用户名获取用户"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
                row = cursor.fetchone()
                if row:
                    return self.User.from_dict(dict(row))
            return None
        else:
            for user_data in self._users.values():
                if user_data.get("username") == username:
                    return self.User.from_dict(user_data)
            return None
    
    # ========== 密码操作 ==========
    
    async def save_password(self, user_id: str, hashed: str) -> None:
        """保存密码哈希"""
        async with self._lock:
            if self.storage_type == "sqlite":
                with self._get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO passwords (user_id, password_hash)
                        VALUES (?, ?)
                    """, (user_id, hashed))
            else:
                self._passwords[user_id] = hashed
                self._save_json(self.passwords_file, self._passwords)
    
    async def get_password(self, user_id: str) -> Optional[str]:
        """获取密码哈希"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT password_hash FROM passwords WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                return row['password_hash'] if row else None
        else:
            return self._passwords.get(user_id)
    
    # ========== 房间操作 ==========
    
    async def save_room(self, room: "Room") -> None:
        """保存房间"""
        async with self._lock:
            room_data = room.to_dict()
            if self.storage_type == "sqlite":
                with self._get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO rooms (id, name, owner_id, public, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (room.id, room.name, room.owner_id, 1 if room.is_public else 0, room.created_at))
                    
                    # 更新成员
                    cursor.execute("DELETE FROM room_members WHERE room_id = ?", (room.id,))
                    for member_id in room.members:
                        cursor.execute("""
                            INSERT INTO room_members (room_id, user_id, joined_at)
                            VALUES (?, ?, ?)
                        """, (room.id, member_id, time.time()))
            else:
                # 转换 set 为 list 以便 JSON 序列化
                room_data["members"] = list(room.members)
                self._rooms[room.id] = room_data
                self._save_json(self.rooms_file, self._rooms)

    async def get_room(self, room_id: str) -> Optional["Room"]:
        """获取房间"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
                row = cursor.fetchone()
                if row:
                    room_data = dict(row)
                    # 加载成员
                    cursor.execute("SELECT user_id FROM room_members WHERE room_id = ?", (room_id,))
                    room_data["members"] = {r['user_id'] for r in cursor.fetchall()}
                    return self.Room.from_dict(room_data)
            return None
        else:
            if room_id in self._rooms:
                # 复制字典避免修改原始数据
                room_data = self._rooms[room_id].copy()
                room_data["members"] = set(room_data.get("members", []))
                return self.Room.from_dict(room_data)
            return None

    async def list_rooms(self) -> List["Room"]:
        """列出所有房间"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM rooms")
                rooms = []
                for row in cursor.fetchall():
                    room_data = dict(row)
                    cursor.execute("SELECT user_id FROM room_members WHERE room_id = ?", (room_data['id'],))
                    room_data["members"] = {r['user_id'] for r in cursor.fetchall()}
                    rooms.append(self.Room.from_dict(room_data))
                return rooms
        else:
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
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (from_user, to_user, content, timestamp, delivered)
                    VALUES (?, ?, ?, ?, ?)
                """, (from_user, to_user, message.get('content', ''), message.get('timestamp', time.time()), 0))
        else:
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
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT from_user, to_user, content, timestamp, delivered
                    FROM messages
                    WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (user1, user2, user2, user1, limit))
                return [dict(row) for row in cursor.fetchall()][::-1]
        else:
            pair_id = "_".join(sorted([user1, user2]))
            messages_file = self.messages_dir / f"{pair_id}.json"
            
            messages = self._load_json(messages_file)
            return messages.get("messages", [])[-limit:]
    
    # ========== 离线消息 ==========
    
    async def save_offline_message(self, user_id: str, message: Dict) -> None:
        """保存离线消息"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO offline_messages (user_id, from_user, content, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (user_id, message.get('from', ''), message.get('content', ''), message.get('timestamp', time.time())))
        else:
            offline_file = self.offline_dir / f"{user_id}.json"
            
            messages = self._load_json(offline_file)
            if "messages" not in messages:
                messages["messages"] = []
            
            messages["messages"].append(message)
            self._save_json(offline_file, messages)
    
    async def get_offline_messages(self, user_id: str) -> List[Dict]:
        """获取离线消息"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT from_user, content, timestamp
                    FROM offline_messages
                    WHERE user_id = ?
                    ORDER BY timestamp ASC
                """, (user_id,))
                return [dict(row) for row in cursor.fetchall()]
        else:
            offline_file = self.offline_dir / f"{user_id}.json"
            
            messages = self._load_json(offline_file)
            return messages.get("messages", [])
    
    async def clear_offline_messages(self, user_id: str) -> None:
        """清除已读取的离线消息"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM offline_messages WHERE user_id = ?", (user_id,))
        else:
            offline_file = self.offline_dir / f"{user_id}.json"
            if offline_file.exists():
                offline_file.unlink()
    
    # ========== 房间消息 ==========
    
    async def save_room_message(self, room_id: str, message: Dict) -> None:
        """保存房间消息"""
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO room_messages (room_id, from_user, content, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (room_id, message.get('from', ''), message.get('content', ''), message.get('timestamp', time.time())))
        else:
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
        if self.storage_type == "sqlite":
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT room_id, from_user, content, timestamp
                    FROM room_messages
                    WHERE room_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (room_id, limit))
                return [dict(row) for row in cursor.fetchall()][::-1]
        else:
            room_file = self.room_messages_dir / f"{room_id}.json"
            
            messages = self._load_json(room_file)
            return messages.get("messages", [])[-limit:]
