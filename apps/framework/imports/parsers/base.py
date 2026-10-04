from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseImportParser(ABC):
    """
    Parser generik untuk file import.

    Turunan wajib mengisi `source_type` dan mengimplementasikan `parse()`
    yang mengembalikan list dict dengan key header sudah di-lowercase,
    plus metadata `_row_number` dan `_source_type`.
    """

    source_type: str

    def __init__(
        self,
        file_path: str | Path,
        *,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.file_path = Path(file_path)
        self.options = options or {}

    def validate_file(self) -> None:
        if not self.file_path.exists():
            raise FileNotFoundError(
                f"Import file not found: {self.file_path}"
            )

        if not self.file_path.is_file():
            raise ValueError(
                f"Import path is not a file: {self.file_path}"
            )

    @abstractmethod
    def parse(self) -> list[dict[str, Any]]:
        raise NotImplementedError
