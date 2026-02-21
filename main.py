#!/usr/bin/env python3
"""
NexusChat 主入口
==============

启动 NexusChat 聊天服务器。

用法:
    python main.py [--config CONFIG_PATH] [--port PORT]

示例:
    python main.py --config config/config.yaml
    python main.py --port 8888
"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from server.core import NexusChatServer


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    path = Path(config_path)
    
    if not path.exists():
        print(f"配置文件不存在：{config_path}，使用默认配置")
        return {}
    
    # 尝试 YAML
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        pass
    
    # 尝试 JSON
    if path.suffix in [".json", ".yaml", ".yml"]:
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                if path.suffix == ".json":
                    return json.loads(content)
        except Exception:
            pass
    
    print("无法解析配置文件，使用默认配置")
    return {}


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="NexusChat - 新一代轻量级聊天服务器"
    )
    parser.add_argument(
        "-c", "--config",
        default="config/config.yaml",
        help="配置文件路径 (默认：config/config.yaml)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        help="服务器端口 (覆盖配置文件)"
    )
    parser.add_argument(
        "--host",
        help="服务器监听地址 (默认：0.0.0.0)"
    )
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 命令行参数覆盖
    if args.port:
        config.setdefault("server", {})["port"] = args.port
    if args.host:
        config.setdefault("server", {})["host"] = args.host
    
    # 创建服务器
    server = NexusChatServer(config)
    
    # 设置信号处理
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    def signal_handler():
        print("\n收到停止信号，正在关闭服务器...")
        stop_event.set()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    # 启动服务器任务
    server_task = asyncio.create_task(server.start())
    
    # 等待停止信号
    await stop_event.wait()
    
    # 停止服务器
    await server.stop()
    server_task.cancel()
    
    try:
        await server_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务器已停止")
    except Exception as e:
        print(f"启动失败：{e}")
        sys.exit(1)
