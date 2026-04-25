"""
NexusChat 存储模块单元测试
=========================

测试 JSON 和 SQLite 两种存储后端的功能。
"""

import asyncio
import pytest
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.storage import StorageManager
from server.auth import User


class TestJSONStorage:
    """测试 JSON 存储后端"""
    
    @pytest.fixture
    def storage(self):
        """创建临时 JSON 存储"""
        temp_dir = tempfile.mkdtemp()
        config = {
            "storage": {"data_dir": temp_dir, "type": "json"},
            "message": {"history_size": 100}
        }
        storage = StorageManager(config)
        yield storage
        shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_save_and_get_user(self, storage):
        """测试用户保存和获取"""
        user = User(id="user1", username="testuser", created_at=1234567890.0)
        await storage.save_user(user)
        
        retrieved = await storage.get_user("user1")
        assert retrieved is not None
        assert retrieved.username == "testuser"
    
    @pytest.mark.asyncio
    async def test_get_user_by_username(self, storage):
        """测试通过用户名获取用户"""
        user = User(id="user1", username="testuser", created_at=1234567890.0)
        await storage.save_user(user)
        
        retrieved = await storage.get_user_by_username("testuser")
        assert retrieved is not None
        assert retrieved.id == "user1"
    
    @pytest.mark.asyncio
    async def test_save_and_get_password(self, storage):
        """测试密码保存和获取"""
        await storage.save_password("user1", "hashed_password_123")
        
        password = await storage.get_password("user1")
        assert password == "hashed_password_123"
    
    @pytest.mark.asyncio
    async def test_save_and_get_room(self, storage):
        """测试房间保存和获取"""
        from server.room import Room
        room = Room(id="room1", name="Test Room", owner_id="user1", is_public=True, created_at=1234567890.0)
        room.members.add("user1")
        room.members.add("user2")
        await storage.save_room(room)
        
        retrieved = await storage.get_room("room1")
        assert retrieved is not None
        assert retrieved.name == "Test Room"
        assert "user1" in retrieved.members
        assert "user2" in retrieved.members
    
    @pytest.mark.asyncio
    async def test_list_rooms(self, storage):
        """测试列出所有房间"""
        from server.room import Room
        room1 = Room(id="room1", name="Room 1", owner_id="user1", is_public=True, created_at=1234567890.0)
        room2 = Room(id="room2", name="Room 2", owner_id="user2", is_public=False, created_at=1234567891.0)
        await storage.save_room(room1)
        await storage.save_room(room2)
        
        rooms = await storage.list_rooms()
        assert len(rooms) == 2


class TestSQLiteStorage:
    """测试 SQLite 存储后端"""
    
    @pytest.fixture
    def storage(self):
        """创建临时 SQLite 存储"""
        temp_dir = tempfile.mkdtemp()
        config = {
            "storage": {"data_dir": temp_dir, "type": "sqlite"},
            "message": {"history_size": 100}
        }
        storage = StorageManager(config)
        yield storage
        shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_save_and_get_user(self, storage):
        """测试用户保存和获取"""
        user = User(id="user1", username="testuser", created_at=1234567890.0)
        await storage.save_user(user)
        
        retrieved = await storage.get_user("user1")
        assert retrieved is not None
        assert retrieved.username == "testuser"
    
    @pytest.mark.asyncio
    async def test_get_user_by_username(self, storage):
        """测试通过用户名获取用户"""
        user = User(id="user1", username="testuser", created_at=1234567890.0)
        await storage.save_user(user)
        
        retrieved = await storage.get_user_by_username("testuser")
        assert retrieved is not None
        assert retrieved.id == "user1"
    
    @pytest.mark.asyncio
    async def test_save_and_get_password(self, storage):
        """测试密码保存和获取"""
        await storage.save_password("user1", "hashed_password_123")
        
        password = await storage.get_password("user1")
        assert password == "hashed_password_123"
    
    @pytest.mark.asyncio
    async def test_save_and_get_room(self, storage):
        """测试房间保存和获取"""
        from server.room import Room
        room = Room(id="room1", name="Test Room", owner_id="user1", is_public=True, created_at=1234567890.0)
        room.members.add("user1")
        room.members.add("user2")
        await storage.save_room(room)
        
        retrieved = await storage.get_room("room1")
        assert retrieved is not None
        assert retrieved.name == "Test Room"
        assert "user1" in retrieved.members
        assert "user2" in retrieved.members
    
    @pytest.mark.asyncio
    async def test_save_and_get_message(self, storage):
        """测试消息保存和获取"""
        message = {
            "from": "user1",
            "to": "user2",
            "content": "Hello!",
            "timestamp": 1234567890.0
        }
        await storage.save_message("user1", "user2", message)
        
        history = await storage.get_message_history("user1", "user2")
        assert len(history) == 1
        assert history[0]["content"] == "Hello!"
    
    @pytest.mark.asyncio
    async def test_save_and_get_offline_message(self, storage):
        """测试离线消息保存和获取"""
        message = {
            "from": "user1",
            "content": "Offline message",
            "timestamp": 1234567890.0
        }
        await storage.save_offline_message("user2", message)
        
        messages = await storage.get_offline_messages("user2")
        assert len(messages) == 1
        assert messages[0]["content"] == "Offline message"
        
        await storage.clear_offline_messages("user2")
        messages = await storage.get_offline_messages("user2")
        assert len(messages) == 0
    
    @pytest.mark.asyncio
    async def test_save_and_get_room_message(self, storage):
        """测试房间消息保存和获取"""
        message = {
            "from": "user1",
            "content": "Room message",
            "timestamp": 1234567890.0
        }
        await storage.save_room_message("room1", message)
        await storage.save_room_message("room1", {**message, "content": "Message 2"})
        await storage.save_room_message("room1", {**message, "content": "Message 3"})
        
        history = await storage.get_room_history("room1")
        assert len(history) == 3
        # 按时间倒序排列，最新的在前面
        assert history[-1]["content"] == "Room message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
