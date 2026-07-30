from __future__ import annotations
from typing import Any

def workspace(*, size: str = "full", columns: int = 2, **extra: Any) -> dict[str, Any]:
    return {"editor": "workspace", "size": size, "columns": columns, **extra}

def dialog(*, size: str = "lg", columns: int = 1, **extra: Any) -> dict[str, Any]:
    return {"editor": "dialog", "size": size, "columns": columns, **extra}

def page(*, size: str = "full", columns: int = 2, **extra: Any) -> dict[str, Any]:
    return {"editor": "page", "size": size, "columns": columns, **extra}

def drawer(*, side: str = "right", size: str = "lg", columns: int = 1,
           **extra: Any) -> dict[str, Any]:
    return {"editor": "drawer", "side": side, "size": size, "columns": columns, **extra}

def wizard(*, size: str = "full", columns: int = 2, linear: bool = True,
           **extra: Any) -> dict[str, Any]:
    return {"editor": "wizard", "size": size, "columns": columns,
            "linear": linear, **extra}
