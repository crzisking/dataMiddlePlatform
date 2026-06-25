"""语义层的读写与渲染：把一个视图/表的业务描述登记进 schema_docs、向量化、
并在需要时渲染成两种文本。

这是 TextToSQL "怎么读懂业务库"的中枢。三件事：
- upsert_schema_doc：登记/更新一条语义记录（一个视图或一组裸表）。
- build_embed_text：拼"检索用文本"（偏用户问法），拿去向量化，让问题能匹配到对的表。
- render_ddl_card：拼"喂模型的 DDL 名片"（偏精确列名/类型），让模型写出能跑的 SQL。

注意：本模块只读写**我们自己的 PostgreSQL** 和调用向量化服务，**绝不碰业务库 SQL Server**。
设计背景见 项目选型/TextToSQL.md 第七节。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema_doc import SchemaDoc, SourceType
from app.services.rag.embedding import embed_texts


def build_embed_text(doc: SchemaDoc) -> str:
    """拼"检索用文本"：偏向用户会怎么问的语言，供 embedding。

    放进去的是"用途 + 别名 + 各字段中文名 + 样例问法"——目的是让用户问题的向量能命中这条。
    不放精确类型/SQL（那是给模型写 SQL 用的，见 render_ddl_card）。
    """
    parts = [f"用途：{doc.desc}"]
    if doc.aliases:
        parts.append(f"别名：{doc.aliases}")
    if doc.columns:
        # 只取字段的中文含义，拼成一串（用户是按"含义"问的，不是按英文列名）
        names = [c.get("desc") or c.get("name", "") for c in doc.columns]
        parts.append("字段：" + "、".join(n for n in names if n))
    if doc.samples:
        parts.append(f"样例：{doc.samples}")
    return "\n".join(parts)


def render_ddl_card(doc: SchemaDoc) -> str:
    """拼"喂模型的 DDL 名片"：偏精确的列名/类型 + 注释 + 关系 + 样例 + 护栏说明。

    检索命中这条后，把它渲染成下面这段交给大模型，模型据此写出列名拼写正确、带正确
    过滤的 SQL。视图路径通常没有 relations（已 JOIN 好），裸表路径必须有。
    """
    lines = [f"-- {doc.source_type} {doc.object_name}：{doc.desc}"]
    if doc.grain:
        lines.append(f"-- 粒度：{doc.grain}")
    lines.append(f"CREATE {doc.source_type.upper()} {doc.object_name} (")
    for c in doc.columns or []:
        unit = f"，单位：{c['unit']}" if c.get("unit") else ""
        values = f"，取值：{c['values']}" if c.get("values") else ""
        note = f"{c.get('desc', '')}{unit}{values}"
        lines.append(f"  {c.get('name')}  {c.get('type', '')},  -- {note}")
    lines.append(")")
    if doc.relations:
        lines.append(f"-- 关系：{doc.relations}")
    if doc.required_filter:
        win = f"，默认 {doc.default_window}" if doc.default_window else ""
        mx = f"，最长 {doc.max_window}" if doc.max_window else ""
        lines.append(f"-- 必须按【{doc.required_filter}】过滤{win}{mx}")
    if doc.samples:
        lines.append(f"-- 样例：{doc.samples}")
    return "\n".join(lines)


async def upsert_schema_doc(
    session: AsyncSession,
    *,
    object_name: str,
    desc: str,
    source_type: str = SourceType.view.value,
    columns: list[dict] | None = None,
    grain: str | None = None,
    relations: str | None = None,
    samples: str | None = None,
    aliases: str | None = None,
    required_filter: str | None = None,
    default_window: str | None = None,
    max_window: str | None = None,
    isolation: str | None = None,
    enabled: bool = True,
) -> SchemaDoc:
    """登记或更新一条语义记录（按 object_name 唯一，有则改、无则建）。

    只写字段、不在这里向量化——向量化单独调 vectorize()（它要调通义 API，分开更清楚、
    也方便"先建占位行、内容齐了再向量化"）。调用方负责 commit。
    """
    doc = (
        await session.execute(select(SchemaDoc).where(SchemaDoc.object_name == object_name))
    ).scalar_one_or_none()
    if doc is None:
        doc = SchemaDoc(object_name=object_name)
        session.add(doc)
    doc.source_type = source_type
    doc.desc = desc
    doc.columns = columns
    doc.grain = grain
    doc.relations = relations
    doc.samples = samples
    doc.aliases = aliases
    doc.required_filter = required_filter
    doc.default_window = default_window
    doc.max_window = max_window
    doc.isolation = isolation
    doc.enabled = enabled
    await session.flush()
    return doc


async def vectorize(session: AsyncSession, doc: SchemaDoc) -> None:
    """给一条语义记录算 embedding 并存回（用 build_embed_text 的文本）。

    内容填好后调一次即可。没向量的行不会被检索命中。调用方负责 commit。
    """
    vector = (await embed_texts([build_embed_text(doc)]))[0]
    doc.embedding = vector
    await session.flush()


async def list_schema_docs(session: AsyncSession) -> list[SchemaDoc]:
    """列出所有语义记录（管理/检查用）。"""
    rows = (await session.execute(select(SchemaDoc).order_by(SchemaDoc.object_name))).scalars()
    return list(rows)


async def retrieve_schemas(
    session: AsyncSession, question: str, *, top_k: int = 3
) -> list[SchemaDoc]:
    """schema-RAG：按问题向量检索最相关的若干条语义记录（视图/表）。

    这是 TextToSQL 的"找对表"环节：把问题向量化，在 schema_docs 里按余弦距离找最近的几条，
    只在 **enabled 且已向量化** 的行里找。返回的就是"该让模型照着写 SQL 的那几张视图/表"。
    语义层为空（还没登记任何视图）时返回空列表——上层据此直接提示"未配置"，不会去碰业务库。
    """
    query_vec = (await embed_texts([question]))[0]
    # cosine_distance 越小越相近，会用上 schema_docs 的 HNSW 索引
    distance = SchemaDoc.embedding.cosine_distance(query_vec)
    stmt = (
        select(SchemaDoc)
        .where(SchemaDoc.enabled.is_(True), SchemaDoc.embedding.isnot(None))
        .order_by(distance)
        .limit(top_k)
    )
    return list((await session.execute(stmt)).scalars().all())
