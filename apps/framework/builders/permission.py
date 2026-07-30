from __future__ import annotations
from typing import Any

def module(codename: str, **permissions: Any) -> dict[str, Any]:
    return {"module": codename, **permissions}

def allow(*permissions: str, mode: str = "any") -> dict[str, Any]:
    return {"type": "allow", "mode": mode, "permissions": list(permissions)}

def deny(*permissions: str, mode: str = "any") -> dict[str, Any]:
    return {"type": "deny", "mode": mode, "permissions": list(permissions)}

def role(*roles: str, mode: str = "any") -> dict[str, Any]:
    return {"type": "role", "mode": mode, "roles": list(roles)}

def owner(*, field: str = "created_by") -> dict[str, Any]:
    return {"type": "owner", "field": field}

def tenant_scope() -> dict[str, Any]:
    return {"type": "scope", "scope": "tenant"}

def company_scope(*, field: str = "company") -> dict[str, Any]:
    return {"type": "scope", "scope": "company", "field": field}

def read_only() -> dict[str, Any]:
    return {"type": "read_only"}
