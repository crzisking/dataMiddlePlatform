"""中文分词：给关键词检索(BM25)用。

为什么需要：PostgreSQL 自带的全文检索默认不会切中文(会把一整句当成一个词)。
办法是我们先用 jieba 把中文切成一个个词、用空格连起来，再交给 PG 按空格建索引。

两个用途：
- tokenize()：入库时把每块文本切词，存进 content_tokens 列(供建全文索引)。
- to_tsquery_or()：查询时把问题也切词，拼成 PG 能识别的查询表达式。
"""

import re

import jieba

# 只保留中文、字母、数字的字符；其它(标点、空格等)在拼查询表达式时要去掉，
# 否则会让 PG 的 to_tsquery 语法报错。
_KEEP = re.compile(r"[^\w一-鿿]")


def tokenize(text: str) -> str:
    """把文本切成"词 词 词"(空格分隔)。入库时用，结果存进 content_tokens。"""
    return " ".join(w for w in jieba.cut(text) if w.strip())


def to_tsquery_or(query: str) -> str | None:
    """把查询切词，拼成 PG 的全文检索表达式(各词之间用 OR)。

    用 OR(任一词命中即算相关)而不是 AND，是为了召回更全——
    精确匹配的程度由排序分数体现，而不是一刀切要求所有词都出现。
    若切完没有有效词，返回 None(表示没法做关键词检索)。
    """
    words = [_KEEP.sub("", w) for w in jieba.cut(query)]
    words = [w for w in words if w]
    if not words:
        return None
    return " | ".join(words)  # " | " 是 PG 全文检索里的"或"
