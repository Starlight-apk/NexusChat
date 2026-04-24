"""
集群节点管理
实现节点状态、心跳检测、健康检查
"""

import asyncio
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class NodeStatus(Enum):
    """节点状态"""
    INITIALIZING = "initializing"
    RUNNING = "running"
    DEGRADED = "degraded"  # 性能下降
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


@dataclass
class NodeInfo:
    """节点信息"""
    node_id: str
    host: str
    port: int
    status: NodeStatus = NodeStatus.INITIALIZING
    load: float = 0.0  # 负载 0-1
    connections: int = 0
    last_heartbeat: float = 0.0
    region: str = "default"
    tags: Dict[str, str] = field(default_factory=dict)
    start_time: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'node_id': self.node_id,
            'host': self.host,
            'port': self.port,
            'status': self.status.value,
            'load': self.load,
            'connections': self.connections,
            'last_heartbeat': self.last_heartbeat,
            'region': self.region,
            'tags': self.tags,
            'start_time': self.start_time,
            'uptime': time.time() - self.start_time if self.start_time else 0
        }


class ClusterNode:
    """
    集群节点管理器
    负责本节点的状态维护和其他节点的心跳检测
    """
    
    HEARTBEAT_INTERVAL = 3.0  # 心跳间隔 (秒)
    HEARTBEAT_TIMEOUT = 10.0  # 心跳超时 (秒)
    LOAD_UPDATE_INTERVAL = 5.0  # 负载更新间隔
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8080, 
                 region: str = "default", node_id: Optional[str] = None):
        self.node_id = node_id or f"node-{uuid.uuid4().hex[:8]}"
        self.host = host
        self.port = port
        self.region = region
        self.info = NodeInfo(
            node_id=self.node_id,
            host=host,
            port=port,
            region=region,
            start_time=time.time()
        )
        
        self._running = False
        self._peers: Dict[str, NodeInfo] = {}
        self._callbacks: List[Callable] = []
        self._tasks: List[asyncio.Task] = []
        
    async def start(self):
        """启动节点管理"""
        logger.info(f"[CLUSTER] 启动集群节点 {self.node_id} @ {self.host}:{self.port}")
        self._running = True
        self.info.status = NodeStatus.RUNNING
        
        # 启动心跳任务
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._tasks.append(asyncio.create_task(self._load_monitor_loop()))
        
        logger.info(f"[CLUSTER] 节点 {self.node_id} 已就绪")
        
    async def stop(self):
        """停止节点管理"""
        logger.info(f"[CLUSTER] 停止集群节点 {self.node_id}")
        self._running = False
        self.info.status = NodeStatus.OFFLINE
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks.clear()
        
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            try:
                self.info.last_heartbeat = time.time()
                
                # 检查其他节点心跳
                current_time = time.time()
                dead_nodes = []
                
                for peer_id, peer_info in self._peers.items():
                    if current_time - peer_info.last_heartbeat > self.HEARTBEAT_TIMEOUT:
                        logger.warning(f"[CLUSTER] 节点 {peer_id} 心跳超时")
                        peer_info.status = NodeStatus.OFFLINE
                        dead_nodes.append(peer_id)
                
                for node_id in dead_nodes:
                    del self._peers[node_id]
                    await self._notify_peer_offline(node_id)
                
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[CLUSTER] 心跳检测错误: {e}")
                await asyncio.sleep(1)
    
    async def _load_monitor_loop(self):
        """负载监控循环"""
        while self._running:
            try:
                # 模拟负载计算 (实际应从系统获取)
                self.info.load = min(1.0, len(self._peers) * 0.01 + 0.1)
                await asyncio.sleep(self.LOAD_UPDATE_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[CLUSTER] 负载监控错误: {e}")
    
    def register_peer(self, peer_info: NodeInfo):
        """注册对等节点"""
        self._peers[peer_info.node_id] = peer_info
        logger.info(f"[CLUSTER] 注册对等节点 {peer_info.node_id} @ {peer_info.host}:{peer_info.port}")
        
    def get_peers(self) -> List[NodeInfo]:
        """获取所有活跃节点"""
        return [p for p in self._peers.values() if p.status == NodeStatus.RUNNING]
    
    def get_active_count(self) -> int:
        """获取活跃节点数"""
        return len(self.get_peers())
    
    def update_connections(self, count: int):
        """更新连接数"""
        self.info.connections = count
    
    async def _notify_peer_offline(self, node_id: str):
        """通知节点下线"""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(node_id)
                else:
                    callback(node_id)
            except Exception as e:
                logger.error(f"[CLUSTER] 回调执行错误: {e}")
    
    def on_peer_offline(self, callback: Callable):
        """注册节点下线回调"""
        self._callbacks.append(callback)
