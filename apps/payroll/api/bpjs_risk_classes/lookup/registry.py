from apps.framework.lookup import BaseLookup, register_lookup
from apps.payroll.models import BpjsRiskClass


@register_lookup
class BpjsRiskClassLookup(BaseLookup):
    name = "bpjs-risk-classes"
    model = BpjsRiskClass

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name"]

    ordering = ["code"]
