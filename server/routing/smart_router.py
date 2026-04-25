"""
智能路由模块
实现地理位置路由、负载均衡、热点迁移
"""

import asyncio
import time
import random
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging
import math

logger = logging.getLogger(__name__)


@dataclass
class GeoLocation:
    """地理位置"""
    latitude: float
    longitude: float
    city: str = ""
    region: str = ""
    country: str = ""
    
    def distance_to(self, other: 'GeoLocation') -> float:
        """计算与另一个位置的距離 (Haversine 公式)"""
        R = 6371  # 地球半径 (km)
        
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c


@dataclass
class RouteNode:
    """路由节点"""
    node_id: str
    host: str
    port: int
    location: GeoLocation
    load: float = 0.0
    connections: int = 0
    max_connections: int = 10000
    health_score: float = 1.0
    latency_ms: float = 0.0
    
    def available_capacity(self) -> float:
        """可用容量"""
        return 1.0 - (self.connections / self.max_connections)
    
    def is_healthy(self) -> bool:
        """是否健康"""
        return self.health_score > 0.5 and self.available_capacity() > 0.1


class SmartRouter:
    """
    智能路由器
    实现地理位置就近路由、负载均衡、热点检测与迁移
    """
    
    LOAD_SAMPLE_INTERVAL = 2.0
    HOTSPOT_THRESHOLD = 0.8  # 热点阈值
    MIGRATION_COOLDOWN = 60.0  # 迁移冷却时间 (秒)
    
    def __init__(self, local_node_id: str):
        self.local_node_id = local_node_id
        self._nodes: Dict[str, RouteNode] = {}
        self._region_nodes: Dict[str, List[str]] = defaultdict(list)
        self._user_routes: Dict[str, str] = {}  # user_id -> node_id
        self._hotspots: Dict[str, float] = {}  # node_id -> heat_score
        self._migration_history: Dict[str, float] = {}  # node_id -> last_migration_time
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
    async def start(self):
        """启动路由器"""
        logger.info(f"[ROUTER] 启动智能路由器 (本节点：{self.local_node_id})")
        self._running = True
        
        # 加载地理位置数据库
        await self._load_geo_database()
        
        # 启动负载采样任务
        self._tasks.append(asyncio.create_task(self._load_sample_loop()))
        self._tasks.append(asyncio.create_task(self._hotspot_detection_loop()))
        
        logger.info(f"[ROUTER] 智能路由器已就绪")
    
    async def stop(self):
        """停止路由器"""
        logger.info(f"[ROUTER] 停止智能路由器")
        self._running = False
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks.clear()
    
    async def _load_geo_database(self):
        """加载地理位置数据库（内置数据）"""
        logger.info("[ROUTER] 加载地理位置数据库...")
        
        # 使用内置城市数据
        cities = ['北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '西安']
        logger.info(f"[ROUTER] 已加载 {len(cities)} 个城市的地理数据")
    
    def register_node(self, node: RouteNode) -> bool:
        """注册路由节点"""
        if node.node_id in self._nodes:
            logger.warning(f"[ROUTER] 节点 {node.node_id} 已存在")
            return False
        
        self._nodes[node.node_id] = node
        self._region_nodes[node.location.region].append(node.node_id)
        
        logger.info(f"[ROUTER] 注册节点 {node.node_id} @ {node.location.city}")
        return True
    
    def unregister_node(self, node_id: str) -> bool:
        """注销路由节点"""
        if node_id not in self._nodes:
            return False
        
        node = self._nodes.pop(node_id)
        if node.node_id in self._region_nodes[node.location.region]:
            self._region_nodes[node.location.region].remove(node.node_id)
        
        logger.info(f"[ROUTER] 注销节点 {node_id}")
        return True
    
    def route_user(self, user_id: str, 
                   user_location: Optional[GeoLocation] = None) -> str:
        """为用户路由到最佳节点"""
        # 如果已有路由且节点健康，保持不变
        if user_id in self._user_routes:
            current_node = self._user_routes[user_id]
            if current_node in self._nodes and self._nodes[current_node].is_healthy():
                return current_node
        
        # 选择最佳节点
        best_node = self._select_best_node(user_location)
        
        if best_node:
            self._user_routes[user_id] = best_node
            logger.debug(f"[ROUTER] 用户 {user_id} 路由到节点 {best_node}")
        
        return best_node or self.local_node_id
    
    def _select_best_node(self, user_location: Optional[GeoLocation]) -> Optional[str]:
        """选择最佳节点"""
        candidates = []
        
        for node_id, node in self._nodes.items():
            if not node.is_healthy():
                continue
            
            # 计算综合得分
            score = self._calculate_node_score(node, user_location)
            candidates.append((node_id, score))
        
        if not candidates:
            return None
        
        # 按得分排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # 返回得分最高的节点
        return candidates[0][0]
    
    def _calculate_node_score(self, node: RouteNode, 
                             user_location: Optional[GeoLocation]) -> float:
        """计算节点得分"""
        # 地理位置得分 (越近越好)
        geo_score = 1.0
        if user_location:
            distance = node.location.distance_to(user_location)
            # 1000km 内得满分，每增加 1000km 降低 0.1
            geo_score = max(0, 1.0 - (distance / 10000))
        
        # 负载得分 (越低越好)
        load_score = node.available_capacity()
        
        # 健康得分
        health_score = node.health_score
        
        # 延迟得分
        latency_score = max(0, 1.0 - (node.latency_ms / 500))
        
        # 加权平均
        total_score = (
            geo_score * 0.3 +
            load_score * 0.3 +
            health_score * 0.2 +
            latency_score * 0.2
        )
        
        return total_score
    
    async def _load_sample_loop(self):
        """负载采样循环"""
        while self._running:
            try:
                # 更新所有节点的负载信息 (模拟)
                for node in self._nodes.values():
                    # 模拟负载波动
                    node.load = min(1.0, max(0, node.load + random.uniform(-0.1, 0.1)))
                    node.connections = int(node.max_connections * node.load)
                
                await asyncio.sleep(self.LOAD_SAMPLE_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ROUTER] 负载采样错误：{e}")
    
    async def _hotspot_detection_loop(self):
        """热点检测循环"""
        while self._running:
            try:
                # 检测热点节点
                self._hotspots.clear()
                
                for node_id, node in self._nodes.items():
                    if node.load > self.HOTSPOT_THRESHOLD:
                        self._hotspots[node_id] = node.load
                        logger.warning(f"[ROUTER] 检测到热点节点：{node_id} (负载：{node.load:.2%})")
                
                # 触发热点迁移
                if self._hotspots:
                    await self._trigger_migration()
                
                await asyncio.sleep(5.0)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ROUTER] 热点检测错误：{e}")
    
    async def _trigger_migration(self):
        """触发热点迁移"""
        current_time = time.time()
        
        for node_id, heat_score in list(self._hotspots.items()):
            # 检查冷却时间
            last_migration = self._migration_history.get(node_id, 0)
            if current_time - last_migration < self.MIGRATION_COOLDOWN:
                continue
            
            logger.info(f"[ROUTER] 开始迁移热点节点 {node_id} 的用户...")
            
            # 找到目标节点
            target_node = self._find_migration_target(node_id)
            
            if target_node:
                # 迁移部分用户
                await self._migrate_users(node_id, target_node, ratio=0.3)
                self._migration_history[node_id] = current_time
                logger.info(f"[ROUTER] 热点节点 {node_id} 迁移完成 -> {target_node}")
    
    def _find_migration_target(self, source_node_id: str) -> Optional[str]:
        """寻找迁移目标节点"""
        if source_node_id not in self._nodes:
            return None
        
        source_node = self._nodes[source_node_id]
        best_target = None
        best_score = 0
        
        for node_id, node in self._nodes.items():
            if node_id == source_node_id:
                continue
            
            if not node.is_healthy():
                continue
            
            # 同一区域优先
            if node.location.region != source_node.location.region:
                continue
            
            score = node.available_capacity() * node.health_score
            
            if score > best_score:
                best_score = score
                best_target = node_id
        
        return best_target
    
    async def _migrate_users(self, from_node: str, to_node: str, ratio: float = 0.3):
        """迁移用户"""
        users_to_migrate = []
        
        for user_id, node_id in list(self._user_routes.items()):
            if node_id == from_node:
                users_to_migrate.append(user_id)
        
        # 随机选择部分用户迁移
        migrate_count = max(1, int(len(users_to_migrate) * ratio))
        selected_users = random.sample(users_to_migrate, min(migrate_count, len(users_to_migrate)))
        
        for user_id in selected_users:
            self._user_routes[user_id] = to_node
        
        logger.info(f"[ROUTER] 迁移 {len(selected_users)} 个用户从 {from_node} -> {to_node}")
    
    def get_routing_stats(self) -> dict:
        """获取路由统计"""
        return {
            'total_nodes': len(self._nodes),
            'healthy_nodes': sum(1 for n in self._nodes.values() if n.is_healthy()),
            'routed_users': len(self._user_routes),
            'hotspots': len(self._hotspots),
            'regions': len(self._region_nodes)
        }
