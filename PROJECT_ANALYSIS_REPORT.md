# 🔍 聚宝赞AI智能客服Agent — 项目全面分析报告

> 分析日期：2026-06-29 | 分析范围：全量源码、配置、文档、测试、基础设施

---

## 一、项目概览

### 1.1 项目定位

**聚宝赞AI智能客服Agent** 是一个面向电商场景的 **多租户 AI 客服系统（MVP 版）**，核心目标是用 LLM 驱动的智能 Agent 替代/辅助传统人工客服，实现售前咨询、订单查询、物流追踪、优惠券查询、售后投诉等业务场景的自动化处理。

### 1.2 核心指标

| 维度 | 数值 |
|------|------|
| 总源文件数 | ~120 个（不含 `__pycache__`、`.git`、data） |
| Python 源码 | ~80 个模块文件 |
| 代码规模 | 约 8,000–10,000 行 Python |
| 单元测试 | 16 个测试文件，60+ 用例 |
| 意图分类 | 10 大类，50+ 子类 |
| API 端点 | 20+（chat / knowledge / tenant / stats） |
| 模型层表 | 9 张表（PostgreSQL） |
| Docker 服务 | 6 个容器（app/redis/pg/prometheus/grafana） |

---

## 二、技术架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    Nacos 服务注册/发现                            │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│  │ 订单服务  │   │ 商品服务  │   │ 物流服务  │   │ 优惠券服务│    │
│  │(external)│   │(external)│   │(external)│   │(external)│    │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘    │
│       │              │              │              │           │
│       └──────────────┴──────┬───────┴──────────────┘           │
│                             │                                   │
│  ┌──────────────────────────▼──────────────────────────┐       │
│  │                 kefu-agent (FastAPI)                  │       │
│  │  ┌──────────────────────────────────────────────┐   │       │
│  │  │         Middleware Stack                      │   │       │
│  │  │  CORS → RequestID → BodyLimit → Metrics → Rate │   │       │
│  │  └──────────────────────────────────────────────┘   │       │
│  │  ┌──────────────┐  ┌──────────────────────────┐    │       │
│  │  │  API Layer   │  │     LangGraph Agent       │    │       │
│  │  │  chat/knowl/ │  │  classify → route → exec   │    │       │
│  │  │  tenant/stats│  │  8 domain nodes + RAG     │    │       │
│  │  └──────────────┘  └──────────────────────────┘    │       │
│  │        │                    │                       │       │
│  │  ┌─────▼────────────────────▼──────────────┐       │       │
│  │  │           Shared Infrastructure          │       │       │
│  │  │  Redis(cache/rate)  PostgreSQL(state)    │       │       │
│  │  │  ChromaDB(vector)   Prometheus(metrics)  │       │       │
│  │  └──────────────────────────────────────────┘       │       │
│  └──────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈明细

| 层级 | 技术选型 | 版本/说明 |
|------|---------|----------|
| **Web框架** | FastAPI + Uvicorn | 异步高性能，SSE 流式原生支持 |
| **AI编排** | LangGraph 0.6.11 | StateGraph 状态机，PostgreSQL checkpoint 持久化 |
| **LLM** | DeepSeek (deepseek-chat) | 64K上下文，经 langchain-deepseek 适配 |
| **Embedding** | BAAI/bge-small-zh-v1.5 | 中文优化，512维，sentence-transformers 本地推理 |
| **向量数据库** | ChromaDB 1.5.9 | 嵌入式向量存储，文件级持久化 |
| **关系数据库** | PostgreSQL 16 | SQLAlchemy 2.0 ORM，Alembic 迁移管理 |
| **缓存** | Redis 7.4 | allkeys-lru 淘汰策略，AOF 持久化 |
| **服务发现** | Nacos (Alibaba) | nacos-sdk-python，服务注册+心跳+发现 |
| **认证** | JWT (HS256) + Static Token | Gateway 双模式认证，IP 白名单 |
| **监控** | Prometheus + Grafana 11.2 | 7 条告警规则，10 面板仪表盘 |
| **部署** | Docker Compose | 多容器编排，多阶段 Docker 构建 |
| **AI安全** | 自定义过滤器 | 敏感词过滤、注入检测、Prompt泄露防护 |
| **前端** | 原生 HTML/CSS/JS | Jinja2 模板，SSE ReadableStream |

