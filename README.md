# 制造业数据中台（后端）

RAG + TextToSQL 后端服务。技术选型与路线图见 [项目选型/](项目选型/)。

## 技术栈
- Python 3.12 + **uv** 包管理
- FastAPI + Uvicorn
- PostgreSQL + PGVector（向量库 + 元数据）、SQL Server（业务数据只读，TextToSQL 用）
- procrastinate（PostgreSQL 任务队列，异步任务，无需 Redis）
- MinIO（上传原件）
- 文档解析：PyMuPDF(PDF) / python-docx(Word) / openpyxl(Excel)；切割：langchain-text-splitters
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

启动后：
- 接口文档 `http://127.0.0.1:8000/docs`
- 健康检查 `http://127.0.0.1:8000/api/v1/health`
- 数据库连通性 `http://127.0.0.1:8000/api/v1/health/db`
- 可用模型 `http://127.0.0.1:8000/api/v1/meta/models`
- 对话（一次性）`POST http://127.0.0.1:8000/api/v1/chat`，body: `{"message": "...", "conversation_id": "...", "history": [], "model": "qwen-plus"}`
- 对话（流式 SSE）`POST http://127.0.0.1:8000/api/v1/chat/stream`，同样 body；返回 `text/event-stream`，逐 token `data:`，末尾 `event: done`
- 文档上传 `POST http://127.0.0.1:8000/api/v1/documents`（multipart）：字段 `file`（文件）+ `doc_type`（类型）+ `biz_tags`（可选 JSON）
- 文档列表 `GET http://127.0.0.1:8000/api/v1/documents`：分页 + 按 `doc_type`/`status`/`only_active` 过滤
- 文档详情/状态 `GET http://127.0.0.1:8000/api/v1/documents/{id}`：轮询入库进度
- 知识库检索 `POST http://127.0.0.1:8000/api/v1/search`，body: `{"query": "...", "top_k": 5, "doc_type": null, "mode": "hybrid"}`（mode: hybrid/vector/keyword）
- 切割配置 `GET/PUT http://127.0.0.1:8000/api/v1/chunk-configs[/{doc_type}]`：每类文档配切割策略(recursive/parent_child)与参数

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
    rag/               RAG：上传校验/入库编排/解析/切割/向量化（P2 ①-④ 完成）
    texttosql/         TextToSQL 引擎（P5）
    agent/             多轮对话 Agent（工具调用）+ 工具/skill 注册表
  workers/             procrastinate 任务队列
alembic/               数据库迁移
tests/                 冒烟测试（health / meta / 错误格式）
```

> 进度：P1 骨架、P2(RAG 入库) 全部完成——上传→校验→存MinIO→登记→投递→
> worker 解析/切割/向量化/入库 全链路打通，并提供文档列表/状态回查接口。
> 下一步 P3(切割可配置 + 中文混合检索)。详见 [项目选型/工作清单.md](项目选型/工作清单.md)。
