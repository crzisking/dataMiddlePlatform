"""上传校验单元测试（纯逻辑，不依赖外部服务）。"""

import pytest

from app.core.exceptions import BadRequestError
from app.services.rag.upload import sha256_of, validate_upload

PDF = b"%PDF-1.7\n..."
ZIP = b"PK\x03\x04rest..."
TXT = "你好，制造业中台".encode()
EXE = b"MZ\x90\x00executable"


def test_pdf_ok():
    assert validate_upload("sop.pdf", PDF) == "pdf"


def test_docx_ok():
    assert validate_upload("制度.docx", ZIP) == "docx"


def test_txt_ok():
    assert validate_upload("notes.txt", TXT) == "txt"


def test_reject_unknown_ext():
    with pytest.raises(BadRequestError):
        validate_upload("video.mp4", b"\x00\x00\x00\x18ftyp")


def test_reject_executable_disguised_as_pdf():
    # 后缀是 pdf，内容是 exe → 必须拒绝
    with pytest.raises(BadRequestError):
        validate_upload("malware.pdf", EXE)


def test_reject_content_ext_mismatch():
    # 后缀 pdf 但不是 PDF 内容
    with pytest.raises(BadRequestError):
        validate_upload("fake.pdf", ZIP)


def test_reject_empty():
    with pytest.raises(BadRequestError):
        validate_upload("empty.pdf", b"")


def test_reject_binary_as_txt():
    with pytest.raises(BadRequestError):
        validate_upload("bin.txt", b"abc\x00\x01\x02")


def test_sha256_stable():
    assert sha256_of(b"abc") == sha256_of(b"abc")
    assert len(sha256_of(b"abc")) == 64
