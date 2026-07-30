from django.db import models

SYSTEM_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "deleted_at",
    "created_by",
    "updated_by",
    "deleted_by",
    "is_deleted",
}


def model_field_type(field):
    if isinstance(field, models.EmailField):
        return "email"

    if isinstance(field, models.URLField):
        return "url"

    if isinstance(field, models.BooleanField):
        return "boolean"

    if isinstance(field, models.IntegerField):
        return "integer"

    if isinstance(field, models.DecimalField):
        return "decimal"

    if isinstance(field, models.FloatField):
        return "number"

    if isinstance(field, models.DateTimeField):
        return "datetime"

    if isinstance(field, models.DateField):
        return "date"

    if isinstance(field, models.TimeField):
        return "time"

    if isinstance(field, models.TextField):
        return "textarea"

    if isinstance(field, models.JSONField):
        return "json"

    if isinstance(field, models.ImageField):
        return "image"

    if isinstance(field, models.FileField):
        return "file"

    if isinstance(
        field,
        (
            models.ForeignKey,
            models.OneToOneField,
            models.ManyToManyField,
        ),
    ):
        return "lookup"

    return "text"


def humanize(value: str) -> str:
    return (
        value
        .replace("_", " ")
        .replace("-", " ")
        .strip()
        .title()
    )


def is_required_field(field):
    if getattr(field, "primary_key", False):
        return False

    if getattr(field, "auto_created", False):
        return False

    if getattr(field, "has_default", lambda: False)():
        return False

    return not field.blank and not field.null


def is_table_field(field):
    if field.name in SYSTEM_FIELDS:
        return False

    return not isinstance(
        field,
        (
            models.TextField,
            models.JSONField,
            models.FileField,
            models.ImageField,
            models.ManyToManyField,
        ),
    )


def is_filter_field(field):
    return isinstance(
        field,
        (
            models.BooleanField,
            models.ForeignKey,
            models.OneToOneField,
        ),
    )


def is_search_field(field):
    return isinstance(
        field,
        (
            models.CharField,
            models.TextField,
            models.EmailField,
        ),
    )


def is_sortable_field(field):
    return not isinstance(
        field,
        (
            models.TextField,
            models.JSONField,
            models.FileField,
            models.ImageField,
            models.ManyToManyField,
        ),
    )


def is_exportable_field(field):
    return not isinstance(
        field,
        (
            models.FileField,
            models.ImageField,
            models.ManyToManyField,
        ),
    )


def is_quick_filter(field):
    if field.name == "is_active":
        return True

    return isinstance(field, models.BooleanField)


def get_field_default(field):
    if not field.has_default():
        return None

    default = field.default

    if callable(default):
        return None

    return default


def get_field_choices(field):
    choices = getattr(field, "choices", None)

    if not choices:
        return None

    return [
        {
            "value": value,
            "label": str(label),
        }
        for value, label in choices
    ]


def inspect_model(model):
    fields = {}

    for field in model._meta.get_fields():
        if getattr(field, "auto_created", False):
            continue

        if not getattr(field, "concrete", False) and not isinstance(
            field,
            models.ManyToManyField,
        ):
            continue

        if field.name in SYSTEM_FIELDS:
            continue

        field_type = model_field_type(field)

        options = {
            "type": field_type,
            "widget": field_type,
            "label": str(
                getattr(field, "verbose_name", None)
                or humanize(field.name)
            ),
            "required": is_required_field(field),
            "form": not getattr(field, "auto_created", False),
            "table": is_table_field(field),
            "filter": is_filter_field(field),
            "search": is_search_field(field),
            "sortable": is_sortable_field(field),
            "export": is_exportable_field(field),
        }

        default = get_field_default(field)
        if default is not None:
            options["default"] = default

        help_text = getattr(field, "help_text", None)
        if help_text:
            options["help_text"] = str(help_text)

        max_length = getattr(field, "max_length", None)
        if max_length:
            options["max_length"] = max_length

        if isinstance(field, models.DecimalField):
            options.update(
                {
                    "max_digits": field.max_digits,
                    "decimal_places": field.decimal_places,
                }
            )

        choices = get_field_choices(field)
        if choices:
            options.update(
                {
                    "type": "select",
                    "widget": "select",
                    "options": choices,
                    "filter": True,
                }
            )

        if isinstance(
            field,
            (
                models.ForeignKey,
                models.OneToOneField,
                models.ManyToManyField,
            ),
        ):
            options.update(
                {
                    "type": "lookup",
                    "widget": "lookup",
                    "lookup_endpoint": None,
                    "multiple": isinstance(
                        field,
                        models.ManyToManyField,
                    ),
                }
            )

        if is_quick_filter(field):
            options.update(
                {
                    "table": True,
                    "filter": True,
                    "placement": "quick",
                }
            )

        fields[field.name] = options

    return fields