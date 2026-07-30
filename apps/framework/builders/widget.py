from __future__ import annotations
from typing import Any, Mapping

def custom(name: str, *, component: str | None = None,
           props: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"name": name, "component": component,
            "props": dict(props) if props else None, **extra}

def text(**props: Any) -> dict[str, Any]: return custom("text", props=props)
def textarea(**props: Any) -> dict[str, Any]: return custom("textarea", props=props)
def select(**props: Any) -> dict[str, Any]: return custom("select", props=props)
def switch(**props: Any) -> dict[str, Any]: return custom("switch", props=props)
def checkbox(**props: Any) -> dict[str, Any]: return custom("checkbox", props=props)
def date(**props: Any) -> dict[str, Any]: return custom("date", props=props)
def datetime(**props: Any) -> dict[str, Any]: return custom("datetime", props=props)
def currency(**props: Any) -> dict[str, Any]: return custom("currency", props=props)
def file(**props: Any) -> dict[str, Any]: return custom("file", props=props)
def image(**props: Any) -> dict[str, Any]: return custom("image", props=props)
def json(**props: Any) -> dict[str, Any]: return custom("json", props=props)
def color(**props: Any) -> dict[str, Any]: return custom("color", props=props)
def icon(**props: Any) -> dict[str, Any]: return custom("icon", props=props)

def richtext(**props: Any) -> dict[str, Any]:
    return custom("richtext", component="MRichEditor", props=props)

def lookup(**props: Any) -> dict[str, Any]:
    return custom("lookup", component="MAsyncLookupSelect", props=props)
