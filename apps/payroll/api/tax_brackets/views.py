from apps.framework.builders import field, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import PayrollTaxBracketService

from .serializers import PayrollTaxBracketSerializer


PAYROLL_TAX_BRACKET_SCHEMA = {
    "module": "payroll/tax-brackets",
    "name": "PayrollTaxBracket",
    "label": "Tax Bracket",
    "endpoint": "/api/payroll/tax-brackets/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="PPh21 Tax Brackets",
            description=(
                "Lapisan tarif PPh21 dalam rupiah SETAHUN. PTKP-nya "
                "dibaca dari master Tax Status."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "fields": {
        "sequence": field.integer(
            label="Sequence", default=1, required=True,
            table=True, sortable=True, order=10,
        ),
        "income_from": field.currency(
            label="Annual Income From", min=0, required=True,
            table=True, sortable=True, order=20,
        ),
        "income_to": field.currency(
            label="Annual Income To", min=0, table=True, sortable=True,
            help_text="Kosong = lapisan teratas, tanpa batas.",
            order=30,
        ),
        "rate": field.decimal(
            label="Rate (%)", min=0, decimal_places=3, required=True,
            table=True, sortable=True, order=40,
        ),
        "description": field.textarea(
            label="Description", rows=2, layout="full", table=False, order=50,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}


class PayrollTaxBracketViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = PayrollTaxBracketSerializer
    service_class = PayrollTaxBracketService

    framework_module = "payroll/tax-brackets"
    schema = PAYROLL_TAX_BRACKET_SCHEMA

    search_fields = ["description"]

    filterset_fields = ["is_active"]

    ordering = ["sequence", "income_from"]

    ordering_fields = [
        "sequence", "income_from", "income_to", "rate",
        "is_active", "created_at",
    ]

    def get_queryset(self):
        return PayrollTaxBracketService.get_queryset()
