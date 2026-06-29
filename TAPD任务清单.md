# 聚宝赞AI智能客服Agent — TAPD任务清单

> 覆盖周期：2026年6月（22个工作日） | 总预计工时：266h（部分任务可并行，实际日历天数22天）

---

## 第一阶段：项目初始化与环境搭建（6月1日-3日，3天）

### T1.1 项目脚手架搭建
- **详细描述**：初始化Python项目结构（backend/frontend/tests/docs目录），配置git仓库和.gitignore，创建虚拟环境，安装FastAPI/LangChain/LangGraph等核心依赖，编写requirements.txt和requirements-dev.txt
- **预计开始**：6月1日
- **预计结束**：6月1日
- **预计工时**：4h

### T1.2 Docker开发环境搭建
- **详细描述**：编写Dockerfile（多阶段构建，CPU-only PyTorch）、docker-compose.yml（kefu-agent/PostgreSQL/Redis/Prometheus/Grafana 5个服务）、docker-entrypoint.sh（gosu权限降级）、.dockerignore，验证容器启动和健康检查
- **预计开始**：6月1日
- **预计结束**：6月2日
- **预计工时**：6h

### T1.3 配置管理体系搭建
- **详细描述**：基于Pydantic Settings实现类型安全的Settings类（80+配置项），支持.env文件加载和环境变量覆盖，实现validate_config()启动校验函数（必填项/弱凭证/安全配置检查），区分dev/test/prod三套环境配置（.env.dev/.env.prod/.env.example），配置模块级变量重导出保持向后兼容
- **预计开始**：6月2日
- **预计结束**：6月3日
- **预计工时**：6h

### T1.4 数据库设计与ORM建模
- **详细描述**：设计9张核心表（tenants/conversations/messages/sync_logs/handoff_tickets/faqs/documents/feedbacks/tool_call_logs），编写SQLAlchemy ORM模型和索引策略，实现延迟初始化引擎（连接池pool_size=10/max_overflow=20/pool_recycle=1800），get_db依赖注入，init_db自动建表和补全索引，编写database-design.md文档
- **预计开始**：6月2日
- **预计结束**：6月3日
- **预计工时**：8h

---

## 第二阶段：AI Agent核心引擎（6月4日-9日，5天）

### T2.1 LLM调用封装与容错
- **详细描述**：实现safe_llm_invoke/safe_llm_stream函数（含指数退避重试max_retries=3），get_classify_llm/get_generate_llm模型工厂（temperature区分0.0/0.7），Token预算管理系统（按context/history/knowledge/response分区控制），消息裁剪（trim_messages保留system prompt），JSON输出解析容错（robust_json_parse处理尾部逗号/单引号/markdown代码块/嵌套对象）
- **预计开始**：6月4日
- **预计结束**：6月5日
- **预计工时**：10h

### T2.2 意图分类体系设计
- **详细描述**：设计10大类50+子类的两层意图层级INTENT_HIERARCHY（human_service/order_query/logistics_query/product_query/coupon_query/account_query/knowledge_query/complaint/greeting/feedback/other），编写CLASSIFY_SYSTEM_PROMPT动态生成函数_build_intent_prompt()，实现指代消解+意图分类双阶段classify_intent_node，intent_entities实体提取（order_no/phone/product_name/product_id等10+字段），子类标准化映射_SUB_TYPE_NORMALIZE，意图缓存（LRU+TTL，仅首条消息生效），连续失败自动转人工检测（ai_failed_count>=2）
- **预计开始**：6月5日
- **预计结束**：6月7日
- **预计工时**：14h

### T2.3 LangGraph状态图构建
- **详细描述**：定义AgentState TypedDict（18个字段含messages/tenant_id/intent/entities/retrieved_docs/final_answer等），构建StateGraph拓扑（START→classify→route→8个domain节点→END），实现route_by_intent条件路由（11条分支映射），AsyncPostgresSaver持久化checkpoint（服务重启不丢失对话），get_agent单例+asyncio.Lock防竞态，close_agent资源清理
- **预计开始**：6月7日
- **预计结束**：6月8日
- **预计工时**：8h

