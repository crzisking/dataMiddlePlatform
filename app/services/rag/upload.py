"""上传文件校验：在文件进系统前，把住三道关。

为什么要校验：用户可能传我们处理不了的格式（视频、压缩包）、超大文件、
甚至把病毒改名成 .pdf。这里在落库/存盘之前先挡掉，保证进来的都是
能解析、且安全的文件。

三道关：① 扩展名白名单 → ② 大小上限 → ③ 看文件真实内容（防伪装）。
不通过就抛 BadRequestError，由全局异常处理器统一转成 {code, message} 返回前端。
"""

import hashlib

from app.core.config import settings
from app.core.exceptions import BadRequestError

# 下面这些是各类文件开头的"魔数"（固定的几个字节，像文件的指纹）。
# 扩展名能改，但文件开头的指纹改不了，所以用它来判断"这到底是不是它声称的类型"。
_PDF = b"%PDF"  # PDF 文件都以 %PDF 开头
_ZIP = b"PK\x03\x04"  # docx / xlsx 本质是 zip 压缩包，都以 PK.. 开头
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # 老版 doc / xls 的开头
_MZ = b"MZ"  # Windows 可执行文件(exe/dll)的开头 —— 一律拒绝
_ELF = b"\x7fELF"  # Linux 可执行文件的开头 —— 一律拒绝

# 每种扩展名应该对应哪种文件头。txt/md 是纯文本、没有固定指纹，单独处理。
_EXT_SIGNATURES: dict[str, list[bytes]] = {
    "pdf": [_PDF],
    "docx": [_ZIP],
    "xlsx": [_ZIP],
    "doc": [_OLE],
    "xls": [_OLE],
}


def _ext_of(filename: str) -> str:
    """取文件名里最后一个点后面的扩展名，转小写。没有点就返回空串。"""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_upload(filename: str, data: bytes) -> str:
    """校验上传的文件。通过就返回小写扩展名；不通过抛 BadRequestError。"""
    # 第一关：扩展名必须在白名单里
    ext = _ext_of(filename)
    if ext not in settings.allowed_exts:
        allowed = "、".join(sorted(settings.allowed_exts))
        raise BadRequestError(f"不支持的文件类型 .{ext or '(无后缀)'}，仅允许：{allowed}")

    # 第二关：大小。空文件没意义；超上限会拖垮后面的解析/向量化
    if not data:
        raise BadRequestError("文件内容为空")
    if len(data) > settings.upload_max_bytes:
        raise BadRequestError(f"文件超过大小上限 {settings.upload_max_mb}MB")

    # 第三关：看文件开头的真实内容
    head = data[:16]
    # 不管后缀是什么，只要内容是可执行文件，直接拒绝（防止病毒改名成 .pdf）
    if head.startswith(_MZ) or head.startswith(_ELF):
        raise BadRequestError("检测到可执行文件，已拒绝")

    sigs = _EXT_SIGNATURES.get(ext)
    if sigs is not None:
        # PDF/Office：文件头必须和声称的扩展名对得上，否则就是伪装
        if not any(head.startswith(s) for s in sigs):
            raise BadRequestError(f"文件内容与扩展名 .{ext} 不符（疑似伪装）")
    else:
        # txt/md：没有固定文件头。检查前段有没有 NUL 字节——
        # 二进制文件几乎一定含 NUL，纯文本不会，以此挡掉"二进制冒充文本"
        if b"\x00" in data[:8192]:
            raise BadRequestError("文本文件包含二进制内容，疑似非文本")

    return ext


def sha256_of(data: bytes) -> str:
    """算文件内容的 SHA256 指纹（64 位十六进制字符串）。

    用途：内容完全相同的文件指纹也相同，可用于将来做去重、
    或判断"重传的文件内容有没有变"。
    """
    return hashlib.sha256(data).hexdigest()
