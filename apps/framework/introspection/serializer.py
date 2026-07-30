from rest_framework import serializers


def inspect_serializer(serializer_class):
    serializer = serializer_class()
    result = {}

    for name, field in serializer.fields.items():
        result[name] = {
            # existing
            "required": getattr(field, "required", False),
            "read_only": getattr(field, "read_only", False),
            "allow_null": getattr(field, "allow_null", False),

            # additional
            "allow_blank": getattr(field, "allow_blank", False),
            "write_only": getattr(field, "write_only", False),
            "default": (
                field.default
                if getattr(field, "default", serializers.empty)
                is not serializers.empty
                else None
            ),
            "label": getattr(field, "label", None),
            "help_text": getattr(field, "help_text", None),
            "style": getattr(field, "style", {}),
            "max_length": getattr(field, "max_length", None),
            "min_length": getattr(field, "min_length", None),
            "max_value": getattr(field, "max_value", None),
            "min_value": getattr(field, "min_value", None),
        }

    return result