from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.reference.bank.serializers.bank import (
    BankSerializer,
    BankBranchSerializer,
)
from apps.administration.api.reference.bank.services.bank_service import (
    BankService,
    BankBranchService,
)


def bank_schema(slug):
    return {
        "endpoint": f"/api/administration/references/bank/{slug}/",
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. BCA",
                "order": 10,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Bank name",
                "order": 20,
            },
            "short_name": {
                "label": "Short Name",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. BCA",
                "order": 30,
            },
            "swift_code": {
                "label": "SWIFT Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. CENAIDJA",
                "order": 40,
            },
            "description": {
                "form": True,
                "table": False,
                "filter": False,
                "widget": "textarea",
                "rows": 4,
                "layout": "full",
                "order": 50,
            },
            "is_active": {
                "label": "Active",
                "form": True,
                "table": True,
                "filter": True,
                "placement": "quick",
                "order": 999,
            },
        },
    }


def bank_branch_schema(slug):
    return {
        "endpoint": f"/api/administration/references/bank/{slug}/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
            "columns": 2,
        },
        "fields": {
            "bank": {
                "lookup_endpoint": "/api/administration/references/bank/lookup/banks/",
                "placement": "quick",
                "order": 10,
            },
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. BCA-JKT",
                "order": 20,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Branch name",
                "order": 30,
            },
            "branch_code": {
                "label": "Branch Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. 001",
                "order": 40,
            },
            "swift_code": {
                "label": "SWIFT Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. CENAIDJA",
                "order": 50,
            },
            "address": {
                "form": True,
                "table": False,
                "filter": False,
                "widget": "textarea",
                "rows": 4,
                "layout": "full",
                "order": 60,
            },
            "is_active": {
                "label": "Active",
                "form": True,
                "table": True,
                "filter": True,
                "placement": "quick",
                "order": 999,
            },
        },
    }


class BankViewSet(BaseMasterViewSet):
    serializer_class = BankSerializer
    service_class = BankService

    filterset_fields = ["is_active"]
    framework_module = "references/bank/banks"
    schema = bank_schema("banks")

    ordering = ["name"]
    search_fields = ["code", "name", "short_name", "swift_code"]


class BankBranchViewSet(BaseMasterViewSet):
    serializer_class = BankBranchSerializer
    service_class = BankBranchService

    filterset_fields = ["bank", "is_active"]
    framework_module = "references/bank/bank-branches"
    schema = bank_branch_schema("bank-branches")

    ordering = ["name"]
    search_fields = ["code", "name", "branch_code", "swift_code"]