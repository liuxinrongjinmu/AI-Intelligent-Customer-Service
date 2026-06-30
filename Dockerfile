# ============ Builder 阶段：编译 C 扩展 + 安装依赖 ============
FROM docker.m.daocloud.io/library/python:3.12-slim AS builder

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

# 指定 PyTorch CPU 版本索引（避免拉取 CUDA 版，镜像从 9GB 降至 3-4GB）
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
# 禁止 Python 生成 .pyc 文件（减少镜像体积、避免字节码缓存问题）
ENV PYTHONDONTWRITEBYTECODE=1

# 先复制依赖文件，利用 Docker 缓存层
COPY requirements.txt requirements-lock.txt ./

# 强制安装 CPU-only PyTorch（先于其他依赖，防止 CUDA 版被依赖解析引入）
# 然后按 requirements.txt 版本范围安装其余依赖（比 lock 文件更健壮，自动适配镜像源可用版本）
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --no-compile

# 预下载 Embedding 模型到镜像层（避免每次首次启动从 HuggingFace 下载约 100MB）
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"

# 清理虚拟环境中的缓存和编译产物
RUN find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type f -name "*.pyc" -delete 2>/dev/null; \
    find /opt/venv -type f -name "*.pyo" -delete 2>/dev/null; \
    find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "*.dist-info" -exec sh -c 'rm -rf "$1/RECORD" "$1/INSTALLER" "$1/REQUESTED" "$1/direct_url.json"' _ {} \; 2>/dev/null; \
    rm -rf /opt/venv/share/doc /opt/venv/share/man

# ============ Runtime 阶段：精简运行镜像 ============
FROM docker.m.daocloud.io/library/python:3.12-slim

WORKDIR /app

# 使用阿里云镜像源加速 apt 下载
RUN sed -i "s|http://deb.debian.org|http://mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources && \
    sed -i "s|http://security.debian.org|http://mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources

# 运行时仅需 curl（健康检查）+ gosu（权限降级）+ pg_dump（数据库备份），无需 build-essential
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd -m -u 1000 appuser

# 从 builder 复制已编译好的虚拟环境（依赖产物）
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 仅复制项目必要文件（.dockerignore 控制排除范围）
# --chown 确保非 root 用户（appuser）有权限读取和执行
COPY --chown=appuser:appuser backend/ backend/
COPY --chown=appuser:appuser frontend/ frontend/
COPY --chown=appuser:appuser monitoring/ monitoring/
COPY --chown=appuser:appuser docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

RUN mkdir -p data/chroma_db data/backups && chown -R appuser:appuser data

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8080
# HuggingFace 镜像站（国内加速模型下载）
ENV HF_ENDPOINT=https://hf-mirror.com
# Worker 数量，生产环境建议根据 CPU 核数调整
ENV WORKERS=1
# 生产环境关闭 Swagger UI（设为 1 启用，0 关闭）
ENV ENABLE_DOCS=0

EXPOSE 8080

# 容器以 root 启动，entrypoint 修复卷权限后降权为 appuser
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# 使用 curl 健康检查，比 python -c 启动更快
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fs -o /dev/null http://localhost:8080/api/v1/system/health

# 使用 exec 确保 uvicorn 直接接收 SIGTERM 信号（优雅关闭）
# sh -c 展开环境变量后 exec 替换为 uvicorn 进程，信号不经过 shell 中转
CMD ["sh", "-c", "exec uvicorn backend.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8080} --workers ${WORKERS:-1}"]
