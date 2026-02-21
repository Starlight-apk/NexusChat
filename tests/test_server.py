"""
NexusChat 测试套件
=================

测试服务器的各项功能。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestClient:
    """测试客户端"""
    
    def __init__(self, host: str = "localhost", port: int = 5222):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
    
    async def connect(self) -> bool:
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            # 读取欢迎消息
            await self.reader.readline()
            return True
        except Exception as e:
            print(f"连接失败：{e}")
            return False
    
    async def send(self, data: dict) -> dict:
        message = json.dumps(data) + "\n"
        self.writer.write(message.encode())
        await self.writer.drain()
        
        response = await self.reader.readline()
        if response:
            return json.loads(response.decode())
        return {}
    
    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()


async def test_register(client: TestClient) -> bool:
    """测试注册"""
    print("测试：用户注册...", end=" ")
    
    username = f"test_user_{int(time.time())}"
    password = "test123456"
    
    response = await client.send({
        "type": "register",
        "username": username,
        "password": password
    })
    
    if response.get("type") == "register_success":
        print("✓ 通过")
        return True, username, password
    elif response.get("type") == "error" and "已存在" in response.get("message", ""):
        print("✓ 通过 (用户已存在)")
        return True, username, password
    else:
        print(f"✗ 失败：{response.get('message')}")
        return False, None, None


async def test_auth(client: TestClient, username: str, password: str) -> bool:
    """测试认证"""
    print("测试：用户认证...", end=" ")
    
    response = await client.send({
        "type": "auth",
        "username": username,
        "password": password
    })
    
    if response.get("type") == "auth_success":
        print("✓ 通过")
        return True
    else:
        print(f"✗ 失败：{response.get('message')}")
        return False


async def test_ping(client: TestClient) -> bool:
    """测试 ping"""
    print("测试：Ping 连接...", end=" ")
    
    start = time.time()
    response = await client.send({"type": "ping"})
    latency = (time.time() - start) * 1000
    
    if response.get("type") == "pong":
        print(f"✓ 通过 (延迟：{latency:.1f}ms)")
        return True
    else:
        print(f"✗ 失败")
        return False


async def test_room(client: TestClient) -> bool:
    """测试房间功能"""
    print("测试：房间创建和加入...", end=" ")
    
    # 创建房间
    response = await client.send({
        "type": "room_create",
        "name": f"测试房间_{int(time.time())}",
        "public": True
    })
    
    if response.get("type") != "room_created":
        print(f"✗ 创建失败：{response.get('message')}")
        return False
    
    room_id = response["room"]["id"]
    
    # 加入房间
    response = await client.send({
        "type": "room_join",
        "room_id": room_id
    })
    
    if response.get("type") != "room_joined":
        print(f"✗ 加入失败：{response.get('message')}")
        return False
    
    # 发送房间消息
    response = await client.send({
        "type": "room_message",
        "room_id": room_id,
        "content": "测试消息"
    })
    
    if response.get("type") != "room_message_sent":
        print(f"✗ 消息发送失败")
        return False
    
    # 离开房间
    response = await client.send({
        "type": "room_leave",
        "room_id": room_id
    })
    
    if response.get("type") != "room_left":
        print(f"✗ 离开失败")
        return False
    
    print("✓ 通过")
    return True


async def test_message(client: TestClient, username: str) -> bool:
    """测试消息功能"""
    print("测试：消息发送（离线）...", end=" ")
    
    # 发送给自己（离线消息测试）
    response = await client.send({
        "type": "message",
        "to": username,
        "content": "离线消息测试"
    })
    
    if response.get("type") == "message" and response.get("status") == "sent":
        print("✓ 通过")
        return True
    else:
        print(f"✗ 失败")
        return False


async def test_room_list(client: TestClient) -> bool:
    """测试房间列表"""
    print("测试：房间列表...", end=" ")
    
    response = await client.send({"type": "room_list"})
    
    if response.get("type") == "room_list":
        rooms = response.get("rooms", [])
        print(f"✓ 通过 (共 {len(rooms)} 个房间)")
        return True
    else:
        print(f"✗ 失败")
        return False


async def test_users(client: TestClient) -> bool:
    """测试用户列表"""
    print("测试：在线用户列表...", end=" ")
    
    response = await client.send({"type": "users"})
    
    if response.get("type") == "users":
        users = response.get("users", [])
        print(f"✓ 通过 (共 {len(users)} 个在线用户)")
        return True
    else:
        print(f"✗ 失败")
        return False


async def run_tests():
    """运行所有测试"""
    print("=" * 50)
    print("NexusChat 功能测试")
    print("=" * 50)
    print()
    
    # 检查服务器是否运行
    print("检查服务器连接...")
    client = TestClient()
    
    if not await client.connect():
        print("\n✗ 无法连接到服务器，请先启动服务器:")
        print("  python main.py")
        return
    
    print("服务器连接成功!\n")
    
    results = []

    # 测试注册
    success, username, password = await test_register(client)
    if not success:
        # 尝试使用已有用户测试
        username = "test"
        password = "test123"
    
    # 注册后需要登录才能进行后续测试
    print("测试：用户登录...", end=" ")
    login_response = await client.send({
        "type": "auth",
        "username": username,
        "password": password
    })
    if login_response.get("type") == "auth_success":
        print("✓ 通过")
    else:
        print(f"✗ 失败：{login_response.get('message')}")
        print("\n认证失败，无法继续测试")
        await client.close()
        return
    
    # 测试认证
    if not await test_auth(client, username, password):
        print("\n认证失败，无法继续测试")
        await client.close()
        return
    
    # 运行其他测试
    results.append(await test_ping(client))
    results.append(await test_room(client))
    results.append(await test_message(client, username))
    results.append(await test_room_list(client))
    results.append(await test_users(client))
    
    # 清理
    await client.close()
    
    # 总结
    print()
    print("=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"测试结果：{passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过!")
    else:
        print(f"⚠️  {total - passed} 个测试失败")
    
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(run_tests())