### T2.4 RAG知识检索系统
- **详细描述**：实现ChromaDB向量存储（租户隔离Collection），sentence-transformers embedding模型加载（BAAI/bge-small-zh-v1.5，HF镜像加速，LRU缓存1000条），混合检索hybrid_search（向量检索+关键词检索+RRF融合），检索参数配置（top_k=5/threshold=0.2），关键词提权keyword_boost，Embedding专用线程池（2线程隔离CPU密集型推理）
- **预计开始**：6月8日
- **预计结束**：6月9日
- **预计工时**：10h

### T2.5 回答生成与降级策略
- **详细描述**：实现generate_answer_node（知识库RAG回答）和greeting_answer_node（问候/闲聊/反馈），6大类兜底话术体系FALLBACK_RESPONSES（工具失败/AI无法理解/安全/功能限制/情绪安抚/系统异常），答案缓存（LRU+TTL min_length>10），clean_answer输出清洗（移除引用标记/信息来源声明），sanitize_output安全过滤（系统提示词泄露检测），safe_llm_stream流式输出
- **预计开始**：6月9日
- **预计结束**：6月9日
- **预计工时**：8h

---

## 第三阶段：业务域服务对接（6月10日-13日，4天）

### T3.1 订单查询域
- **详细描述**：实现order_query_node（处理order_query和logistics_query），query_order调用聚宝赞order-details API（POST /api/v1/ext-merchant/order-details），format_order_result格式化为可读文本（订单号/商品/金额/状态/收货人/子订单/手机号脱敏），_map_order_status状态映射（11个状态码含中文标签优先），适配嵌套fullOrderInfo响应结构，logistics_query联动查询物流
- **预计开始**：6月10日
- **预计结束**：6月11日
- **预计工时**：10h

### T3.2 商品查询域
- **详细描述**：实现product_query_node（优先API查询，失败降级知识库检索），query_product支持精确查询（product-details按ID）和模糊搜索（product-search按关键词），format_product_result格式化（商品名/价格/原价/库存/状态/图片/供应商），适配productList响应字段，商品搜索关键词提取优化（search_query首词拆分），规格SKU列表展示
- **预计开始**：6月11日
- **预计结束**：6月12日
- **预计工时**：8h

### T3.3 优惠券/账户/投诉/转人工域
- **详细描述**：实现coupon_query_node（调用coupon-list API查询可用优惠券/使用规则），account_query_node（调用user-profile API查询会员等级/积分余额/地址管理），complaint_node（投诉安抚+自动转人工），human_service_node（5种转人工场景：用户请求/投诉/情绪不满/敏感操作/AI失败），call_and_log工具调用日志记录（审计+性能分析）
- **预计开始**：6月12日
- **预计结束**：6月13日
- **预计工时**：10h

### T3.4 Nacos服务发现集成
- **详细描述**：实现Nacos客户端封装nacos_client（服务发现+HTTP请求代理+断路器保护），ServiceDiscovery类（实例缓存30s TTL+轮询负载均衡），服务注册registry（启动注册+15s心跳循环+关闭注销），服务发现discovery（get_base_url获取健康实例），nacos_request统一请求入口（重试下一个实例+缓存失效），环境区分（生产环境注册失败拒绝启动）
- **预计开始**：6月13日
- **预计结束**：6月13日
- **预计工时**：8h

---

## 第四阶段：API层与安全（6月14日-17日，3天）

