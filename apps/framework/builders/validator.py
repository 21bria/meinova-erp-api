from __future__ import annotations
from typing import Any, Sequence

def custom(name: str, *, message: str | None = None, **params: Any) -> dict[str, Any]:
    return {"name": name, "message": message, "params": params or None}

def required(**kwargs: Any) -> dict[str, Any]: return custom("required", **kwargs)
def email(**kwargs: Any) -> dict[str, Any]: return custom("email", **kwargs)
def url(**kwargs: Any) -> dict[str, Any]: return custom("url", **kwargs)

def min_length(value: int, **kwargs: Any) -> dict[str, Any]:
    return custom("min_length", value=value, **kwargs)

def max_length(value: int, **kwargs: Any) -> dict[str, Any]:
    return custom("max_length", value=value, **kwargs)

def min_value(value: int | float, **kwargs: Any) -> dict[str, Any]:
    return custom("min_value", value=value, **kwargs)

def max_value(value: int | float, **kwargs: Any) -> dict[str, Any]:
    return custom("max_value", value=value, **kwargs)

def regex(pattern: str, **kwargs: Any) -> dict[str, Any]:
    return custom("regex", pattern=pattern, **kwargs)

def unique(*, endpoint: str | None = None, exclude_current: bool = True,
           **kwargs: Any) -> dict[str, Any]:
    return custom("unique", endpoint=endpoint,
                  exclude_current=exclude_current, **kwargs)

def same_as(field: str, **kwargs: Any) -> dict[str, Any]:
    return custom("same_as", field=field, **kwargs)

def in_choices(values: Sequence[Any], **kwargs: Any) -> dict[str, Any]:
    return custom("in", values=list(values), **kwargs)
