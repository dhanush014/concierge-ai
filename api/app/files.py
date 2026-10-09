"""Upload checks: real file type from the bytes, size limit, safe display names."""

import os
import unicodedata

from fastapi import UploadFile

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILENAME = 200

# (leading bytes, content type, extension). The extension a user typed is ignored.
SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"%PDF-", "application/pdf", "pdf"),
]


def read_limited(upload: UploadFile) -> bytes:
    """Read at most MAX_BYTES + 1, enough to tell a too-large file without loading all of it."""
    return upload.file.read(MAX_BYTES + 1)


def detect_type(data: bytes) -> tuple[str, str] | None:
    """(content_type, extension) from the file's first bytes, or None if not allowed."""
    for magic, content_type, ext in SIGNATURES:
        if data.startswith(magic):
            return content_type, ext
    return None


def clean_filename(name: str | None) -> str:
    """Display name only (never used as a path): drop folders and control characters, cap length."""
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    if base in ("", ".", ".."):
        return "document"
    if len(base) > MAX_FILENAME:
        stem, ext = os.path.splitext(base)
        ext = ext if len(ext) <= 10 else ""
        base = stem[: MAX_FILENAME - len(ext)] + ext
    return base
