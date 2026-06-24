"""文本切割（P2-4 先用递归切兜底；P3 再做按类型可配置策略）。"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 中文友好的分隔符优先级：段落 → 换行 → 中文句末标点 → 空格 → 字符
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", " ", ""]


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """递归切割：尽量在自然边界切，块间留 overlap 重叠以保上下文。"""
    if not text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=_SEPARATORS,
        keep_separator=True,
    )
    return [c for c in splitter.split_text(text) if c.strip()]