---

## 三、代码组织与模块结构

### 3.1 目录树

```
kefu_agent/
├── backend/                    # ★ 核心后端
│   ├── main.py                 # FastAPI 入口，中间件注册，生命周期管理
│   ├── config.py               # 配置管理（Pydantic Settings，80+ 配置项）
│   ├── database.py             # PostgreSQL 引擎、会话管理、表创建
│   ├── seed.py                 # 种子数据
│   │
│   ├── agent/                  # ★ LangGraph Agent 核心
│   │   ├── graph.py            # 图构建 + 编译（AsyncPostgresSaver）
│   │   ├── state.py            # AgentState 类型 + INTENT_HIERARCHY（10大类）
│   │   ├── nodes.py            # 节点统一导出（向后兼容层）
│   │   ├── classifier.py       # 意图分类 + 指代消解 + 路由
│   │   ├── retriever.py        # 知识检索节点
│   │   ├── generator.py        # 回答生成 + 问候回复
│   │   ├── llm_utils.py        # LLM 调用工具（safe_invoke/stream + 重试）
│   │   ├── prompts.py          # 系统提示词模板
│   │   ├── retrieval_utils.py  # RRF融和、关键词提权、文本清洗
│   │   └── domains/            # 业务域节点（6个）
│   │       ├── order.py        # 订单+物流查询
│   │       ├── product.py      # 商品查询
│   │       ├── coupon.py       # 优惠券查询
│   │       ├── account.py      # 账户信息查询
│   │       ├── complaint.py    # 投诉处理
│   │       └── human.py        # 转人工处理
│   │
│   ├── api/                    # REST API 层
│   │   ├── chat.py             # 消费者对话 SSE（stream/history/new）
│   │   ├── knowledge.py        # 知识库管理 CRUD
│   │   ├── tenant.py           # 租户管理
│   │   └── stats.py            # 统计看板
│   │
│   ├── schemas/                # Pydantic 请求/响应模型
│   │   ├── chat.py / knowledge.py / stats.py / tenant.py
│   │
│   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── conversation.py     # 会话 + 消息
│   │   ├── tenant.py           # 租户
│   │   ├── knowledge.py        # 知识库文档
│   │   ├── feedback.py         # 用户反馈
│   │   └── handoff.py          # 人工转接工单
│   │
│   ├── services/               # 外部系统 API 服务层
│   │   ├── order_service.py    # 对接聚宝赞订单API
│   │   ├── logistics_service.py
│   │   ├── product_service.py
│   │   ├── coupon_service.py
│   │   ├── user_profile_service.py
│   │   ├── handoff_service.py  # 转人工工单管理
│   │   └── sync_service.py     # 知识库同步
│   │
│   ├── middleware/             # HTTP 中间件
│   │   ├── gateway_auth.py     # JWT + Static 双模式认证
│   │   ├── http_client.py      # 限流中间件（Redis）
│   │   └── tenant.py           # 租户上下文
│   │
│   ├── retrieval/              # 检索系统
│   │   ├── chunker.py          # 文档分割
│   │   ├── embedding.py        # 向量嵌入
│   │   ├── vector_store.py     # ChromaDB 操作（多线程写）
│   │   └── hybrid_search.py    # 混合检索（向量+关键词+RRF）
│   │
│   ├── knowledge/              # 知识库管理
│   │   ├── loader.py           # 文档加载（PDF/Markdown）
│   │   ├── splitter.py         # 文本分割
│   │   ├── faq_service.py      # FAQ 问答对管理
│   │   └── sync_log.py         # 同步日志模型
│   │
│   ├── nacos/                  # Nacos 集成
│   │   ├── nacos_client.py     # 客户端封装（HTTP 请求代理）
│   │   ├── discovery.py        # 服务发现
│   │   └── registry.py         # 服务注册 + 心跳
│   │
│   └── utils/                  # 工具库（14个模块）
│       ├── advanced.py         # 降级兜底话术体系（6类）
│       ├── auth.py             # API Key + 身份提取
│       ├── backup.py           # 数据库备份（定时+手动）
│       ├── helpers.py          # 辅助函数
│       ├── json_logger.py      # JSON 格式化日志
│       ├── metrics.py          # Prometheus 指标
│       ├── redis_client.py     # Redis 封装
│       ├── request_id.py       # 链路追踪
│       ├── response_cache.py   # LRU 缓存
│       ├── retry.py            # 重试装饰器
│       ├── security.py         # 安全校验（消息/注入/敏感词/输出清洗）
│       ├── sensitive_filter.py # 日志敏感信息脱敏
│       ├── token_budget.py     # Token 预算管理
│       └── tool_logger.py      # 工具调用日志
│
├── frontend/                   # 前端（原生SSE流式）
│   ├── templates/              # Jinja2 模板
│   └── static/                 # CSS/JS
│
├── tests/                      # 测试
│   ├── unit/                   # 单元测试（16文件）
│   ├── integration/            # 集成测试（4文件）
│   └── eval/                   # 评估脚本（3文件）
│
├── alembic/                    # 数据库迁移
├── monitoring/                 # Grafana仪表盘 + Prometheus配置
├── config/                     # 敏感词库
├── Dockerfile / docker-compose.yml  # 容器化
├── deploy.py                   # SSH 远程部署脚本
├── chat.py                     # CLI 交互测试工具
└── docs/                       # 技术文档
```

