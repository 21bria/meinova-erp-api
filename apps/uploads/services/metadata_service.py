from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from apps.uploads.models import UploadedFile
from apps.uploads.validators import (
    detect_mime_type,
    normalize_filename,
)


DOCUMENT_EXTENSIONS = {
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".txt",
    ".rtf",
    ".odt",
    ".odp",
}

SPREADSHEET_EXTENSIONS = {
    ".xls",
    ".xlsx",
    ".csv",
    ".ods",
}

ARCHIVE_EXTENSIONS = {
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
}


def calculate_sha256(uploaded_file) -> str:
    hasher = hashlib.sha256()

    uploaded_file.seek(0)

    for chunk in uploaded_file.chunks():
        hasher.update(chunk)

    uploaded_file.seek(0)

    return hasher.hexdigest()


def detect_file_type(
    *,
    extension: str,
    mime_type: str,
) -> str:
    extension = extension.lower()
    mime_type = mime_type.lower()

    if mime_type.startswith("image/"):
        return UploadedFile.FileType.IMAGE

    if mime_type == "application/pdf" or extension == ".pdf":
        return UploadedFile.FileType.PDF

    if mime_type.startswith("video/"):
        return UploadedFile.FileType.VIDEO

    if mime_type.startswith("audio/"):
        return UploadedFile.FileType.AUDIO

    if extension in SPREADSHEET_EXTENSIONS:
        return UploadedFile.FileType.SPREADSHEET

    if extension in DOCUMENT_EXTENSIONS:
        return UploadedFile.FileType.DOCUMENT

    if extension in ARCHIVE_EXTENSIONS:
        return UploadedFile.FileType.ARCHIVE

    return UploadedFile.FileType.OTHER


def extract_image_dimensions(uploaded_file) -> tuple[int | None, int | None]:
    uploaded_file.seek(0)

    try:
        with Image.open(uploaded_file) as image:
            width, height = image.size

            return int(width), int(height)
    except (UnidentifiedImageError, OSError, ValueError):
        return None, None
    finally:
        uploaded_file.seek(0)


def build_file_metadata(uploaded_file) -> dict:
    original_name = normalize_filename(uploaded_file.name)
    extension_with_dot = Path(original_name).suffix.lower()
    extension = extension_with_dot.lstrip(".")

    mime_type = detect_mime_type(
        uploaded_file,
        original_name,
    )

    file_type = detect_file_type(
        extension=extension_with_dot,
        mime_type=mime_type,
    )

    width = None
    height = None

    if file_type == UploadedFile.FileType.IMAGE:
        width, height = extract_image_dimensions(uploaded_file)

    return {
        "original_name": original_name,
        "extension": extension,
        "mime_type": mime_type,
        "file_type": file_type,
        "size": int(uploaded_file.size),
        "checksum_sha256": calculate_sha256(uploaded_file),
        "width": width,
        "height": height,
    }