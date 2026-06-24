# RAG 系统

> 本文档聚焦 RAG：通用文档入库管线、切割策略体系、向量化、重排序、版本管理。
> 平台层见 [中台架构.md](中台架构.md)；TextToSQL 复用本文档的检索能力，见 [TextToSQL.md](TextToSQL.md)。

---

## 一、设计目标

做一套**通用基础 RAG 系统**：用户上传任意文档，系统**根据类型 / 情况自动选择切割策略**，且切割策略**可配置**。

---

## 二、入库管线（异步流水线）

```
上传 → 识别 → 解析 → 分块(按类型策略) → 向量化 → 入库 → 可检索
 │       │      │         │              │        │
文件   类型/格式  抽文本   chunk策略路由   通义embed  PGVector
      元数据   +结构    +元数据标注
```

### 1. 上传与元数据（管理页关键）
上传时必须带元数据，作为后续切割与过滤依据：
- **文档类型**（SOP / 工艺 / 质量 / 设备手册 / 制度…）：上传页选择，也是检索过滤标签
- 业务标签（部门 / 产线 / 设备型号，可选，用于预留的权限过滤）
- 文件格式：PDF / Word / Excel / 扫描件

#### 上传限制（已确定）
- **格式白名单**：仅允许 **PDF、Word（.docx/.doc）、Excel（.xlsx/.xls）、纯文本/Markdown（.txt/.md）**，其余一律拒绝（理由：RAG 只能消化可抽取文本的文件；同时挡住可执行/恶意文件）。白名单**可配置**，后续可加 PPT、图片等。
- **校验方式**：不只看后缀，**结合文件真实内容（魔数/MIME）** 判断，防伪装。
- **单文件上限**：**100 MB**（兼顾扫描版手册等大文件）。
- **重复 / 版本**：**同名 + 同文档类型 自动视为新版本**，旧版标记失效但保留可追溯（见「七、文档版本管理」）。

### 2. 解析层（按文件格式选解析器）
| 格式 | 解析器 |
|---|---|
| PDF（原生文字） | PyMuPDF 快速抽取 |
| PDF（扫描件 / 复杂表格） | **MinerU**（OCR + 版面 + 表格还原） |
| Word | python-docx / Unstructured |
| Excel | 按 sheet / 表结构单独处理（表格不当纯文本切） |

> **一期实现现状（P2-④ 已完成）**：已实现 PDF(PyMuPDF) / docx(python-docx) / xlsx(openpyxl) / txt·md。
> **尚未实现**：扫描件 OCR（MinerU，留作增强）、老格式 .doc/.xls（暂报错引导转存为 docx/xlsx）。

### 3. 向量化
- **通义云 `text-embedding-v3`** 批量向量化（已定：纯 API，不本地部署 embedding）。

### 4. 入库
- **原始文件**存 **MinIO 对象存储**（已有现成服务）：上传原件存 MinIO，库里只存对象 key / URL，供下载与溯源
- **chunk 与向量**存 **PGVector**（复用现有 PostgreSQL）：一张表存 chunk 文本 + 向量 + 元数据 JSON
- 建 **HNSW** 索引

#### MinIO 连接（已有）
- host: `192.168.120.198`，port: `9000`，bucket: `temp`
- accessKey / secretKey：**实际密钥放配置文件 / 环境变量，不硬编码进代码或文档**
- 注：当前 bucket 名为 `temp`，正式上线前建议规划正式 bucket（如按文档类型 / 环境分桶）

---

## 三、切割策略体系

切割分两个正交维度：**① 怎么切（主策略）** 与 **② 切完怎么组织（检索结构，可叠加）**。

### 主策略（市面主流梳理）

**基础切割（按长度/规则）**
- 固定长度切割（Fixed-size）
- 重叠切割（Sliding window / Overlap）
- 递归切割（Recursive）— 通用性最好

**结构感知切割（按文档结构）**
- 按标题/层级切（Markdown / HTML header）
- 文档版面切（Layout-aware，配合 MinerU）
- 表格独立切（Table-aware）
- 代码切割（Code splitter）