### 3.2 关键模块关系

```
main.py (入口，生命周期管理)
  ├─→ database.py (DB引擎/会话/建表)
  ├─→ config.py (配置加载+校验)
  ├─→ middleware/gateway_auth.py (认证)
  ├─→ middleware/http_client.py (限流)
  │
  ├─→ api/chat.py ──→ agent/graph.py (LangGraph Agent)
  │                       ├─→ agent/classifier.py (意图分类)
  │                       │     ├─→ agent/prompts.py (提示词)
  │                       │     ├─→ agent/llm_utils.py (DeepSeek调用)
  │                       │     └─→ utils/response_cache.py / token_budget.py
  │                       ├─→ agent/retriever.py (知识检索)
  │                       │     └─→ retrieval/hybrid_search.py
  │                       │           ├─→ retrieval/vector_store.py (ChromaDB)
  │                       │           └─→ retrieval/embedding.py (sentence-transformers)
  │                       ├─→ agent/generator.py (生成回答)
  │                       │     └─→ agent/llm_utils.py + utils/security.py
  │                       └─→ agent/domains/{order,product,coupon,account,complaint,human}.py
  │                             └─→ services/{order,product,coupon,...}_service.py
  │                                   └─→ nacos/nacos_client.py ──→ Nacos → 外部API
  │
  ├─→ api/knowledge.py ──→ knowledge/{loader,splitter,faq_service}.py
  │                           └─→ retrieval/{chunker,embedding,vector_store}.py
  │
  └─→ utils/ (横切关注点：metrics, redis, backup, security, logger...)
```

---

## 四、核心功能详解

### 4.1 LangGraph Agent 管道

**图拓扑**（有向无环图 DAG）：

```
START
  │
  ▼
classify_intent ─────── route_by_intent ──────┬── human_service_node ──── END
                                              ├── order_query_node ────── END (含物流联动)
                                              ├── product_query_node ──── END
                                              ├── coupon_query_node ───── END
                                              ├── account_query_node ──── END
                                              ├── complaint_node ──────── END
                                              ├── retrieve_knowledge → generate_answer ── END
                                              └── greeting_answer ─────── END
```

**关键特性**：
- **意图缓存**：对无历史的首条消息缓存意图结果，避免重复 LLM 调用
- **指代消解**：LLM 在分类时一并完成（如："那个订单呢？"→ 还原为具体订单号）
- **连续失败自动转人工**：连续 2 次分类失败 → 自动路由到 `human_service`
- **子类标准化**：LLM 的非标准输出映射到标准子类名
- **Token 预算管理**：按优先级控制 context/history/knowledge/response 各部分 token 分配

### 4.2 混合检索（Hybrid Search）

- **向量检索**：ChromaDB，基于 `sentence-transformers` 的中文语义相似度
- **关键词检索**：`where_document` 全文匹配，计算 partial match score
- **RRF 融合**：Reciprocal Rank Fusion 算法合并两路结果
- **多知识库类型**：FAQ、商品文档、公共知识三类隔离检索
- **租户隔离**：每个租户独立的 ChromaDB Collection（UUID 命名）

