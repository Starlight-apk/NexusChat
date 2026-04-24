"""
NexusChat 缓存管理模块
=====================

提供类似 QQ 的缓存预热和加速机制：
- Redis 缓存支持（可选）
- 内存 LRU 缓存
- 热点数据预热
- 对象池化
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from collections import OrderedDict
import json


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def touch(self):
        self.access_count += 1
        self.last_accessed = time.time()


class LRUCache:
    """
    内存 LRU 缓存实现
    """
    
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        
        # 统计
        self.hits = 0
        self.misses = 0
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        async with self._lock:
            if key not in self._cache:
                self.misses += 1
                return None
            
            entry = self._cache[key]
            
            # 检查过期
            if entry.is_expired():
                del self._cache[key]
                self.misses += 1
                return None
            
            # 更新访问信息并移到末尾（最近使用）
            entry.touch()
            self._cache.move_to_end(key)
            self.hits += 1
            
            return entry.value
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ):
        """设置缓存值"""
        async with self._lock:
            expires_at = None
            if ttl is not None:
                expires_at = time.time() + ttl
            
            # 如果已存在，先删除
            if key in self._cache:
                del self._cache[key]
            
            # 如果超出容量，删除最旧的
            while len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            
            entry = CacheEntry(value=value, expires_at=expires_at)
            self._cache[key] = entry
    
    async def delete(self, key: str):
        """删除缓存"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    async def clear(self):
        """清空缓存"""
        async with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
    
    async def keys(self) -> List[str]:
        """获取所有键"""
        async with self._lock:
            return list(self._cache.keys())
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.2f}%",
        }


