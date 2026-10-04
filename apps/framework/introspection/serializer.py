from __future__ import annotations

from rest_framework import serializers

from apps.uploads.models import UploadedFile


def is_uploaded_file_serializer_field(
    name: str,
    field,
) -> bool:
    """
    Deteksi field serializer yang merepresentasikan relasi
    ke uploads.UploadedFile.

    Mendukung:
    - PrimaryKeyRelatedField
    - SlugRelatedField
    - field standar bernama uploaded_file
    """
    if name == "uploaded_file":
        return True

    if not isinstance(
        field,
        serializers.RelatedField,
    ):
        return False

    queryset = getattr(
        field,
        "queryset",
        None,
    )

    model = getattr(
        queryset,
        "model",
        None,
    )

    return model is UploadedFile


def normalize_default(field):
    default = getattr(
        field,
        "default",
        serializers.empty,
    )

    if default is serializers.empty:
        return None

    if callable(default):
        return None

    return default


def inspect_serializer(serializer_class):
    serializer = serializer_class()
    result = {}

    for name, field in serializer.fields.items():
        options = {
            "required": getattr(
                field,
                "required",
                False,
            ),
            "read_only": getattr(
                field,
                "read_only",
                False,
            ),
            "allow_null": getattr(
                field,
                "allow_null",
                False,
            ),
            "allow_blank": getattr(
                field,
                "allow_blank",
                False,
            ),
            "write_only": getattr(
                field,
                "write_only",
                False,
            ),
            "default": normalize_default(field),
            "label": getattr(
                field,
                "label",
                None,
            ),
            "help_text": getattr(
                field,
                "help_text",
                None,
            ),
            "style": getattr(
                field,
                "style",
                {},
            ),
            "max_length": getattr(
                field,
                "max_length",
                None,
            ),
            "min_length": getattr(
                field,
                "min_length",
                None,
            ),
            "max_value": getattr(
                field,
                "max_value",
                None,
            ),
            "min_value": getattr(
                field,
                "min_value",
                None,
            ),
        }

        if is_uploaded_file_serializer_field(
            name,
            field,
        ):
            options.update(
                {
                    "type": "file",
                    "widget": "upload",
                    "value_mode": "id",
                    "upload_mode": "separate",
                    "upload_endpoint": "/api/uploads/",
                    "multiple": False,
                    "category": "attachment",
                    "public": False,
                    "preview": True,
                    "download": True,
                    "replace": True,
                    "delete": True,
                    "table": False,
                    "filter": False,
                    "search": False,
                    "sortable": False,
                    "export": False,
                }
            )

        result[name] = {
            key: value
            for key, value in options.items()
            if value is not None
        }

    return result