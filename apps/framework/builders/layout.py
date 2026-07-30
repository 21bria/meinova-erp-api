from __future__ import annotations
from typing import Any, Sequence

def section(key: str, *, label: str | None = None, columns: int = 2,
            fields: Sequence[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "section", "label": label, "columns": columns,
            "fields": list(fields) if fields else None, **extra}

def row(key: str, *, fields: Sequence[str], **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "row", "fields": list(fields), **extra}

def column(key: str, *, fields: Sequence[str], span: int | None = None,
           **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "column", "fields": list(fields),
            "span": span, **extra}

def group(key: str, *, fields: Sequence[str], label: str | None = None,
          **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "group", "label": label,
            "fields": list(fields), **extra}

def divider(key: str, *, label: str | None = None,
            **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "divider", "label": label, **extra}