### T4.1 消费者聊天API
- **详细描述**：实现POST /api/v1/chat/{tenant_id}/stream（SSE流式对话，双模式stream_mode=["updates","messages"]，120s总超时，用户消息+AI回复原子持久化），POST /api/v1/chat/{tenant_id}/new（创建会话返回thread_id），GET /api/v1/chat/{tenant_id}/history/{session_id}（历史消息查询含user_id归属校验），_locate_or_create_session会话定位（跨租户访问拦截），消息校验validate_message（长度/注入/敏感词）
- **预计开始**：6月14日
- **预计结束**：6月15日
- **预计工时**：12h

### T4.2 Gateway认证与安全
- **详细描述**：实现双模式认证verify_request（JWT HS256验签+Static Token+IP白名单，支持jwt/static/both三种模式），JWT密钥优先级加载（Nacos>环境变量>开发默认），IP白名单CIDR解析+线程安全懒加载，extract_identity从Gateway Header提取身份（X-Tenant-Id/X-Buyer-Id/X-Username），verify_chat_api_key管理接口认证，verify_gateway_request向后兼容别名
- **预计开始**：6月15日
- **预计结束**：6月16日
- **预计工时**：10h

### T4.3 安全防护体系
- **详细描述**：实现validate_message多维度校验（空消息/超长/注入检测/敏感内容），detect_injection注入检测（10+中英文SQL/Shell/Prompt注入模式），check_sensitive_content敏感词过滤（手机号/身份证/银行卡+零宽字符防御），sanitize_output输出过滤（系统提示词泄露+Unicode归一化），_normalize_unicode全角字符NFKC规范化，_strip_zero_width零宽字符移除
- **预计开始**：6月16日
- **预计结束**：6月16日
- **预计工时**：8h

### T4.4 中间件体系
- **详细描述**：实现RequestIDMiddleware（X-Request-ID注入+ContextVar链路追踪），MetricsMiddleware（HTTP请求计数/延迟P50-P99/活跃连接数），BodySizeLimitMiddleware（双重防护：Content-Length头快速拦截+流式读取累计检查，默认10MB可配置），RateLimitMiddleware（Redis滑动窗口，默认120req/min聊天60req/min），CORS中间件配置，全局异常处理（RequestValidationError 422 + Exception 500统一格式）
- **预计开始**：6月17日
- **预计结束**：6月17日
- **预计工时**：8h

---

## 第五阶段：知识库管理（6月18日-19日，2天）

### T5.1 文档加载与分割
- **详细描述**：实现知识文档加载器（支持PDF/Markdown），文本分割器（chunk_size=800/chunk_overlap=100可配置），文档批量embedding（embed_documents_async专用线程池），FAQ问答对CRUD管理，知识库类型分类（faq/product/rule三类隔离），ChromaDB Collection管理（租户级UUID隔离，多线程写入）
- **预计开始**：6月18日
- **预计结束**：6月18日
- **预计工时**：8h

### T5.2 知识同步服务
- **详细描述**：实现process_sync增量/全量同步（单批最大1000条可配置），process_batch批量处理，sync_log同步日志+快照（支持回滚），sync_faq_to_chromadb FAQ同步，sync_document_to_chromadb文档同步，remove操作支持，snapshot快照截断保护，Alembic数据库迁移管理（initial_schema含全部9张表）
- **预计开始**：6月18日
- **预计结束**：6月19日
- **预计工时**：8h

### T5.3 知识管理API
- **详细描述**：实现GET/POST/PUT/DELETE /api/v1/knowledge（知识库CRUD），POST /api/v1/knowledge/sync（触发同步），GET /api/v1/knowledge/sync-logs（同步日志查询），FAQ管理端点（创建/更新/删除/批量导入），文档管理端点（上传/分块/索引/删除），多租户数据隔离校验
- **预计开始**：6月19日
- **预计结束**：6月19日
- **预计工时**：8h

---

## 第六阶段：前端聊天界面（6月20日-21日，2天）

