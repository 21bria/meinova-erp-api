from rest_framework.views import exception_handler


def meinova_exception_handler(exc, context):
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