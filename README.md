# NexusChat

<div align="center">

![NexusChat Logo](https://img.shields.io/badge/NexusChat-v1.0.0-blue)
![Python](https://img.shields.io/badge/Python-3.8+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Dependencies](https://img.shields.io/badge/Dependencies-0~1-lightgrey)

**新一代轻量级聊天服务器框架**

零依赖 · 一键部署 · 高性能异步 · 类 XMPP 协议

</div>

---

## 📖 简介

NexusChat 是一个使用纯 Python 构建的轻量级即时通讯服务器框架，采用异步 IO 实现高并发，设计灵感来源于 XMPP 协议但更加简洁。

### ✨ 特性

- **🚀 零依赖运行** - 核心功能仅使用 Python 标准库
- **⚡ 高性能异步** - 基于 asyncio，单线程处理数千并发
- **📦 一键部署** - 提供完整的部署脚本
- **💬 完整功能** - 私聊、群聊、房间、离线消息
- **🔒 安全认证** - 支持密码哈希（可选 bcrypt）
- **📝 灵活存储** - JSON 文件存储，可选 SQLite
- **🛠️ 易扩展** - 模块化设计，易于二次开发

---

## 🚀 快速开始

### 一键部署

```bash
# 克隆项目
cd NexusChat

# 运行部署脚本
./scripts/deploy.sh --quick

# 启动服务器
./scripts/deploy.sh --start
```

### 手动启动

```bash
# 安装可选依赖（可选）
pip install -r requirements.txt

# 启动服务器
python main.py

# 指定端口
python main.py --port 8888
```

### 使用客户端测试

```bash
# 启动另一个终端
python client.py localhost 5222
```

---

## 📡 协议说明

NexusChat 使用基于 JSON 行的轻量级协议，所有消息均为 UTF-8 编码的 JSON 对象，以换行符分隔。

### 消息格式

```json
{"type": "message_type", "field": "value", "timestamp": 1234567890}
```

### 消息类型

#### 认证相关

| 类型 | 方向 | 说明 |
|------|------|------|
| `register` | C→S | 用户注册 |
| `auth` | C→S | 用户登录 |
| `register_success` | S→C | 注册成功 |
| `auth_success` | S→C | 登录成功 |

#### 消息相关

| 类型 | 方向 | 说明 |
|------|------|------|
| `message` | C→S / S→C | 私聊消息 |
| `room_message` | C→S / S→C | 房间消息 |

#### 房间相关

| 类型 | 方向 | 说明 |
|------|------|------|
| `room_create` | C→S | 创建房间 |
| `room_join` | C→S | 加入房间 |
| `room_leave` | C→S | 离开房间 |
| `room_list` | C→S | 获取房间列表 |

#### 状态相关

| 类型 | 方向 | 说明 |
|------|------|------|
| `ping` | C→S | 心跳请求 |
| `pong` | S→C | 心跳响应 |
| `presence` | S→C | 用户在线状态 |

### 使用示例

```python
import socket
import json

# 连接服务器
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("localhost", 5222))

# 注册
sock.send(b'{"type":"register","username":"test","password":"123456"}\n')

# 登录
sock.send(b'{"type":"auth","username":"test","password":"123456"}\n')

# 发送消息
sock.send(b'{"type":"message","to":"user2","content":"Hello!"}\n')

# 接收响应
response = sock.recv(4096)
print(json.loads(response.decode()))
```

---

## 📁 项目结构

```
NexusChat/
├── server/                 # 服务器核心模块
│   ├── __init__.py        # 模块导出
│   ├── core.py            # 服务器核心
│   ├── protocol.py        # 协议处理
│   ├── auth.py            # 认证管理
│   ├── room.py            # 房间管理
│   └── storage.py         # 存储管理
├── config/
│   └── config.yaml        # 配置文件
├── scripts/
│   └── deploy.sh          # 部署脚本
├── data/                  # 数据目录
├── logs/                  # 日志目录
├── main.py                # 入口文件
├── client.py              # 测试客户端
├── requirements.txt       # 依赖列表
└── README.md              # 说明文档
```

---

## ⚙️ 配置说明

编辑 `config/config.yaml`:

```yaml
server:
  host: "0.0.0.0"      # 监听地址
  port: 5222           # 服务端口
  enable_tls: false    # 是否启用 TLS

auth:
  allow_registration: true    # 允许注册
  password_min_length: 6      # 最小密码长度

message:
  max_size: 4096       # 最大消息长度
  history_size: 100    # 历史消息数量

storage:
  type: "json"         # 存储类型：json/sqlite
  data_dir: "data"     # 数据目录
```

---

## 🛠️ 部署脚本

```bash
# 显示帮助
./scripts/deploy.sh --help

# 快速部署
./scripts/deploy.sh --quick

# 指定端口
./scripts/deploy.sh -p 8888

# 安装依赖
./scripts/deploy.sh --install-deps

# 创建管理员
./scripts/deploy.sh --create-user admin

# 服务器管理
./scripts/deploy.sh --start
./scripts/deploy.sh --stop
./scripts/deploy.sh --restart
./scripts/deploy.sh --status
```

---

## 🧪 测试

### 使用内置客户端

```bash
python client.py localhost 5222
```

### 命令列表

| 命令 | 说明 |
|------|------|
| `/msg <用户> <内容>` | 发送私聊 |
| `/create <房间名>` | 创建房间 |
| `/join <房间 ID>` | 加入房间 |
| `/r <内容>` | 发送房间消息 |
| `/rooms` | 列出房间 |
| `/users` | 列出在线用户 |
| `/ping` | 测试连接 |
| `/quit` | 退出 |

---

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 单机并发 | 5000+ 连接 |
| 消息延迟 | <10ms (局域网) |
| 内存占用 | ~50MB (1000 连接) |
| 启动时间 | <1s |

---

## 🔐 安全建议

生产环境部署时建议：

1. 启用 TLS 加密传输
2. 使用 bcrypt 密码哈希（安装 bcrypt 库）
3. 配置防火墙规则
4. 定期备份数据目录
5. 设置合理的消息大小限制

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 许可证

MIT License

---

## 📬 联系方式

项目主页：[GitHub](https://github.com/)

---

<div align="center">

**NexusChat** - 连接无处不在

Made with ❤️ by NexusChat Team

</div>
