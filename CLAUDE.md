# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 这是「制造业数据中台」后端：整合现有 OA/ERP/MES，对外提供两种能力 —— **RAG**（文档知识问答）和 **TextToSQL**（自然语言查业务库）。一期仅限内网、无鉴权。

## 进度真相源（先读这两处）
- **`项目选型/工作清单.md`** 是进度与待办的唯一真相源（含 P0–P9 阶段状态、技术债、待讨论事项）。开工前先读它确认当前位置。
- `项目选型/` 下文档**按主题拆分**：`中台架构.md` / `RAG系统.md` / `TextToSQL.md` 各自独立。改文档时归到对应主题，**不要跨主题混写**。
- 当前位置：**P0–P4（RAG 问答）实质完成**（P4-④ 工具进度流式已决定不做）；**P5 TextToSQL 代码链路全就绪**（A1 连接 / B1 语义层 / B2 拉字段脚手架 / B4 检索 / C1 生成 / D1·D2 护栏执行 / E1 接 Agent 全部完成），但 **A2/B3 视图接入延期**——DBA 整理好视图后照 `TextToSQL.md` 第八节「操作手册」接入即可（语义层空时链路安全短路、不碰生产库）。**P6 Agent 编排调优**：提示词/工具说明/失败兜底/**迭代检索(agentic RAG)** 已打磨、验证通过。**P7 前端管理页进行中**（前端独立仓库 `D:\workSpace\tmbomweb`，已建 5 个管理页）。设计见 `TextToSQL.md` 第七/八节。

## 前端管理页（P7，独立仓库）
- 仓库：**`D:\workSpace\tmbomweb`**（Vue3+Vite+TS+Element Plus；门户挂载式，URL `?token=` 拿 JWT）。本仓库是后端。
- 接我们后端：`.env` 的 `VITE_AI_API`（开发=本机:8000）+ 专用 axios `src/services/requestAI.ts`（**不带 token、适配裸 JSON**，与主后端 `request.ts` 分开）。接口封装在 `DataPlatformService.ts`。
- 已建：文档管理 / 切割配置 / 检索测试 / 智能问答(流式) / 会话历史（`src/views/DataPlatform/`）。
- 坑：流式用 fetch 手解析 SSE，**sse-starlette 是 `\r\n` 分隔**（按 `\r?\n` 解析）；文档类型下拉来自 `GET /meta/doc-types`。
- 改前端**配置**（`.env*`/`env.d.ts`/`vite.config`）须先跟用户确认；纯页面可直接改。

## 常用命令
全部经 uv。日常运维命令统一封装在 `scripts/ops.ps1`（PowerShell，纯英文，避免 cp950 乱码）。

```bash
uv sync                                              # 装依赖（建 .venv）
uv run pytest -q                                     # 跑全部测试
uv run pytest tests/test_health.py::test_xxx -q      # 跑单个测试
uv run ruff check .                                  # lint（select = E,F,I,W,UP）
uv run ruff format .                                 # 格式化（line-length 100）
uv run uvicorn app.main:app --reload                 # 启 API（开发）
```

```powershell
# 运维脚本（推荐入口）
scripts\ops.ps1 api          # 启 API
scripts\ops.ps1 worker       # 启后台 worker（另开终端；上传解析入库靠它）
scripts\ops.ps1 migrate      # alembic upgrade head
scripts\ops.ps1 makemigration "说明"   # 生成迁移脚本
scripts\ops.ps1 ingest <文件夹> [类型]  # 批量入库（直接入库，不经队列/不需 worker）
scripts\ops.ps1 health       # 自检 API + DB（PostgreSQL + SQL Server）
scripts\ops.ps1 mssqlcheck   # 单独测 SQL Server 连通（不用启 API）
scripts\ops.ps1 scaffold <视图名>  # 拉视图/表字段 → 生成可粘进 register_views.py 的配置（B2）
```

- 首次建队列表（一次性）：`uv run procrastinate --app=app.workers.queue.app schema --apply`
- 批量入库脚本也可直接调：`uv run python scripts/batch_ingest.py <文件夹> --doc-type <类型>`（默认类型「通用」）
- 应用日志落 `logs/api.log` / `logs/worker.log`（轮转 10MB×5，已 gitignore）。

## 架构要点（跨文件才看得懂的部分）

**请求链路（RAG 问答）**：`api/v1/endpoints/chat.py` → `services/agent/agent.py`（LangGraph 工具调用 Agent）→ Agent 自行决定调 `services/agent/tools.py` 里的工具 → `search_knowledge_base` 走 `services/rag/retrieval.py` 的 `hybrid_search` → 答案 + 来源返回。Agent **不是写死流程**，是模型自己决定调哪个工具、调几次。

**Agent 无状态 + 自管会话（记忆"方案 B"）**：`get_agent()` 用 `lru_cache` 按模型缓存编译好的图，所有请求安全复用。多轮上下文不靠框架 checkpointer，而是每次请求把「该会话历史 + 本轮消息」整列表喂进去（`_build_messages`）。历史来源两端：网页端服务端从 `conversations`/`messages` 表取（`services/chat/history.py`，`persist=True`），桌面端由客户端带 `history` 上来。

**来源采集靠 ContextVar**：工具函数只能返回字符串，无法顺带返回结构化来源。所以检索时用 `services/agent/context.py` 的 ContextVar（`begin_capture`/`record_sources`/`get_captured`）把命中的文档「旁路」记录下来，端点再据此拼 `sources`。改动检索/工具时要保持这条旁路链路。

**混合检索（retrieval.py）**：向量（通义 embedding 1024 维，pgvector `cosine_distance` + HNSW）+ 关键词（jieba 切词 → PG `simple` tsvector 生成列 + GIN，BM25 风格）→ **RRF 融合**（只看排名，规避量纲不同）→ `_dedupe_by_content`（父子切割时同一父块被多块命中要去重）→ 可选 rerank 精排。**rerank 失败必须回退到融合结果**，不能让检索整体挂掉。

**入库链路（异步）**：上传 → 存 MinIO → 登记 documents 行 → 投 procrastinate 任务 → worker 解析/切割/向量化/入库。切割策略**按 doc_type 存 `chunk_configs` 表**（recursive / parent_child），不在 .env；改了配置要对该类文档重新入库才生效。`ingest()` 是可重入的（重跑会先删旧 chunk）。

## 关键约定与坑（务必遵守）

- **Windows 事件循环**：`app/core/eventloop.py` 必须被 `main.py` 和 `workers/queue.py` **最先 import**——它把策略切成 `SelectorEventLoop`，否则 psycopg 异步会崩（默认 ProactorEventLoop 不兼容）。新增进程入口同样要先 import 它。
- **Alembic 别删队列表**：procrastinate 的表也在同一个 PG 库里但不在 ORM 模型中。`alembic/env.py` 有 `include_name` 过滤只比对 `target_metadata` 里的表——**不要移除这个过滤**，否则 autogenerate 会生成 DROP procrastinate_* 的迁移。
- **PostgreSQL 三种连接串**：`config.py` 里 `pg_dsn`（SQLAlchemy 异步，`+psycopg`）、`pg_dsn_sync`（Alembic）、`pg_conninfo`（procrastinate，原生无前缀）。给不同工具用不同串，别混。
- **业务库 SQL Server 是另一套**（TextToSQL 用）：`pymssql` 连，配置 `mssql_*`，连接逻辑在 `services/texttosql/db.py`。**它是只读生产库 `ICAS_FPC`（192.168.20.6），绝不往里写、不建对象、不跑重查询**；不归 Alembic 管（Alembic 只管我们自己的 PG）。SQL Server 2008 必须 `MSSQL_TDS_VERSION=7.0` 才连得上（新协议跟老库 TLS 握手失败），代价是 `date`/`datetime2` 读成字符串（值正确，够用）。
- **新建 ORM 模型**：必须在 `app/models/__init__.py` 里 import，Alembic 才扫得到。
- **MinIO 下载链接不存库**：预签名 URL 限时 1 小时，**用时现签**（`storage/minio_client.py` 的 `presigned_get_url`），绝不把 URL 写进数据库（会过期）。
- **上传白名单**：只收 `pdf,docx,xlsx,txt,md`。老二进制 `.doc/.xls/.wps` 解析不了，已排除——遇到要先转 docx 再入库。
- **PowerShell + 中文**：`.ps1` / `.ini`（如 `alembic.ini`）保持纯英文，PowerShell 5.1 以 cp950 读 UTF-8 中文会乱码。
- **密钥只在 `.env`**（不进 git），`.env.example` 用占位符。真实 PG/MinIO/通义/DeepSeek 密钥在本机 `.env`。

## 代码规范

把这个项目当**长期维护的工程**来写。核心原则：**不过度设计，但要想清楚再写**——不为「将来可能用到」加抽象层，也不为图省事写出看不懂、难维护的代码。

- **类型标注是硬要求**：所有函数的参数和返回值都写类型（`-> str`、`-> list[dict]`、`-> None`）。用 3.12 原生写法：`str | None` 而非 `Optional[str]`，`list[dict]` 而非 `List[Dict]`。对外/对内的数据结构用 Pydantic `BaseModel`（见 `chat.py` 里的 `ChatRequest`/`SourceOut`），字段配 `Field(..., description=...)`，别用裸 dict 当接口契约。
- **不要过度简化**：宁可多写几行让逻辑清楚，也不要把三件事压成一行炫技。命名用完整词（`keyword_search` 不是 `kws`）。能拆出一个有名字的小函数（如 `_rrf_fuse`、`_dedupe_by_content`、`_build_messages`）就拆，让主流程读起来像目录。
- **私有辅助函数加 `_` 前缀**，跟模块内已有写法一致。
- **错误处理要明确**：业务错误抛 `app/core/exceptions.py` 里的具体异常（`BadRequestError`/`NotFoundError`/`LLMError`…），不要裸 `raise Exception`。可选增强（rerank、队列连接）失败要**有回退**、不能拖垮主流程（见 `hybrid_search` 的 try/except 回退、`main.py` 的队列容错）。
- **资源务必释放**：外部连接/句柄用 `try/finally` 或 `with` 关掉（见 `ingest._download` 关闭 MinIO 连接）。
- **改动前先看周围代码**：匹配已有的导入顺序、命名、分层（端点只做编排和出入参，业务逻辑下沉到 `services/`）。新增依赖走 `uv add`，不手改 pyproject。
- **提交前**：`uv run ruff check .` 和 `uv run pytest -q` 都要过。

## 注释规范（详细解释型）

本项目注释统一用「详细解释型」——面向**看不懂的人**，讲清「这是什么 + 为什么这么做」，不是复述代码字面。下面是必须遵守的几条，照着现有文件（`config.py`、`retrieval.py`、`ingest.py`）的风格写。

- **每个模块开头写 docstring**：一句话说清这个文件是干嘛的；如果有多个对外函数或非显而易见的流程，列出来（见 `retrieval.py` 顶部列出三种检索、`ingest.py` 列出完整步骤）。
- **每个函数写 docstring**：说清它做什么；参数里有「不看说明猜不到」的（如 `doc_type` 只搜某类、`persist` 决定走不走库），逐个解释。
- **解释「为什么」，不复述「是什么」**：`x += 1  # x 加一` 这种禁止。要写就写 `# 每路多取一些候选，融合/精排才有得挑，最后再截到 top_k` 这种——讲清意图。
- **复杂或不常用的东西必须讲清作用**，不管是自己的还是第三方库的：
  - 算法/非直觉逻辑：如 RRF 融合为什么用倒数排名、父子切割为什么要去重——讲清原理和动机。
  - 第三方库里不常见的类/方法/参数：写明它是什么、为什么用它。例如 `cosine_distance`（越小越相近、会用上 HNSW 索引）、`func.to_tsquery("simple", ...)`（PG 全文检索、simple 配置不做词干）、`run_in_threadpool`（把同步阻塞调用挪到线程池别堵事件循环）、`server_default=func.now()`（默认值由数据库生成而非 Python 端）。读代码的人不一定熟这些，点一句省他半小时。
  - 踩过的坑/平台相关：直接在代码旁写明原因（如 `eventloop.py` 为什么要切 SelectorEventLoop、`env_file_encoding="utf-8"` 为什么必须指定）。
- **语言**：注释和 docstring 用中文（与现有代码一致）。
- **别写废话注释**：跟代码重复、或过时会误导的注释，不如不写。注释跟着代码一起改，不要留下骗人的旧注释。

> 一句话标准：一个**不熟这块业务、也不熟这些库**的同事，只看你的注释能不能明白「这在干嘛、为什么这么干」。能，就合格。

## 模型与外部服务
- LLM：通义千问 / DeepSeek，均走 OpenAI 兼容接口（`services/llm/client.py` 按模型路由）；用户对话时自选模型，端点用白名单校验非法模型名返回 400。
- **可选模型来自 `.env` 白名单**（`QWEN_MODELS` / `DEEPSEEK_MODELS`，逗号分隔），不写死在代码：厂商 `/models` 会返回上百个混杂模型（图像/语音/第三方），由运维挑出要用的几个填配置。`MODEL_REGISTRY` 按这两个列表动态构建（模型→厂商路由也据此）。当前：`qwen3.7-max` / `qwen3.7-plus` / `deepseek-v4-pro`（默认 `qwen3.7-plus`）。`/meta/models` 返回该清单。
- **文档类型也是 `.env` 受控词表**（`DOC_TYPES`，逗号分隔），`GET /meta/doc-types` 返回，给前端上传/筛选下拉。加减类型改 `.env`、不动代码。
- **Agent 迭代检索**：系统提示词要求知识类问题每轮重新检索、且结果不全就换关键词再查（agentic RAG），LangGraph 工具循环天然支持多轮。
- **文档列表过滤**：`GET /documents` 支持 `doc_type`/`status`/`only_active`/`name`(文件名模糊)/`created_from`·`created_to`(时间范围)。
- rerank 是通义 gte-rerank-v2，走 DashScope **原生** HTTP（非 OpenAI 兼容），默认关（`RERANK_ENABLED`）。
- 业务库（TextToSQL，P5）：SQL Server 2008 只读生产库，已连通（`mssql_*` 已启用，`pymssql` + TDS 7.0）。语义层存我们自己的 PG（`schema_docs` 表，`services/texttosql/semantic_layer.py`），视图整理好用 `scripts/register_views.py` 登记。

## TextToSQL（P5）要点
- **方针**：不喂整库给模型；建一层"业务视图"，把它们的中文说明存进 `schema_docs` 并向量化，提问时先检索相关视图再让模型写 SQL。准确率靠"视图建得好 + 检索找得准 + 样例给得对"。详见 `TextToSQL.md` 第七节。
- **两类数据源**（`schema_docs.source_type`）：`view`（DBA 整理好的 `v_ai_` 宽视图，首选）/ `table`（建不了视图的裸表，文字描述 + 显式 JOIN 关系兜底）。
- **大数据量护栏**：业务表常千万级，必带过滤（没带自动注入默认时间窗）、一视图只挂一张大表、聚合走预聚合表（建在我们 PG，不压生产）。
- **会话来源（P4 修复）**：知识类问题每轮强制重新检索（系统提示词）；来源随消息存 `messages.sources`（只存 id+名，链接用时现签）；`conversation_id` 不传则服务端生成新会话并返回（不再有共享的 "default"）。
