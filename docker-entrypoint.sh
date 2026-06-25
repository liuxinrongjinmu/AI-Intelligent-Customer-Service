#!/bin/bash
set -e

# 修复 Docker 挂载卷的目录权限（volume 首次创建时默认归 root 所有）
# 容器以 root 启动，修复权限后降权为 appuser 运行应用
if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appuser /app/data
    exec gosu appuser "$@"
fi

exec "$@"
