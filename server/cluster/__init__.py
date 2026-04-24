"""
分布式集群协调模块
提供节点注册、服务发现、一致性哈希路由功能
"""

from .node import ClusterNode, NodeStatus
from .registry import ServiceRegistry
from .hash_ring import ConsistentHashRing

__all__ = ['ClusterNode', 'NodeStatus', 'ServiceRegistry', 'ConsistentHashRing']
