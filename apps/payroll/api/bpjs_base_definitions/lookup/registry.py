from apps.framework.lookup import BaseLookup, register_lookup
from apps.payroll.models import BpjsBaseDefinition


@register_lookup
class BpjsBaseDefinitionLookup(BaseLookup):
    name = "bpjs-base-definitions"
    model = BpjsBaseDefinition

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name"]

    ordering = ["code"]
