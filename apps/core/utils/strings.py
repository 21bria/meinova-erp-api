import re


def camel_to_snake(value: str) -> str:
    value = re.sub(
        r"(?<!^)(?=[A-Z])",
        "_",
        value,
    )

    return value.lower()


def camel_to_kebab(value: str) -> str:
    return camel_to_snake(value).replace("_", "-")


def snake_to_camel(value: str) -> str:
    words = value.split("_")

    return (
        words[0]
        + "".join(word.title() for word in words[1:])
    )


def snake_to_title(value: str) -> str:
    return value.replace(
        "_",
        " ",
    ).title()


def normalize_slug(value: str) -> str:
    value = value.strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    return value.strip("-")


def normalize_spaces(value: str) -> str:
    return " ".join(value.split())