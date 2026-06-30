# 聚宝赞 AI 智能客服 Agent

> 基于大语言模型（DeepSeek）+ RAG 检索增强生成的多租户 AI 客服系统，支持意图识别、知识库问答、订单查询、物流追踪、商品查询、转人工等全链路客服场景。

---

## 目录

- [项目简介](#项目简介)
- [系统架构](#系统架构)
- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [环境变量配置](#环境变量配置)
- [API 接口文档](#api-接口文档)
- [项目目录结构](#项目目录结构)
- [核心模块详解](#核心模块详解)
- [安全防护](#安全防护)
- [部署指南](#部署指南)
- [测试](#测试)
- [常见问题](#常见问题)

---

## 项目简介

这是一个为电商平台「聚宝赞」设计的 AI 智能客服系统。用户（消费者）通过聊天界面提问，系统自动完成：

1. **理解用户意图** — 用户想干什么？查订单？问退货？还是闲聊？
2. **获取相关信息** — 从知识库检索相关文档，或调用业务 API 查询数据
3. **生成专业回答** — 基于检索到的信息，用友好自然的语言回复用户
4. **必要时转人工** — 当 AI 无法解决时，自动创建工单转接人工客服

### 设计理念

| 原则 | 说明 |
|------|------|
| 不猜测数据 | 涉及订单、金额等具体数据时，必须调用 API 查询，绝不凭空编造 |
| 一次解决 | 尽量在一次回复中完整回答，减少反复追问 |
| 安全第一 | Prompt 注入检测、敏感词过滤、输出审核、API Key 时序安全比较 |
| 多租户隔离 | 每个商家的知识库、数据完全隔离 |

---

## 系统架构

```
用户消息
   │
   ▼
┌──────────────────────────────────────────────────┐
│                   FastAPI 服务                     │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ 限流中间件    │  │ Request-ID   │  │ CORS     │ │
│  └─────────────┘  └──────────────┘  └──────────┘ │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ 安全校验     │  │ 消息验证      │               │
│  │ (Gateway认证)│  │ (注入/敏感词) │               │
│  └─────────────┘  └──────────────┘               │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│              LangGraph Agent 工作流                │
│                                                    │
│  ┌──────────────┐                                  │
│  │ 意图识别节点  │ ← DeepSeek LLM (temperature=0)  │
│  │ (含指代消解)  │                                  │
│  └──────┬───────┘                                  │
│         │                                          │
│    路由分发（10种意图）                              │
│         │                                          │
│  ┌──────┴──────┬──────────┬──────────┐            │
│  ▼             ▼          ▼          ▼            │
│ 知识检索    订单查询    商品查询   转人工 ...       │
│  │             │          │          │             │
│  ▼             ▼          ▼          ▼             │
│ 生成回答    格式化结果   查询结果  创建工单         │
│  │             │          │          │             │
│  └─────────────┴──────────┴──────────┘             │
│                    │                                │
│                    ▼                                │
│              输出过滤 + 敏感词审核                    │
└──────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ ChromaDB  │  │PostgreSQL│  │ 业务 API  │
   │ 向量知识库 │  │ 对话存储  │  │ 订单/物流  │
   └──────────┘  └──────────┘  └──────────┘
```

---

## 核心功能

### 意图识别与路由

系统支持 10 种意图大类，按优先级从高到低路由：

| 优先级 | 意图 | 说明 | 路由目标 |
|--------|------|------|----------|
| 1 | `human_service` | 转人工服务 | 创建工单 + 转人工 |
| 3 | `order_query` | 订单查询 | 调用订单 API |
| 3 | `logistics_query` | 物流查询 | 查订单 + 查物流 |
| 3 | `product_query` | 商品咨询 | 调用商品 API |
| 3 | `coupon_query` | 优惠券咨询 | 调用优惠券 API |
| 3 | `account_query` | 账户查询 | 调用用户画像 API |
| 4 | `knowledge_query` | 通用知识查询 | 知识库检索 + LLM 生成 |
| 5 | `greeting` | 问候/闲聊 | LLM 生成 |
| 5 | `feedback` | 反馈/确认 | 固定话术 |
| 5 | `other` | 其他 | 兜底话术 |

### 知识库检索（RAG）

- **混合检索**：向量语义检索 + 关键词文本匹配，双路并行召回
- **多知识库类型**：FAQ、商品、规则
- **租户隔离**：每个商家的知识库完全独立
- **RRF 融合**：双路结果通过 Reciprocal Rank Fusion 算法合并排序，向量路权重 0.7 + 关键词路权重 0.3

### 安全防护

- **Prompt 注入检测**：20 种注入模式 + Unicode 归一化 + 零宽字符过滤
- **敏感词审核**：赌博/色情/毒品/诈骗等敏感词拦截
- **输出过滤**：防止系统提示词泄露
- **API Key 安全**：`hmac.compare_digest` 时序安全比较
- **日志脱敏**：手机号、订单号、API Key 自动掩码

---

## 技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 高性能异步 API 框架 |
| LLM | DeepSeek (langchain-deepseek) | 意图识别 + 回答生成 |
| Agent 框架 | LangGraph | 有状态的 Agent 工作流编排 |
| 向量数据库 | ChromaDB | 知识库向量存储与检索 |
| Embedding | BAAI/bge-small-zh-v1.5 | 中文文本向量化模型（本地运行） |
| 关系数据库 | PostgreSQL + SQLAlchemy | 对话记录、租户、工单等 |
| 前端 | HTML + CSS + JavaScript | SSE 流式聊天气泡界面 |
| 容器化 | Docker + docker-compose | 一键部署 |

---

## 快速开始

### 前置条件

- Python 3.11+
- 2GB+ 内存（Embedding 模型需要）
- DeepSeek API Key（[获取地址](https://platform.deepseek.com/)）

### 第一步：克隆项目

```bash
git clone <仓库地址>
cd kefu_agent
```

### 第二步：安装依赖

```bash
pip install -r requirements.txt
```

> 首次运行时，Embedding 模型会自动从 HuggingFace 镜像下载（约 100MB），请耐心等待。

### 第三步：配置环境变量

```bash
# 复制示例配置文件
copy .env.example .env
```

然后用文本编辑器打开 `.env`，**必须修改**以下配置：

```ini
# 必须修改：填入你的 DeepSeek API Key
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 建议修改：管理接口认证密钥
ADMIN_API_KEY=your-custom-admin-key
```

### 第四步：初始化数据

```bash
python -m backend.seed
```

这会创建演示租户 `demo_001` 和 10 条示例 FAQ，并同步到向量知识库。

### 第五步：启动服务

```bash
python -m backend.main
```

服务启动后：

- 聊天界面：浏览器打开 http://127.0.0.1:8080
- API 文档（开发模式）：http://127.0.0.1:8080/docs

### 快速测试（命令行）

```bash
python chat.py
```

进入交互式聊天界面，输入消息即可测试。

---

## 环境变量配置

所有配置项都在 `.env` 文件中，以下是完整说明：

### 必须配置

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-xxxxxxxx` |

### LLM 模型配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `LLM_TEMPERATURE_CLASSIFY` | `0.0` | 意图分类温度（越低越确定） |
| `LLM_TEMPERATURE_GENERATE` | `0.7` | 回答生成温度（越高越多样） |
| `LLM_MAX_TOKENS` | `2048` | 最大生成 token 数 |

### Embedding 模型配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 中文 Embedding 模型 |
| `EMBEDDING_DEVICE` | `cpu` | 运行设备（`cpu` 或 `cuda`） |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace 镜像（国内加速） |

### 数据存储路径

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DATABASE_URL` | 必填，无默认值（示例: `postgresql://kefu:kefu_pwd@localhost:5432/kefu_agent`） | PostgreSQL 数据库连接串 |
| `CHROMA_PATH` | `data/chroma_db` | ChromaDB 向量库路径 |

### 检索参数

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `RETRIEVAL_TOP_K` | `5` | 检索返回的最大文档数 |
| `RETRIEVAL_THRESHOLD` | `0.2` | 最低相关性阈值（0-1，越低召回越多） |
| `MAX_HISTORY_TURNS` | `10` | 最大对话历史轮数 |
| `DOC_CHUNK_SIZE` | `800` | 文档分块大小（字符数） |
| `DOC_CHUNK_OVERLAP` | `100` | 分块重叠字符数 |

### Token 预算管理

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `CONTEXT_TOTAL_BUDGET` | `8000` | 上下文总 token 预算 |
| `SYSTEM_PROMPT_BUDGET` | `1500` | 系统提示词 token 预算 |
| `HISTORY_MESSAGE_BUDGET` | `2500` | 对话历史 token 预算 |
| `KNOWLEDGE_CONTEXT_BUDGET` | `2500` | 知识上下文 token 预算 |
| `RESPONSE_RESERVED_TOKENS` | `2048` | 响应预留 token 数 |
| `HISTORY_MAX_TURNS_FALLBACK` | `6` | 历史轮数回退值 |

### 服务配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `HOST` | `127.0.0.1` | 监听地址 |
| `PORT` | `8080` | 监听端口（Docker 可通过 PORT 环境变量映射到宿主机端口如 8720） |
| `ADMIN_API_KEY` | `change-me-admin-key` | 管理接口认证密钥 |
| `GATEWAY_VERIFIED_HEADER` | `X-Gateway-Verified` | Gateway 验证头名称 |
| `GATEWAY_IP_WHITELIST` | `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | Gateway/VPN 网段 IP 白名单 |

### 业务 API 对接（Nacos 服务发现）

以下配置用于对接聚宝赞后端业务系统，所有业务 API 调用均通过 Nacos 服务发现：

| 变量名 | 说明 |
|--------|------|
| `NACOS_SERVER_ADDR` | Nacos 服务端地址 |
| `NACOS_NAMESPACE` | Nacos 命名空间 ID |
| `NACOS_GROUP` | Nacos 分组名称 |
| `ORDER_SERVICE_NAME` | 订单服务在 Nacos 中的注册名 |
| `PRODUCT_SERVICE_NAME` | 商品服务在 Nacos 中的注册名 |
| `LOGISTICS_SERVICE_NAME` | 物流服务在 Nacos 中的注册名 |
| `COUPON_SERVICE_NAME` | 优惠券服务在 Nacos 中的注册名 |
| `USER_PROFILE_SERVICE_NAME` | 用户画像服务在 Nacos 中的注册名 |
| `ORDER_API_TIMEOUT` | 订单 API 超时（秒） |
| `PRODUCT_API_TIMEOUT` | 商品 API 超时（秒） |
| `LOGISTICS_API_TIMEOUT` | 物流 API 超时（秒） |
| `COUPON_API_TIMEOUT` | 优惠券 API 超时（秒） |
| `USER_PROFILE_API_TIMEOUT` | 用户画像 API 超时（秒） |

---

## API 接口文档

开发模式下访问 http://127.0.0.1:8080/docs 可查看完整的 Swagger 交互式文档。

### 消费者聊天

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/{tenant_id}/stream` | 发起/继续对话（SSE 流式） |
| GET | `/api/v1/chat/{tenant_id}/history/{session_id}` | 获取历史消息 |

**请求示例（流式对话）：**

```bash
curl -X POST http://localhost:8080/api/v1/chat/demo_001/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"message": "退货政策是什么？", "session_id": "sess_001", "user_id": "user_001"}'
```

### 知识库同步

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/knowledge/sync/{tenant_id}/{kb_type}` | 全量/增量同步 |
| DELETE | `/api/v1/knowledge/sync/{tenant_id}/{kb_type}` | 清空知识库 |

**知识库类型（kb_type）：**

| 类型 | 说明 |
|------|------|
| `faq` | 商家 FAQ 问答对 |
| `product` | 商品知识 |
| `rule` | 规则文档 |

### 系统监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/system/health` | 健康检查 |
| GET | `/api/v1/system/metrics` | Prometheus 运行指标 |

### 租户管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/tenant/create` | 创建租户 |

---

## 项目目录结构

```
kefu_agent/
├── backend/                    # 后端核心代码
│   ├── agent/                  # Agent 工作流
│   │   ├── graph.py            # LangGraph 图构建（节点 + 路由拓扑）
│   │   ├── nodes.py            # 节点重导出（向后兼容）
│   │   ├── prompts.py          # 系统提示词（分类 + 生成 + 各场景）
│   │   ├── state.py            # Agent 状态定义 + 意图层级体系
│   │   ├── classifier.py       # 意图识别 + 路由分发
│   │   ├── retriever.py        # 知识检索节点
│   │   ├── generator.py        # 回答生成 + 问候节点
│   │   ├── llm_utils.py        # LLM 安全调用 + 模型工厂
│   │   ├── retrieval_utils.py  # RRF 融合 / 格式化 / 输出清理
│   │   └── domains/            # 业务域节点
│   │       ├── order.py        # 订单 + 物流查询
│   │       ├── product.py      # 商品咨询
│   │       ├── coupon.py       # 优惠券查询
│   │       ├── account.py      # 账户查询
│   │       ├── complaint.py    # 投诉处理
│   │       └── human.py        # 转人工服务
│   ├── api/                    # API 路由
│   │   ├── chat.py             # 消费者聊天（SSE 流式）
│   │   ├── knowledge.py        # 知识库同步
│   │   ├── stats.py            # 监控统计（健康检查/指标/对话统计）
│   │   └── tenant.py           # 租户管理
│   ├── knowledge/              # 知识处理
│   │   ├── faq_service.py      # FAQ 服务
│   │   ├── loader.py           # 文档加载器
│   │   ├── splitter.py         # 文档分块器
│   │   └── sync_log.py         # 同步日志 + 回滚
│   ├── middleware/              # 中间件
│   │   ├── http_client.py      # 全局 HTTP 客户端 + 限流中间件
│   │   ├── tenant.py           # 租户上下文 + API Key 认证
│   │   └── gateway_auth.py     # Gateway 认证 + IP 白名单
│   ├── nacos/                  # Nacos 服务治理
│   │   ├── registry.py         # 服务注册 + 心跳
│   │   ├── discovery.py        # 服务发现 + 负载均衡
│   │   └── nacos_client.py     # Nacos HTTP 请求 + 熔断器
│   ├── models/                 # 数据库模型
│   │   ├── conversation.py     # 对话 + 消息 + 工具调用日志
│   │   ├── handoff.py          # 转人工工单
│   │   ├── knowledge.py        # FAQ + 文档
│   │   ├── tenant.py           # 租户
│   │   └── feedback.py         # 满意度评价
│   ├── retrieval/              # 检索引擎
│   │   ├── chunker.py          # 知识条目分块
│   │   ├── embedding.py        # Embedding 模型加载
│   │   ├── hybrid_search.py    # 混合检索（向量 + 关键词）
│   │   └── vector_store.py     # ChromaDB 向量存储封装
│   ├── schemas/                # Pydantic 请求/响应模型
│   │   ├── chat.py             # 聊天相关
│   │   ├── knowledge.py        # 知识同步相关
│   │   ├── tenant.py           # 租户相关
│   │   └── stats.py            # 反馈/统计相关
│   ├── services/               # 业务服务
│   │   ├── coupon_service.py   # 优惠券查询
│   │   ├── handoff_service.py  # 转人工工单
│   │   ├── logistics_service.py# 物流查询
│   │   ├── order_service.py    # 订单查询
│   │   ├── product_service.py  # 商品查询
│   │   ├── sync_service.py     # 知识库异步同步
│   │   └── user_profile_service.py # 用户画像
│   ├── utils/                  # 工具模块
│   │   ├── advanced.py         # 兜底话术 + A/B 测试
│   │   ├── auth.py             # 管理接口 API Key 认证（时序安全）
│   │   ├── helpers.py          # 公共辅助函数
│   │   ├── metrics.py          # 系统指标收集
│   │   ├── request_id.py       # 请求链路追踪 ID
│   │   ├── response_cache.py   # LRU 响应缓存
│   │   ├── security.py         # 安全防护（注入检测 + 敏感词 + 输出过滤）
│   │   ├── sensitive_filter.py # 日志脱敏过滤器
│   │   └── token_budget.py     # Token 预算管理 + 上下文裁剪
│   ├── config.py               # 配置加载 + 校验
│   ├── database.py             # 数据库引擎 + 连接池
│   ├── main.py                 # FastAPI 应用入口
│   └── seed.py                 # 种子数据初始化
├── frontend/                   # 前端
│   ├── static/
│   │   ├── css/style.css       # 样式
│   │   └── js/chat.js          # SSE 聊天交互逻辑
│   └── templates/
│       ├── base.html           # 基础模板
│       └── consumer/chat.html  # 消费者聊天页
├── tests/                      # 测试
│   ├── conftest.py             # pytest 全局配置
│   ├── unit/                   # 单元测试（20个文件, 290+ 用例）
│   ├── integration/            # 集成测试
│   └── eval/                   # 评估测试
├── monitoring/                  # 监控配置
│   ├── prometheus.yml          # Prometheus 抓取配置
│   ├── alerts.yml              # 告警规则
│   └── grafana/                # Grafana 仪表盘
├── data/                       # 运行时数据（git 忽略）
│   └── chroma_db/              # ChromaDB 向量库
├── .env.example                # 环境变量示例
├── .gitignore                  # Git 忽略规则
├── Dockerfile                  # Docker 镜像构建
├── docker-compose.yml          # Docker Compose 编排
├── requirements.txt            # Python 依赖
├── chat.py                     # 命令行交互测试工具
└── README.md                   # 本文档
```

---

## 核心模块详解

### 1. Agent 工作流（backend/agent/）

系统使用 LangGraph 构建有状态的 Agent 工作流。用户消息进入后，经过以下流程：

```
用户消息 → 意图识别 → 路由分发 → 具体处理节点 → 输出过滤 → 返回
```

**意图识别**（`classify_intent_node`）：
- 先完成指代消解（"这个多少钱" → "iPhone 15 多少钱"）
- 再进行两层意图分类（大类 + 子类）
- 提取实体信息（订单号、手机号、商品名等）
- 连续 2 次识别失败自动转人工

**路由分发**（`route_by_intent`）：
- 根据意图大类路由到对应处理节点
- 未知意图默认路由到问候节点

### 2. 检索引擎（backend/retrieval/）

**混合检索流程**：

```
用户问题 + 意图关键词
   │
   ├── 向量语义检索 ──→ ChromaDB 向量匹配 ──→ 相似度排序（权重 0.7）
   │
   ├── 关键词文本匹配 ──→ 全文关键词命中 ──→ 命中数排序（权重 0.3）
   │
   └── RRF 融合 ──→ 去重 + 加权排名求和 ──→ 最终排序结果
```

- 向量检索：将用户问题转为向量，在 ChromaDB 中找最相似的文档
- 关键词匹配：直接在文档内容中搜索关键词，作为向量检索的补充
- RRF 融合：两路结果按 Reciprocal Rank Fusion 算法合并，同一文档双路命中时分数叠加

### 3. Token 预算管理（backend/utils/token_budget.py）

LLM 的上下文窗口有限，系统通过 Token 预算管理确保不超出限制：

```
总预算 8000 tokens
├── 系统提示词：1500 tokens
├── 对话历史：2500 tokens（超出自动裁剪，保留最近消息）
├── 知识上下文：2500 tokens（超出自动裁剪，保留高相关文档）
└── 响应预留：2048 tokens（由 LLM max_tokens 控制）
```

### 4. 响应缓存（backend/utils/response_cache.py）

- **意图缓存**：相同问题文本直接复用意图结果（TTL 5 分钟，最多 500 条）
- **答案缓存**：高频问题缓存完整回复（TTL 10 分钟，最多 200 条）
- 使用 LRU 策略，线程安全

### 5. 知识库同步（backend/services/sync_service.py）

支持三种同步模式：

| 模式 | 说明 |
|------|------|
| `full` | 全量替换：先清空，再写入新数据 |
| `incremental` | 增量追加：只添加/更新，不删除 |

同步流程为实时处理：聚宝赞控制批量大小（约 10 条/批），调用后实时返回处理结果。

---

## 安全防护

### 多层安全体系

```
用户输入
   │
   ├── 第1层：消息长度限制（4000 字符）
   │
   ├── 第2层：Prompt 注入检测
   │   ├── 20 种注入模式匹配（中英文）
   │   ├── Unicode 归一化（防止全角字符绕过）
   │   └── 零宽字符过滤（防止不可见字符插入）
   │
   ├── 第3层：敏感词审核
   │   └── 赌博/色情/毒品/诈骗等敏感词拦截
   │
   ├── 第4层：JWT Bearer Token 认证 / Gateway 静态令牌 + Admin API Key（管理接口）
   │   └── hmac.compare_digest 时序安全比较
   │
   └── 第5层：输出过滤
       ├── 系统提示词泄露过滤
       └── 内部变量名过滤
```

### 日志脱敏

所有日志输出自动进行敏感信息掩码：

| 类型 | 原始 | 脱敏后 |
|------|------|--------|
| 手机号 | 13812345678 | 138****5678 |
| 订单号 | ORD20240101890 | ORD***890 |
| API Key | sk-abc123def456 | sk-a****56 |

---

## 部署指南

### Docker 部署（推荐）

```bash
# 1. 配置环境变量
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 等配置

# 2. 构建并启动
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 初始化种子数据
docker-compose exec kefu-agent python -m backend.seed
```

### 生产环境注意事项

1. **必须修改默认密钥**：修改 `ADMIN_API_KEY`，生产环境使用默认弱密钥将拒绝启动
2. **配置认证模式**：通过 `GATEWAY_AUTH_MODE` 选择 `jwt`/`static`/`both`（默认 `both`）。若启用 JWT（`jwt`/`both` 模式），必须配置 `JWT_SECRET` 与聚宝赞 Nacos 一致——生产环境 `JWT_SECRET` 为空将拒绝启动，运行时为空将拒绝验签（不跳过）
3. **CORS 配置**：通过 `ALLOWED_ORIGINS` 环境变量配置允许的跨域来源
4. **资源限制**：docker-compose 已配置 CPU 2核 / 内存 2G 上限
5. **健康检查**：`/api/v1/system/health` 端点可用于负载均衡器探活

### Nginx 反向代理示例

```nginx
server {
    listen 80;
    server_name kefu.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;

        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 120s;
    }
}
```

---

## 测试

### 运行单元测试

```bash
python -m pytest tests/ -v
```

### 测试覆盖范围

| 测试文件 | 覆盖模块 | 用例数 |
|----------|----------|--------|
| `test_security.py` | validate_message、detect_injection、check_sensitive_content、sanitize_output、Unicode 归一化 | 50+ |
| `test_routing.py` | route_by_intent、INTENT_HIERARCHY 完整性 | 14 |
| `test_chat_schema.py` | ChatRequest 校验（session_id/user_id/message 边界值） | 15+ |
| `test_config.py` | validate_config（errors/warnings 逻辑） | 5+ |
| `test_core_modules.py` | auth、token_budget、response_cache、sensitive_filter | 40+ |
| `test_gateway_auth.py` | IP白名单、CIDR网段、Header校验、IPv6 | 35+ |
| `test_hybrid_search.py` | 向量检索、关键词匹配、RRF融合、降级策略 | 40+ |

### 命令行交互测试

```bash
# 使用默认租户
python chat.py

# 指定租户
python chat.py --tenant demo_001
```

---

## 常见问题

### Q: 首次启动很慢？

A: 首次启动时需要下载 Embedding 模型（约 100MB），后续会使用缓存。如果下载慢，确认 `HF_ENDPOINT=https://hf-mirror.com` 已配置。

### Q: 如何添加新的知识库内容？

A: 通过知识同步 API 推送：

```bash
curl -X POST http://localhost:8080/api/v1/knowledge/sync/demo_001/faq \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{
    "sync_type": "incremental",
    "items": [
      {"id": "faq_001", "content": "Q: 配送范围？\nA: 全国包邮（偏远地区除外）", "metadata": {"category": "物流"}}
    ]
  }'
```

### Q: 如何对接真实的业务 API？

A: 所有业务 API 调用均通过 Nacos 服务发现进行，无需单独配置 API 地址和密钥。确保 `.env` 中 Nacos 相关配置正确，聚宝赞端服务已在 Nacos 中注册即可。

### Q: 如何创建新的租户？

A: 调用租户管理 API：

```bash
curl -X POST http://localhost:8080/api/v1/tenant/create \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-admin-key" \
  -d '{"tenant_id": "shop_002", "name": "新商家"}'
```

### Q: 生产环境如何保证安全？

A:
1. 修改 `ADMIN_API_KEY` 默认密钥
2. 配置 JWT 认证（`JWT_SECRET` 与聚宝赞 Nacos 保持一致）
3. 配置 Nginx 反向代理 + HTTPS
4. 定期轮换 Admin API Key

### Q: 数据存储在哪里？

A: 所有数据存储分布如下：
- PostgreSQL 数据库 — 对话、租户、工单、检查点等（通过 `DATABASE_URL` 配置）
- `data/chroma_db/` — ChromaDB 向量知识库

备份方式：PostgreSQL 使用 `pg_dump` 备份，ChromaDB 备份 `data/chroma_db/` 目录。
