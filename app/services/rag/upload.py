"""上传文件校验（P2 子步骤 2）。

三道关：① 扩展名白名单 → ② 大小上限 → ③ 内容魔数（防伪装、挡可执行文件）。
不通过抛 BadRequestError，由全局异常处理器转成统一 {code,message}。
"""

import hashlib

from app.core.config import settings
from app.core.exceptions import BadRequestError

# —— 各类型文件的"魔数"（文件头固定标志，扩展名可伪造，内容头难伪造）——
_PDF = b"%PDF"  # PDF
_ZIP = b"PK\x03\x04"  # docx / xlsx（本质是 zip 包）
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # 老版 doc / xls（OLE 复合文件）
_MZ = b"MZ"  # Windows 可执行(exe/dll) —— 一律拒绝
_ELF = b"\x7fELF"  # Linux 可执行 —— 一律拒绝

# 扩展名 → 允许的文件头签名；txt/md 无签名，走文本检查
_EXT_SIGNATURES: dict[str, list[bytes]] = {
    "pdf": [_PDF],
    "docx": [_ZIP],
    "xlsx": [_ZIP],
    "doc": [_OLE],
    "xls": [_OLE],
}


def _ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_upload(filename: str, data: bytes) -> str:
    """校验上传文件，通过则返回小写扩展名；否则抛 BadRequestError。"""
    # ① 扩展名白名单
    ext = _ext_of(filename)
    if ext not in settings.allowed_exts:
        allowed = "、".join(sorted(settings.allowed_exts))
        raise BadRequestError(f"不支持的文件类型 .{ext or '(无后缀)'}，仅允许：{allowed}")

    # ② 大小
    if not data:
        raise BadRequestError("文件内容为空")
    if len(data) > settings.upload_max_bytes:
        raise BadRequestError(f"文件超过大小上限 {settings.upload_max_mb}MB")

    # ③ 内容魔数
    head = data[:16]
    if head.startswith(_MZ) or head.startswith(_ELF):
        raise BadRequestError("检测到可执行文件，已拒绝")

    sigs = _EXT_SIGNATURES.get(ext)
    if sigs is not None:
        if not any(head.startswith(s) for s in sigs):
            raise BadRequestError(f"文件内容与扩展名 .{ext} 不符（疑似伪装）")
    else:
        # txt / md：确认是文本（前段无 NUL 字节，二进制文件几乎必含 NUL）
        if b"\x00" in data[:8192]:
            raise BadRequestError("文本文件包含二进制内容，疑似非文本")

    return ext


def sha256_of(data: bytes) -> str:
    """内容 SHA256（用于去重 / 版本判断的辅助）。"""
    return hashlib.sha256(data).hexdigest()
