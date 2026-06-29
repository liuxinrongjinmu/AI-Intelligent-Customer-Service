# 监控告警运维文档

> 本文档说明 kefu-agent 的监控体系、指标定义、告警规则与常见排查命令。
>
> 相关代码与配置：
> - 指标采集：`backend/utils/metrics.py`
> - 指标暴露：`/api/v1/system/metrics`（Prometheus 文本格式）
> - Prometheus 配置：`monitoring/prometheus.yml`
> - 告警规则：`monitoring/alerts.yml`
> - Grafana 配置：`monitoring/grafana/`
> - 容器编排：`docker-compose.yml`

---

## 一、监控架构

```
kefu-agent (FastAPI)
   │  /api/v1/system/metrics
   ▼
Prometheus  ──抓取──→  存储 TSDB（保留 7 天）
   │
   ├── 告警规则评估（每 15s）
   │
   ▼
Grafana  ──查询──→  可视化仪表盘
```

- **抓取间隔**：15 秒
- **告警评估间隔**：15 秒
- **数据保留**：Prometheus TSDB 保留 7 天
- **仪表盘自动加载**：Grafana 启动时从 `/etc/grafana/provisioning/dashboards` 自动导入

---

## 二、Prometheus 指标列表

指标通过 `GET /api/v1/system/metrics` 端点暴露，Prometheus 文本格式。

### 2.1 服务运行指标

| 指标名 | 类型 | 说明 | 标签 |
|--------|------|------|------|
| `kefu_uptime_seconds` | gauge | 服务运行时间（秒） | 无 |
| `kefu_active_requests` | gauge | 当前活跃请求数 | 无 |

### 2.2 HTTP 请求指标

| 指标名 | 类型 | 说明 | 标签 |
|--------|------|------|------|
| `kefu_requests_total` | counter | HTTP 请求总数 | `method`, `path`, `status` |
| `kefu_request_duration_ms` | histogram | 请求延迟（毫秒），buckets: 10/25/50/100/250/500/1000/2500/5000/10000 | `method`, `path` |

> 说明：使用 Prometheus Histogram 类型，通过 `histogram_quantile()` 函数计算 P50/P95/P99 分位数。

### 2.3 业务指标

| 指标名 | 类型 | 说明 | 标签 |
|--------|------|------|------|
| `kefu_chat_messages_total` | counter | 聊天消息总数 | 无 |
| `kefu_llm_calls_total` | counter | LLM 调用次数 | `node`（节点名） |

### 2.4 错误与缓存指标

| 指标名 | 类型 | 说明 | 标签 |
|--------|------|------|------|
| `kefu_errors_total` | counter | 错误次数 | `type`（错误类型） |
| `kefu_cache_total` | counter | 缓存命中/未命中计数 | `result`（hit/miss） |
| `kefu_retrieval_total` | counter | 检索结果计数 | `result`（found/empty） |
| `kefu_handoff_total` | counter | 转人工次数 | 无 |
| `kefu_timing_total` | counter | 请求处理耗时计数（按意图统计） | `intent` |

> 说明：`kefu_errors_total` 通过 `type` 标签区分错误类型（llm_call_failed/api_timeout 等），统一管理所有错误计数。

### 2.5 指标采集函数（开发参考）

| 函数 | 作用 |
|------|------|
| `record_request(method, path, status_code, latency_ms)` | 记录一次 HTTP 请求 |
| `increment_active()` / `decrement_active()` | 活跃请求数 +/-1 |
| `record_chat_message()` | 聊天消息计数 +1 |
| `record_llm_call(node_name)` | LLM 调用计数 +1 |
| `record_error(error_type)` | 错误计数 +1 |
| `record_cache(hit: bool)` | 缓存命中/未命中 |
| `record_retrieval(has_results: bool)` | 检索有结果/无结果 |
| `record_handoff()` | 转人工计数 +1 |

---

## 三、Grafana 访问方式

### 3.1 访问地址

```
http://<server-ip>:3000
```

- 默认端口：`3000`（见 `docker-compose.yml`）
- 容器名：`kefu-grafana`

### 3.2 登录凭证

