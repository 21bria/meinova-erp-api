from __future__ import annotations
from typing import Any, Mapping, Sequence

FieldConfig = dict[str, Any]

def _clean(data: Mapping[str, Any]) -> FieldConfig:
    return {k: v for k, v in data.items() if v is not None}

def custom(field_type: str, *, widget: str | Mapping[str, Any] | None = None, **kwargs: Any) -> FieldConfig:
    return _clean({"type": field_type, "widget": widget or field_type, **kwargs})

def text(**kwargs: Any) -> FieldConfig: return custom("text", **kwargs)
def email(**kwargs: Any) -> FieldConfig: return custom("email", **kwargs)
def password(**kwargs: Any) -> FieldConfig: return custom("password", **kwargs)
def url(**kwargs: Any) -> FieldConfig: return custom("url", **kwargs)
def phone(**kwargs: Any) -> FieldConfig: return custom("phone", **kwargs)
def integer(**kwargs: Any) -> FieldConfig: return custom("integer", **kwargs)
def percentage(**kwargs: Any) -> FieldConfig: return custom("percentage", **kwargs)
def date(**kwargs: Any) -> FieldConfig: return custom("date", **kwargs)
def datetime(**kwargs: Any) -> FieldConfig: return custom("datetime", **kwargs)
def time(**kwargs: Any) -> FieldConfig: return custom("time", **kwargs)
def textarea(*, rows: int | None = None, **kwargs: Any) -> FieldConfig:
    return custom("textarea", rows=rows, **kwargs)
def richtext(**kwargs: Any) -> FieldConfig: return custom("richtext", **kwargs)
def json(**kwargs: Any) -> FieldConfig: return custom("json", **kwargs)
def color(**kwargs: Any) -> FieldConfig: return custom("color", **kwargs)
def icon(**kwargs: Any) -> FieldConfig: return custom("icon", **kwargs)

def number(*, min: int | float | None = None, max: int | float | None = None,
           step: int | float | str | None = None, **kwargs: Any) -> FieldConfig:
    return custom("number", min=min, max=max, step=step, **kwargs)

def decimal(*, decimal_places: int | None = None, max_digits: int | None = None,
            **kwargs: Any) -> FieldConfig:
    return custom("decimal", decimal_places=decimal_places, max_digits=max_digits, **kwargs)

def currency(*, currency: str | None = None, currency_field: str | None = None,
             **kwargs: Any) -> FieldConfig:
    return custom("currency", currency=currency, currency_field=currency_field, **kwargs)

def boolean(**kwargs: Any) -> FieldConfig:
    return custom("boolean", widget="switch", **kwargs)

def switch(**kwargs: Any) -> FieldConfig:
    return custom("boolean", widget="switch", **kwargs)

def checkbox(**kwargs: Any) -> FieldConfig:
    return custom("boolean", widget="checkbox", **kwargs)

def select(*, options: Sequence[Mapping[str, Any]] | None = None,
           multiple: bool | None = None, **kwargs: Any) -> FieldConfig:
    return custom("select", options=list(options) if options else None,
                  multiple=multiple, **kwargs)

def multiselect(*, options: Sequence[Mapping[str, Any]] | None = None,
                **kwargs: Any) -> FieldConfig:
    return select(options=options, multiple=True, **kwargs)

def lookup(*, endpoint: str | None = None, lookup_endpoint: str | None = None,
           label_key: str | None = None, value_key: str | None = None,
           multiple: bool | None = None, **kwargs: Any) -> FieldConfig:
    return custom("lookup", lookup_endpoint=lookup_endpoint or endpoint,
                  label_key=label_key, value_key=value_key,
                  multiple=multiple, **kwargs)

def file(
    *,
    accept: str | Sequence[str] | None = None,
    max_size: int | float | None = None,
    max_size_mb: int | float | None = None,
    multiple: bool = False,
    category: str = "attachment",
    public: bool = False,
    preview: bool = True,
    download: bool = True,
    replace: bool = True,
    delete: bool = True,
    upload_endpoint: str = "/api/uploads/",
    widget: str = "upload",
    **kwargs: Any,
) -> FieldConfig:
    normalized_accept: str | list[str] | None

    if isinstance(accept, str):
        normalized_accept = accept
    elif accept:
        normalized_accept = list(accept)
    else:
        normalized_accept = None

    resolved_max_size = (
        max_size_mb
        if max_size_mb is not None
        else max_size
    )

    return custom(
        "file",
        widget=widget,
        accept=normalized_accept,
        max_size_mb=resolved_max_size,
        multiple=multiple,
        category=category,
        public=public,
        preview=preview,
        download=download,
        replace=replace,
        delete=delete,
        upload_endpoint=upload_endpoint,
        **kwargs,
    )

def image(
    *,
    accept: str | Sequence[str] = "image/*",
    max_size: int | float | None = None,
    max_size_mb: int | float | None = None,
    multiple: bool = False,
    category: str = "image",
    public: bool = False,
    preview: bool = True,
    download: bool = True,
    replace: bool = True,
    delete: bool = True,
    upload_endpoint: str = "/api/uploads/",
    **kwargs: Any,
) -> FieldConfig:
    return file(
        accept=accept,
        max_size=max_size,
        max_size_mb=max_size_mb,
        multiple=multiple,
        category=category,
        public=public,
        preview=preview,
        download=download,
        replace=replace,
        delete=delete,
        upload_endpoint=upload_endpoint,
        widget="image-upload",
        **kwargs,
    )

def hidden(**kwargs: Any) -> FieldConfig:
    return custom("hidden", hidden=True, **kwargs)

def merge(config: Mapping[str, Any], **overrides: Any) -> FieldConfig:
    return {**config, **_clean(overrides)}
