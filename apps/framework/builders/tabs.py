from __future__ import annotations
from typing import Any, Sequence

def form(key: str, *, label: str | None = None, fields: Sequence[str] | None = None,
         modes: Sequence[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "form", "label": label,
            "fields": list(fields) if fields else None,
            "modes": list(modes) if modes else None, **extra}

def resource(key: str, *, label: str | None = None, endpoint: str | None = None,
             module: str | None = None, foreign_key: str = "employee",
             requires_record: bool = True, **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "resource", "label": label, "endpoint": endpoint,
            "module": module, "foreign_key": foreign_key,
            "requires_record": requires_record, **extra}

def history(key: str, *, label: str | None = None, endpoint: str | None = None,
            requires_record: bool = True, readonly: bool = True,
            **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "history", "label": label, "endpoint": endpoint,
            "requires_record": requires_record, "readonly": readonly, **extra}

def custom(key: str, *, component: str, label: str | None = None,
           requires_record: bool | None = None, **extra: Any) -> dict[str, Any]:
    return {"key": key, "type": "custom", "component": component, "label": label,
            "requires_record": requires_record, **extra}
