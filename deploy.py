"""部署到服务器"""
import paramiko, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def run_cmd(ssh, cmd, timeout=600):
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
    while True:
        line = stdout.readline()
        if not line:
            break
        print(line.rstrip())
    return stdout.channel.recv_exit_status()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.0.234", port=6022, username="deploy", password="123456", timeout=30)
print("SSH连接成功")

# 1. 拉取代码
run_cmd(ssh, "cd /home/deploy/rag && git pull origin master")

# 2. 停止
run_cmd(ssh, "cd /home/deploy/rag && docker compose down", timeout=60)

# 3. 构建+启动
code = run_cmd(ssh, "cd /home/deploy/rag && docker compose up -d --build 2>&1", timeout=1800)

# 4. 等待+验证
time.sleep(15)

stdin, stdout, stderr = ssh.exec_command("curl -s http://localhost:8081/api/v1/system/health", timeout=10)
print(f"\n健康检查: {stdout.read().decode('utf-8', errors='replace').strip()}")

stdin, stdout, stderr = ssh.exec_command("curl -s -o /dev/null -w '%{http_code}' http://localhost:8081/chat/demo_001", timeout=10)
print(f"聊天页面: HTTP {stdout.read().decode('utf-8', errors='replace').strip()}")

ssh.close()
print("\n部署完成!")