### 4.3 多租户架构

- **数据隔离**：Conversation/Message/FAQ/Document 均按 `tenant_id` 分区
- **配置隔离**：通过 `TENANT_ID_MAP` 环境变量映射租户到不同的 Nacos 服务
- **安全隔离**：跨租户访问在 `_locate_or_create_session` 中校验拦截
- **ChromaDB 隔离**：每个租户独立 Collection（实现为每租户独立目录）

### 4.4 SSE 流式对话

- **双模式流式**：`stream_mode=["updates", "messages"]` 同时输出节点状态和 LLM token
- **支持两种输出**：LLM streaming 节点（RAG 生成）实时推 token；API 查询节点（订单等）在节点完成时一次性推送结果
- **总超时 120s**：防止永不结束的流式连接
- **原子性**：用户消息和 AI 回复在同一事务中持久化

### 4.5 安全体系

| 安全层 | 实现方式 |
|--------|---------|
| **接口认证** | JWT (HS256) / Static Token + IP 白名单双模式 |
| **消息校验** | 空消息/超长/注入检测/敏感词过滤 |
| **输出清洗** | 系统提示词泄露过滤、Unicode 规范化 |
| **敏感信息** | 手机号/身份证/银行卡正则脱敏 |
| **速率限制** | Redis 滑动窗口，默认 120 req/min |
| **请求大小** | BodySizeLimit 中间件，10MB 上限 |
| **异常处理** | 全局 Exception Handler 统一 500 响应 |
| **生产文档** | 强制关闭 Swagger/ReDoc |
| **CORS** | 可配置来源白名单 |

---

## 五、数据模型

### 5.1 数据库设计（9 张表）

```
tenants                  ← 租户主表
  ├── conversations      ← 会话（tenant_id + user_id + thread_id）
  │     └── messages     ← 消息（user/assistant）
  ├── faqs               ← FAQ 问答对（按 kb_type 分类）
  ├── documents          ← 知识文档（chunks + metadata）
  ├── sync_logs          ← 知识同步日志
  ├── handoff_tickets    ← 人工转接工单
  ├── feedbacks          ← 用户反馈
  └── tool_call_logs     ← 工具调用日志
```

关键索引：conversations(created_at, ended_at, user_id), messages(created_at), handoff_tickets(created_at)

### 5.2 LangGraph State（AgentState TypedDict）

```python
AgentState:
  tenant_id, tenant_name, user_id, user_name, channel, thread_id
  messages: Sequence[BaseMessage]        # LangGraph 管理的对话消息
  intent, intent_sub_type, intent_priority
  intent_entities, coref_resolved, search_query
  suggested_kb_types, retrieved_docs
  final_answer
  user_profile, recent_orders, current_order_id, current_product_id
  ai_failed_count
```

---

## 六、运维基础设施

### 6.1 Docker 部署

- **6个服务**：kefu-agent + Redis + PostgreSQL + Prometheus + Grafana
- **多阶段构建**：CPU-only PyTorch（减少镜像体积），gosu 权限降级
- **健康检查**：app 提供 `/api/v1/system/health`，PG/Redis 各有专用 healthcheck
- **资源限制**：app(2CPU/2G), PG(1CPU/1G), Redis(0.5CPU/512M)
- **远程部署**：deploy.py 支持 SSH（密码/密钥），包含 pg_dump 备份和版本回滚

### 6.2 监控告警

**7 条告警规则**：
1. ServiceDown（严重，1m）
2. HighErrorRate（严重，2m，>5%）
3. LLMCallsFailed（严重，1m，5分钟内 >3 次）
4. HighLatency（警告，5m，P99 >5000ms）
5. HighActiveRequests（警告，3m，>50 并发）
6. ChatMessageSpike（警告，5m，10分钟内 >500 条）
7. HighHandoffRate（警告，10m，>30%）

**Grafana 仪表盘**：10 个面板覆盖服务状态、QPS、延迟、LLM 调用分布、错误分类

### 6.3 CI/CD

- **GitHub Actions**：3 个 Job（test → build → deploy）
- **质量门禁**：ruff lint、mypy 类型检查（continue-on-error）、pytest 覆盖率 ≥70%
- **条件部署**：仅在有 secrets 的分支触发

