# 数据库与迁移 SOP

> 本文规范"建数据库"与"建表/改表"的标准流程。
> 技术栈：PostgreSQL 18 + pgvector + SQLAlchemy(模型) + Alembic(迁移)。

> ⚠️ **本 SOP 只管我们自己的 PostgreSQL（`data_platform`）。** 业务库 SQL Server（`ICAS_FPC`，
> TextToSQL 用）是**外部只读生产库**，不归 Alembic 管、绝不在里面建表/改表（详见 [TextToSQL.md](TextToSQL.md)）。
> TextToSQL 的语义层（`schema_docs` 表）反而是建在**我们自己的 PG** 里、走下面的迁移流程。

核心区分两件事：
- **建数据库**（一次性）：手动执行一句 SQL 建"容器"。
- **建表 / 改表**（日常）：走"模型 → 迁移 → 执行"工作流，**不手写 SQL**。

三个角色的关系：
- **模型（`app/models/`）**＝表结构的唯一真相，写在 Python 代码里。
- **迁移（`alembic/versions/`）**＝从"数据库现状"到"模型描述"的变更脚本。
- **`alembic_version` 表**＝数据库里记录"已执行到哪个迁移"。

---

## 一、首次初始化数据库（一次性）

新环境（换服务器 / 新同事）只需做一次。

### 1. 确保 PostgreSQL 可连
填好 `.env` 的 `PG_*`（host/port/user/password/database）。

### 2. 建数据库 + 启用 pgvector
连到默认 `postgres` 库执行：

```sql
CREATE DATABASE data_platform;
```

再连到 `data_platform` 库执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

> pgvector 是硬依赖（向量列 + HNSW 索引都需要）。若报 `extension "vector" is not available`，
> 说明 PG 服务器未安装 pgvector，需先安装（见下方「附录：Windows 离线安装 pgvector」）。

### 3. 执行迁移建表
```bash
uv run alembic upgrade head
```
迁移脚本里已带 `CREATE EXTENSION IF NOT EXISTS vector`，第 2 步的扩展启用可省，但 `CREATE DATABASE` 必须先做。

---

## 二、日常改表流程（最常用）

每次新增表、加字段、改索引，重复这三步：

### 步骤 A：改模型
在 `app/models/` 下改/加 SQLAlchemy 模型。
**新建模型文件后，务必在 `app/models/__init__.py` 导入**，否则 Alembic 检测不到。

### 步骤 B：生成迁移脚本
```bash
uv run alembic revision --autogenerate -m "简短描述本次变更"
```
Alembic 会连库对比"模型 vs 现状"，在 `alembic/versions/` 生成一个迁移脚本。
**这步只生成脚本，不动数据库。**

### 步骤 C：检查脚本后执行
1. **务必打开生成的迁移脚本看一眼**（autogenerate 不总是完美）：
   - 用到 `pgvector` 的 VECTOR 列 → 确认顶部有 `import pgvector.sqlalchemy.vector`
   - 涉及向量 → 确认开头有 `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`
2. 执行：
```bash
uv run alembic upgrade head
```

---

## 三、常用命令速查

```bash
# 查看当前数据库迁移到哪个版本
uv run alembic current

# 查看迁移历史
uv run alembic history

# 升级到最新
uv run alembic upgrade head

# 回退一步（撤销最近一次迁移）
uv run alembic downgrade -1

# 手写一个空迁移（autogenerate 搞不定的复杂变更时）
uv run alembic revision -m "描述"
```

---

## 四、注意事项 / 已踩过的坑

1. **`alembic.ini` 不要写中文注释**：Alembic 用系统区域编码（Windows 为 cp950）读它，中文会触发 `UnicodeDecodeError`。注释用英文。（迁移 `.py` 文件按 UTF-8 读，可写中文。）
2. **pgvector 的 VECTOR 列**：autogenerate 生成的迁移会引用 `pgvector.sqlalchemy.vector.VECTOR`，但常**漏掉对应 import** → 运行报 `NameError`。手动在脚本顶部补 `import pgvector.sqlalchemy.vector`。
3. **HNSW 向量索引**：在模型 `__table_args__` 用
   `Index(..., postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})`，
   autogenerate 能识别。余弦距离 `vector_cosine_ops` 要与检索时用的 `<=>` 一致。
4. **改向量维度**：`Vector(dim)` 的维度变化需要配套迁移（重建列/索引）。
5. **生产执行迁移前先备份**。

---

## 附录：Windows 离线安装 pgvector（PG 18 无现成包时）

PG 18 在 Windows 上无官方预编译 pgvector，需自行编译。若 PG 服务器**无外网**：

1. 在一台**有网 + 有 VS2022(含 C++ 生成工具) + git** 的机器上：
   - 下载并解压对应版本的 PG 二进制（取头文件/库），记其路径为 `PGROOT`。
   - `git clone https://github.com/pgvector/pgvector.git`
   - 用 **x64 Native Tools Command Prompt** 执行：
     ```cmd
     set "PGROOT=<解压出的PG目录>\pgsql"
     cd pgvector
     nmake /F Makefile.win
     ```
   - 产物：`vector.dll` + `vector.control` + `sql\vector--*.sql`
2. 把产物拷到 PG 服务器：
   - `vector.dll` → `<PG安装目录>\lib\`
   - `vector.control` 与所有 `vector--*.sql` → `<PG安装目录>\share\extension\`
3. 连库执行 `CREATE EXTENSION vector;`（无需重启 PG）。

> 校验：`vector.dll` 必须是 **x64** 架构、放在 `lib`（即 `$libdir`）里，否则 PG 加载不到。

---

## 当前库内主要表（data_platform，便于对照）
- `documents` / `document_chunks`：RAG 文档与切块（含向量、tsvector）
- `chunk_configs`：每类文档的切割配置
- `conversations` / `messages`：网页端对话历史（`messages.sources` 存本轮引用来源）
- `schema_docs`：TextToSQL 语义层（业务视图/表的中文说明 + 向量）
- `procrastinate_*`：任务队列（不在 ORM 模型里，**Alembic 已配 include_name 过滤，勿动**）

---

_最后更新：2026-06-25_