**语义切割（按含义，成本高，一期不做）**
- 语义切割（Semantic chunking）
- 命题切割（Proposition-based）
- LLM 智能切割（Agentic chunking）

### 检索结构优化（可叠加，与主策略正交）
- **父子切割（Parent-Child / Small-to-Big）**：小块检索、返回父块给 LLM
- 窗口切割（Sentence-window）：父子的轻量版
- **混合检索（Hybrid）**：向量 + 关键词 BM25 融合，补型号/代码/术语等精确词召回
- 摘要索引（Multi-vector）：摘要检索、返回原文
- 层级索引（RAPTOR）：递归摘要树（一期不做）

---

## 四、一期落地范围（已确定）

内置以下策略，覆盖约 90% 场景：

| 文档类型 | 默认主策略 |
|---|---|
| SOP / 制度 | 标题层级递归切 |
| 工艺 / 质量（多表格） | 表格独立成块 + 文本递归切 |
| 设备手册 | 标题层级 + 故障代码表独立 |
| 长段落 / 纯文本 | 递归字符切 + 重叠（chunk 512 / overlap 50） |
| 扫描件 | 先 OCR 再走对应策略 |

**可叠加开关**：父子切割、混合检索 BM25。

**语义/命题/RAPTOR 切割：一期不做**，留作后期高价值文档的可选项。

---

## 五、切割配置（可配置，已确定）

管理页支持管理员针对**每类文档**配置：
- 主切割策略（递归 / 标题 / 表格）
- chunk 大小 / 重叠
- 是否开启父子切割
- 是否开启混合检索

---

## 六、检索（供 RAG 与 TextToSQL 共用）
- 向量召回 Top-K + 元数据过滤（类型 / 业务标签）
- **重排序 rerank（已确定：做，作为可配开关）**：通义 rerank，召回 Top20 → 重排取 Top5，制造业精确词场景提升明显，延迟 +约几百 ms
- 混合检索 BM25 兜底精确词（型号 / 故障代码 / 术语等精确词，纯向量召回差）

### 中文全文检索（BM25）方案——重要前提
PostgreSQL 自带全文检索（`tsvector`）**默认不会对中文分词**（它只按空格/标点切，中文会整段当一个词），所以混合检索要落地必须先解决中文分词。两条路线：

#### 方案 A（推荐，Windows 友好，无需编译扩展）
**应用层用 jieba 分词 + PG 内置 `simple` 配置**：
1. Python 端装 jieba：`pip install jieba`
2. 入库时：把 chunk 文本用 jieba 切成"词 词 词"（空格分隔），写入一个额外列 `content_tokens`
3. 建索引（`simple` 配置只按空格切，正好吃我们已分好的词）：
   ```sql
   ALTER TABLE rag_chunks ADD COLUMN content_tokens text;
   ALTER TABLE rag_chunks ADD COLUMN ts tsvector
     GENERATED ALWAYS AS (to_tsvector('simple', content_tokens)) STORED;
   CREATE INDEX idx_rag_chunks_ts ON rag_chunks USING GIN (ts);
   ```
4. 查询时：把用户问题同样用 jieba 切词，再 `ts @@ plainto_tsquery('simple', '切好的词')`，用 `ts_rank` 排序
- 优点：**不依赖任何 PG 扩展，Windows 直接可用**；分词规则可控（可加制造业词典 `jieba.load_userdict`）
- 缺点：要自己维护分词列

#### 方案 B（效果更好，但 Windows 安装麻烦）
装 PG 中文分词扩展 **zhparser**（基于 SCWS）或 **pg_jieba**：
- Linux/Docker 下相对好装；**Windows 下需要预编译二进制或自行编译，较折腾**
- 迁移到 Docker 后可切换到此方案（Dockerfile 里装扩展更干净）

> **结论**：一期 Windows 用**方案 A**；后期迁 Docker 时再评估是否升级到方案 B。可加制造业术语自定义词典提升分词准确度。

---

## 七、文档版本管理（已确定）
- 文档带**版本号**
- SOP 等改版后重新入库，**旧版本需可追溯**（旧版标记失效但不物理删除，保留历史向量与原文）

---

_最后更新：2026-06-24_
