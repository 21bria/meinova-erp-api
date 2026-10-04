from apps.framework.lookup import BaseLookup, register_lookup
from apps.payroll.models import PayrollPolicy


@register_lookup
class PayrollPolicyLookup(BaseLookup):
    name = "payroll-policies"
    model = PayrollPolicy

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name"]

    ordering = ["code"]
