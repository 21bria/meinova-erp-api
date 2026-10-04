from apps.framework.builders import field, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import PayrollLeaveRuleService

from .serializers import PayrollLeaveRuleSerializer


PAYROLL_LEAVE_RULE_SCHEMA = {
    "module": "payroll/leave-rules",
    "name": "PayrollLeaveRule",
    "label": "Payroll Leave Rule",
    "endpoint": "/api/payroll/leave-rules/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Payroll Leave Rules",
            description=(
                "Jenis cuti mana yang tidak dibayar. Jenis yang tidak "
                "punya baris di sini dianggap dibayar."
            ),
            size="lg",
            columns=1,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "fields": {
        "leave_type": field.lookup(
            label="Leave Type",
            lookup_endpoint=(
                "/api/administration/references/hr/lookup/leave-types/"
            ),
            display_key="leave_type_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            order=10,
        ),
        "is_unpaid": field.boolean(
            label="Unpaid Leave",
            default=False,
            table=True,
            filter=True,
            help_text=(
                "Hari cuti jenis ini dihitung sebagai hari tidak "
                "dibayar dan memotong gaji."
            ),
            order=20,
        ),
        "notes": field.textarea(
            label="Notes", rows=3, layout="full", table=False, order=30,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}


class PayrollLeaveRuleViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = PayrollLeaveRuleSerializer
    service_class = PayrollLeaveRuleService

    framework_module = "payroll/leave-rules"
    schema = PAYROLL_LEAVE_RULE_SCHEMA

    # Model ini tidak punya kolom `code`/`name`; bawaan base akan
    # membalas 500 begitu kotak pencarian diketik.
    search_fields = ["leave_type__code", "leave_type__name"]

    filterset_fields = ["leave_type", "is_unpaid", "is_active"]

    ordering = ["leave_type__code"]

    ordering_fields = [
        "leave_type__code", "leave_type__name", "is_unpaid",
        "is_active", "created_at",
    ]

    def get_queryset(self):
        return PayrollLeaveRuleService.get_queryset()