class RedisCache:
    """
    Redis 缓存适配器（可选）
    
    需要安装 redis-py: pip install redis
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.host = self.config.get("host", "localhost")
        self.port = self.config.get("port", 6379)
        self.db = self.config.get("db", 0)
        self.password = self.config.get("password")
        self.prefix = self.config.get("prefix", "nexuschat:")
        
        self._redis = None
        self._connected = False
    
    async def connect(self):
        """连接 Redis"""
        try:
            import redis.asyncio as redis
            self._redis = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True
            )
            await self._redis.ping()
            self._connected = True
            return True
        except ImportError:
            print("警告：redis 库未安装，使用内存缓存")
            return False
        except Exception as e:
            print(f"警告：Redis 连接失败 ({e})，使用内存缓存")
            return False
    
    async def disconnect(self):
        """断开 Redis 连接"""
        if self._redis and self._connected:
            await self._redis.close()
            self._connected = False
    
    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if not self._connected:
            return None
        
        try:
            value = await self._redis.get(self._key(key))
            if value:
                return json.loads(value)
            return None
        except Exception:
            return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ):
        """设置缓存值"""
        if not self._connected:
            return
        
        try:
            serialized = json.dumps(value)
            if ttl:
                await self._redis.setex(self._key(key), ttl, serialized)
            else:
                await self._redis.set(self._key(key), serialized)
        except Exception:
            pass
    
    async def delete(self, key: str):
        """删除缓存"""
        if not self._connected:
            return
        
        try:
            await self._redis.delete(self._key(key))
        except Exception:
            pass
    
    async def clear(self):
        """清空缓存（谨慎使用）"""
        if not self._connected:
            return
        
        try:
            pattern = f"{self.prefix}*"
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            pass
    
    def get_stats(self) -> Dict:
        """获取 Redis 状态"""
        if not self._connected:
            return {"connected": False}
        
        return {"connected": True, "type": "redis"}


class CacheManager:
    """
    统一缓存管理器
    
    支持多层缓存策略：
    - L1: 内存 LRU 缓存（快速）
    - L2: Redis 缓存（分布式，可选）
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # 初始化 L1 缓存
        lru_config = self.config.get("lru", {})
        self.l1_cache = LRUCache(max_size=lru_config.get("max_size", 10000))
        
        # 初始化 L2 缓存（可选）
        redis_config = self.config.get("redis", {})
        self.l2_cache = RedisCache(redis_config) if redis_config.get("enabled", False) else None
        
        # 预热任务
        self._warmup_tasks: List[Callable] = []
        
        # 统计
        self.stats = {
            "l1_hits": 0,
            "l2_hits": 0,
            "misses": 0,
        }
    
    async def start(self):
        """启动缓存系统"""
        if self.l2_cache:
            await self.l2_cache.connect()
        
        # 执行预热
        await self._warmup()
    
    async def stop(self):
        """停止缓存系统"""
        if self.l2_cache:
            await self.l2_cache.disconnect()
    
    def register_warmup(self, func: Callable):
        """注册预热函数"""
        self._warmup_tasks.append(func)
    
    async def _warmup(self):
        """执行数据预热"""
        if not self._warmup_tasks:
            return
        
        print("开始缓存预热...")
        start_time = time.time()
        
        for func in self._warmup_tasks:
            try:
                if asyncio.iscoroutinefunction(func):
                    await func()
                else:
                    # 同步函数直接调用
                    func()
            except Exception as e:
                print(f"预热任务失败：{e}")
        
        elapsed = time.time() - start_time
        print(f"缓存预热完成，耗时 {elapsed:.2f} 秒")
    
    async def get(self, key: str, loader: Optional[Callable] = None) -> Optional[Any]:
        """
        获取缓存值（支持穿透加载）
        
        Args:
            key: 缓存键
            loader: 如果缓存未命中，调用此函数加载数据
        """
        # 尝试 L1
        value = await self.l1_cache.get(key)
        if value is not None:
            self.stats["l1_hits"] += 1
            return value
        
        # 尝试 L2
        if self.l2_cache:
            value = await self.l2_cache.get(key)
            if value is not None:
                self.stats["l2_hits"] += 1
                # 回写到 L1
                await self.l1_cache.set(key, value)
                return value
        
        self.stats["misses"] += 1
        
        # 缓存未命中，使用 loader 加载
        if loader:
            if asyncio.iscoroutinefunction(loader):
                value = await loader()
            else:
                value = loader()
            
            if value is not None:
                # 写入两层缓存
                await self.l1_cache.set(key, value)
                if self.l2_cache:
                    await self.l2_cache.set(key, value)
                
                return value
        
        return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ):
        """设置缓存值"""
        await self.l1_cache.set(key, value, ttl)
        if self.l2_cache:
            await self.l2_cache.set(key, value, ttl)
    
    async def delete(self, key: str):
        """删除缓存"""
        await self.l1_cache.delete(key)
        if self.l2_cache:
            await self.l2_cache.delete(key)
    
    async def warmup_users(self, storage_manager):
        """预热用户数据"""
        print("正在预热用户数据...")
        # 实际实现需要从存储加载热点用户
        # 这里只是示例
        pass
    
    async def warmup_rooms(self, storage_manager):
        """预热房间数据"""
        print("正在预热房间数据...")
        # 实际实现需要从存储加载活跃房间
        pass
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        return {
            **self.stats,
            "l1_cache": self.l1_cache.get_stats(),
            "l2_cache": self.l2_cache.get_stats() if self.l2_cache else {"enabled": False},
        }


class ObjectPool:
    """
    对象池 - 预分配常用对象
    
    用于减少运行时内存分配开销
    """
    
    def __init__(
        self, 
        factory: Callable[[], Any],
        initial_size: int = 100,
        max_size: int = 1000
    ):
        self.factory = factory
        self.max_size = max_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._created = 0
        self._in_use = 0
        
        # 预分配
        self._preallocate(initial_size)
    
    def _preallocate(self, count: int):
        """预分配对象"""
        for _ in range(min(count, self.max_size)):
            try:
                obj = self.factory()
                self._pool.put_nowait(obj)
                self._created += 1
            except Exception:
                break
    
    async def acquire(self) -> Any:
        """获取对象"""
        try:
            obj = await asyncio.wait_for(self._pool.get(), timeout=0.1)
            self._in_use += 1
            return obj
        except asyncio.TimeoutError:
            # 池为空，创建新对象
            if self._created < self.max_size:
                self._created += 1
                self._in_use += 1
                return self.factory()
            else:
                # 达到最大限制，等待
                obj = await self._pool.get()
                self._in_use += 1
                return obj
    
    async def release(self, obj: Any):
        """释放对象回池"""
        self._in_use -= 1
        
        if self._pool.qsize() < self.max_size:
            try:
                self._pool.put_nowait(obj)
            except asyncio.QueueFull:
                pass
    
    def get_stats(self) -> Dict:
        """获取池统计"""
        return {
            "created": self._created,
            "in_use": self._in_use,
            "available": self._pool.qsize(),
            "max_size": self.max_size,
        }
