"""文本切割：把一篇文档的长文本切成一个个小块（chunk）。

为什么要切：后面要把每一块单独转成向量、单独检索。块太大检索不精准、
也超模型输入；块太小又会丢上下文。所以切成大小适中、且尽量在自然边界
（段落/句子）断开的小块。

当前是 P2-4 的"递归切割兜底"——所有文档类型都用这一套。
按文档类型分策略、可配置那部分，是 P3 才做的。
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 切割时优先在哪里断开，从前往后依次尝试：
# 先按空行(段落) → 再按换行 → 再按中文句末标点 → 再按空格 → 实在不行才逐字切。
# 这样尽量保证一块话是完整的，不会从句子中间硬切断。
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", " ", ""]


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """把文本切成小块。

    chunk_size：每块最多约 512 个字符。
    overlap：相邻两块在交界处重叠约 50 个字符。
        为什么要重叠：万一关键内容正好落在两块的边界上，重叠能保证它
        在某一块里是完整的，检索时不会因为被切断而漏掉。
    """
    # 空文本（比如扫描件没抽出文字）直接返回空，省得后面白跑。
    if not text.strip():
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=_SEPARATORS,
        keep_separator=True,  # 保留标点，切完读起来不会丢句号、问号
    )
    # 过滤掉切完后只剩空白的块
    return [c for c in splitter.split_text(text) if c.strip()]
