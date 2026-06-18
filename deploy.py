"""
部署到服务器

安全说明：
  - 优先使用 SSH 密钥认证（推荐），设置 DEPLOY_SSH_KEY_PATH 环境变量
  - 密码认证仅作为后备，通过环境变量 DEPLOY_SSH_PASSWORD 传入，禁止硬编码
  - 服务器地址、端口、用户名均通过环境变量配置

使用方式：
  # 方式1: SSH 密钥（推荐）
  set DEPLOY_SSH_KEY_PATH=C:\\Users\\you\\.ssh\\id_rsa
  python deploy.py

  # 方式2: 密码（不推荐，仅用于临时部署）
  set DEPLOY_SSH_PASSWORD=your-password
  python deploy.py

  # 自定义服务器地址
  set DEPLOY_HOST=192.168.0.234
  set DEPLOY_PORT=6022
  set DEPLOY_USER=deploy
  set DEPLOY_PATH=/home/deploy/rag
"""
import os
import sys
import io
import time

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def run_cmd(ssh, cmd, timeout=600):
    """
    执行远程命令并实时打印输出

    :param ssh: SSHClient 实例
    :param cmd: 要执行的命令字符串
    :param timeout: 命令超时时间（秒）
    :return: 命令退出码
    """
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
    while True:
        line = stdout.readline()
        if not line:
            break
        print(line.rstrip())
    return stdout.channel.recv_exit_status()


def connect_ssh():
    """
    建立 SSH 连接

    优先使用 SSH 密钥认证，后备使用密码认证。
    所有连接参数从环境变量读取，禁止硬编码。

    :return: SSHClient 实例
    """
    host = os.getenv("DEPLOY_HOST", "192.168.0.234")
    port = int(os.getenv("DEPLOY_PORT", "6022"))
    user = os.getenv("DEPLOY_USER", "deploy")
    key_path = os.getenv("DEPLOY_SSH_KEY_PATH", "")
    password = os.getenv("DEPLOY_SSH_PASSWORD", "")

    ssh = paramiko.SSHClient()

    # 加载已知主机密钥（优先从 known_hosts 读取）
    known_hosts = os.path.expanduser("~/.ssh/known_hosts")
    if os.path.exists(known_hosts):
        ssh.load_host_keys(known_hosts)
    else:
        print(f"[警告] 未找到 known_hosts 文件 ({known_hosts})，使用 AutoAddPolicy")
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if key_path:
        print(f"使用 SSH 密钥认证: {key_path}")
        ssh.connect(host, port=port, username=user, key_filename=key_path, timeout=30)
    elif password:
        print("使用密码认证（建议升级为 SSH 密钥）")
        ssh.connect(host, port=port, username=user, password=password, timeout=30)
    else:
        print("[错误] 未配置认证方式，请设置 DEPLOY_SSH_KEY_PATH 或 DEPLOY_SSH_PASSWORD 环境变量")
        sys.exit(1)

    print(f"SSH 连接成功: {user}@{host}:{port}")
    return ssh


def main():
    """
    部署主流程：
      1. 拉取最新代码
      2. 停止旧容器
      3. 构建并启动新容器
      4. 健康检查验证
    """
    deploy_path = os.getenv("DEPLOY_PATH", "/home/deploy/rag")

    ssh = connect_ssh()

    # 1. 拉取代码
    run_cmd(ssh, f"cd {deploy_path} && git pull origin master")

    # 2. 停止旧容器
    run_cmd(ssh, f"cd {deploy_path} && docker compose down", timeout=60)

    # 3. 构建 + 启动
    code = run_cmd(ssh, f"cd {deploy_path} && docker compose up -d --build 2>&1", timeout=1800)
    if code != 0:
        print(f"\n[错误] Docker 构建失败，退出码: {code}")
        ssh.close()
        sys.exit(1)

    # 4. 等待启动 + 健康检查（带重试）
    time.sleep(15)

    port = os.getenv("DEPLOY_HOST_PORT", "8081")
    health_ok = False
    for attempt in range(3):
        stdin, stdout, stderr = ssh.exec_command(
            f"curl -s http://localhost:{port}/api/v1/system/health", timeout=10
        )
        health_resp = stdout.read().decode('utf-8', errors='replace').strip()
        print(f"\n健康检查 (第{attempt + 1}次): {health_resp}")
        if '"ok"' in health_resp:
            health_ok = True
            break
        if attempt < 2:
            print("等待 5 秒后重试...")
            time.sleep(5)

    if not health_ok:
        print("[警告] 健康检查未通过，请检查容器日志: docker logs kefu-agent")

    stdin, stdout, stderr = ssh.exec_command(
        f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{port}/chat/demo_001", timeout=10
    )
    page_code = stdout.read().decode('utf-8', errors='replace').strip()
    print(f"聊天页面: HTTP {page_code}")

    ssh.close()

    if health_ok and page_code == "200":
        print("\n部署成功!")
    else:
        print("\n[警告] 部署可能存在问题，请手动验证")
        sys.exit(1)


if __name__ == "__main__":
    main()
