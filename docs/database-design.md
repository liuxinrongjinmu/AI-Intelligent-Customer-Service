# 数据库设计文档

> 本文档说明 kefu-agent 的 PostgreSQL 数据库结构、索引设计与备份策略。
>
> 相关代码：
> - 数据库引擎：`backend/database.py`
> - 配置项：`backend/config.py`（`DATABASE_URL`）
> - 数据模型：`backend/models/`
> - 同步日志模型：`backend/knowledge/sync_log.py`
> - 备份模块：`backend/utils/backup.py`
> - 迁移工具：`alembic/`

---

## 一、数据库概述

| 项 | 值 |
|----|----|
| 数据库类型 | PostgreSQL 16 |
| 连接串配置 | `DATABASE_URL`（必填，如 `postgresql://kefu:kefu_pwd@postgres:5432/kefu_agent`） |
| ORM 框架 | SQLAlchemy 2.0（DeclarativeBase） |
| 连接池 | QueuePool（pool_size=10，max_overflow=20，pool_recycle=1800s，pool_timeout=30s，pool_pre_ping=True） |
| 引擎初始化 | 延迟初始化（`_init_engine()` 首次访问时创建，避免测试环境 import 报错） |
| Schema 管理 | Alembic 迁移（`alembic/versions/`） + `init_db()`首次启动建表 + `_ensure_indexes()` 补全索引 |
| 向后兼容 | `SessionLocal`/`engine` 通过模块 `__getattr__` 支持旧 import 路径 |

---

## 二、表结构

数据库共 9 张表，均通过 SQLAlchemy 模型定义，由 `init_db()` 自动创建。

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
| `ai_failed_count` | Integer | default 0 | AI 失败次数（连续超阈值转人工） |
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
| `sync_type` | String(32) | not null | 同步类型（full/incremental/batch/clear/rollback） |
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

`init_db()` 调用 `_ensure_indexes()` 为已有表补全缺失索引（使用 PostgreSQL `CREATE INDEX IF NOT EXISTS`）：

| 表 | 补全字段 |
|----|----------|
| `conversations` | `created_at`, `ended_at`, `user_id` |
| `messages` | `created_at` |
| `handoff_tickets` | `created_at` |

---

## 四、备份策略

### 4.1 备份配置

| 项 | 值 |
|----|----|
| 备份模块 | `backend/utils/backup.py` |
| 备份命令 | `docker exec kefu-postgres pg_dump -U kefu kefu_agent` |
| 备份目录 | `data/` |
| 备份文件命名 | `pg_backup_YYYYMMDD_HHMMSS.sql` |
| 备份间隔 | 3600 秒（1 小时） |
| 每小时备份保留数 | 24 个（1 天） |
| 每日快照保留数 | 7 个（1 周） |
| 过期清理 | `find data/ -name 'pg_backup_*.sql' -mtime +7 -delete` |

### 4.2 备份流程

1. **启动备份**：`backup_now()` 在 FastAPI lifespan 启动时立即执行一次备份。
2. **定时备份**：`start_backup_scheduler()` 启动后台任务，每小时执行 `pg_dump`。
3. **部署前备份**：`deploy.py` 在 `docker compose down` 前执行 `pg_dump` 备份。
4. **过期清理**：每次备份后清理超过 7 天的旧备份文件。

### 4.3 备份任务管理

| 函数 | 作用 |
|------|------|
| `start_backup_scheduler()` | 启动后台备份任务（FastAPI 启动时调用） |
| `stop_backup_scheduler()` | 停止后台备份任务（FastAPI 关闭时调用） |
| `backup_now()` | 立即执行一次 `pg_dump` 备份 |
| `_cleanup_old_backups()` | 清理过期备份（保留 24 个每小时 + 7 个每日） |

### 4.4 手动恢复

```bash
# 登录到部署服务器
ssh deploy@192.168.0.234

# 恢复 PostgreSQL 数据库
cd /home/deploy/kefu_agent
docker exec -i kefu-postgres psql -U kefu kefu_agent < data/pg_backup_20260629_120000.sql

# 重启服务
docker compose restart kefu-agent
```

> 注意：恢复前建议先对当前数据库做一次备份。恢复后需重启 kefu-agent 以重建连接池。

---

## 五、数据存储位置汇总

| 路径 | 说明 | 配置变量 |
|------|------|----------|
| PostgreSQL 数据库 | 主业务数据库（Docker 容器 `kefu-postgres`） | `DATABASE_URL` |
| `data/chroma_db/` | ChromaDB 向量知识库（租户级 Collection 隔离） | `CHROMA_PATH` |
| `data/pg_backup_*.sql` | PostgreSQL 备份文件 | - |
| `alembic/versions/` | Schema 迁移脚本 | - |

> LangGraph Checkpoint 数据直接存储在 PostgreSQL 中（`langgraph-checkpoint-postgres`），无需额外文件。
