from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler


def meinova_exception_handler(exc, context):
    # DRF tidak mengenali ValidationError milik Django, jadi tanpa
    # penerjemahan ini `Model.full_clean()` yang gagal di service
    # membalas HTTP 500, bukan 400 berisi error per field.
    if isinstance(exc, DjangoValidationError):
        exc = DRFValidationError(
            as_serializer_error(exc),
        )

    response = exception_handler(exc, context)

    if response is None:
        return None

    data = response.data

    if isinstance(data, dict) and "detail" in data:
        message = str(data["detail"])
        errors = None
    else:
        message = "Validation failed."
        errors = data

    response.data = {
        "success": False,
        "message": message,
        "errors": errors,
        "status_code": response.status_code,
    }

    return response
