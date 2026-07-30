from __future__ import annotations
from typing import Any

def custom(key: str, **kwargs: Any) -> dict[str, Any]:
    return {"key": key, **kwargs}

def save(**kwargs: Any) -> dict[str, Any]:
    return custom("save", label="Save", icon="Save", variant="default",
                  placement="primary", modes=["create", "edit"], **kwargs)

def save_and_new(**kwargs: Any) -> dict[str, Any]:
    return custom("save_and_new", label="Save & New", icon="CopyPlus",
                  variant="outline", modes=["create", "edit"], **kwargs)

def save_and_close(**kwargs: Any) -> dict[str, Any]:
    return custom("save_and_close", label="Save & Close", icon="Save",
                  variant="outline", close=True, modes=["create", "edit"], **kwargs)

def cancel(**kwargs: Any) -> dict[str, Any]:
    return custom("cancel", label="Cancel", icon="X", variant="ghost", **kwargs)

def delete(**kwargs: Any) -> dict[str, Any]:
    return custom("delete", label="Delete", icon="Trash2", variant="destructive",
                  method="DELETE", confirm=True, modes=["edit", "detail"], **kwargs)

def export(**kwargs: Any) -> dict[str, Any]:
    return custom("export", label="Export", icon="Download",
                  variant="outline", **kwargs)

def import_data(**kwargs: Any) -> dict[str, Any]:
    return custom("import", label="Import", icon="Upload",
                  variant="outline", **kwargs)

def submit(**kwargs: Any) -> dict[str, Any]:
    return custom("submit", label="Submit", icon="Send", method="POST", **kwargs)

def approve(**kwargs: Any) -> dict[str, Any]:
    return custom("approve", label="Approve", icon="CheckCircle2",
                  method="POST", **kwargs)

def reject(**kwargs: Any) -> dict[str, Any]:
    return custom("reject", label="Reject", icon="XCircle",
                  variant="destructive", method="POST", confirm=True, **kwargs)
