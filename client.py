#!/usr/bin/env python3
"""
NexusChat 简单命令行客户端
=========================

用于测试和演示 NexusChat 服务器功能。

用法:
    python client.py <host> <port>
    python client.py localhost 5222
"""

import asyncio
import json
import sys
import time


class NexusChatClient:
    """简单的命令行客户端"""
    
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.username = None
        self.user_id = None
        self.running = False
    
    async def connect(self) -> bool:
        """连接到服务器"""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            print(f"已连接到 {self.host}:{self.port}")
            
            # 读取欢迎消息
            welcome = await self.reader.readline()
            if welcome:
                data = json.loads(welcome.decode())
                print(f"服务器：{data.get('server')} v{data.get('version')}")
            
            return True
        except Exception as e:
            print(f"连接失败：{e}")
            return False
    
    async def send(self, data: dict) -> None:
        """发送消息"""
        message = json.dumps(data) + "\n"
        self.writer.write(message.encode())
        await self.writer.drain()
    
    async def receive(self):
        """接收消息"""
        try:
            line = await self.reader.readline()
            if line:
                return json.loads(line.decode())
        except Exception:
            pass
        return None
    
    async def register(self, username: str, password: str) -> bool:
        """注册"""
        await self.send({
            "type": "register",
            "username": username,
            "password": password
        })
        
        response = await self.receive()
        if response:
            if response.get("type") == "register_success":
                print(f"注册成功！用户 ID: {response['user']['id']}")
                return True
            else:
                print(f"注册失败：{response.get('message')}")
        return False
    
    async def login(self, username: str, password: str) -> bool:
        """登录"""
        await self.send({
            "type": "auth",
            "username": username,
            "password": password
        })
        
        response = await self.receive()
        if response:
            if response.get("type") == "auth_success":
                self.username = username
                self.user_id = response.get("session_id")
                print(f"登录成功！欢迎，{username}")
                return True
            else:
                print(f"登录失败：{response.get('message')}")
        return False
    
    async def send_message(self, to: str, content: str) -> None:
        """发送私聊消息"""
        await self.send({
            "type": "message",
            "to": to,
            "content": content
        })
    
    async def create_room(self, name: str, public: bool = True) -> None:
        """创建房间"""
        await self.send({
            "type": "room_create",
            "name": name,
            "public": public
        })
    
    async def join_room(self, room_id: str) -> None:
        """加入房间"""
        await self.send({
            "type": "room_join",
            "room_id": room_id
        })
    
    async def send_room_message(self, room_id: str, content: str) -> None:
        """发送房间消息"""
        await self.send({
            "type": "room_message",
            "room_id": room_id,
            "content": content
        })
    
    async def list_rooms(self) -> None:
        """列出房间"""
        await self.send({"type": "room_list"})
    
    async def list_users(self) -> None:
        """列出在线用户"""
        await self.send({"type": "users"})
    
    async def ping(self) -> None:
        """发送 ping"""
        await self.send({"type": "ping"})
    
    async def message_loop(self):
        """消息接收循环"""
        while self.running:
            try:
                msg = await self.receive()
                if msg:
                    self._print_message(msg)
            except Exception:
                break
    
    def _print_message(self, msg: dict) -> None:
        """打印消息"""
        msg_type = msg.get("type", "unknown")
        
        if msg_type == "message":
            print(f"\n[私聊] {msg.get('from_username')}: {msg.get('content')}")
        elif msg_type == "room_message":
            print(f"\n[房间:{msg.get('room_id')}] {msg.get('from_username')}: {msg.get('content')}")
        elif msg_type == "room_joined":
            print(f"\n已加入房间：{msg['room']['name']} ({msg['room']['id']})")
        elif msg_type == "room_created":
            print(f"\n房间已创建：{msg['room']['name']} ({msg['room']['id']})")
        elif msg_type == "room_list":
            print("\n=== 房间列表 ===")
            for room in msg.get("rooms", []):
                print(f"  {room['id']}: {room['name']} ({room['member_count']}人)")
        elif msg_type == "users":
            print("\n=== 在线用户 ===")
            for user in msg.get("users", []):
                print(f"  {user['username']} ({user['id']})")
        elif msg_type == "presence":
            status = "上线" if msg.get("online") else "下线"
            print(f"\n[状态] {msg.get('username')} {status}")
        elif msg_type == "pong":
            print(f"\n[Ping] 延迟：{(time.time() - msg.get('timestamp', 0)) * 1000:.0f}ms")
        elif msg_type == "error":
            print(f"\n[错误] {msg.get('message')}")
        elif msg_type == "welcome":
            pass  # 已处理
        else:
            print(f"\n[{msg_type}] {json.dumps(msg, ensure_ascii=False)}")
    
    async def input_loop(self):
        """用户输入循环"""
        print("\n=== 命令帮助 ===")
        print("  /msg <用户> <内容>  - 发送私聊")
        print("  /create <房间名>    - 创建房间")
        print("  /join <房间 ID>     - 加入房间")
        print("  /r <内容>           - 发送房间消息")
        print("  /rooms              - 列出房间")
        print("  /users              - 列出用户")
        print("  /ping               - 测试连接")
        print("  /quit               - 退出")
        print("==================\n")
        
        while self.running:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                await self._handle_command(line)
            except Exception:
                break
        
        self.running = False
    
    async def _handle_command(self, line: str):
        """处理命令"""
        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()
        
        if cmd == "/quit" or cmd == "/exit":
            self.running = False
            return
        
        if cmd == "/msg" and len(parts) >= 3:
            to = parts[1]
            content = parts[2]
            await self.send_message(to, content)
        
        elif cmd == "/create" and len(parts) >= 2:
            name = parts[1]
            await self.create_room(name)
        
        elif cmd == "/join" and len(parts) >= 2:
            room_id = parts[1]
            await self.join_room(room_id)
        
        elif cmd == "/r" and len(parts) >= 2:
            content = parts[1] if len(parts) == 2 else parts[1] + " " + parts[2]
            # 需要知道当前房间 ID，简化处理
            print("请先使用 /join 加入房间")
        
        elif cmd == "/rooms":
            await self.list_rooms()
        
        elif cmd == "/users":
            await self.list_users()
        
        elif cmd == "/ping":
            await self.ping()
        
        else:
            print(f"未知命令：{cmd}")
    
    async def run(self):
        """运行客户端"""
        if not await self.connect():
            return
        
        self.running = True
        
        # 登录/注册
        print("\n=== 登录/注册 ===")
        username = input("用户名：")
        password = input("密码：")
        
        if not await self.login(username, password):
            print("登录失败，是否注册？[y/N] ", end="")
            if input().lower() == "y":
                if await self.register(username, password):
                    await self.login(username, password)
                else:
                    return
            else:
                return
        
        # 启动消息循环
        receive_task = asyncio.create_task(self.message_loop())
        input_task = asyncio.create_task(self.input_loop())
        
        await asyncio.gather(receive_task, input_task, return_exceptions=True)
        
        # 清理
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass
        
        print("\n已断开连接")


async def main():
    if len(sys.argv) < 3:
        print("用法：python client.py <host> <port>")
        print("示例：python client.py localhost 5222")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2])
    
    client = NexusChatClient(host, port)
    await client.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见!")
