"""
NexusChat 核心服务器模块
======================

基于 asyncio 实现的高性能异步服务器核心。
"""

import asyncio
import json
import logging
import ssl
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Callable, Any
from pathlib import Path

from .protocol import ProtocolHandler, Message, MessageType
from .auth import AuthManager, User
from .room import RoomManager, Room
from .storage import StorageManager


@dataclass
class ClientSession:
    """客户端会话信息"""
    user: User
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    client_info: Dict[str, Any] = field(default_factory=dict)


class NexusChatServer:
    """
    NexusChat 核心服务器类
    
    功能:
    - 异步 TCP 服务器
    - 多客户端并发处理
    - 自动会话管理
    - 热重载配置支持
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
        self.logger = self._setup_logging()
        
        # 核心组件
        self.storage = StorageManager(self.config)
        self.auth = AuthManager(self.storage)
        self.room_manager = RoomManager(self.storage)
        self.protocol = ProtocolHandler()
        
        # 会话管理
        self.sessions: Dict[str, ClientSession] = {}  # user_id -> session
        self.socket_sessions: Dict[int, ClientSession] = {}  # socket_id -> session
        
        # 服务器状态
        self.server: Optional[asyncio.Server] = None
        self.running = False
        self.start_time: Optional[float] = None
        
        # 统计信息
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "connections_total": 0,
            "connections_current": 0,
        }
        
        self.logger.info("NexusChat 服务器初始化完成")
    
    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            "server": {
                "host": "0.0.0.0",
                "port": 5222,
                "tls_port": 5223,
                "enable_tls": False,
            },
            "auth": {
                "allow_registration": True,
                "password_min_length": 6,
            },
            "message": {
                "max_size": 4096,
                "history_size": 100,
            },
            "logging": {
                "level": "INFO",
            },
        }
    
    def _setup_logging(self) -> logging.Logger:
        """配置日志系统"""
        logger = logging.getLogger("NexusChat")
        level = getattr(logging, self.config.get("logging", {}).get("level", "INFO"))
        logger.setLevel(level)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    async def start(self) -> None:
        """启动服务器"""
        server_config = self.config.get("server", {})
        host = server_config.get("host", "0.0.0.0")
        port = server_config.get("port", 5222)
        
        # SSL 配置
        ssl_context = None
        if server_config.get("enable_tls"):
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(
                server_config.get("tls_cert"),
                server_config.get("tls_key")
            )
            self.logger.info(f"TLS 已启用，证书：{server_config.get('tls_cert')}")
        
        # 创建服务器
        self.server = await asyncio.start_server(
            self._handle_client,
            host,
            port,
            ssl=ssl_context
        )
        
        self.running = True
        self.start_time = time.time()
        
        addr = self.server.sockets[0].getsockname()
        self.logger.info(f"服务器启动于 {addr[0]}:{addr[1]}")
        self.logger.info("=" * 50)
        
        async with self.server:
            await self.server.serve_forever()
    
    async def stop(self) -> None:
        """停止服务器"""
        self.logger.info("正在关闭服务器...")
        self.running = False
        
        # 关闭所有客户端连接
        for session in list(self.sessions.values()):
            try:
                session.writer.close()
                await session.writer.wait_closed()
            except Exception:
                pass
        
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # 保存数据
        await self.storage.save_all()
        
        self.logger.info("服务器已关闭")
    
    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """处理客户端连接"""
        socket_id = id(writer)
        self.stats["connections_total"] += 1
        self.stats["connections_current"] += 1
        
        peername = writer.get_extra_info("peername")
        self.logger.debug(f"新连接来自 {peername}")
        
        session: Optional[ClientSession] = None
        
        try:
            # 发送欢迎消息
            welcome = self.protocol.encode({
                "type": "welcome",
                "server": "NexusChat",
                "version": "1.0.0",
                "timestamp": time.time()
            })
            writer.write(welcome)
            await writer.drain()
            
            while self.running:
                data = await reader.read(4096)
                if not data:
                    break
                
                # 更新会话活动
                if session:
                    session.last_activity = time.time()
                
                # 解析消息
                try:
                    messages = self.protocol.decode(data)
                except Exception as e:
                    self.logger.warning(f"协议解析错误：{e}")
                    continue
                
                for msg in messages:
                    response, new_session = await self._process_message(msg, session, writer)
                    if new_session:
                        session = new_session
                    if response:
                        writer.write(response)
                        await writer.drain()
        
        except asyncio.CancelledError:
            self.logger.debug(f"连接 {socket_id} 被取消")
        except ConnectionResetError:
            self.logger.debug(f"连接 {socket_id} 被重置")
        except Exception as e:
            self.logger.error(f"处理连接错误：{e}")
        
        finally:
            # 清理会话
            if session and session.user.id in self.sessions:
                del self.sessions[session.user.id]
                await self._broadcast_presence(session.user, False)
            
            if socket_id in self.socket_sessions:
                del self.socket_sessions[socket_id]
            
            self.stats["connections_current"] -= 1
            
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            
            self.logger.debug(f"连接 {socket_id} 关闭")
    
    async def _process_message(
        self,
        msg: Dict,
        session: Optional[ClientSession],
        writer: asyncio.StreamWriter
    ) -> tuple:
        """处理单条消息
        
        Returns:
            (response_bytes, new_session_or_none)
        """
        self.stats["messages_received"] += 1
        msg_type = msg.get("type", "")

        self.logger.debug(f"收到消息类型：{msg_type}")
        
        try:
            if msg_type == "auth":
                response, new_session = await self._handle_auth(msg, writer)
                return response, new_session

            elif msg_type == "register":
                return await self._handle_register(msg, writer)

            elif msg_type == "message":
                if not session:
                    return self.protocol.error("未认证"), None
                return await self._handle_message(msg, session)

            elif msg_type == "room_create":
                if not session:
                    return self.protocol.error("未认证"), None
                return await self._handle_room_create(msg, session)

            elif msg_type == "room_join":
                if not session:
                    return self.protocol.error("未认证"), None
                return await self._handle_room_join(msg, session)

            elif msg_type == "room_leave":
                if not session:
                    return self.protocol.error("未认证"), None
                return await self._handle_room_leave(msg, session)

            elif msg_type == "room_message":
                if not session:
                    return self.protocol.error("未认证"), None
                return await self._handle_room_message(msg, session)

            elif msg_type == "room_list":
                if not session:
                    return self.protocol.error("未认证"), None
                return await self._handle_room_list(session)

            elif msg_type == "ping":
                return self.protocol.encode({"type": "pong", "timestamp": time.time()}), None

            elif msg_type == "whoami":
                if not session:
                    return self.protocol.error("未认证"), None
                return self.protocol.encode({
                    "type": "whoami",
                    "user": session.user.to_dict()
                }), None

            elif msg_type == "users":
                if not session:
                    return self.protocol.error("未认证"), None
                return await self._handle_users(session)

            else:
                return self.protocol.error(f"未知消息类型：{msg_type}"), None

        except Exception as e:
            self.logger.error(f"处理消息错误：{e}")
            return self.protocol.error(str(e)), None
    
    async def _handle_auth(
        self,
        msg: Dict,
        writer: asyncio.StreamWriter
    ) -> tuple:
        """处理认证请求
        
        Returns:
            (response_bytes, session)
        """
        username = msg.get("username")
        password = msg.get("password")

        if not username or not password:
            return self.protocol.error("缺少用户名或密码"), None

        user = await self.auth.authenticate(username, password)
        if not user:
            return self.protocol.error("认证失败"), None

        # 创建会话
        session = ClientSession(user=user, reader=None, writer=writer)
        self.sessions[user.id] = session
        self.socket_sessions[id(writer)] = session

        self.logger.info(f"用户 {username} 已认证")

        # 广播在线状态
        await self._broadcast_presence(user, True)

        return self.protocol.encode({
            "type": "auth_success",
            "user": user.to_dict(),
            "session_id": user.id
        }), session
    
    async def _handle_register(
        self,
        msg: Dict,
        writer: asyncio.StreamWriter
    ) -> tuple:
        """处理注册请求
        
        Returns:
            (response_bytes, None)
        """
        if not self.config.get("auth", {}).get("allow_registration", True):
            return self.protocol.error("注册已禁用"), None

        username = msg.get("username")
        password = msg.get("password")
        email = msg.get("email", "")

        if not username or not password:
            return self.protocol.error("缺少用户名或密码"), None

        # 验证密码长度
        min_len = self.config.get("auth", {}).get("password_min_length", 6)
        if len(password) < min_len:
            return self.protocol.error(f"密码长度至少为 {min_len}"), None

        user = await self.auth.register(username, password, email)
        if not user:
            return self.protocol.error("用户名已存在"), None

        self.logger.info(f"新用户注册：{username}")

        return self.protocol.encode({
            "type": "register_success",
            "user": user.to_dict()
        }), None
    
    async def _handle_message(
        self,
        msg: Dict,
        session: ClientSession
    ) -> tuple:
        """处理私聊消息"""
        to_user = msg.get("to")
        content = msg.get("content", "")

        if not to_user:
            return self.protocol.error("缺少接收者"), None

        # 限制消息大小
        max_size = self.config.get("message", {}).get("max_size", 4096)
        if len(content) > max_size:
            return self.protocol.error(f"消息超过最大长度 {max_size}"), None

        # 查找接收者
        target_session = self.sessions.get(to_user)

        # 创建消息对象
        message_data = {
            "type": "message",
            "from": session.user.id,
            "from_username": session.user.username,
            "to": to_user,
            "content": content,
            "timestamp": time.time()
        }

        # 保存消息历史
        await self.storage.save_message(session.user.id, to_user, message_data)

        if target_session:
            # 在线，直接发送
            try:
                target_session.writer.write(self.protocol.encode(message_data))
                await target_session.writer.drain()
            except Exception as e:
                self.logger.warning(f"发送消息失败：{e}")
        elif self.config.get("message", {}).get("enable_offline", True):
            # 离线消息存储
            await self.storage.save_offline_message(to_user, message_data)

        self.stats["messages_sent"] += 1

        # 发送确认
        message_data["status"] = "sent"
        return self.protocol.encode(message_data), None
    
    async def _handle_room_create(
        self,
        msg: Dict,
        session: ClientSession
    ) -> tuple:
        """创建房间"""
        name = msg.get("name")
        is_public = msg.get("public", True)

        if not name:
            return self.protocol.error("缺少房间名称"), None

        room = await self.room_manager.create_room(
            name=name,
            owner=session.user,
            is_public=is_public
        )

        if not room:
            return self.protocol.error("创建房间失败"), None

        self.logger.info(f"房间创建：{room.id} by {session.user.username}")

        return self.protocol.encode({
            "type": "room_created",
            "room": room.to_dict()
        }), None

    async def _handle_room_join(
        self,
        msg: Dict,
        session: ClientSession
    ) -> tuple:
        """加入房间"""
        room_id = msg.get("room_id")

        if not room_id:
            return self.protocol.error("缺少房间 ID"), None

        room = await self.room_manager.get_room(room_id)
        if not room:
            return self.protocol.error("房间不存在"), None

        success = await self.room_manager.join_room(room, session.user)
        if not success:
            return self.protocol.error("加入房间失败"), None

        # 通知房间内其他成员
        await self._broadcast_to_room(
            room,
            {
                "type": "room_member_join",
                "room_id": room.id,
                "user": session.user.to_dict(),
                "timestamp": time.time()
            },
            exclude=session.user.id
        )

        # 发送房间历史消息
        history = await self.storage.get_room_history(room.id, 50)

        return self.protocol.encode({
            "type": "room_joined",
            "room": room.to_dict(),
            "history": history
        }), None

    async def _handle_room_leave(
        self,
        msg: Dict,
        session: ClientSession
    ) -> tuple:
        """离开房间"""
        room_id = msg.get("room_id")

        if not room_id:
            return self.protocol.error("缺少房间 ID"), None

        room = await self.room_manager.get_room(room_id)
        if not room:
            return self.protocol.error("房间不存在"), None

        await self.room_manager.leave_room(room, session.user.id)

        # 通知房间内其他成员
        await self._broadcast_to_room(
            room,
            {
                "type": "room_member_leave",
                "room_id": room.id,
                "user_id": session.user.id,
                "timestamp": time.time()
            }
        )

        return self.protocol.encode({
            "type": "room_left",
            "room_id": room.id
        }), None
    
    async def _handle_room_message(
        self,
        msg: Dict,
        session: ClientSession
    ) -> tuple:
        """发送房间消息"""
        room_id = msg.get("room_id")
        content = msg.get("content", "")

        if not room_id:
            return self.protocol.error("缺少房间 ID"), None

        room = await self.room_manager.get_room(room_id)
        if not room:
            return self.protocol.error("房间不存在"), None

        if session.user.id not in room.members:
            return self.protocol.error("不在房间内"), None

        # 限制消息大小
        max_size = self.config.get("message", {}).get("max_size", 4096)
        if len(content) > max_size:
            return self.protocol.error(f"消息超过最大长度 {max_size}"), None

        message_data = {
            "type": "room_message",
            "room_id": room_id,
            "from": session.user.id,
            "from_username": session.user.username,
            "content": content,
            "timestamp": time.time()
        }

        # 保存消息
        await self.storage.save_room_message(room_id, message_data)

        # 广播给房间成员（排除发送者）
        await self._broadcast_to_room(room, message_data, exclude=session.user.id)

        self.stats["messages_sent"] += 1

        return self.protocol.encode({
            "type": "room_message_sent",
            "room_id": room_id,
            "status": "sent"
        }), None

    async def _handle_room_list(
        self,
        session: ClientSession
    ) -> tuple:
        """获取房间列表"""
        rooms = await self.room_manager.list_rooms()
        return self.protocol.encode({
            "type": "room_list",
            "rooms": [r.to_dict() for r in rooms]
        }), None

    async def _handle_users(
        self,
        session: ClientSession
    ) -> tuple:
        """获取在线用户列表"""
        users = [
            {
                "id": s.user.id,
                "username": s.user.username,
                "connected_at": s.connected_at
            }
            for s in self.sessions.values()
        ]
        return self.protocol.encode({
            "type": "users",
            "users": users
        }), None
    
    async def _broadcast_presence(self, user: User, online: bool) -> None:
        """广播用户在线状态"""
        message = self.protocol.encode({
            "type": "presence",
            "user_id": user.id,
            "username": user.username,
            "online": online,
            "timestamp": time.time()
        })
        
        for session in self.sessions.values():
            if session.user.id != user.id:
                try:
                    session.writer.write(message)
                    await session.writer.drain()
                except Exception:
                    pass
    
    async def _broadcast_to_room(
        self,
        room: Room,
        message: Dict,
        exclude: Optional[str] = None
    ) -> None:
        """广播消息到房间"""
        data = self.protocol.encode(message)
        
        for member_id in room.members:
            if member_id == exclude:
                continue
            
            session = self.sessions.get(member_id)
            if session:
                try:
                    session.writer.write(data)
                    await session.writer.drain()
                except Exception:
                    pass
    
    def get_stats(self) -> Dict:
        """获取服务器统计信息"""
        uptime = time.time() - self.start_time if self.start_time else 0
        return {
            **self.stats,
            "uptime": uptime,
            "sessions": len(self.sessions),
            "rooms": len(self.room_manager.rooms),
        }
