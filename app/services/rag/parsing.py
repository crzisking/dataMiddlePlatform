"""文档解析：按格式抽取纯文本（P2-4）。

一期支持 PDF(原生文字) / docx / xlsx / txt / md。
- 扫描件 PDF（无文字层）会抽出空文本，OCR(MinerU) 作为后续增强。
- 老二进制格式 .doc/.xls 解析复杂，暂不支持，明确报错引导转存。
"""

import io

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from openpyxl import load_workbook

from app.core.exceptions import BadRequestError


def extract_text(ext: str, data: bytes) -> str:
    """按扩展名抽取文本。"""
    if ext == "pdf":
        return _pdf(data)
    if ext == "docx":
        return _docx(data)
    if ext == "xlsx":
        return _xlsx(data)
    if ext in ("txt", "md"):
        return data.decode("utf-8", errors="ignore")
    if ext in ("doc", "xls"):
        raise BadRequestError(f"老格式 .{ext} 暂不支持解析，请另存为 .docx/.xlsx 再上传")
    raise BadRequestError(f"不支持解析的格式 .{ext}")


def _pdf(data: bytes) -> str:
    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _docx(data: bytes) -> str:
    d = DocxDocument(io.BytesIO(data))
    return "\n".join(p.text for p in d.paragraphs if p.text.strip())


def _xlsx(data: bytes) -> str:
    # data_only=True 取计算结果而非公式；read_only 省内存
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        lines.append(f"# 工作表：{ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append(" | ".join(cells))  # 整行成一行，保留表格语义
    wb.close()
    return "\n".join(lines)
