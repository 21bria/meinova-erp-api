from rest_framework import status
from rest_framework.exceptions import APIException


class MeinovaAPIException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "An error occurred."
    default_code = "error"


class BusinessRuleError(MeinovaAPIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "Business rule validation failed."
    default_code = "business_rule_error"


class ResourceConflictError(MeinovaAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The resource conflicts with existing data."
    default_code = "resource_conflict"


class ResourceNotFoundError(MeinovaAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested resource was not found."
    default_code = "resource_not_found"