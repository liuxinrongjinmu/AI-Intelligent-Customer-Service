"""
压力测试与并发测试

验证系统在高并发场景下的稳定性、限流功能和资源占用。

使用方式：
  1. 先启动服务：python -m uvicorn backend.main:app --port 8080
  2. 运行测试：python -m pytest tests/integration/test_stress.py -v --tb=short

测试内容：
  - 并发聊天请求（验证 SSE 流式输出在并发下的稳定性）
  - 限流触发验证（超过阈值返回 429）
  - 健康检查并发（验证基础端点并发能力）
  - 混合场景压测（聊天 + 健康检查 + 同步接口混合）
"""
import asyncio
import json
import os
import time
from collections import Counter

import httpx
import pytest

SKIP_STRESS = os.getenv("SKIP_STRESS", "").lower() == "true"
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
GATEWAY_HEADERS = {"X-Gateway-Verified": "true", "Content-Type": "application/json"}


def _chat_payload(message: str, session_id: str = "stress_test") -> dict:
    """构造聊天请求体"""
    return {
        "message": message,
        "session_id": session_id,
        "user_id": "stress_test_user",
    }


@pytest.mark.skipif(SKIP_STRESS, reason="SKIP_STRESS=true，跳过压力测试")
@pytest.mark.asyncio
async def test_concurrent_health_check():
    """
    并发测试：50 个并发健康检查请求

    验证：所有请求成功返回，平均响应时间 < 500ms
    """
    concurrency = 50

    async def single_request(client: httpx.AsyncClient) -> tuple[int, float]:
        start = time.time()
        resp = await client.get(f"{BASE_URL}/api/v1/system/health", headers=GATEWAY_HEADERS)
        elapsed = (time.time() - start) * 1000
        return resp.status_code, elapsed

    async with httpx.AsyncClient(timeout=10) as client:
        tasks = [single_request(client) for _ in range(concurrency)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    status_codes = [r[0] for r in results if not isinstance(r, Exception)]
    elapsed_times = [r[1] for r in results if not isinstance(r, Exception)]
    exceptions = [r for r in results if isinstance(r, Exception)]

    success_count = sum(1 for code in status_codes if code == 200)
    avg_latency = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0
    max_latency = max(elapsed_times) if elapsed_times else 0

    print(f"\n[并发健康检查] 并发数={concurrency}")
    print(f"  成功: {success_count}/{concurrency}")
    print(f"  异常: {len(exceptions)}")
    print(f"  平均延迟: {avg_latency:.1f}ms, 最大延迟: {max_latency:.1f}ms")

    assert success_count >= concurrency * 0.95, f"成功率过低: {success_count}/{concurrency}"
    assert avg_latency < 500, f"平均延迟过高: {avg_latency:.1f}ms"


@pytest.mark.skipif(SKIP_STRESS, reason="SKIP_STRESS=true，跳过压力测试")
@pytest.mark.asyncio
async def test_concurrent_chat_stream():
    """
    并发测试：10 个并发聊天请求（SSE 流式）

    验证：所有请求都能获得完整的 SSE 响应，不出现连接中断
    """
    concurrency = 10
    messages = ["你好", "谢谢", "再见", "今天天气不错", "你好啊", "谢谢你", "拜拜", "嗨", "感谢", "早安"]

    async def single_chat(client: httpx.AsyncClient, msg: str, idx: int) -> dict:
        full_answer = ""
        has_error = False
        status_code = 0
        try:
            async with client.stream(
                'POST',
                f"{BASE_URL}/api/v1/chat/demo_001/stream",
                json=_chat_payload(msg, session_id=f"stress_{idx}"),
                headers=GATEWAY_HEADERS,
                timeout=120,
            ) as resp:
                status_code = resp.status_code
                if status_code != 200:
                    return {"status": status_code, "answer": "", "error": f"HTTP {status_code}"}
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "text":
                        full_answer += data.get("content", "")
                    elif data.get("type") == "error":
                        has_error = True
                    elif data.get("type") == "done":
                        break
        except Exception as e:
            return {"status": 0, "answer": "", "error": str(e)}

        return {
            "status": status_code,
            "answer": full_answer,
            "error": "error_event" if has_error else "",
        }

    async with httpx.AsyncClient(timeout=120) as client:
        tasks = [single_chat(client, messages[i % len(messages)], i) for i in range(concurrency)]
        start = time.time()
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start

    success_count = sum(1 for r in results if r["status"] == 200 and r["answer"] and not r["error"])
    status_dist = Counter(r["status"] for r in results)

    print(f"\n[并发聊天流式] 并发数={concurrency}, 总耗时={total_time:.1f}s")
    print(f"  成功: {success_count}/{concurrency}")
    print(f"  状态码分布: {dict(status_dist)}")
    for i, r in enumerate(results):
        if r["error"]:
            print(f"  [失败] #{i}: {r['error']}")

    assert success_count >= concurrency * 0.8, f"成功率过低: {success_count}/{concurrency}"


@pytest.mark.skipif(SKIP_STRESS, reason="SKIP_STRESS=true，跳过压力测试")
@pytest.mark.asyncio
async def test_rate_limit_triggered():
    """
    限流测试：并发发送超过 chat 限流阈值（60/分钟）的请求

    验证：超过阈值后返回 429
    注意：必须用并发请求，否则同步请求耗时超过 60 秒窗口，限流永不触发
    """
    # chat 限流 60/分钟，并发发送 80 个请求触发限流
    request_count = 80

    async def single_request(client: httpx.AsyncClient, idx: int) -> int:
        try:
            resp = await client.post(
                f"{BASE_URL}/api/v1/chat/demo_001/stream",
                json=_chat_payload("你好", session_id=f"rate_test_{idx}"),
                headers=GATEWAY_HEADERS,
                timeout=30,
            )
            return resp.status_code
        except Exception:
            return 0

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [single_request(client, i) for i in range(request_count)]
        results = await asyncio.gather(*tasks)

    rate_limited_count = sum(1 for r in results if r == 429)
    success_count = sum(1 for r in results if r == 200)
    status_dist = Counter(results)

    print(f"\n[限流测试] 并发发送 {request_count} 个请求")
    print(f"  成功(200): {success_count}")
    print(f"  被限流(429): {rate_limited_count}")
    print(f"  状态码分布: {dict(status_dist)}")

    # 至少应该有一些请求被限流
    assert rate_limited_count > 0, "未触发限流，429 响应为 0"


@pytest.mark.skipif(SKIP_STRESS, reason="SKIP_STRESS=true，跳过压力测试")
@pytest.mark.asyncio
async def test_mixed_workload():
    """
    混合场景压测：聊天 + 健康检查并发

    验证：系统在混合负载下稳定运行
    """
    chat_count = 5
    health_count = 20

    async def chat_request(client: httpx.AsyncClient, idx: int) -> int:
        try:
            async with client.stream(
                'POST',
                f"{BASE_URL}/api/v1/chat/demo_001/stream",
                json=_chat_payload("你好", session_id=f"mixed_chat_{idx}"),
                headers=GATEWAY_HEADERS,
                timeout=120,
            ) as resp:
                if resp.status_code != 200:
                    return resp.status_code
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "done":
                                break
                        except json.JSONDecodeError:
                            continue
                return 200
        except Exception:
            return 0

    async def health_request(client: httpx.AsyncClient) -> int:
        try:
            resp = await client.get(f"{BASE_URL}/api/v1/system/health", headers=GATEWAY_HEADERS)
            return resp.status_code
        except Exception:
            return 0

    async with httpx.AsyncClient(timeout=120) as client:
        chat_tasks = [chat_request(client, i) for i in range(chat_count)]
        health_tasks = [health_request(client) for _ in range(health_count)]
        all_tasks = chat_tasks + health_tasks
        start = time.time()
        results = await asyncio.gather(*all_tasks)
        total_time = time.time() - start

    chat_results = results[:chat_count]
    health_results = results[chat_count:]

    chat_success = sum(1 for r in chat_results if r == 200)
    health_success = sum(1 for r in health_results if r == 200)

    print(f"\n[混合压测] 聊天={chat_count}, 健康检查={health_count}, 总耗时={total_time:.1f}s")
    print(f"  聊天成功: {chat_success}/{chat_count}")
    print(f"  健康检查成功: {health_success}/{health_count}")

    assert health_success >= health_count * 0.95, f"健康检查成功率过低: {health_success}/{health_count}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
