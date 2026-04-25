"""
服务注册与发现
模拟 Consul/Etcd/Nacos 的功能
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
import logging

from .node import NodeInfo, NodeStatus

logger = logging.getLogger(__name__)


@dataclass
class ServiceInstance:
    """服务实例"""
    service_name: str
    instance_id: str
    host: str
    port: int
    health_status: str = "healthy"
    metadata: Dict = None
    register_time: float = 0.0
    last_heartbeat: float = 0.0
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.register_time == 0:
            self.register_time = time.time()
        if self.last_heartbeat == 0:
            self.last_heartbeat = time.time()


class ServiceRegistry:
    """
    服务注册中心
    提供服务注册、注销、发现、健康检查功能
    """
    
    HEALTH_CHECK_INTERVAL = 5.0
    SESSION_TIMEOUT = 30.0
    
    def __init__(self, cluster_node_id: str):
        self.cluster_node_id = cluster_node_id
        self._services: Dict[str, Dict[str, ServiceInstance]] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
    async def start(self):
        """启动注册中心"""
        logger.info(f"[REGISTRY] 启动服务注册中心 (节点：{self.cluster_node_id})")
        self._running = True
        
        # 启动健康检查任务
        self._tasks.append(asyncio.create_task(self._health_check_loop()))
        
        # 模拟从远程配置中心加载配置
        await self._load_remote_config()
        
        logger.info(f"[REGISTRY] 服务注册中心已就绪")
    
    async def stop(self):
        """停止注册中心"""
        logger.info(f"[REGISTRY] 停止服务注册中心")
        self._running = False
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks.clear()
    
    async def _load_remote_config(self):
        """从本地配置加载（无远程依赖）"""
        logger.info("[REGISTRY] 加载本地配置...")
        
        # 使用内置默认配置
        config = {
            'max_connections': 10000,
            'message_timeout': 30,
            'enable_encryption': True,
            'regions': ['cn-east', 'cn-north', 'us-west']
        }
        
        logger.info(f"[REGISTRY] 已加载配置项：{len(config)} 个")
        return config
    
    async def register(self, instance: ServiceInstance) -> bool:
        """注册服务实例"""
        service_name = instance.service_name
        
        if service_name not in self._services:
            self._services[service_name] = {}
        
        self._services[service_name][instance.instance_id] = instance
        logger.info(f"[REGISTRY] 注册服务 {service_name}/{instance.instance_id} @ {instance.host}:{instance.port}")
        
        # 触发回调
        await self._notify_service_change(service_name, 'register', instance)
        
        return True
    
    async def deregister(self, service_name: str, instance_id: str) -> bool:
        """注销服务实例"""
        if service_name in self._services:
            if instance_id in self._services[service_name]:
                instance = self._services[service_name].pop(instance_id)
                logger.info(f"[REGISTRY] 注销服务 {service_name}/{instance_id}")
                
                await self._notify_service_change(service_name, 'deregister', instance)
                return True
        
        return False
    
    def discover(self, service_name: str) -> List[ServiceInstance]:
        """发现服务实例"""
        if service_name not in self._services:
            return []
        
        instances = [
            inst for inst in self._services[service_name].values()
            if inst.health_status == "healthy"
        ]
        
        logger.debug(f"[REGISTRY] 发现服务 {service_name}: {len(instances)} 个实例")
        return instances
    
    def get_all_services(self) -> Dict[str, List[str]]:
        """获取所有服务列表"""
        result = {}
        for service_name, instances in self._services.items():
            result[service_name] = list(instances.keys())
        return result
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while self._running:
            try:
                current_time = time.time()
                
                for service_name, instances in list(self._services.items()):
                    for instance_id, instance in list(instances.items()):
                        # 检查心跳超时
                        if current_time - instance.last_heartbeat > self.SESSION_TIMEOUT:
                            logger.warning(f"[REGISTRY] 服务实例 {service_name}/{instance_id} 健康检查失败")
                            instance.health_status = "unhealthy"
                            
                            # 移除不健康实例
                            await self.deregister(service_name, instance_id)
                        
                        # 更新心跳 (模拟)
                        instance.last_heartbeat = current_time
                
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[REGISTRY] 健康检查错误：{e}")
                await asyncio.sleep(1)
    
    def on_service_change(self, service_name: str, callback: Callable):
        """注册服务变更回调"""
        if service_name not in self._callbacks:
            self._callbacks[service_name] = []
        self._callbacks[service_name].append(callback)
    
    async def _notify_service_change(self, service_name: str, action: str, instance: ServiceInstance):
        """通知服务变更"""
        callbacks = self._callbacks.get(service_name, [])
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(action, instance)
                else:
                    callback(action, instance)
            except Exception as e:
                logger.error(f"[REGISTRY] 回调执行错误：{e}")
