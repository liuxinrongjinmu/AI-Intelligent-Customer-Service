# 数据库设计文档

> 本文档说明 kefu-agent 的 SQLite 数据库结构、索引设计与备份策略。
>
> 相关代码：
> - 数据库引擎：`backend/database.py`
> - 配置项：`backend/config.py`（`SQLITE_PATH`）
> - 数据模型：`backend/models/`
> - 同步日志模型：`backend/knowledge/sync_log.py`
> - 备份模块：`backend/utils/backup.py`

---

## 一、数据库概述

| 项 | 值 |
|----|----|
| 数据库类型 | SQLite |
| 数据库文件路径 | `data/app.db` |
| 配置变量 | `SQLITE_PATH`（默认 `data/app.db`） |
| ORM 框架 | SQLAlchemy 2.0（DeclarativeBase） |
| 连接池 | QueuePool（pool_size=5，max_overflow=10，pool_recycle=300s，pool_timeout=30s） |
| 日志模式 | WAL（Write-Ahead Logging） |
| 同步模式 | `PRAGMA synchronous=NORMAL` |
| 忙等超时 | `PRAGMA busy_timeout=5000`（5 秒） |
| 缓存大小 | `PRAGMA cache_size=-2000`（2MB） |

### 连接初始化

每个新连接建立时执行以下 PRAGMA（见 `backend/database.py`）：

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-2000;
```

---

## 二、表结构

数据库共 8 张表，均通过 SQLAlchemy 模型定义，由 `init_db()` 自动创建。

### 2.1 tenants — 租户表

每个商家作为一个独立租户，数据隔离的顶层主体。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | Integer | PK, autoincrement | 主键 |
| `tenant_id` | String(64) | unique, not null, index | 租户业务 ID（如 `demo_001`） |
| `name` | String(128) | not null | 租户名称 |
| `api_key_hash` | String(256) | not null | API Key 的 SHA-256 哈希值 |
| `api_key_prefix` | String(16) | not null | API Key 前缀（用于展示，如 `jbz-xxxxx`） |
| `is_active` | Boolean | default True | 是否启用 |
| `created_at` | DateTime | default utcnow | 创建时间 |
| `updated_at` | DateTime | default utcnow, onupdate utcnow | 更新时间 |

- 模型文件：`backend/models/tenant.py`
- API Key 生成：`generate_api_key()` 返回 `(raw, hash, prefix)`，原始 Key 仅在创建时返回一次。

### 2.2 conversations — 会话表

一次完整的用户对话会话。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | String(64) | PK | 会话 ID（UUID） |
| `thread_id` | String(64) | unique, index | LangGraph 线程 ID |
| `tenant_id` | String(64) | not null, index | 租户 ID |
| `user_id` | String(64) | index | 用户 ID |
| `user_name` | String(128) | default "匿名用户" | 用户名 |
| `channel` | String(16) | default "unknown" | 渠道（app/miniapp/pc/h5） |
| `status` | String(16) | default "ai_serving", index | 会话状态 |
| `agent_id` | String(64) | default "" | 接待坐席 ID |
| `priority` | Integer | default 0 | 优先级（转人工时使用） |
| `tags` | JSON | default list | 标签列表 |
| `summary` | Text | default "" | 会话摘要 |
| `context_snapshot` | JSON | default dict | 上下文快照 |
| `ai_failed_count` | Integer | default 0 | AI 失败次数（连续 2 次转人工） |
| `message_count` | Integer | default 0 | 消息数 |
| `rating` | Integer | default 0 | 用户评分 |
| `created_at` | DateTime | index | 创建时间 |
| `updated_at` | DateTime | | 更新时间 |
| `ended_at` | DateTime | index | 结束时间 |

- 模型文件：`backend/models/conversation.py`
- 会话状态机：`queued` → `ai_serving` / `human_serving` → `ended`

### 2.3 messages — 消息表

会话内的每一条消息（用户消息 / AI 回复 / 系统消息）。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | String(64) | PK | 消息 ID（UUID） |
| `conversation_id` | String(64) | FK→conversations.id, not null, index | 会话 ID |
| `role` | String(16) | not null | 角色（user/assistant/system） |
| `content` | Text | default "" | 消息内容 |
| `intent` | String(32) | default "" | 意图大类 |
| `intent_sub_type` | String(32) | default "" | 意图子类 |
| `entities` | JSON | default dict | 实体信息（订单号、商品名等） |
| `created_at` | DateTime | index | 创建时间 |

- 模型文件：`backend/models/conversation.py`
- 与 `conversations` 表通过 `relationship` 关联，级联删除（`cascade="all, delete-orphan"`）。

### 2.4 sync_logs — 知识库同步日志表

记录每次知识库同步操作，支持查看变更历史与回滚。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | Integer | PK, autoincrement | 主键 |
| `tenant_id` | String(64) | not null, index | 租户 ID |
| `kb_type` | String(32) | not null | 知识库类型（faq/product/rule/public） |
| `sync_type` | String(32) | not null | 同步类型（full/incremental） |
| `item_count` | Integer | default 0 | 原始条目数 |
| `processed_count` | Integer | default 0 | 实际处理数 |
| `deleted_count` | Integer | default 0 | 删除条目数 |
| `snapshot` | Text | nullable | JSON 快照数据（最多 1000 条，用于回滚） |
| `status` | String(16) | default "success" | 状态（success/partial/failed） |
| `created_at` | DateTime | | 创建时间 |

- 模型文件：`backend/knowledge/sync_log.py`
- 清理策略：每个 `tenant_id + kb_type` 保留最近 50 条日志。

### 2.5 handoff_tickets — 转人工工单表

AI 转人工时创建的工单。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | String(64) | PK | 工单 ID（UUID） |
| `tenant_id` | String(64) | not null, index | 租户 ID |
| `conversation_id` | String(64) | not null, index | 会话 ID |
| `thread_id` | String(64) | not null | LangGraph 线程 ID |
| `user_id` | String(128) | default "" | 用户 ID |
| `user_name` | String(128) | default "" | 用户名 |
| `reason` | String(32) | not null | 转人工原因 |
| `reason_detail` | Text | default "" | 原因详情 |
| `summary` | Text | default "" | 会话摘要 |
| `status` | String(16) | default "pending", index | 工单状态 |
| `priority` | Integer | default 0 | 优先级 |
| `assigned_to` | String(128) | default "" | 分配坐席 |
| `resolved_at` | DateTime | nullable | 解决时间 |
| `created_at` | DateTime | index | 创建时间 |
| `updated_at` | DateTime | | 更新时间 |

- 模型文件：`backend/models/handoff.py`
- 复合索引：`idx_handoff_tenant_status`（`tenant_id`, `status`）

### 2.6 faqs — FAQ 问答对表

商家 FAQ 知识库的元数据记录（向量数据存储在 ChromaDB）。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | Integer | PK, autoincrement | 主键 |
| `tenant_id` | String(64) | not null, index | 租户 ID |
| `question` | Text | not null | 问题 |
| `answer` | Text | not null | 答案 |
| `category` | String(32) | default "通用" | 分类 |
| `tags` | String(256) | default "" | 标签（逗号分隔） |
| `is_enabled` | Boolean | default True | 是否启用 |
| `chroma_ids` | Text | default "" | ChromaDB 中的向量 ID（逗号分隔） |
| `created_at` | DateTime | | 创建时间 |
| `updated_at` | DateTime | | 更新时间 |

- 模型文件：`backend/models/knowledge.py`

### 2.7 documents — 文档记录表

商家上传文档的元数据记录。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | Integer | PK, autoincrement | 主键 |
| `tenant_id` | String(64) | not null, index | 租户 ID |
| `filename` | String(256) | not null | 文件名 |
| `file_type` | String(16) | not null | 文件类型 |
| `file_size` | Integer | default 0 | 文件大小（字节） |
| `chunk_count` | Integer | default 0 | 分块数 |
| `is_enabled` | Boolean | default True | 是否启用 |
| `chroma_ids` | Text | default "" | ChromaDB 中的向量 ID |
| `created_at` | DateTime | | 创建时间 |

- 模型文件：`backend/models/knowledge.py`

### 2.8 feedbacks — 用户反馈表

用户对会话的满意度评价。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | String(64) | PK | 反馈 ID（UUID） |
| `tenant_id` | String(64) | not null, index | 租户 ID |
| `conversation_id` | String(64) | not null, index | 会话 ID |
| `thread_id` | String(64) | not null | LangGraph 线程 ID |
| `message_id` | String(64) | default "" | 关联消息 ID |
| `rating` | Integer | not null | 评分（1-5 星） |
| `comment` | Text | default "" | 文字反馈 |
| `created_at` | DateTime | index | 创建时间 |

- 模型文件：`backend/models/feedback.py`

### 2.9 tool_call_logs — 工具调用日志表

Agent 节点调用外部工具（业务 API）的日志记录。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | String(64) | PK | 日志 ID（UUID） |
| `conversation_id` | String(64) | index | 会话 ID |
| `tenant_id` | String(64) | not null, index | 租户 ID |
| `tool_name` | String(64) | not null | 工具名称 |
| `tool_params` | JSON | default dict | 调用参数 |
| `tool_result` | JSON | default dict | 返回结果 |
| `success` | Integer | default 0 | 是否成功（0/1） |
| `duration_ms` | Float | default 0.0 | 耗时（毫秒） |
| `error_message` | Text | default "" | 错误信息 |
| `created_at` | DateTime | | 创建时间 |

- 模型文件：`backend/models/conversation.py`

---

## 三、索引说明

### 3.1 模型定义的索引

| 表 | 索引字段 | 类型 | 说明 |
|----|----------|------|------|
| `tenants` | `tenant_id` | unique | 租户业务 ID 唯一索引 |
| `conversations` | `thread_id` | unique | LangGraph 线程 ID 唯一索引 |
| `conversations` | `tenant_id` | normal | 按租户查询会话 |
| `conversations` | `user_id` | normal | 按用户查询会话 |
| `conversations` | `status` | normal | 按状态筛选会话 |
| `conversations` | `created_at` | normal | 按时间排序 |
| `conversations` | `ended_at` | normal | 按结束时间筛选 |
| `messages` | `conversation_id` | normal | 按会话查询消息 |
| `messages` | `created_at` | normal | 按时间排序 |
| `sync_logs` | `tenant_id` | normal | 按租户查询同步日志 |
| `handoff_tickets` | `tenant_id` | normal | 按租户查询工单 |
| `handoff_tickets` | `conversation_id` | normal | 按会话查询工单 |
| `handoff_tickets` | `status` | normal | 按状态筛选工单 |
| `handoff_tickets` | `created_at` | normal | 按时间排序 |
| `faqs` | `tenant_id` | normal | 按租户查询 FAQ |
| `documents` | `tenant_id` | normal | 按租户查询文档 |
| `feedbacks` | `tenant_id` | normal | 按租户查询反馈 |
| `feedbacks` | `conversation_id` | normal | 按会话查询反馈 |
| `feedbacks` | `created_at` | normal | 按时间排序 |
| `tool_call_logs` | `conversation_id` | normal | 按会话查询工具调用 |
| `tool_call_logs` | `tenant_id` | normal | 按租户查询工具调用 |

### 3.2 复合索引

| 表 | 索引名 | 字段 | 说明 |
|----|--------|------|------|
| `handoff_tickets` | `idx_handoff_tenant_status` | `tenant_id`, `status` | 按租户 + 状态组合查询工单 |

### 3.3 索引自动补全

`init_db()` 调用 `_ensure_indexes()` 为旧数据库补全缺失索引（见 `backend/database.py`）：

| 表 | 补全字段 |
|----|----------|
| `conversations` | `created_at`, `ended_at`, `user_id` |
| `messages` | `created_at` |
| `feedbacks` | `created_at` |
| `handoff_tickets` | `created_at` |

补全逻辑：检查现有索引，若字段未被索引则创建 `ix_<table>_<column>` 索引。

---

## 四、备份策略

### 4.1 备份配置

| 项 | 值 |
|----|----|
| 备份模块 | `backend/utils/backup.py` |
| 备份目录 | `data/backups/` |
| 备份文件命名 | `app_YYYYMMDD_HHMMSS.db` |
| 备份间隔 | 3600 秒（1 小时） |
| 每小时备份保留数 | 24 个 |
| 每日快照保留数 | 7 个 |
| 备份方式 | SQLite `backup` API（保证一致性） |

### 4.2 备份保留策略

```
data/backups/
├── app_20260622_080000.db   ← 每小时备份（保留最近 24 个）
├── app_20260622_090000.db
├── app_20260622_100000.db
├── ...
└── app_20260615_000000.db   ← 每日快照（保留最近 7 个）
```

清理逻辑（`_cleanup_old_backups()`）：

1. 按修改时间倒序排列所有备份文件。
2. 保留最新的 24 个作为每小时备份。
3. 从剩余文件中，每天保留第一个作为每日快照。
4. 每日快照最多保留 7 个，超出则删除最早的。
5. 既不在每小时保留也不在每日快照中的备份将被删除。

### 4.3 备份任务管理

| 函数 | 作用 |
|------|------|
| `start_backup_scheduler()` | 启动后台备份任务（FastAPI 启动时调用） |
| `stop_backup_scheduler()` | 停止后台备份任务（FastAPI 关闭时调用） |
| `backup_now()` | 立即执行一次备份（手动触发） |
| `_cleanup_old_backups()` | 清理过期备份（每次备份后自动执行） |

### 4.4 手动备份与恢复

```powershell
# 手动触发一次备份（Python 交互式）
python -c "from backend.utils.backup import backup_now; print(backup_now())"

# 恢复数据库（停止服务后操作）
copy data\backups\app_20260622_080000.db data\app.db
```

> 注意：恢复前必须停止 kefu-agent 服务，避免 WAL 文件冲突。恢复后建议删除 `data/app.db-wal` 和 `data/app.db-shm` 文件。

---

## 五、数据存储位置汇总

| 路径 | 说明 | 配置变量 |
|------|------|----------|
| `data/app.db` | SQLite 主数据库 | `SQLITE_PATH` |
| `data/app.db-wal` | SQLite WAL 日志文件（自动生成） | - |
| `data/app.db-shm` | SQLite 共享内存文件（自动生成） | - |
| `data/chroma_db/` | ChromaDB 向量知识库 | `CHROMA_PATH` |
| `data/checkpoints.db` | LangGraph 对话检查点 | `CHECKPOINT_PATH` |
| `data/backups/` | SQLite 备份目录 | - |

> 备份时建议备份整个 `data/` 目录，以包含数据库、向量库与检查点的完整状态。
