"""
一致性哈希环
用于用户分片和消息路由
"""

import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class HashNode:
    """哈希环上的节点"""
    position: int
    node_id: str
    virtual_index: int  # 虚拟节点索引


class ConsistentHashRing:
    """
    一致性哈希环实现
    用于分布式系统中的数据分片和负载均衡
    """
    
    VIRTUAL_NODES = 150  # 每个物理节点的虚拟节点数
    HASH_RING_SIZE = 2 ** 32  # 哈希环大小
    
    def __init__(self):
        self._ring: Dict[int, HashNode] = {}
        self._sorted_keys: List[int] = []
        self._node_count = 0
        
    def _hash(self, key: str) -> int:
        """计算哈希值"""
        return int(hashlib.md5(key.encode()).hexdigest(), 16) % self.HASH_RING_SIZE
    
    def add_node(self, node_id: str) -> bool:
        """添加节点到哈希环"""
        if self._has_node(node_id):
            logger.warning(f"[HASH] 节点 {node_id} 已存在")
            return False
        
        # 添加虚拟节点
        for i in range(self.VIRTUAL_NODES):
            virtual_key = f"{node_id}:vn{i}"
            position = self._hash(virtual_key)
            
            hash_node = HashNode(
                position=position,
                node_id=node_id,
                virtual_index=i
            )
            
            self._ring[position] = hash_node
            self._sorted_keys.append(position)
        
        self._sorted_keys.sort()
        self._node_count += 1
        
        logger.info(f"[HASH] 添加节点 {node_id} (虚拟节点：{self.VIRTUAL_NODES}个)")
        return True
    
    def remove_node(self, node_id: str) -> bool:
        """从哈希环移除节点"""
        if not self._has_node(node_id):
            logger.warning(f"[HASH] 节点 {node_id} 不存在")
            return False
        
        # 移除所有虚拟节点
        keys_to_remove = []
        for pos, node in self._ring.items():
            if node.node_id == node_id:
                keys_to_remove.append(pos)
        
        for key in keys_to_remove:
            del self._ring[key]
            self._sorted_keys.remove(key)
        
        self._node_count -= 1
        
        logger.info(f"[HASH] 移除节点 {node_id}")
        return True
    
    def _has_node(self, node_id: str) -> bool:
        """检查节点是否存在"""
        for node in self._ring.values():
            if node.node_id == node_id:
                return True
        return False
    
    def get_node(self, key: str) -> Optional[str]:
        """根据键获取对应的节点"""
        if not self._ring:
            return None
        
        hash_value = self._hash(key)
        
        # 二分查找顺时针第一个节点
        left, right = 0, len(self._sorted_keys) - 1
        result_pos = None
        
        while left <= right:
            mid = (left + right) // 2
            if self._sorted_keys[mid] >= hash_value:
                result_pos = self._sorted_keys[mid]
                right = mid - 1
            else:
                left = mid + 1
        
        # 如果没有找到更大的，返回第一个节点 (环状)
        if result_pos is None:
            result_pos = self._sorted_keys[0]
        
        return self._ring[result_pos].node_id
    
    def get_nodes(self, key: str, count: int = 1) -> List[str]:
        """获取多个节点 (用于副本)"""
        if not self._ring or count <= 0:
            return []
        
        nodes = []
        seen = set()
        hash_value = self._hash(key)
        
        # 找到起始位置
        start_idx = 0
        for i, pos in enumerate(self._sorted_keys):
            if pos >= hash_value:
                start_idx = i
                break
        
        # 遍历获取不重复的节点
        idx = start_idx
        while len(nodes) < count and len(seen) < self._node_count:
            pos = self._sorted_keys[idx % len(self._sorted_keys)]
            node_id = self._ring[pos].node_id
            
            if node_id not in seen:
                seen.add(node_id)
                nodes.append(node_id)
            
            idx += 1
        
        return nodes
    
    def get_distribution(self) -> Dict[str, int]:
        """获取节点分布情况"""
        distribution = {}
        
        for node in self._ring.values():
            distribution[node.node_id] = distribution.get(node.node_id, 0) + 1
        
        return distribution
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        distribution = self.get_distribution()
        
        if not distribution:
            return {'nodes': 0, 'total_virtual': 0, 'balance': 0}
        
        values = list(distribution.values())
        avg = sum(values) / len(values)
        variance = sum((v - avg) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5
        
        return {
            'nodes': self._node_count,
            'total_virtual': len(self._ring),
            'avg_virtual_per_node': avg,
            'std_dev': std_dev,
            'balance': 1 - (std_dev / avg) if avg > 0 else 0  # 均衡度 0-1
        }