### T6.1 聊天页面模板与样式
- **详细描述**：编写Jinja2模板base.html（CSP安全头+基础布局）+ consumer/chat.html（聊天容器/导航栏/AI标识/输入区/快捷提问），设计CSS自定义属性主题色系（chat.css消息气泡316行 + style.css全局样式356行），AI/用户双色气泡，打字指示器动画，快捷问题按钮，重试按钮，移动端响应式适配（768px断点）
- **预计开始**：6月20日
- **预计结束**：6月20日
- **预计工时**：8h

### T6.2 聊天交互JS
- **详细描述**：实现SSE ReadableStream流式接收（fetch+AbortController），session_id localStorage管理（隐私模式降级），消息气泡动态创建（用户/AI双角色），流式文本增量渲染，status状态映射显示（classify/retrieve/generate/order等8种），done事件处理+session_id持久化，retry重试按钮（失败消息重新发送），新会话/快捷提问按钮，超时处理（AbortError友好提示）
- **预计开始**：6月20日
- **预计结束**：6月21日
- **预计工时**：10h

---

## 第七阶段：监控运维（6月22日-23日，1.5天）

### T7.1 Prometheus指标采集
- **详细描述**：实现7个核心指标（kefu_uptime_seconds/kefu_active_requests/kefu_requests_total/kefu_request_latency_ms/kefu_chat_messages_total/kefu_llm_calls_total/kefu_errors_total），mark_request_start/record_request/increment_active/decrement_active采集函数，record_chat_message/record_cache/record_retrieval/record_error业务指标，record_request_timing分意图耗时统计
- **预计开始**：6月22日
- **预计结束**：6月22日
- **预计工时**：6h

### T7.2 Grafana仪表盘与告警
- **详细描述**：编写kefu-agent.json仪表盘（10面板：服务状态/uptime/活跃请求/消息总量/错误总量/QPS曲线/延迟P50-P95-P99/LLM调用分布/错误分类饼图/HTTP状态码分布），配置Prometheus数据源+自动provisioning，编写7条告警规则（ServiceDown critical-1m/HighErrorRate critical-2m-5%/LLMCallsFailed critical-1m/HighLatency warning-5m-P99-5s/HighActiveRequests warning-3m-50/ChatMessageSpike warning-5m-500/HighHandoffRate warning-10m-30%）
- **预计开始**：6月22日
- **预计结束**：6月23日
- **预计工时**：6h

### T7.3 日志与备份系统
- **详细描述**：实现JSON格式结构化日志（生产环境）+文本格式（开发环境），sensitive_filter敏感信息脱敏（手机号/身份证/银行卡/API Key），request_id链路追踪注入，数据库自动备份（每小时+每日快照，保留24个每小时+7个每日），backup_now启动时立即备份，start_backup_scheduler定时调度，过期备份自动清理
- **预计开始**：6月23日
- **预计结束**：6月23日
- **预计工时**：6h

---

## 第八阶段：测试体系（6月24日-27日，3天）

### T8.1 单元测试框架搭建
- **详细描述**：编写conftest.py测试fixture（DB会话/mock LLM/测试租户），test_agent_nodes.py（safe_llm_invoke重试+route_by_intent 12条映射+INTENT_HIERARCHY完整性+fallback节点），test_core_modules.py（认证/token估算/消息裁剪/LRU缓存/意图缓存/敏感过滤），test_security.py（注入检测10+模式+敏感词+输出清洗+Unicode绕过），test_services.py（订单格式化8种状态+工单创建/解决）
- **预计开始**：6月24日
- **预计结束**：6月25日
- **预计工时**：10h

### T8.2 API与集成测试
- **详细描述**：编写test_api_chat.py（SSE流式/会话创建/历史查询/租户校验/参数验证），test_api_knowledge.py（CRUD/同步/搜索），test_api_stats.py（统计查询），test_api_tenant.py（租户管理），test_full_pipeline.py（6大场景：知识同步/多租户隔离/消费者对话11子测试/知识更新/会话安全/认证），test_e2e.py（11种意图参数化端到端），test_gateway_auth.py（JWT/Static/IP白名单）
- **预计开始**：6月25日
- **预计结束**：6月26日
- **预计工时**：10h

