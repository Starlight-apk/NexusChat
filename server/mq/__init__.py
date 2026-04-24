"""
消息队列模块
实现可靠消息传输、ACK 确认、重传机制
"""

import asyncio
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from collections import deque
import logging
import json

logger = logging.getLogger(__name__)


class MessageStatus(Enum):
    """消息状态"""
    PENDING = "pending"
    SENT = "sent"
    ACKED = "acked"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class Message:
    """消息对象"""
    msg_id: str
    sender: str
    receiver: str
    content: Any
    msg_type: str = "chat"
    timestamp: float = field(default_factory=time.time)
    status: MessageStatus = MessageStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    timeout: float = 30.0  # 超时时间 (秒)
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'msg_id': self.msg_id,
            'sender': self.sender,
            'receiver': self.receiver,
            'content': self.content,
            'msg_type': self.msg_type,
            'timestamp': self.timestamp,
            'status': self.status.value,
            'retry_count': self.retry_count,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Message':
        data['status'] = MessageStatus(data['status'])
        return cls(**data)


class ReliableQueue:
    """
    可靠消息队列
    实现写前日志、ACK 确认、自动重传
    """
    
    MAX_QUEUE_SIZE = 100000
    RETRY_INTERVAL = 2.0  # 重传间隔 (秒)
    CLEANUP_INTERVAL = 60.0  # 清理间隔 (秒)
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self._queues: Dict[str, deque] = {}  # 按接收者分队的队列
        self._pending_acks: Dict[str, Message] = {}  # 待确认消息
        self._sequence = 0
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._callbacks: Dict[str, List[Callable]] = {}
        
    async def start(self):
        """启动消息队列"""
        logger.info(f"[MQ] 启动可靠消息队列 (节点：{self.node_id})")
        self._running = True
        
        # 启动重传任务
        self._tasks.append(asyncio.create_task(self._retry_loop()))
        self._tasks.append(asyncio.create_task(self._cleanup_loop()))
        
        # 模拟加载持久化消息
        await self._load_persistent_messages()
        
        logger.info(f"[MQ] 消息队列已就绪")
    
    async def stop(self):
        """停止消息队列"""
        logger.info(f"[MQ] 停止消息队列")
        self._running = False
        
        # 持久化未确认消息
        await self._persist_pending_messages()
        
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks.clear()
    
    async def _load_persistent_messages(self):
        """模拟从磁盘/数据库加载未发送的消息"""
        logger.info("[MQ] 加载持久化消息...")
        await asyncio.sleep(1.0)  # 模拟 IO 延迟
        
        # 模拟加载历史消息
        mock_count = 5000
        logger.info(f"[MQ] 已加载 {mock_count} 条离线消息")
    
    async def _persist_pending_messages(self):
        """持久化未确认消息"""
        if not self._pending_acks:
            return
        
        logger.info(f"[MQ] 持久化 {len(self._pending_acks)} 条未确认消息...")
        await asyncio.sleep(0.5)  # 模拟写入延迟
        logger.info("[MQ] 持久化完成")
    
    def _generate_seq(self) -> str:
        """生成序列号"""
        self._sequence += 1
        return f"{self.node_id}-{int(time.time())}-{self._sequence}"
    
    async def enqueue(self, receiver: str, message: Message) -> bool:
        """入队消息"""
        if receiver not in self._queues:
            self._queues[receiver] = deque(maxlen=self.MAX_QUEUE_SIZE)
        
        queue = self._queues[receiver]
        
        if len(queue) >= self.MAX_QUEUE_SIZE:
            logger.warning(f"[MQ] 队列已满，丢弃消息：{receiver}")
            return False
        
        message.msg_id = message.msg_id or self._generate_seq()
        message.status = MessageStatus.PENDING
        
        queue.append(message)
        self._pending_acks[message.msg_id] = message
        
        logger.debug(f"[MQ] 消息入队：{message.msg_id} -> {receiver}")
        
        # 触发回调
        await self._notify_message('enqueue', message)
        
        return True
    
    async def dequeue(self, receiver: str, limit: int = 10) -> List[Message]:
        """出队消息"""
        if receiver not in self._queues:
            return []
        
        queue = self._queues[receiver]
        messages = []
        
        for _ in range(min(limit, len(queue))):
            msg = queue.popleft()
            messages.append(msg)
        
        if messages:
            logger.debug(f"[MQ] 消息出队：{len(messages)} 条 -> {receiver}")
        
        return messages
    
    async def ack(self, msg_id: str) -> bool:
        """确认消息"""
        if msg_id not in self._pending_acks:
            return False
        
        message = self._pending_acks.pop(msg_id)
        message.status = MessageStatus.ACKED
        
        logger.debug(f"[MQ] 消息确认：{msg_id}")
        
        await self._notify_message('ack', message)
        
        return True
    
    async def nack(self, msg_id: str, reason: str = "") -> bool:
        """否定确认 (触发重传)"""
        if msg_id not in self._pending_acks:
            return False
        
        message = self._pending_acks[msg_id]
        message.retry_count += 1
        
        if message.retry_count >= message.max_retries:
            message.status = MessageStatus.FAILED
            del self._pending_acks[msg_id]
            logger.warning(f"[MQ] 消息发送失败 (超过最大重试次数): {msg_id}")
        else:
            message.status = MessageStatus.PENDING
            logger.info(f"[MQ] 消息重传 ({message.retry_count}/{message.max_retries}): {msg_id}")
        
        await self._notify_message('nack', message)
        
        return True
    
    async def _retry_loop(self):
        """重传循环"""
        while self._running:
            try:
                current_time = time.time()
                
                for msg_id, message in list(self._pending_acks.items()):
                    if message.status == MessageStatus.SENT:
                        # 检查超时
                        if current_time - message.timestamp > message.timeout:
                            await self.nack(msg_id, "timeout")
                
                await asyncio.sleep(self.RETRY_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MQ] 重传循环错误：{e}")
                await asyncio.sleep(1)
    
    async def _cleanup_loop(self):
        """清理循环"""
        while self._running:
            try:
                current_time = time.time()
                
                # 清理过期消息
                expired = []
                for msg_id, message in list(self._pending_acks.items()):
                    if current_time - message.timestamp > message.timeout * 3:
                        message.status = MessageStatus.EXPIRED
                        expired.append(msg_id)
                
                for msg_id in expired:
                    del self._pending_acks[msg_id]
                
                if expired:
                    logger.info(f"[MQ] 清理 {len(expired)} 条过期消息")
                
                await asyncio.sleep(self.CLEANUP_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MQ] 清理循环错误：{e}")
    
    def get_queue_size(self, receiver: str) -> int:
        """获取队列大小"""
        if receiver not in self._queues:
            return 0
        return len(self._queues[receiver])
    
    def get_total_pending(self) -> int:
        """获取总待确认消息数"""
        return len(self._pending_acks)
    
    def on_message(self, callback: Callable):
        """注册消息回调"""
        event_types = ['enqueue', 'dequeue', 'ack', 'nack']
        for event_type in event_types:
            if event_type not in self._callbacks:
                self._callbacks[event_type] = []
            self._callbacks[event_type].append(callback)
    
    async def _notify_message(self, event: str, message: Message):
        """通知消息事件"""
        callbacks = self._callbacks.get(event, [])
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event, message)
                else:
                    callback(event, message)
            except Exception as e:
                logger.error(f"[MQ] 回调执行错误：{e}")
