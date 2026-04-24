"""
NexusChat 安全网关模块
=====================

提供工业级的接入层安全防护：
- IP 频率限制
- 黑白名单管理
- 协议校验
- DDoS 防护基础
- 连接数控制
"""

import time
import ipaddress
from typing import Dict, Set, Optional, List
from dataclasses import dataclass, field
from collections import defaultdict
import asyncio


@dataclass
class RateLimitConfig:
    """频率限制配置"""
    max_requests_per_second: int = 10
    max_requests_per_minute: int = 100
    max_connections_per_ip: int = 5
    burst_size: int = 20


@dataclass
class IPStats:
    """IP 统计信息"""
    request_times: List[float] = field(default_factory=list)
    connection_count: int = 0
    last_request_time: float = 0.0
    blocked_until: float = 0.0
    violation_count: int = 0


class SecurityGateway:
    """
    安全网关 - 类似 QQ 的防火墙机制
    
    功能:
    - 实时 IP 频率限制
    - 动态黑名单
    - 白名单管理
    - 连接数控制
    - 异常行为检测
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.rate_limit_config = RateLimitConfig(
            max_requests_per_second=self.config.get("max_requests_per_second", 10),
            max_requests_per_minute=self.config.get("max_requests_per_minute", 100),
            max_connections_per_ip=self.config.get("max_connections_per_ip", 5),
            burst_size=self.config.get("burst_size", 20),
        )
        
        # IP 统计
        self.ip_stats: Dict[str, IPStats] = defaultdict(IPStats)
        
        # 黑名单 (自动 + 手动)
        self.blacklist: Set[str] = set()
        self.auto_blacklist: Set[str] = set()
        
        # 白名单
        self.whitelist: Set[str] = set()
        
        # 网络段黑名单 (CIDR)
        self.blocked_networks: List[ipaddress.IPv4Network] = []
        
        # 全局连接计数
        self.total_connections = 0
        self.max_total_connections = self.config.get("max_total_connections", 10000)
        
        # 锁
        self._lock = asyncio.Lock()
        
        # 自动清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # 启动时加载配置
        self._load_config()
    
    def _load_config(self):
        """加载配置"""
        # 加载白名单
        for ip in self.config.get("whitelist", []):
            self.whitelist.add(ip)
        
        # 加载黑名单
        for ip in self.config.get("blacklist", []):
            self.blacklist.add(ip)
        
        # 加载网段封锁
        for network in self.config.get("blocked_networks", []):
            try:
                self.blocked_networks.append(ipaddress.ip_network(network, strict=False))
            except ValueError:
                pass
    
    async def start(self):
        """启动网关（后台清理任务）"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self):
        """停止网关"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def check_connection(
        self, 
        ip: str, 
        socket_id: int
    ) -> tuple[bool, Optional[str]]:
        """
        检查是否允许建立连接
        
        Returns:
            (allowed, reason)
        """
        async with self._lock:
            now = time.time()
            
            # 白名单直接放行
            if ip in self.whitelist:
                return True, None
            
            # 检查全局连接数
            if self.total_connections >= self.max_total_connections:
                return False, "服务器连接数已达上限"
            
            # 检查黑名单
            if ip in self.blacklist or ip in self.auto_blacklist:
                return False, "IP 已被列入黑名单"
            
            # 检查网段封锁
            try:
                ip_obj = ipaddress.ip_address(ip)
                for network in self.blocked_networks:
                    if ip_obj in network:
                        return False, f"IP 属于被封锁的网段 {network}"
            except ValueError:
                return False, "无效的 IP 地址"
            
            # 检查单 IP 连接数
            stats = self.ip_stats[ip]
            if stats.connection_count >= self.rate_limit_config.max_connections_per_ip:
                return False, f"单 IP 连接数超过限制 ({self.rate_limit_config.max_connections_per_ip})"
            
            # 检查是否处于临时封禁期
            if stats.blocked_until > now:
                remaining = int(stats.blocked_until - now)
                return False, f"IP 被临时封禁，剩余 {remaining} 秒"
            
            # 允许连接
            stats.connection_count += 1
            self.total_connections += 1
            
            return True, None
    
    async def record_disconnect(self, ip: str):
        """记录断开连接"""
        async with self._lock:
            if ip in self.ip_stats:
                self.ip_stats[ip].connection_count = max(
                    0, 
                    self.ip_stats[ip].connection_count - 1
                )
            self.total_connections = max(0, self.total_connections - 1)
    
    async def check_request(self, ip: str) -> tuple[bool, Optional[str]]:
        """
        检查请求是否允许（频率限制）
        
        Returns:
            (allowed, reason)
        """
        async with self._lock:
            now = time.time()
            
            # 白名单直接放行
            if ip in self.whitelist:
                return True, None
            
            stats = self.ip_stats[ip]
            
            # 检查临时封禁
            if stats.blocked_until > now:
                remaining = int(stats.blocked_until - now)
                return False, f"IP 被临时封禁，剩余 {remaining} 秒"
            
            # 清理旧的请求记录（保留最近 60 秒）
            cutoff = now - 60
            stats.request_times = [t for t in stats.request_times if t > cutoff]
            
            # 检查每秒限制
            recent_1s = [t for t in stats.request_times if t > now - 1]
            if len(recent_1s) >= self.rate_limit_config.max_requests_per_second:
                # 触发限流，记录违规
                stats.violation_count += 1
                if stats.violation_count >= 5:
                    # 多次违规，临时封禁
                    stats.blocked_until = now + 300  # 封禁 5 分钟
                    self.auto_blacklist.add(ip)
                    return False, "频繁请求，IP 已被临时封禁"
                return False, "请求频率过高"
            
            # 检查每分钟限制
            if len(stats.request_times) >= self.rate_limit_config.max_requests_per_minute:
                return False, "请求频率过高"
            
            # 记录请求
            stats.request_times.append(now)
            stats.last_request_time = now
            
            return True, None
    
    async def add_to_blacklist(self, ip: str, duration: Optional[int] = None):
        """添加 IP 到黑名单"""
        async with self._lock:
            if duration:
                self.ip_stats[ip].blocked_until = time.time() + duration
            else:
                self.blacklist.add(ip)
    
    async def remove_from_blacklist(self, ip: str):
        """从黑名单移除"""
        async with self._lock:
            self.blacklist.discard(ip)
            self.auto_blacklist.discard(ip)
            if ip in self.ip_stats:
                self.ip_stats[ip].blocked_until = 0
                self.ip_stats[ip].violation_count = 0
    
    async def add_to_whitelist(self, ip: str):
        """添加 IP 到白名单"""
        async with self._lock:
            self.whitelist.add(ip)
    
    async def block_network(self, network: str):
        """封锁网段"""
        async with self._lock:
            try:
                net = ipaddress.ip_network(network, strict=False)
                self.blocked_networks.append(net)
            except ValueError:
                raise ValueError(f"无效的网络地址：{network}")
    
    async def _cleanup_loop(self):
        """定期清理过期数据"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟清理一次
                
                async with self._lock:
                    now = time.time()
                    
                    # 清理长期不活动的 IP 统计
                    inactive_threshold = now - 3600  # 1 小时
                    to_remove = []
                    
                    for ip, stats in self.ip_stats.items():
                        if (stats.last_request_time < inactive_threshold and 
                            stats.connection_count == 0 and
                            ip not in self.blacklist and
                            ip not in self.whitelist):
                            to_remove.append(ip)
                    
                    for ip in to_remove:
                        del self.ip_stats[ip]
                    
                    # 清理过期的自动黑名单
                    expired_auto_blacklist = []
                    for ip in self.auto_blacklist:
                        if ip in self.ip_stats:
                            if self.ip_stats[ip].blocked_until < now:
                                expired_auto_blacklist.append(ip)
                    
                    for ip in expired_auto_blacklist:
                        self.auto_blacklist.discard(ip)
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                # 记录错误但不中断清理循环
                pass
    
    def get_stats(self) -> Dict:
        """获取网关统计信息"""
        return {
            "total_connections": self.total_connections,
            "max_total_connections": self.max_total_connections,
            "blacklist_size": len(self.blacklist),
            "auto_blacklist_size": len(self.auto_blacklist),
            "whitelist_size": len(self.whitelist),
            "tracked_ips": len(self.ip_stats),
        }
