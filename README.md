# 制造业数据中台（后端）

RAG + TextToSQL 后端服务。技术选型与路线图见 [项目选型/](项目选型/)。

## 技术栈
- Python 3.12 + **uv** 包管理
- FastAPI + Uvicorn
- PostgreSQL + PGVector（向量库 + 中台元数据 + 对话）、SQL Server（业务数据只读，TextToSQL 用）
- procrastinate（PostgreSQL 任务队列，异步任务，无需 Redis）
- MinIO（上传原件）
- 文档解析：PyMuPDF(PDF) / python-docx(Word) / openpyxl(Excel)；切割：langchain-text-splitters
- SQL Server 驱动：`pymssql`（业务库是 SQL Server 2008，须 `MSSQL_TDS_VERSION=7.0` 才连得上）
- Embedding：通义 text-embedding-v3（1024 维）
- LLM：通义千问 / DeepSeek（OpenAI 兼容，用户对话中自选）
- LangGraph（多轮工具调用 Agent）

## 快速开始

```bash
# 1. 安装依赖（创建 .venv）
uv sync

# 2. 准备配置
cp .env.example .env   # 填入 PG / MinIO / LLM 密钥

# 3. 启动 API
uv run uvicorn app.main:app --reload

# 4. 数据库迁移（建模型后）
uv run alembic revision --autogenerate -m "init"
uv run alembic upgrade head

# 5. 初始化任务队列表（首次，需 PG 可连）
uv run procrastinate --app=app.workers.queue.app schema --apply

# 6. 启动任务 worker
uv run procrastinate --app=app.workers.queue.app worker

# 运行测试
uv run pytest -q
```

## 运维脚本（日常命令一处管）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops.ps1 <命令>
#   api                      启动 API(开发, 热重载)
#   worker                   启动后台 worker(解析入库)
#   migrate                  数据库迁移到最新
#   makemigration "说明"     生成迁移脚本
#   ingest <文件夹> [类型]   批量入库(类型默认 通用)
#   health                   检查 API + 数据库
```
批量入库脚本：`uv run python scripts/batch_ingest.py <文件夹> --doc-type <类型>`
SQL Server 连通自检（不用启 API）：`uv run python scripts/check_mssql.py` 或 `ops.ps1 mssqlcheck`
登记业务视图到语义层（TextToSQL，填好模板后跑）：`uv run python scripts/register_views.py`

启动后：
- 接口文档 `http://127.0.0.1:8000/docs`
- 健康检查 `http://127.0.0.1:8000/api/v1/health`
- 数据库连通性 `http://127.0.0.1:8000/api/v1/health/db`（PostgreSQL）、`.../health/mssql`（SQL Server，未配则 skipped）
- 可用模型 `http://127.0.0.1:8000/api/v1/meta/models`
- 对话（一次性）`POST http://127.0.0.1:8000/api/v1/chat`，body: `{"message": "...", "model": "qwen-plus"}`；返回 `answer` + `conversation_id` + `sources`(含 MinIO 下载链接)。**会话 ID：不传则服务端新建并在返回里给出（=开新对话）；想接着聊就把上次返回的 `conversation_id` 传回来。`persist=true`（默认）时 `history` 字段被忽略，历史以库为准。**
- 对话（流式 SSE）`POST http://127.0.0.1:8000/api/v1/chat/stream`，同样 body；返回 `text/event-stream`：先 `event: meta`(JSON 带 `conversation_id`)，再逐 token `data:`，然后 `event: sources`(JSON)，末尾 `event: done`
- 文档上传 `POST http://127.0.0.1:8000/api/v1/documents`（multipart）：字段 `file`（文件）+ `doc_type`（类型）+ `biz_tags`（可选 JSON）
- 文档列表 `GET http://127.0.0.1:8000/api/v1/documents`：分页 + 按 `doc_type`/`status`/`only_active` 过滤
- 文档详情/状态 `GET http://127.0.0.1:8000/api/v1/documents/{id}`：轮询入库进度
- 知识库检索 `POST http://127.0.0.1:8000/api/v1/search`，body: `{"query": "...", "top_k": 5, "doc_type": null, "mode": "hybrid"}`（mode: hybrid/vector/keyword）
- 切割配置 `GET/PUT http://127.0.0.1:8000/api/v1/chunk-configs[/{doc_type}]`：每类文档配切割策略(recursive/parent_child)与参数
- 会话历史 `GET http://127.0.0.1:8000/api/v1/conversations`、`GET .../conversations/{id}/messages`：列会话 / 查消息

## 统一错误响应

所有接口出错都返回统一结构（前端按此处理）：

```json
{ "code": "LLM_ERROR", "message": "模型调用失败，请稍后重试", "detail": null }
```

常见 `code`：`VALIDATION_ERROR`(422) / `BAD_REQUEST`(400) / `NOT_FOUND`(404) /
`LLM_ERROR`(502) / `DB_ERROR`(500) / `EXTERNAL_ERROR`(502) / `INTERNAL_ERROR`(500)。
未预期异常只返回笼统提示，完整堆栈记服务端日志、不外泄。

## 目录结构

```
app/
  main.py              FastAPI 入口
  core/                配置、日志、统一异常处理
  db/                  SQLAlchemy 引擎、Base
  models/              ORM 模型（Alembic 识别）
  api/v1/              路由与端点（health / meta / chat / documents）
  services/
    llm/               LLM 接入层（模型路由 + ChatModel 工厂）
    storage/           MinIO 封装
    rag/               RAG：上传校验/入库编排/解析/切割/向量化/检索
    texttosql/         TextToSQL：SQL Server 连接(db.py) + 语义层(semantic_layer.py)
    chat/              会话历史 + 来源整理（sources.py）
    agent/             多轮对话 Agent（工具调用）+ 工具/skill 注册表 + 来源旁路
  workers/             procrastinate 任务队列
alembic/               数据库迁移
tests/                 冒烟测试（health / meta / 错误格式）
```

> 进度：P0–P4（RAG 问答）实质完成——文档入库→混合检索→工具调用 Agent 多轮问答→带来源
> 下载链接，全链路打通。P5 TextToSQL 进行中：SQL Server 已连通、语义层表与登记机制就绪，
> 待 DBA 整理首个业务视图。详见 [项目选型/工作清单.md](项目选型/工作清单.md)。
