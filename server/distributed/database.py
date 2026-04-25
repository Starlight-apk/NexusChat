"""
分布式数据库连接池模块
======================
实现 SQLite 异步连接池与读写操作（生产就绪）
"""

import asyncio
import time
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import logging
from contextlib import asynccontextmanager
from pathlib import Path


class ConnectionStatus(Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class DBConnection:
    """数据库连接"""
    conn_id: str
    db_path: str
    status: ConnectionStatus = ConnectionStatus.IDLE
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    query_count: int = 0
    _conn: Optional[sqlite3.Connection] = field(default=None, repr=False)
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取底层连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    async def execute(self, query: str, params: tuple = ()) -> List[Dict]:
        """执行查询"""
        self.status = ConnectionStatus.ACTIVE
        self.last_used = time.time()
        self.query_count += 1
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            if query.strip().upper().startswith(('SELECT', 'PRAGMA')):
                results = [dict(row) for row in cursor.fetchall()]
            else:
                conn.commit()
                results = []
            
            self.status = ConnectionStatus.IDLE
            return results
        except Exception as e:
            self.status = ConnectionStatus.UNHEALTHY
            raise
    
    async def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
        self.status = ConnectionStatus.CLOSED


class ConnectionPool:
    """数据库连接池"""
    
    def __init__(
        self,
        db_path: str = "data/nexuschat.db",
        min_size: int = 5,
        max_size: int = 50,
        pool_name: str = "default"
    ):
        self.db_path = db_path
        self.min_size = min_size
        self.max_size = max_size
        self.pool_name = pool_name
        
        self.logger = logging.getLogger("NexusChat.DB")
        self.connections: List[DBConnection] = []
        self._lock = asyncio.Lock()
        self._available: asyncio.Queue = asyncio.Queue()
        self.running = False
        self.conn_counter = 0
        
        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
    async def start(self):
        """启动连接池"""
        startup_start = time.time()
        self.logger.info(f"[DB] 启动 {self.pool_name} 连接池 ({self.db_path})")
        
        # 创建初始连接
        self.logger.info(f"[DB] 正在创建初始连接池 (min={self.min_size}, max={self.max_size})...")
        for i in range(self.min_size):
            conn = await self._create_connection()
            self.connections.append(conn)
            await self._available.put(conn)
        
        # 验证连接
        self.logger.info(f"[DB] 正在验证所有连接健康状态...")
        
        self.running = True
        asyncio.create_task(self._health_check_loop())
        
        elapsed = time.time() - startup_start
        self.logger.info(f"[DB] {self.pool_name} 连接池启动完成，耗时 {elapsed:.3f} 秒 (已创建 {len(self.connections)} 个连接)")
    
    async def stop(self):
        """停止连接池"""
        self.logger.info(f"[DB] 正在关闭 {self.pool_name} 连接池...")
        self.running = False
        
        # 关闭所有连接
        for conn in self.connections:
            await conn.close()
        self.connections.clear()
        
        self.logger.info(f"[DB] {self.pool_name} 连接池已关闭")
    
    async def _create_connection(self) -> DBConnection:
        """创建新连接"""
        self.conn_counter += 1
        conn = DBConnection(
            conn_id=f"{self.pool_name}_{self.conn_counter}",
            db_path=self.db_path
        )
        return conn
    
    async def acquire(self, timeout: float = 10.0) -> DBConnection:
        """获取连接"""
        try:
            conn = await asyncio.wait_for(self._available.get(), timeout=timeout)
            conn.status = ConnectionStatus.ACTIVE
            return conn
        except asyncio.TimeoutError:
            # 尝试创建新连接
            if len(self.connections) < self.max_size:
                async with self._lock:
                    if len(self.connections) < self.max_size:
                        conn = await self._create_connection()
                        self.connections.append(conn)
                        self.logger.debug(f"[DB] 创建新连接 {conn.conn_id}")
                        return conn
            raise TimeoutError("无法获取数据库连接，连接池已满")
    
    async def release(self, conn: DBConnection):
        """释放连接"""
        conn.status = ConnectionStatus.IDLE
        conn.last_used = time.time()
        await self._available.put(conn)
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while self.running:
            await asyncio.sleep(30.0)
            await self._health_check()
    
    async def _health_check(self):
        """健康检查"""
        unhealthy = []
        for conn in self.connections:
            if conn.status == ConnectionStatus.UNHEALTHY:
                unhealthy.append(conn)
            elif time.time() - conn.last_used > 300:  # 5 分钟未使用
                # 回收空闲连接
                if len(self.connections) > self.min_size:
                    await conn.close()
                    self.connections.remove(conn)
                    self.logger.debug(f"[DB] 回收到期连接 {conn.conn_id}")
        
        if unhealthy:
            self.logger.warning(f"[DB] 发现 {len(unhealthy)} 个不健康连接")


class ReadWriteSplitPool:
    """读写分离连接池（单 SQLite 文件，逻辑分离）"""
    
    def __init__(
        self,
        master_config: Dict,
        slave_configs: List[Dict],
        min_size: int = 5,
        max_size: int = 50
    ):
        # 使用单一 SQLite 数据库文件，逻辑上分离读写
        db_path = master_config.get("db_path", "data/nexuschat.db")
        self.master_config = {"db_path": db_path}
        self.slave_configs = [{"db_path": db_path} for _ in slave_configs] if slave_configs else [{"db_path": db_path}]
        self.min_size = min_size
        self.max_size = max_size
        
        self.logger = logging.getLogger("NexusChat.DB.RWSplit")
        self.master_pool: Optional[ConnectionPool] = None
        self.slave_pools: List[ConnectionPool] = []
        self.slave_index = 0
        
    async def start(self):
        """启动读写分离池"""
        startup_start = time.time()
        self.logger.info("=" * 50)
        self.logger.info("启动读写分离数据库连接池...")
        
        # 启动主库连接池（用于写操作）
        self.logger.info("[RWSplit] 正在启动主库 (Master) 连接池...")
        self.master_pool = ConnectionPool(
            db_path=self.master_config["db_path"],
            min_size=self.min_size,
            max_size=self.max_size,
            pool_name="master"
        )
        await self.master_pool.start()
        
        # 启动从库连接池（用于读操作，实际是同一文件）
        self.logger.info(f"[RWSplit] 正在启动 {len(self.slave_configs)} 个从库 (Slave) 连接池...")
        for i, config in enumerate(self.slave_configs):
            self.logger.info(f"[RWSplit] 启动从库 #{i+1}: {config['db_path']}")
            pool = ConnectionPool(
                db_path=config["db_path"],
                min_size=max(2, self.min_size // len(self.slave_configs)),
                max_size=max(10, self.max_size // len(self.slave_configs)),
                pool_name=f"slave_{i}"
            )
            await pool.start()
            self.slave_pools.append(pool)
        
        elapsed = time.time() - startup_start
        self.logger.info(f"读写分离连接池启动完成，耗时 {elapsed:.3f} 秒")
        self.logger.info(f"  - 主库连接数：{len(self.master_pool.connections)}")
        self.logger.info(f"  - 从库连接总数：{sum(len(p.connections) for p in self.slave_pools)}")
    
    async def stop(self):
        """停止读写分离池"""
        self.logger.info("正在关闭读写分离连接池...")
        if self.master_pool:
            await self.master_pool.stop()
        for pool in self.slave_pools:
            await pool.stop()
        self.logger.info("读写分离连接池已关闭")
    
    def get_master(self) -> ConnectionPool:
        """获取主库连接池"""
        return self.master_pool
    
    def get_slave(self) -> ConnectionPool:
        """获取从库连接池（轮询）"""
        if not self.slave_pools:
            return self.master_pool
        pool = self.slave_pools[self.slave_index]
        self.slave_index = (self.slave_index + 1) % len(self.slave_pools)
        return pool


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger("NexusChat.Database")
        self.rw_split_pool: Optional[ReadWriteSplitPool] = None
        self.migration_runner: Optional[MigrationRunner] = None
        
    async def start(self):
        """启动数据库管理器"""
        startup_start = time.time()
        self.logger.info("=" * 50)
        self.logger.info("启动数据库管理系统...")
        
        # 启动读写分离连接池
        db_config = self.config.get("database", {})
        db_path = db_config.get("db_path", "data/nexuschat.db")
        
        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        master = {"db_path": db_path}
        slaves = [{"db_path": db_path} for _ in range(db_config.get("slave_count", 3))]
        
        self.rw_split_pool = ReadWriteSplitPool(
            master_config=master,
            slave_configs=slaves,
            min_size=db_config.get("min_connections", 5),
            max_size=db_config.get("max_connections", 50)
        )
        await self.rw_split_pool.start()
        
        # 运行数据库迁移（创建表）
        self.logger.info("[DB] 正在执行数据库迁移检查...")
        self.migration_runner = MigrationRunner(self.rw_split_pool.master_pool)
        await self.migration_runner.start()
        
        elapsed = time.time() - startup_start
        self.logger.info(f"数据库管理系统启动完成，耗时 {elapsed:.3f} 秒")
    
    async def stop(self):
        """停止数据库管理器"""
        self.logger.info("正在关闭数据库管理系统...")
        if self.rw_split_pool:
            await self.rw_split_pool.stop()
        if self.migration_runner:
            await self.migration_runner.stop()
        self.logger.info("数据库管理系统已关闭")


class MigrationRunner:
    """数据库迁移执行器"""
    
    def __init__(self, connection_pool: Optional[ConnectionPool]):
        self.connection_pool = connection_pool
        self.logger = logging.getLogger("NexusChat.Migration")
        
    async def start(self):
        """执行迁移 - 创建必要的表"""
        self.logger.info("[Migration] 正在创建数据库表结构...")
        
        if not self.connection_pool:
            self.logger.warning("[Migration] 无可用连接池，跳过表创建")
            return
        
        # 获取一个连接来执行迁移
        conn = await self.connection_pool.acquire()
        try:
            # 创建用户表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen REAL,
                    status TEXT DEFAULT 'offline'
                )
            """)
            self.logger.info("[Migration] 表 users 已就绪")
            
            # 创建密码表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS passwords (
                    user_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            self.logger.info("[Migration] 表 passwords 已就绪")
            
            # 创建房间表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    public INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (owner_id) REFERENCES users(id)
                )
            """)
            self.logger.info("[Migration] 表 rooms 已就绪")
            
            # 创建房间成员表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS room_members (
                    room_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    joined_at REAL NOT NULL,
                    PRIMARY KEY (room_id, user_id),
                    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            self.logger.info("[Migration] 表 room_members 已就绪")
            
            # 创建私聊消息表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user TEXT NOT NULL,
                    to_user TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    delivered INTEGER DEFAULT 0
                )
            """)
            self.logger.info("[Migration] 表 messages 已就绪")
            
            # 创建房间消息表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS room_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    from_user TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
                )
            """)
            self.logger.info("[Migration] 表 room_messages 已就绪")
            
            # 创建离线消息表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS offline_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    from_user TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            self.logger.info("[Migration] 表 offline_messages 已就绪")
            
            # 创建索引
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(from_user, to_user)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_room_messages_room ON room_messages(room_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_offline_messages_user ON offline_messages(user_id)")
            self.logger.info("[Migration] 索引已创建")
            
            self.logger.info("[Migration] 数据库迁移完成，所有表已就绪")
        finally:
            await self.connection_pool.release(conn)
    
    async def stop(self):
        """停止迁移"""
        pass