| 项 | 值 |
|----|----|
| 用户名 | `admin`（可通过 `GRAFANA_ADMIN_USER` 环境变量修改） |
| 密码 | **必须配置** `GRAFANA_ADMIN_PASSWORD` 环境变量 |

> 安全要求：`docker-compose.yml` 中 `GRAFANA_ADMIN_PASSWORD` 标记为 `:?必须配置`，禁止使用默认密码 `admin`，未配置时容器无法启动。

### 3.3 预置仪表盘

- 仪表盘文件：`monitoring/grafana/dashboards/kefu-agent.json`
- 仪表盘 UID：`kefu-agent`
- 标题：`AI客服 Agent 监控面板`
- 刷新频率：15 秒
- 默认时间范围：最近 1 小时

仪表盘包含以下面板：

| 面板 | 类型 | 说明 |
|------|------|------|
| 服务状态 | stat | `up{job="kefu-agent"}` 在线/离线 |
| 运行时间 | stat | `kefu_uptime_seconds` |
| 活跃请求数 | stat | `kefu_active_requests`（阈值 20 黄 / 50 红） |
| 聊天消息总数 | stat | `kefu_chat_messages_total` |
| 错误总数 | stat | `sum(kefu_errors_total)`（阈值 10 黄 / 50 红） |
| 请求 QPS（按路径） | timeseries | `sum(rate(kefu_requests_total[1m])) by (path)` |

### 3.4 数据源

- 数据源类型：Prometheus
- 数据源 URL：`http://prometheus:9090`
- 配置文件：`monitoring/grafana/datasources.yml`
- 默认数据源：是

---

## 四、告警规则说明

告警规则定义在 `monitoring/alerts.yml`，Prometheus 每 15 秒评估一次。

### 4.1 严重告警（critical）

#### ServiceDown — 服务不可用

| 项 | 值 |
|----|----|
| 表达式 | `up{job="kefu-agent"} == 0` |
| 持续时间 | `1m` |
| 触发条件 | 健康检查连续失败 1 分钟 |
| 处理建议 | 立即检查容器状态、应用日志、健康检查端点 |

#### HighErrorRate — 错误率过高

| 项 | 值 |
|----|----|
| 表达式 | `sum(rate(kefu_requests_total{status=~"5.."}[5m])) / sum(rate(kefu_requests_total[5m])) > 0.05` |
| 持续时间 | `2m` |
| 触发条件 | 5xx 错误率超过 5%，持续 2 分钟 |
| 处理建议 | 检查应用日志中的 5xx 堆栈，排查依赖服务（LLM / 业务 API）可用性 |

#### LLMCallsFailed — LLM 调用连续失败

| 项 | 值 |
|----|----|
| 表达式 | `increase(kefu_errors_total{type="llm_call_failed"}[5m]) > 3` |
| 持续时间 | `1m` |
| 触发条件 | 5 分钟内 LLM 调用失败超过 3 次 |
| 处理建议 | 检查 `DEEPSEEK_API_KEY` 有效性、API 配额、网络连通性 |

> 说明：任务规划中曾命名 `LLMCallFailures`，实际规则文件中命名为 `LLMCallsFailed`。

### 4.2 警告级别（warning）

#### HighLatency — P99 延迟过高

| 项 | 值 |
|----|----|
| 表达式 | `kefu_request_latency_ms{quantile="0.99"} > 5000` |
| 持续时间 | `5m` |
| 触发条件 | 请求 P99 延迟超过 5 秒，持续 5 分钟 |
| 处理建议 | 排查慢查询、LLM 响应时间、检索耗时、连接池状态 |

> 说明：任务规划中曾命名 `HighLatencyP99`，实际规则文件中命名为 `HighLatency`。

#### HighActiveRequests — 活跃请求数过高

| 项 | 值 |
|----|----|
| 表达式 | `kefu_active_requests > 50` |
| 持续时间 | `3m` |
| 触发条件 | 当前活跃请求数超过 50，持续 3 分钟 |
| 处理建议 | 检查是否存在慢请求堆积、限流配置、上游流量异常 |

#### ChatMessageSpike — 聊天消息量激增

