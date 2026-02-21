#!/bin/bash
#
# NexusChat 一键部署脚本
# =====================
#
# 用法:
#   ./deploy.sh          # 交互式部署
#   ./deploy.sh --quick  # 快速部署（使用默认配置）
#   ./deploy.sh --help   # 显示帮助
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# 默认配置
DEFAULT_PORT=5222
DEFAULT_HOST="0.0.0.0"

# 打印带颜色的消息
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 显示帮助
show_help() {
    cat << EOF
NexusChat 一键部署脚本

用法: $0 [选项]

选项:
    -q, --quick     快速部署，使用默认配置
    -p, --port      指定服务器端口 (默认：5222)
    -h, --host      指定监听地址 (默认：0.0.0.0)
    --install-deps  安装依赖
    --create-user   创建管理员用户
    --start         启动服务器
    --stop          停止服务器
    --restart       重启服务器
    --status        查看服务器状态
    --help          显示此帮助信息

示例:
    $0                      # 交互式部署
    $0 --quick              # 快速部署
    $0 -p 8888              # 指定端口
    $0 --install-deps       # 仅安装依赖
    $0 --create-user admin  # 创建管理员用户

EOF
}

# 检查 Python 环境
check_python() {
    info "检查 Python 环境..."
    
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        error "未找到 Python，请先安装 Python 3.8+"
        exit 1
    fi
    
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    info "Python 版本：$PYTHON_VERSION"
    
    # 检查版本
    MAJOR_VERSION=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR_VERSION=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$MAJOR_VERSION" -lt 3 ] || ([ "$MAJOR_VERSION" -eq 3 ] && [ "$MINOR_VERSION" -lt 8 ]); then
        error "需要 Python 3.8 或更高版本"
        exit 1
    fi
}

# 安装依赖
install_deps() {
    info "安装依赖..."
    
    if [ -f "$PROJECT_DIR/requirements.txt" ]; then
        $PYTHON_CMD -m pip install -r "$PROJECT_DIR/requirements.txt" -q
        success "依赖安装完成"
    else
        warning "未找到 requirements.txt"
    fi
}

# 创建配置文件
create_config() {
    local port=$1
    local host=$2
    
    info "创建配置文件..."
    
    mkdir -p "$PROJECT_DIR/config"
    
    cat > "$PROJECT_DIR/config/config.yaml" << EOF
# NexusChat 服务器配置文件

server:
  host: "$host"
  port: $port
  tls_port: $((port + 1))
  enable_tls: false
  tls_cert: ""
  tls_key: ""

auth:
  allow_registration: true
  require_email: false
  password_min_length: 6
  session_timeout: 86400

message:
  max_size: 4096
  history_size: 100
  enable_offline: true

room:
  max_members: 500
  max_rooms: 1000
  default_public: true

logging:
  level: "INFO"
  file: "logs/nexuschat.log"
  max_size: 10485760
  backup_count: 5

storage:
  type: "json"
  data_dir: "data"
EOF
    
    success "配置文件已创建：config/config.yaml"
}

# 创建必要的目录
create_dirs() {
    info "创建目录..."
    mkdir -p "$PROJECT_DIR/logs"
    mkdir -p "$PROJECT_DIR/data"
    success "目录创建完成"
}

# 创建 systemd 服务文件
create_systemd_service() {
    info "创建 systemd 服务..."
    
    local service_file="/etc/systemd/system/nexuschat.service"
    
    cat > /tmp/nexuschat.service << EOF
[Unit]
Description=NexusChat Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_CMD $PROJECT_DIR/main.py --config $PROJECT_DIR/config/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    if [ -w "/etc/systemd/system" ]; then
        sudo cp /tmp/nexuschat.service "$service_file"
        sudo systemctl daemon-reload
        success "systemd 服务已创建"
    else
        warning "无法创建 systemd 服务（需要 root 权限）"
    fi
}

# 启动服务器
start_server() {
    info "启动 NexusChat 服务器..."
    
    cd "$PROJECT_DIR"
    
    # 检查是否已在运行
    if [ -f "$PROJECT_DIR/nexuschat.pid" ]; then
        local pid=$(cat "$PROJECT_DIR/nexuschat.pid")
        if kill -0 "$pid" 2>/dev/null; then
            warning "服务器已在运行 (PID: $pid)"
            return 0
        fi
    fi
    
    # 后台启动
    nohup $PYTHON_CMD main.py > logs/stdout.log 2>&1 &
    echo $! > "$PROJECT_DIR/nexuschat.pid"
    
    sleep 2
    
    if [ -f "$PROJECT_DIR/nexuschat.pid" ]; then
        local pid=$(cat "$PROJECT_DIR/nexuschat.pid")
        if kill -0 "$pid" 2>/dev/null; then
            success "服务器已启动 (PID: $pid)"
            return 0
        fi
    fi
    
    error "服务器启动失败，查看 logs/stdout.log 获取详情"
    return 1
}

