# ============ Builder 阶段：编译 C 扩展 ============
FROM python:3.12-slim AS builder

WORKDIR /app

# 使用阿里云镜像源加速 apt 下载
RUN sed -i "s|http://deb.debian.org|http://mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources && \
    sed -i "s|http://security.debian.org|http://mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources

# 仅 builder 需要 build-essential 用于编译 C 扩展
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 创建虚拟环境，便于整体复制到 runtime 阶段
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# ============ Runtime 阶段：精简运行镜像 ============
FROM python:3.12-slim

WORKDIR /app

# 使用阿里云镜像源加速 apt 下载
RUN sed -i "s|http://deb.debian.org|http://mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources && \
    sed -i "s|http://security.debian.org|http://mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources

# 运行时仅需 curl（用于健康检查），无需 build-essential
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd -m -u 1000 appuser

# 从 builder 复制已编译好的虚拟环境（依赖产物）
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . .

RUN mkdir -p data && chown -R appuser:appuser data

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8080
# Worker 数量，生产环境建议根据 CPU 核数调整
ENV WORKERS=1
# 生产环境关闭 Swagger UI（设为 1 启用，0 关闭）
ENV ENABLE_DOCS=0

EXPOSE 8080

USER appuser

# 使用 curl 健康检查，比 python -c 启动更快
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fs -o /dev/null http://localhost:8080/api/v1/system/health

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
