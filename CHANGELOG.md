# 变更日志

本项目所有重要变更均会记录在本文件中。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased] - 2026-06-22

### 新增
- 无

### 变更
- **移除退款功能**：经聚宝赞业务方确认无此场景，删除 `refund_service` 相关代码与配置项，避免误触发与维护成本。

### 修复

#### P0 问题（阻断级）
- 修复退款确认误触发：移除退款流程后，意图路由不再分发到退款节点。
- 修复 PII 泄露：日志输出补全脱敏覆盖范围，避免敏感信息明文落盘。
- 修复 `sensitive_filter` lambda 错误：修正 `session_id` 掩码 lambda 在 `re.sub` 回调中的参数签名问题。
- 修复全量同步状态错误：`sync_type=full` 时 `status` 字段错误标记为 `partial` 的问题。
- 修复 FAQ 同步失败无回滚：同步异常时通过 `SyncLog.snapshot` 回滚至上一次成功快照。

#### P1 问题（严重级）
- 修复意图缓存忽略上下文：缓存键加入 `tenant_id` + `session_id`，避免跨会话串意图。
- 修复子类键名不一致：统一 `intent_sub_type` 在模型、Schema、节点之间的字段命名。
- 修复日志打印 `docs` 对象：检索节点日志改为打印 `doc_id` 列表，避免大对象撑爆日志。
- 修复 `asyncio.create_task` 无引用：同步任务持有强引用，防止被 GC 提前回收导致任务丢失。
- 修复 `metrics.py` IndexError：`get_metrics_text()` 遍历混合键时对非 HTTP 键（cache/retrieval/handoff/timing）跳过三段式解析，并单独输出对应指标，避免 `/api/v1/system/metrics` 端点 500 错误。
- 修复监控 YAML 语法错误：`prometheus.yml` / `alerts.yml` / `grafana/datasources.yml` / `grafana/dashboards.yml` 顶部 Python 风格 `"""` 文档字符串改为 YAML 标准注释，避免 Prometheus/Grafana 启动解析失败。

#### P2 问题（重要级）
- 修复订单查询 PII 泄露：`order_service.format_order_result` 中收件人手机号脱敏为 `138****1234` 格式。
- 修复物流查询 PII 泄露：`logistics_service.format_logistics_result` 中快递员电话脱敏。

#### P3 问题（一般级）
- 统一错误响应格式：`BodySizeLimitMiddleware`（413）与 `RateLimitMiddleware`（429）响应体由 `{detail}` 改为 `{code, message}`，与业务 API 保持一致。
- 修复部署文档 SSE 示例：`type:"content"` 更正为 `type:"text"`，移除 `done` 事件中不存在的 `intent` 字段，补充 `action:"end"` 状态事件。
- 修复部署文档端口不一致：容器内 Uvicorn 监听端口由 `8081` 更正为 `8080`（与 `SERVICE_PORT` 默认值一致）。

### 优化

#### 安全
- CORS 安全：当 `ALLOWED_ORIGINS=*` 时强制禁用 `credentials`，避免跨域凭证泄露。
- `ADMIN_API_KEY` 弱密钥警告：`validate_config` 对默认值 `change-me-admin-key` 输出告警。
- CI 质量门禁生效：GitHub Actions 在 lint / typecheck / test 失败时阻断合并。
- Grafana 强制密码：`docker-compose.yml` 中 `GRAFANA_ADMIN_PASSWORD` 设为必填，禁止使用默认 `admin`。

#### 性能与体验
- SSE 分段流式输出：聊天回复按句分段推送，首字延迟降低至 1s 内。
- 敏感词扩充：`config/sensitive_words.txt` 由 23 词扩充至 50+ 词，覆盖赌博/色情/毒品/诈骗/隐私等类别。
- 日志脱敏扩充：新增身份证号、银行卡号、邮箱三类 PII 掩码规则。
- 新增 CSP meta 标签：前端模板增加 Content-Security-Policy，降低 XSS 风险。

#### 工程化
- 错误响应格式统一：所有 API 错误返回 `{code, message, request_id}` 结构。
- `var` → `let`：前端 JavaScript 变量声明统一为块级作用域。
- Dockerfile 多阶段构建：构建产物与运行环境分离，镜像体积减少约 40%。

## [0.9.0] - 2026-06-21

### 新增
- 监控可视化：集成 Prometheus + Grafana，预置 `kefu-agent` 仪表盘与 7 条告警规则。
- 结构化 JSON 日志：`json_logger` 模块统一日志格式，便于 ELK 采集与查询。
- 前端体验优化：
  - 移动端 H5 适配（响应式布局 + 触摸优化）
  - 满意度评价（5 星打分 + 文字反馈）
  - 快捷问题引导（首屏推荐 6 个高频问题）
- 业务 API 重试机制：`retry.py` 提供指数退避重试，覆盖订单/物流/商品/优惠券/用户画像 5 类 API。
- SQLite 自动备份：`backup.py` 后台任务每小时备份，保留 24 个小时备份 + 7 个每日快照。
- 开发/生产环境配置分离：`ENV` 变量区分 `dev` / `test` / `prod`，Swagger 仅在非生产环境开放。

### 变更
- 无

### 修复
- 无

## [0.8.0] - 2026-06-20

### 新增
- 核心 AI 客服功能上线：
  - 意图识别（含指代消解 + 两层分类）
  - 混合检索（向量 + 关键词 + RRF 融合）
  - 多轮对话（LangGraph 状态机 + 检查点）
  - 安全防护（注入检测 + 敏感词 + 输出过滤 + 时序安全比较）
- 意图分类体系：10 大类 48 子类，覆盖订单/物流/商品/优惠券/账户/知识/投诉/问候/反馈/转人工。
- LangGraph 工作流：11 节点（意图识别 → 路由 → 检索/查询/工单 → 生成 → 过滤 → 输出）。
- 知识库同步：支持 `full`（全量）/ `incremental`（增量）/ 批量 / 清空四种模式。
- 多租户管理：租户级数据隔离（SQLite + ChromaDB 双层隔离）。
- Nacos 服务注册与发现：自动注册到 Nacos，业务 API 通过服务名调用。
- 单元测试：319 个用例通过，覆盖安全/路由/Schema/配置/核心模块/网关认证/混合检索。

### 变更
- 无

### 修复
- 无
