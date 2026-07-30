import re

from django.core.exceptions import ValidationError


CODE_PATTERN = re.compile(
    r"^[A-Z0-9_-]+$",
)

SCHEMA_NAME_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*$",
)

EMAIL_PATTERN = re.compile(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
)


def validate_code(value: str) -> None:
    if not CODE_PATTERN.fullmatch(value):
        raise ValidationError(
            (
                "Code may only contain uppercase letters, "
                "numbers, underscores, and hyphens."
            ),
            code="invalid_code",
        )


def validate_schema_name(value: str) -> None:
    if not SCHEMA_NAME_PATTERN.fullmatch(value):
        raise ValidationError(
            (
                "Schema name must start with a lowercase letter "
                "and contain only lowercase letters, numbers, "
                "and underscores."
            ),
            code="invalid_schema_name",
        )


def validate_email(value: str) -> None:
    if not EMAIL_PATTERN.fullmatch(value):
        raise ValidationError(
            "Enter a valid email address.",
            code="invalid_email",
        )


def validate_not_blank(value: str) -> None:
    if not value or not value.strip():
        raise ValidationError(
            "This field cannot be blank.",
            code="blank",
        )