### T8.3 评估体系与CI/CD
- **详细描述**：编写eval_intent.py（46个测试用例13个类别，准确率统计），eval_retrieval.py（Hit Rate/MRR/Precision@K计算），eval_report.py（15个综合测试5个类别，意图准确率+响应时间+答案质量+错误率+综合评分），CI/CD流水线（GitHub Actions 3 job：test ruff+mypy+pytest-70%→build docker→deploy 条件部署），pre-commit配置
- **预计开始**：6月26日
- **预计结束**：6月27日
- **预计工时**：10h

---

## 第九阶段：联调与文档（6月28日-30日，2天）

### T9.1 联调测试与问题修复
- **详细描述**：部署到测试服务器（192.168.0.234:8720），验证Nacos服务发现（tenant-service:8131），修复MERCHANT_SERVICE_NAME默认值配置错误，刷新OAuth平台Token（auth_status=VALID），修复order-details嵌套fullOrderInfo响应适配，修复product-search API参数名（productName→keyword），状态码映射补充（WAIT_SELLER_SEND_GOODS等），商品搜索LLM实体提取优化
- **预计开始**：6月28日
- **预计结束**：6月29日
- **预计工时**：12h

### T9.2 项目文档编写
- **详细描述**：编写README.md（701行，功能概述/架构图/快速开始/配置说明/API文档），部署文档.md（805行，Docker部署/SSH远程部署/deploy.py使用说明），接口对接方案.md（1452行，聚宝赞API字段映射/调用链路/参数说明），方案实施文档.md（1097行，技术选型/实施计划/里程碑），项目需求说明文档.md（需求背景/功能清单），CHANGELOG.md版本记录，database-design.md数据库设计，monitoring.md监控运维文档
- **预计开始**：6月29日
- **预计结束**：6月30日
- **预计工时**：10h

### T9.3 部署工具与发布
- **详细描述**：编写deploy.py远程部署脚本（SSH密钥/密码双模式，git pull+pg_dump备份+docker compose down+docker compose up -d --build+健康检查3次重试+回滚机制），chat.py本地CLI测试工具（支持--tenant参数），seed.py测试数据初始化，docker-compose.prod.yml生产环境overlay（外部网络+移除redis依赖）
- **预计开始**：6月30日
- **预计结束**：6月30日
- **预计工时**：6h

---

## 📊 工时汇总

| 阶段 | 内容 | 工时 |
|------|------|------|
| 第一阶段 | 项目初始化与环境搭建 | 24h |
| 第二阶段 | AI Agent核心引擎 | 50h |
| 第三阶段 | 业务域服务对接 | 36h |
| 第四阶段 | API层与安全 | 38h |
| 第五阶段 | 知识库管理 | 24h |
| 第六阶段 | 前端聊天界面 | 18h |
| 第七阶段 | 监控运维 | 18h |
| 第八阶段 | 测试体系 | 30h |
| 第九阶段 | 联调与文档 | 28h |
| **合计** | **9阶段 30个任务** | **266h≈33人天** |

---

## 📅 甘特图概要

```
6/1  ████ 项目初始化+环境搭建
6/4  ██████████ AI Agent核心引擎（LLM+意图+Graph+RAG）
6/10 ████████ 业务域服务对接（订单+商品+优惠券+Nacos）
6/14 ████████ API层与安全（Chat+Gateway+中间件）
6/18 █████ 知识库管理
6/20 ████ 前端聊天界面
6/22 ████ 监控运维
6/24 ██████ 测试体系
6/28 ██████ 联调+文档+发布
6/30 ✅ v1.0发布
```

---

> 注：工时按8h/天计算，含编码+自测+Code Review。实际执行中部分任务可并行。
