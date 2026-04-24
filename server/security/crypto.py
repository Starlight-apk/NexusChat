"""
安全加密模块
实现端到端加密、密钥管理、双棘轮算法
"""

import hashlib
import hmac
import os
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class KeyPair:
    """密钥对"""
    public_key: bytes
    private_key: bytes
    key_id: str
    created_at: float = field(default_factory=time.time)


@dataclass
class SessionKeys:
    """会话密钥 (双棘轮)"""
    chain_key_send: bytes
    chain_key_recv: bytes
    root_key: bytes
    dh_public: bytes
    dh_private: bytes
    message_number: int = 0
    received_messages: Dict[int, bytes] = field(default_factory=dict)


class CryptoManager:
    """
    加密管理器
    提供端到端加密、密钥派生、双棘轮算法
    """
    
    KEY_SIZE = 32
    IV_SIZE = 16
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self._key_pairs: Dict[str, KeyPair] = {}
        self._sessions: Dict[str, SessionKeys] = {}  # session_id -> keys
        self._trusted_keys: Dict[str, bytes] = {}  # user_id -> public_key
        
    async def start(self):
        """启动加密模块"""
        logger.info(f"[CRYPTO] 启动加密管理器 (节点：{self.node_id})")
        
        # 生成服务器密钥对
        await self._generate_server_keys()
        
        # 加载 HSM (硬件安全模块) 模拟
        await self._init_hsm()
        
        logger.info(f"[CRYPTO] 加密管理器已就绪")
    
    async def stop(self):
        """停止加密模块"""
        logger.info(f"[CRYPTO] 停止加密管理器")
        # 安全擦除敏感数据
        self._secure_wipe()
    
    async def _generate_server_keys(self):
        """生成服务器密钥对"""
        logger.info("[CRYPTO] 生成服务器密钥对...")
        await asyncio.sleep(0.5)  # 模拟密钥生成时间
        
        # 模拟生成密钥 (实际应使用密码学安全的随机数生成器)
        public_key = os.urandom(self.KEY_SIZE)
        private_key = os.urandom(self.KEY_SIZE)
        key_id = hashlib.sha256(public_key).hexdigest()[:16]
        
        self._key_pairs['server'] = KeyPair(
            public_key=public_key,
            private_key=private_key,
            key_id=key_id
        )
        
        logger.info(f"[CRYPTO] 服务器密钥对已生成 (ID: {key_id})")
    
    async def _init_hsm(self):
        """初始化硬件安全模块 (模拟)"""
        logger.info("[CRYPTO] 连接 HSM (硬件安全模块)...")
        await asyncio.sleep(1.0)  # 模拟 HSM 连接延迟
        
        logger.info("[CRYPTO] HSM 已连接 (模拟模式)")
    
    def generate_user_keys(self, user_id: str) -> KeyPair:
        """为用户生成密钥对"""
        public_key = os.urandom(self.KEY_SIZE)
        private_key = os.urandom(self.KEY_SIZE)
        key_id = hashlib.sha256(public_key).hexdigest()[:16]
        
        key_pair = KeyPair(
            public_key=public_key,
            private_key=private_key,
            key_id=key_id
        )
        
        self._key_pairs[user_id] = key_pair
        logger.debug(f"[CRYPTO] 为用户 {user_id} 生成密钥对")
        
        return key_pair
    
    def trust_key(self, user_id: str, public_key: bytes) -> bool:
        """信任用户公钥"""
        self._trusted_keys[user_id] = public_key
        logger.debug(f"[CRYPTO] 信任用户 {user_id} 的公钥")
        return True
    
    def create_session(self, session_id: str, peer_public_key: bytes) -> SessionKeys:
        """创建加密会话 (双棘轮初始化)"""
        logger.debug(f"[CRYPTO] 创建会话 {session_id}")
        
        # 生成临时 DH 密钥对
        dh_private = os.urandom(self.KEY_SIZE)
        dh_public = os.urandom(self.KEY_SIZE)
        
        # 派生根密钥 (模拟 DH 交换)
        root_key = hashlib.sha256(
            dh_public + peer_public_key + dh_private
        ).digest()
        
        # 派生链密钥
        chain_key_send = hashlib.sha256(root_key + b'send').digest()
        chain_key_recv = hashlib.sha256(root_key + b'recv').digest()
        
        session = SessionKeys(
            chain_key_send=chain_key_send,
            chain_key_recv=chain_key_recv,
            root_key=root_key,
            dh_public=dh_public,
            dh_private=dh_private
        )
        
        self._sessions[session_id] = session
        return session
    
    def encrypt_message(self, session_id: str, plaintext: bytes) -> Tuple[bytes, dict]:
        """加密消息"""
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在：{session_id}")
        
        session = self._sessions[session_id]
        
        # 双棘轮：更新发送链密钥
        session.chain_key_send = hashlib.sha256(session.chain_key_send).digest()
        message_key = hashlib.sha256(session.chain_key_send + b'msg').digest()
        
        # 生成 IV
        iv = os.urandom(self.IV_SIZE)
        
        # 模拟加密 (实际应使用 AES-GCM 等)
        ciphertext = bytes([p ^ k for p, k in zip(plaintext, itertools.cycle(message_key))])
        
        metadata = {
            'iv': iv.hex(),
            'msg_num': session.message_number,
            'session_id': session_id
        }
        
        session.message_number += 1
        
        return ciphertext, metadata
    
    def decrypt_message(self, session_id: str, ciphertext: bytes, 
                       metadata: dict) -> bytes:
        """解密消息"""
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在：{session_id}")
        
        session = self._sessions[session_id]
        msg_num = metadata.get('msg_num', 0)
        
        # 检查是否已接收 (防重放攻击)
        if msg_num in session.received_messages:
            raise ValueError("消息已接收 (重放攻击)")
        
        # 双棘轮：更新接收链密钥
        session.chain_key_recv = hashlib.sha256(session.chain_key_recv).digest()
        message_key = hashlib.sha256(session.chain_key_recv + b'msg').digest()
        
        # 模拟解密
        plaintext = bytes([c ^ k for c, k in zip(ciphertext, itertools.cycle(message_key))])
        
        # 记录已接收消息
        session.received_messages[msg_num] = ciphertext
        
        return plaintext
    
    def rotate_session_keys(self, session_id: str, new_dh_public: bytes) -> SessionKeys:
        """轮换会话密钥 (双棘轮 Ratchet)"""
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在：{session_id}")
        
        session = self._sessions[session_id]
        
        # 生成新的 DH 密钥对
        new_dh_private = os.urandom(self.KEY_SIZE)
        new_dh_public = os.urandom(self.KEY_SIZE)
        
        # DH 计算 (模拟)
        dh_output = hashlib.sha256(
            new_dh_public + session.dh_public + new_dh_private
        ).digest()
        
        # 更新根密钥
        session.root_key = hashlib.sha256(session.root_key + dh_output).digest()
        
        # 更新链密钥
        session.chain_key_send = hashlib.sha256(session.root_key + b'send').digest()
        session.chain_key_recv = hashlib.sha256(session.root_key + b'recv').digest()
        
        # 更新 DH 密钥
        session.dh_public = new_dh_public
        session.dh_private = new_dh_private
        session.message_number = 0
        
        logger.debug(f"[CRYPTO] 会话 {session_id} 密钥已轮换")
        
        return session
    
    def _secure_wipe(self):
        """安全擦除敏感数据"""
        logger.info("[CRYPTO] 安全擦除敏感数据...")
        
        # 擦除私钥
        for key_pair in self._key_pairs.values():
            # 模拟安全擦除
            key_pair.private_key = b'\x00' * len(key_pair.private_key)
        
        # 清除会话
        self._sessions.clear()
        
        logger.info("[CRYPTO] 敏感数据已擦除")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'key_pairs': len(self._key_pairs),
            'active_sessions': len(self._sessions),
            'trusted_keys': len(self._trusted_keys)
        }


# 需要导入 itertools
import itertools
import asyncio