---

## 七、开发规范与文档

### 7.1 代码规范

- **中文注释**：所有模块、类、方法均有中文 docstring
- **类型提示**：使用 TypedDict、NotRequired、`dict[str, Any]` 现代 Python 类型
- **延迟初始化**：DB 引擎、Redis 连接、Agent 等采用延迟导入 + 加锁单例
- **向后兼容**：`nodes.py` 通过重导出保持旧依赖可用
- **配置集中**：所有配置统一在 `config.py`，Pydantic 类型安全，自动校验

### 7.2 文档完整性

| 文档 | 状态 | 质量 |
|------|------|------|
| README.md | ✅ 完整 | 701 行，涵盖功能/架构/快速开始/配置 |
| CHANGELOG.md | ✅ 完整 | 版本迭代记录 |
| 项目需求说明文档.md | ✅ | 227 行，需求背景 |
| 方案实施文档.md | ✅ | 1097 行，详细实施计划 |
| 部署文档.md | ✅ | 805 行，Docker/SSH 部署流程 |
| 接口对接方案.md | ✅ | 1452 行，聚宝赞接口映射表 |
| docs/database-design.md | ✅ | 345 行，完整表结构 |
| docs/monitoring.md | ✅ | 328 行，监控告警体系 |

---

## 八、设计模式与架构风格

| 模式/风格 | 应用位置 |
|-----------|---------|
| **状态机模式** | LangGraph StateGraph（意图分类→路由→执行→结束） |
| **管道/过滤器** | 中间件链（CORS → RequestID → BodyLimit → Metrics → RateLimit） |
| **策略模式** | 双模式认证（JWT vs Static）、多意图路由 |
| **单例模式** | Agent 实例（`get_agent()` + asyncio.Lock）、DB 引擎延迟初始化 |
| **装饰器模式** | `@retry_on_transient_error`、API Key 依赖注入 |
| **工厂模式** | LLM 模型工厂（`get_classify_llm` / `get_generate_llm`） |
| **观察者模式** | Prometheus 指标采集（请求/LLM/错误/缓存） |
| **代理模式** | Nacos 客户端封装后端 API 调用 |
| **模板方法** | Jinja2 模板渲染前端页面 |
| **异步非阻塞** | 全链路 async/await（FastAPI + httpx + LangGraph） |

---

## 九、优势与亮点

### 9.1 架构层面

1. **成熟的 Agent 编排**：LangGraph StateGraph 提供结构化的意图管道，比简单的 prompt 链更可控
2. **真流式体验**：`stream_mode=["updates", "messages"]` 使 LLM 生成 token 实时推送，同时保留非流式节点的完整性
3. **完善的容错机制**：多层 fallback（LLM 调用重试 → 意图回退 → 兜底话术 → 自动转人工）
4. **多租户从始至终**：从配置、数据库、向量存储到 API 全链路隔离
5. **配置热安全**：启动时 20+ 项配置校验，生产环境弱凭证/缺密钥拒绝启动

### 9.2 安全层面

1. **多层防御**：认证 → 消息校验 → 输出清洗 → 敏感信息脱敏
2. **注入防护**：10+ 种中英文 SQL/Shell/Prompt 注入模式检测
3. **Unicode 绕过防护**：全角字母/零宽字符/BOM 规范化处理
4. **生产文档关闭**：`ENV=prod` 时自动禁用 Swagger

### 9.3 运维层面

1. **一键部署**：docker-compose up 即可启动完整 6 服务栈
2. **自动化部署**：deploy.py 支持 SSH 远程部署，含备份和回滚
3. **全链路监控**：Prometheus + Grafana 覆盖 QPS/延迟/LLM/错误/转人工率
4. **定时备份**：数据库每小时+每日自动备份

### 9.4 工程质量

1. **测试分层**：Unit（16 文件）→ Integration（4 文件）→ Eval（3 文件）
2. **意图评估**：46 个测试用例覆盖 13 个类别，量化意图准确率
3. **CI 质量门禁**：ruff + mypy + pytest 覆盖率 ≥70%
4. **版本化迁移**：Alembic 管理 schema 变更

---

## 十、潜在问题与改进空间

