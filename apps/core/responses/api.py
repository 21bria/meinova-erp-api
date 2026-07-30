from typing import Any

from rest_framework import status
from rest_framework.response import Response


def success_response(
    data: Any = None,
    *,
    message: str = "Success.",
    status_code: int = status.HTTP_200_OK,
    meta: dict[str, Any] | None = None,
) -> Response:
    payload = {
        "success": True,
        "message": message,
        "data": data,
        "status_code": status_code,
    }

    if meta is not None:
        payload["meta"] = meta

    return Response(
        payload,
        status=status_code,
    )


def created_response(
    data: Any = None,
    *,
    message: str = "Created successfully.",
) -> Response:
    return success_response(
        data=data,
        message=message,
        status_code=status.HTTP_201_CREATED,
    )


def error_response(
    *,
    message: str = "An error occurred.",
    errors: Any = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    return Response(
        {
            "success": False,
            "message": message,
            "errors": errors,
            "status_code": status_code,
        },
        status=status_code,
    )


def no_content_response() -> Response:
    return Response(
        status=status.HTTP_204_NO_CONTENT,
    )