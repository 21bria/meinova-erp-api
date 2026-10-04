from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename


DEFAULT_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".ppt",
    ".pptx",
    ".txt",
    ".rtf",
    ".zip",
}

DEFAULT_MAX_FILE_SIZE = 25 * 1024 * 1024
DEFAULT_MAX_MULTIPLE_FILES = 20


def normalize_extension(value: str) -> str:
    extension = str(value or "").strip().lower()

    if not extension:
        return ""

    if not extension.startswith("."):
        extension = f".{extension}"

    return extension


def get_allowed_extensions() -> set[str]:
    configured = getattr(
        settings,
        "UPLOAD_ALLOWED_EXTENSIONS",
        DEFAULT_ALLOWED_EXTENSIONS,
    )

    return {
        normalize_extension(extension)
        for extension in configured
        if normalize_extension(extension)
    }


def get_allowed_mime_types() -> set[str]:
    configured = getattr(
        settings,
        "UPLOAD_ALLOWED_MIME_TYPES",
        (),
    )

    return {
        str(mime_type).strip().lower()
        for mime_type in configured
        if str(mime_type).strip()
    }


def get_max_file_size() -> int:
    return int(
        getattr(
            settings,
            "UPLOAD_MAX_FILE_SIZE",
            DEFAULT_MAX_FILE_SIZE,
        )
    )


def get_max_multiple_files() -> int:
    return int(
        getattr(
            settings,
            "UPLOAD_MAX_MULTIPLE_FILES",
            DEFAULT_MAX_MULTIPLE_FILES,
        )
    )


def normalize_filename(filename: str) -> str:
    raw_name = Path(str(filename or "")).name
    normalized_name = get_valid_filename(raw_name)

    if not normalized_name:
        raise ValidationError(
            "Nama file tidak valid.",
            code="invalid_filename",
        )

    return normalized_name


def detect_mime_type(uploaded_file, filename: str) -> str:
    content_type = getattr(uploaded_file, "content_type", None)

    if content_type:
        return str(content_type).split(";")[0].strip().lower()

    guessed_type, _ = mimetypes.guess_type(filename)

    return guessed_type or "application/octet-stream"


def validate_uploaded_file(uploaded_file):
    if uploaded_file is None:
        raise ValidationError(
            "File wajib dipilih.",
            code="file_required",
        )

    filename = normalize_filename(uploaded_file.name)
    extension = Path(filename).suffix.lower()

    if not extension:
        raise ValidationError(
            "File harus mempunyai ekstensi.",
            code="extension_required",
        )

    allowed_extensions = get_allowed_extensions()

    if extension not in allowed_extensions:
        raise ValidationError(
            (
                f"Ekstensi '{extension}' tidak diizinkan. "
                f"Format yang diperbolehkan: "
                f"{', '.join(sorted(allowed_extensions))}."
            ),
            code="extension_not_allowed",
        )

    file_size = int(getattr(uploaded_file, "size", 0) or 0)

    if file_size <= 0:
        raise ValidationError(
            "File kosong tidak dapat diunggah.",
            code="empty_file",
        )

    maximum_size = get_max_file_size()

    if file_size > maximum_size:
        maximum_mb = maximum_size / 1024 / 1024

        raise ValidationError(
            f"Ukuran file maksimal {maximum_mb:g} MB.",
            code="file_too_large",
        )

    allowed_mime_types = get_allowed_mime_types()

    if allowed_mime_types:
        mime_type = detect_mime_type(
            uploaded_file,
            filename,
        )

        if mime_type not in allowed_mime_types:
            raise ValidationError(
                f"Tipe file '{mime_type}' tidak diizinkan.",
                code="mime_type_not_allowed",
            )

    uploaded_file.seek(0)

    return uploaded_file


def validate_multiple_upload(files) -> list:
    file_list = list(files or [])

    if not file_list:
        raise ValidationError(
            "Minimal satu file wajib dipilih.",
            code="files_required",
        )

    maximum_files = get_max_multiple_files()

    if len(file_list) > maximum_files:
        raise ValidationError(
            (
                f"Maksimal {maximum_files} file "
                "dalam satu proses upload."
            ),
            code="too_many_files",
        )

    for uploaded_file in file_list:
        validate_uploaded_file(uploaded_file)

    return file_list