### 10.1 架构层面

| 问题 | 严重度 | 建议 |
|------|--------|------|
| **无异步 Embedding 卸载** | 中 | `sentence-transformers` 在 FastAPI 事件循环中同步推理，可能阻塞。建议将 embedding 放到独立线程池或分离服务 |
| **ChromaDB 单机限制** | 中 | 嵌入式 ChromaDB 不适合高并发/大数据量。生产环境可考虑 Milvus/Qdrant 等分布式方案 |
| **无请求队列** | 低 | 高并发时 LLM 调用可能超 DeepSeek 速率限制。建议引入消息队列削峰 |
| **Agent 无人工审核机制** | 低 | 用户反馈已记录但缺少人工 review 和持续优化闭环 |

### 10.2 代码层面

| 问题 | 位置 | 建议 |
|------|------|------|
| **nodes.py 重导出层增加间接性** | `backend/agent/nodes.py` | 已标记为"向后兼容"，可考虑在下一大版本移除 |
| **部分 deepcopy 开销** | `classifier.py` 缓存 | 意图缓存使用 `json.dumps/loads` 做深拷贝，对小对象开销可接受但可优化 |
| **硬编码阈值** | 多处 | `ai_failed_count >= 2`、`len(answer) > 10` 等应抽取到配置 |
| **LLM JSON 解析容错有限** | `classifier.py` | 仅处理了 markdown code block 包裹，未处理尾部逗号等 JSON 格式问题，可加入 `json_repair` 库 |

### 10.3 安全层面

| 问题 | 严重度 | 建议 |
|------|--------|------|
| **敏感词库仅一个文件** | 低 | `config/sensitive_words.txt` 需定期更新，可考虑接入外部敏感词服务 |
| **消息大小限制仅检查 Content-Length** | 中 | 如果客户端不发送 Content-Length 头则可绕过。建议增加流式读取+累计大小检查 |
| **Redis 缓存无加密** | 低 | 意图/答案缓存以明文存储，包含用户消息内容 |

### 10.4 测试层面

| 问题 | 建议 |
|------|------|
| **真 LLM 调用测试不足** | 单元测试大量 mock LLM，集成测试依赖真实 API。建议增加 VCR/recording 模式的测试 |
| **性能测试缺失** | 仅有 `test_stress.py`（集成测试），缺少正式的负载测试（如 locust/k6） |
| **边界条件覆盖** | 部分领域节点（domains/*.py）的测试覆盖集中在 happy path |

### 10.5 运维层面

| 问题 | 建议 |
|------|------|
| **无日志聚合** | 建议引入 ELK/Loki 做集中式日志 |
| **单点故障** | PostgreSQL/Redis 均单实例，生产环境建议主从/集群 |

---

## 十一、总结评价

### 综合评分

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构设计** | ⭐⭐⭐⭐⭐ | LangGraph + RAG + 多租户架构成熟、清晰 |
| **代码质量** | ⭐⭐⭐⭐ | 类型提示、注释完整、遵循 Python 最佳实践 |
| **安全性** | ⭐⭐⭐⭐ | 多层防御，认证/校验/脱敏体系完善 |
| **可运维性** | ⭐⭐⭐⭐⭐ | Docker 一键部署，Prometheus/Grafana 全链路监控 |
| **测试覆盖** | ⭐⭐⭐⭐ | 三层测试体系，意图评估健全 |
| **文档完整性** | ⭐⭐⭐⭐⭐ | 部署/对接/实施/监控文档齐备 |
| **可扩展性** | ⭐⭐⭐⭐ | 插件化领域节点，新增意图只需添加 domain 文件 |

### 核心结论

这是一个 **工程质量较高** 的 AI Agent 客服系统 MVP。架构设计合理（LangGraph 状态机 + RAG + 多租户），安全防护完善（多层认证+注入检测+输出清洗），运维基础设施健全（Docker 全栈 + 监控告警 + 自动备份）。代码注释丰富，遵循 Python 生态的最佳实践。主要改进方向在于：性能优化（embedding 异步化）、高可用改造（PG/Redis 集群）、LLM 输出鲁棒性增强（JSON 解析容错）。

---

> 📊 本报告基于对项目全部 ~120 个文件的系统性阅读和分析生成。
