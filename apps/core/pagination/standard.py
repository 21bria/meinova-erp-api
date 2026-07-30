from decouple import config

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.core.constants import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
)


class StandardPagination(PageNumberPagination):
    page_size = config(
        "API_PAGE_SIZE",
        default=DEFAULT_PAGE_SIZE,
        cast=int,
    )

    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE

    def get_paginated_response(
        self,
        data,
    ) -> Response:
        return Response(
            {
                "success": True,
                "message": "Data retrieved successfully.",
                "data": data,
                "meta": {
                    "count": self.page.paginator.count,
                    "total_pages": self.page.paginator.num_pages,
                    "page": self.page.number,
                    "page_size": self.get_page_size(
                        self.request,
                    ),
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
                "status_code": 200,
            }
        )

    def get_paginated_response_schema(
        self,
        schema,
    ):
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                },
                "message": {
                    "type": "string",
                },
                "data": {
                    "type": "array",
                    "items": schema,
                },
                "meta": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                        },
                        "total_pages": {
                            "type": "integer",
                        },
                        "page": {
                            "type": "integer",
                        },
                        "page_size": {
                            "type": "integer",
                        },
                        "next": {
                            "type": [
                                "string",
                                "null",
                            ],
                        },
                        "previous": {
                            "type": [
                                "string",
                                "null",
                            ],
                        },
                    },
                },
                "status_code": {
                    "type": "integer",
                },
            },
        }