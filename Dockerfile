# NexusChat Docker 配置

FROM python:3.11-slim

WORKDIR /app

# 复制项目文件
COPY . .

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 安装依赖（可选）
RUN pip install --no-cache-dir -r requirements.txt || true

# 暴露端口
EXPOSE 5222

# 启动服务器
CMD ["python", "main.py", "--config", "config/config.yaml"]