| 项 | 值 |
|----|----|
| 表达式 | `increase(kefu_chat_messages_total[10m]) > 500` |
| 持续时间 | `5m` |
| 触发条件 | 10 分钟内消息量超过 500 条 |
| 处理建议 | 排查是否有营销活动、爬虫流量、异常用户 |

> 说明：任务规划中曾命名 `ChatMessageAnomaly`，实际规则文件中命名为 `ChatMessageSpike`。

#### HighHandoffRate — 转人工率过高

| 项 | 值 |
|----|----|
| 表达式 | `sum(rate(kefu_handoff_total[10m])) / sum(rate(kefu_chat_messages_total[10m])) > 0.3` |
| 持续时间 | `10m` |
| 触发条件 | 转人工率超过 30%，持续 10 分钟 |
| 处理建议 | 排查知识库覆盖度、意图识别准确率、AI 回答质量 |

### 4.3 告警级别汇总

| 级别 | 告警名 | 持续时间 |
|------|--------|----------|
| critical | ServiceDown | 1m |
| critical | HighErrorRate | 2m |
| critical | LLMCallsFailed | 1m |
| warning | HighLatency | 5m |
| warning | HighActiveRequests | 3m |
| warning | ChatMessageSpike | 5m |
| warning | HighHandoffRate | 10m |

---

## 五、常见排查命令

### 5.1 服务状态检查

```powershell
# 查看容器状态
docker-compose ps

# 查看 kefu-agent 日志（最近 100 行）
docker-compose logs --tail=100 kefu-agent

# 实时跟随日志
docker-compose logs -f kefu-agent

# 健康检查
curl http://localhost:8080/api/v1/system/health
```

### 5.2 指标查询

```powershell
# 直接获取 Prometheus 格式指标
curl http://localhost:8080/api/v1/system/metrics

# JSON 格式指标（内部监控用）
curl http://localhost:8080/api/v1/system/metrics?format=json

# 通过 Prometheus API 查询（示例：当前活跃请求数）
curl "http://localhost:9090/api/v1/query?query=kefu_active_requests"
```

### 5.3 Prometheus 命令行查询

访问 `http://localhost:9090`，在 PromQL 查询框中执行：

```promql
# 最近 5 分钟请求 QPS（按路径分组）
sum(rate(kefu_requests_total[5m])) by (path)

# P99 延迟（按路径分组）
kefu_request_latency_ms{quantile="0.99"}

# LLM 调用次数（按节点分组）
sum(increase(kefu_llm_calls_total[1h])) by (node)

# 错误率
sum(rate(kefu_requests_total{status=~"5.."}[5m])) / sum(rate(kefu_requests_total[5m]))

# 转人工率
sum(rate(kefu_requests_total{path~".*handoff.*"}[10m])) / sum(rate(kefu_chat_messages_total[10m]))
```

### 5.4 Grafana 排查

```powershell
# 查看 Grafana 日志
docker-compose logs --tail=100 grafana

# 重启 Grafana
docker-compose restart grafana

# 重新加载仪表盘配置
curl -X POST http://admin:<password>@localhost:3000/api/admin/provisioning/dashboards/reload
```

### 5.5 告警状态查看

```powershell
# 查看当前触发中的告警
curl "http://localhost:9090/api/v1/alerts"

# 查看告警规则
curl "http://localhost:9090/api/v1/rules"
```

### 5.6 监控服务管理

```powershell
# 启动监控服务
docker-compose up -d prometheus grafana

# 重启监控服务
docker-compose restart prometheus grafana

# 重新加载 Prometheus 配置（修改 alerts.yml 后）
curl -X POST http://localhost:9090/-/reload
```

---

## 六、配置文件索引

| 文件 | 说明 |
|------|------|
| `monitoring/prometheus.yml` | Prometheus 抓取配置（job、target、间隔） |
| `monitoring/alerts.yml` | 告警规则定义（7 条规则） |
| `monitoring/grafana/datasources.yml` | Grafana 数据源自动配置 |
| `monitoring/grafana/dashboards.yml` | Grafana 仪表盘自动加载配置 |
| `monitoring/grafana/dashboards/kefu-agent.json` | 预置仪表盘定义 |
| `backend/utils/metrics.py` | 指标采集与 Prometheus 格式输出 |
| `docker-compose.yml` | 监控服务容器编排 |
