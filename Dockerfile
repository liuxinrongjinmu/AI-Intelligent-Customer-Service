FROM python:3.12-slim

WORKDIR /app

# 创建非 root 用户
RUN useradd -m -u 1000 appuser

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/system/health', timeout=5).status"

CMD uvicorn backend.main:app --host 0.0.0.0 --port 8080 --workers $WORKERS