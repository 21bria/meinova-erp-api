from __future__ import annotations
from typing import Any, Mapping, Sequence

def none() -> dict[str, Any]:
    return {"enabled": False, "type": "none"}

def approval(*, code: str | None = None, status_field: str = "status",
             initial_status: str = "draft",
             levels: Sequence[Mapping[str, Any]] | None = None,
             **extra: Any) -> dict[str, Any]:
    return {"enabled": True, "type": "approval", "code": code,
            "status_field": status_field, "initial_status": initial_status,
            "levels": list(levels) if levels else None, **extra}

def state_machine(*, status_field: str = "status", initial: str,
                  states: Sequence[Mapping[str, Any]],
                  transitions: Sequence[Mapping[str, Any]],
                  **extra: Any) -> dict[str, Any]:
    return {"enabled": True, "type": "state_machine",
            "status_field": status_field, "initial": initial,
            "states": list(states), "transitions": list(transitions), **extra}

def level(key: str, *, label: str | None = None,
          permission: str | None = None, order: int | None = None,
          **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "permission": permission,
            "order": order, **extra}