# 停止服务器
stop_server() {
    info "停止 NexusChat 服务器..."
    
    if [ -f "$PROJECT_DIR/nexuschat.pid" ]; then
        local pid=$(cat "$PROJECT_DIR/nexuschat.pid")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            sleep 2
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid"
            fi
            success "服务器已停止"
        else
            warning "服务器未运行"
        fi
        rm -f "$PROJECT_DIR/nexuschat.pid"
    else
        # 尝试通过进程名停止
        pkill -f "nexuschat.*main.py" 2>/dev/null || true
        pkill -f "python.*main.py" 2>/dev/null || true
        warning "未找到 PID 文件，尝试通过进程名停止"
    fi
}

# 查看服务器状态
server_status() {
    if [ -f "$PROJECT_DIR/nexuschat.pid" ]; then
        local pid=$(cat "$PROJECT_DIR/nexuschat.pid")
        if kill -0 "$pid" 2>/dev/null; then
            success "服务器运行中 (PID: $pid)"
            return 0
        fi
    fi
    
    # 尝试通过进程名查找
    local pid=$(pgrep -f "python.*main.py" 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        success "服务器运行中 (PID: $pid)"
        return 0
    fi
    
    error "服务器未运行"
    return 1
}

# 创建管理员用户（通过 Python 脚本）
create_admin_user() {
    local username=${1:-admin}
    
    info "创建管理员用户：$username"
    
    $PYTHON_CMD << EOF
import sys
sys.path.insert(0, "$PROJECT_DIR")

from server.storage import StorageManager
from server.auth import AuthManager, User
import asyncio
import time

async def create():
    config = {"storage": {"data_dir": "$PROJECT_DIR/data"}}
    storage = StorageManager(config)
    auth = AuthManager(storage)
    
    # 检查用户是否存在
    existing = await auth.get_user_by_username("$username")
    if existing:
        print(f"用户 $username 已存在")
        return
    
    # 生成密码
    import secrets
    password = secrets.token_urlsafe(12)
    
    user = await auth.register("$username", password, "admin@localhost")
    if user:
        print(f"用户创建成功!")
        print(f"用户名：$username")
        print(f"密码：{password}")
        print("请妥善保管此密码!")
    else:
        print("创建失败")

asyncio.run(create())
EOF
}

# 主函数
main() {
    local quick_mode=false
    local port=$DEFAULT_PORT
    local host=$DEFAULT_HOST
    local action=""
    local admin_user=""
    
    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -q|--quick)
                quick_mode=true
                shift
                ;;
            -p|--port)
                port="$2"
                shift 2
                ;;
            -h|--host)
                host="$2"
                shift 2
                ;;
            --install-deps)
                action="install_deps"
                shift
                ;;
            --create-user)
                action="create_user"
                admin_user="${2:-admin}"
                shift 2
                ;;
            --start)
                action="start"
                shift
                ;;
            --stop)
                action="stop"
                shift
                ;;
            --restart)
                action="restart"
                shift
                ;;
            --status)
                action="status"
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                error "未知选项：$1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 执行动作
    case $action in
        install_deps)
            check_python
            install_deps
            ;;
        create_user)
            check_python
            create_admin_user "$admin_user"
            ;;
        start)
            start_server
            ;;
        stop)
            stop_server
            ;;
        restart)
            stop_server
            sleep 1
            start_server
            ;;
        status)
            server_status
            ;;
        *)
            # 完整部署流程
            echo ""
            echo "========================================"
            echo "  NexusChat 一键部署"
            echo "========================================"
            echo ""
            
            check_python
            
            if [ "$quick_mode" = false ]; then
                echo -n "是否安装依赖？[Y/n] "
                read -r response
                if [[ "$response" =~ ^[Yy]$ ]] || [[ -z "$response" ]]; then
                    install_deps
                fi
            else
                install_deps
            fi
            
            create_dirs
            
            if [ "$quick_mode" = false ]; then
                echo ""
                echo "服务器配置:"
                echo -n "  监听地址 [$host]: "
                read -r input_host
                [ -n "$input_host" ] && host="$input_host"
                
                echo -n "  端口 [$port]: "
                read -r input_port
                [ -n "$input_port" ] && port="$input_port"
            fi
            
            create_config "$port" "$host"
            
            echo ""
            echo "========================================"
            echo "  部署完成!"
            echo "========================================"
            echo ""
            echo "启动服务器：$0 --start"
            echo "停止服务器：$0 --stop"
            echo "查看状态：  $0 --status"
            echo ""
            echo "服务器配置：$host:$port"
            echo ""
            
            if [ "$quick_mode" = false ]; then
                echo -n "是否现在启动服务器？[Y/n] "
                read -r response
                if [[ "$response" =~ ^[Yy]$ ]] || [[ -z "$response" ]]; then
                    start_server
                fi
            fi
            ;;
    esac
}

# 运行主函数
main "$@"
